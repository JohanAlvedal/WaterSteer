"""Persistent safety supervisor for WaterSteer control intents.

The supervisor runs after the horizon optimizer and has the final word on the
published control request. It only ever makes the request *safer*:

* it latches critical recovery (``force_heat``) across restarts,
* it escalates a comfort recovery that is not producing any temperature rise,
* it limits how long heating may be held continuously while the tank is
  below its normal target (a warm tank needs no protection, and releasing it
  on a timer only lets the heat pump run at whatever the price is).

All state is plain data so it can be persisted with Home Assistant storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_COMFORT_ESCALATION_MINUTES = 45.0
DEFAULT_MAX_HOLD_HOURS = 12.0
HOLD_LOCKOUT_MINUTES = 60.0
RECOVERY_RISE_C = 0.5

INTENT_HOLD = "hold"
INTENT_NORMAL = "normal"
INTENT_FORCE_HEAT = "force_heat"


@dataclass(frozen=True, slots=True)
class SafetyResult:
    """Final, safety-supervised control intent."""

    intent: str
    reason: str
    overridden: bool
    force_latched: bool
    hold_minutes: float | None
    warnings: tuple[str, ...]


class DhwSafetySupervisor:
    """Track safety state that must survive restarts."""

    def __init__(
        self,
        *,
        comfort_escalation_minutes: float = DEFAULT_COMFORT_ESCALATION_MINUTES,
        max_hold_hours: float = DEFAULT_MAX_HOLD_HOURS,
    ) -> None:
        """Initialize an empty supervisor."""
        self.comfort_escalation_minutes = comfort_escalation_minutes
        self.max_hold_hours = max_hold_hours
        self.force_latched = False
        self.below_comfort_since: float | None = None
        self.below_comfort_min_temperature: float | None = None
        self.hold_since: float | None = None
        self.hold_counted_since: float | None = None
        self.hold_lockout_until: float | None = None

    def evaluate(
        self,
        *,
        now: float,
        temperature: float | None,
        absolute_minimum: float,
        comfort_minimum: float,
        proposed_intent: str,
        proposed_reason: str,
        warnings: tuple[str, ...] = (),
        normal_target: float | None = None,
    ) -> SafetyResult:
        """Return the supervised intent for one update cycle."""
        active_warnings = list(warnings)

        if temperature is None:
            # Fail open: hand control back to the heat pump's own logic. A
            # missing sensor never justifies holding DHW production, and an
            # open-ended force without temperature feedback is not wanted
            # either. The latch and comfort timers are kept, not reset, so a
            # short sensor dropout cannot hide a real deficit.
            self._clear_hold()
            active_warnings.append("dhw_temperature_unavailable")
            return SafetyResult(
                intent=INTENT_NORMAL,
                reason="fail_open_missing_temperature",
                overridden=proposed_intent != INTENT_NORMAL,
                force_latched=self.force_latched,
                hold_minutes=None,
                warnings=tuple(active_warnings),
            )

        self._update_comfort_tracking(now, temperature, comfort_minimum)

        if temperature <= absolute_minimum:
            self.force_latched = True
        elif temperature >= comfort_minimum:
            self.force_latched = False

        escalated = False
        if (
            not self.force_latched
            and self.below_comfort_since is not None
            and self.below_comfort_min_temperature is not None
            and now - self.below_comfort_since >= self.comfort_escalation_minutes * 60
            and temperature < self.below_comfort_min_temperature + RECOVERY_RISE_C
        ):
            self.force_latched = True
            escalated = True

        if self.force_latched:
            self._clear_hold()
            if escalated:
                reason = "comfort_recovery_not_progressing"
                active_warnings.append("comfort_recovery_escalated")
            elif temperature <= absolute_minimum:
                reason = "absolute_minimum_requires_immediate_heat"
            else:
                reason = "critical_recovery_latched_until_comfort_minimum"
            return SafetyResult(
                intent=INTENT_FORCE_HEAT,
                reason=reason,
                overridden=proposed_intent != INTENT_FORCE_HEAT,
                force_latched=True,
                hold_minutes=None,
                warnings=tuple(active_warnings),
            )

        if proposed_intent == INTENT_FORCE_HEAT:
            # The optimizer can only propose force_heat from a safety decision;
            # keep it without latching if the supervisor did not see a cause.
            self._clear_hold()
            return SafetyResult(
                intent=proposed_intent,
                reason=proposed_reason,
                overridden=False,
                force_latched=False,
                hold_minutes=None,
                warnings=tuple(active_warnings),
            )

        if proposed_intent != INTENT_HOLD:
            self._clear_hold()
            return SafetyResult(
                intent=proposed_intent,
                reason=proposed_reason,
                overridden=False,
                force_latched=False,
                hold_minutes=None,
                warnings=tuple(active_warnings),
            )

        if temperature < comfort_minimum:
            self._clear_hold()
            return SafetyResult(
                intent=INTENT_NORMAL,
                reason="hold_rejected_below_comfort_minimum",
                overridden=True,
                force_latched=False,
                hold_minutes=None,
                warnings=tuple(active_warnings),
            )

        if self.hold_lockout_until is not None and now < self.hold_lockout_until:
            return SafetyResult(
                intent=INTENT_NORMAL,
                reason="hold_lockout_after_max_hold_duration",
                overridden=True,
                force_latched=False,
                hold_minutes=None,
                warnings=tuple(active_warnings),
            )
        self.hold_lockout_until = None

        if self.hold_since is None:
            self.hold_since = now
        hold_minutes = (now - self.hold_since) / 60
        # Only time spent below the normal target counts towards the limit.
        # Field data (IVT, 5 Nov): a 12 h hold expired at 51.8 °C in the most
        # expensive hour of the day and the heat pump ran for nothing.
        if normal_target is not None and temperature >= normal_target:
            self.hold_counted_since = now
        elif self.hold_counted_since is None:
            self.hold_counted_since = self.hold_since
        counted_minutes = (now - self.hold_counted_since) / 60

        if counted_minutes >= self.max_hold_hours * 60:
            self.hold_since = None
            self.hold_counted_since = None
            self.hold_lockout_until = now + HOLD_LOCKOUT_MINUTES * 60
            active_warnings.append("max_hold_duration_reached")
            return SafetyResult(
                intent=INTENT_NORMAL,
                reason="max_hold_duration_reached",
                overridden=True,
                force_latched=False,
                hold_minutes=None,
                warnings=tuple(active_warnings),
            )

        return SafetyResult(
            intent=INTENT_HOLD,
            reason=proposed_reason,
            overridden=False,
            force_latched=False,
            hold_minutes=hold_minutes,
            warnings=tuple(active_warnings),
        )

    def _update_comfort_tracking(
        self,
        now: float,
        temperature: float,
        comfort_minimum: float,
    ) -> None:
        """Track how long the tank has been below the comfort minimum."""
        if temperature >= comfort_minimum:
            self.below_comfort_since = None
            self.below_comfort_min_temperature = None
            return

        if self.below_comfort_since is None:
            self.below_comfort_since = now
            self.below_comfort_min_temperature = temperature
            return

        if (
            self.below_comfort_min_temperature is None
            or temperature < self.below_comfort_min_temperature
        ):
            self.below_comfort_min_temperature = temperature

    def _clear_hold(self) -> None:
        """Reset continuous-hold tracking."""
        self.hold_since = None
        self.hold_counted_since = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize supervisor state."""
        return {
            "force_latched": self.force_latched,
            "below_comfort_since": self.below_comfort_since,
            "below_comfort_min_temperature": self.below_comfort_min_temperature,
            "hold_since": self.hold_since,
            "hold_counted_since": self.hold_counted_since,
            "hold_lockout_until": self.hold_lockout_until,
        }

    def restore(self, data: dict[str, Any] | None) -> None:
        """Restore supervisor state, ignoring malformed values."""
        if not isinstance(data, dict):
            return
        self.force_latched = data.get("force_latched") is True
        self.below_comfort_since = _optional_float(data.get("below_comfort_since"))
        self.below_comfort_min_temperature = _optional_float(
            data.get("below_comfort_min_temperature")
        )
        self.hold_since = _optional_float(data.get("hold_since"))
        self.hold_counted_since = _optional_float(data.get("hold_counted_since"))
        self.hold_lockout_until = _optional_float(data.get("hold_lockout_until"))


HEATING_ASSIST_MINUTES = 15.0
MAX_ASSIST_WAIT_MINUTES = 45.0
ASSIST_WAIT_FACTOR = 1.5
DEFAULT_START_DELAY_MINUTES = 20.0
MAX_START_DELAY_SAMPLES = 10
SELF_START_HISTORY = 6
STALL_RISE_C = 0.2
MAX_CHARGE_HOURS = 3.0
CHARGE_INTENTS = frozenset({"heat", "precharge"})
COMFORT_RECOVERY_REASON = "comfort_recovery_requires_heat"


@dataclass(frozen=True, slots=True)
class ChargeResult:
    """Supervised charging decision."""

    intent: str
    reason: str
    assist: bool
    target: float | None


class ChargeController:
    """Finish planned charges and make sure they really happen.

    * A started ``heat`` / ``precharge`` continues until its target is reached
      (or ``MAX_CHARGE_HOURS``), even if the plan flips to ``hold`` half-way.
      Without this the tank dithers around the normal target in tiny cycles.
    * The heat pump always gets the chance to start by itself first. Only if
      the tank has not started warming within the learned start delay (x1.5,
      15-45 min) is extra hot water requested.
    * Whether the heat pump starts by itself is kept as a rolling history of
      the last charges, not a one-way latch. Field data (IVT, Nov): a single
      slow start had latched "does not start", after which every charge used
      extra hot water from the first second, which on that heat pump means
      the immersion heater, although it started by itself in 5 of 6 releases.
    * ``assist_planned`` = False never uses extra hot water for price-planned
      charges (only for comfort recovery). A planned charge the heat pump does
      not take is then given up until the plan asks for a new one.

    Only ever extends heating, so it is applied after the safety supervisor.
    """

    def __init__(self) -> None:
        """Initialize without an active charge."""
        self.intent: str | None = None
        self.target: float | None = None
        self.since: float | None = None
        self.start_temperature: float | None = None
        self.assist = False
        self.assist_planned = True
        self.planned = True
        self.self_start_history: list[bool] = []
        self.outcome_recorded = False
        self.given_up = False
        self.heating_requested_since: float | None = None
        self.warmed = False
        self.start_delays: list[float] = []
        self.best_temperature: float | None = None
        self.best_since: float | None = None

    @property
    def pump_starts_on_its_own(self) -> bool | None:
        """Majority of recent charges; None until one has been observed."""
        if not self.self_start_history:
            return None
        starts = sum(1 for item in self.self_start_history if item)
        return starts * 2 >= len(self.self_start_history)

    @pump_starts_on_its_own.setter
    def pump_starts_on_its_own(self, value: bool | None) -> None:
        self.self_start_history = [] if value is None else [value]

    @property
    def start_delay_minutes(self) -> float:
        """Learned time from heating request until the tank starts warming."""
        if not self.start_delays:
            return DEFAULT_START_DELAY_MINUTES
        ordered = sorted(self.start_delays)
        return ordered[len(ordered) // 2]

    @property
    def assist_after_minutes(self) -> float:
        """How long the heat pump gets to start by itself."""
        return min(
            MAX_ASSIST_WAIT_MINUTES,
            max(HEATING_ASSIST_MINUTES, self.start_delay_minutes * ASSIST_WAIT_FACTOR),
        )

    def _assist_allowed(self) -> bool:
        return self.assist_planned or not self.planned

    def evaluate(
        self,
        *,
        now: float,
        intent: str,
        reason: str,
        temperature: float | None,
        target_for: dict[str, float],
        producing: bool | None = None,
    ) -> ChargeResult:
        """Return the intent after charge latching and assist."""
        original_intent, original_reason = intent, reason
        if temperature is None or intent in {"force_heat", "boost"}:
            self._reset()
            self.given_up = False
            return ChargeResult(intent, reason, False, None)

        if self.given_up:
            if intent in CHARGE_INTENTS and reason != COMFORT_RECOVERY_REASON:
                # The heat pump did not take this planned charge; keep it
                # unblocked but do not restart the charge every cycle.
                return ChargeResult(intent, reason, False, None)
            self.given_up = False

        if intent in CHARGE_INTENTS and self.intent is None:
            self.intent = intent
            self.target = target_for[intent]
            self.since = now
            self.start_temperature = temperature
            self.assist = False
            self.planned = reason != COMFORT_RECOVERY_REASON
            self.outcome_recorded = False
            self.heating_requested_since = now
            self.warmed = False
        elif intent in CHARGE_INTENTS and intent != self.intent:
            self.intent = intent
            self.target = max(self.target or 0.0, target_for[intent])

        if self.intent is None or self.since is None or self.target is None:
            return ChargeResult(intent, reason, False, None)

        if temperature >= self.target or now - self.since > MAX_CHARGE_HOURS * 3600:
            self._reset()
            return ChargeResult(intent, reason, False, None)

        if intent not in CHARGE_INTENTS:
            if reason.startswith(("max_hold", "hold_lockout", "hold_rejected")) or (
                intent not in {"hold", "normal"}
            ):
                self._reset()
                return ChargeResult(intent, reason, False, None)
            intent = self.intent
            reason = "finishing_planned_charge"

        # A production signal (power or on/off) shows the start directly;
        # otherwise a temperature rise is the evidence.
        warmed = producing is True or (
            self.start_temperature is not None
            and temperature >= self.start_temperature + RECOVERY_RISE_C
        )
        if warmed and not self.warmed:
            self.warmed = True
            if self.heating_requested_since is not None:
                self._record_delay((now - self.heating_requested_since) / 60)
        if not self.assist and not self.outcome_recorded:
            if warmed:
                self._record_self_start(True)
            elif now - self.since >= self.assist_after_minutes * 60:
                self._record_self_start(False)
                if not self._assist_allowed():
                    return self._give_up(original_intent, original_reason)
                self.assist = True
                # Extra hot water is requested now; measure the delay from here.
                self.heating_requested_since = now

        # Stall detection: a heat pump's own cycle often stops below the
        # planned target (for example at 51-52 °C when the plan wants 55 °C).
        if self.best_temperature is None or (
            temperature >= self.best_temperature + STALL_RISE_C
        ):
            self.best_temperature = temperature
            self.best_since = now
        elif (
            self.warmed
            and producing is not True
            and self.best_since is not None
            and now - self.best_since >= HEATING_ASSIST_MINUTES * 60
        ):
            if not self.assist and self._assist_allowed():
                self.assist = True
                self.best_since = now
            else:
                # The charge is as complete as this heat pump allows (or
                # extra hot water is not wanted for planned charges).
                return self._give_up(original_intent, original_reason)

        return ChargeResult(intent, reason, self.assist, self.target)

    def _give_up(self, intent: str, reason: str) -> ChargeResult:
        self._reset()
        if intent in CHARGE_INTENTS:
            self.given_up = True
        return ChargeResult(intent, reason, False, None)

    def _record_self_start(self, started: bool) -> None:
        self.outcome_recorded = True
        self.self_start_history = [*self.self_start_history, started][
            -SELF_START_HISTORY:
        ]

    def _record_delay(self, minutes: float) -> None:
        if 0 <= minutes <= 120:
            self.start_delays = [*self.start_delays, minutes][-MAX_START_DELAY_SAMPLES:]

    def _reset(self) -> None:
        self.best_temperature = None
        self.best_since = None
        self.heating_requested_since = None
        self.warmed = False
        self.intent = None
        self.target = None
        self.since = None
        self.start_temperature = None
        self.assist = False
        self.planned = True
        self.outcome_recorded = False

    def as_dict(self) -> dict[str, Any]:
        """Serialize charge state."""
        return {
            "intent": self.intent,
            "target": self.target,
            "since": self.since,
            "start_temperature": self.start_temperature,
            "assist": self.assist,
            "planned": self.planned,
            "pump_starts_on_its_own": self.pump_starts_on_its_own,
            "self_start_history": self.self_start_history,
            "outcome_recorded": self.outcome_recorded,
            "given_up": self.given_up,
            "heating_requested_since": self.heating_requested_since,
            "warmed": self.warmed,
            "start_delays": self.start_delays,
            "best_temperature": self.best_temperature,
            "best_since": self.best_since,
        }

    def restore(self, data: dict[str, Any] | None) -> None:
        """Restore charge state."""
        if not isinstance(data, dict):
            return
        intent = data.get("intent")
        self.intent = intent if intent in CHARGE_INTENTS else None
        self.target = _optional_float(data.get("target"))
        self.since = _optional_float(data.get("since"))
        self.start_temperature = _optional_float(data.get("start_temperature"))
        self.assist = data.get("assist") is True
        self.planned = data.get("planned") is not False
        self.outcome_recorded = data.get("outcome_recorded") is True
        self.given_up = data.get("given_up") is True
        history = data.get("self_start_history")
        if isinstance(history, list):
            self.self_start_history = [
                item for item in history if isinstance(item, bool)
            ][-SELF_START_HISTORY:]
        else:
            # Storage from before the rolling history: keep the old verdict
            # as a single observation so the next charge can overturn it.
            learned = data.get("pump_starts_on_its_own")
            self.self_start_history = [learned] if isinstance(learned, bool) else []
        self.heating_requested_since = _optional_float(
            data.get("heating_requested_since")
        )
        self.warmed = data.get("warmed") is True
        self.best_temperature = _optional_float(data.get("best_temperature"))
        self.best_since = _optional_float(data.get("best_since"))
        delays = data.get("start_delays")
        self.start_delays = (
            [
                float(item)
                for item in delays
                if isinstance(item, int | float) and not isinstance(item, bool)
            ][-MAX_START_DELAY_SAMPLES:]
            if isinstance(delays, list)
            else []
        )


def _optional_float(value: Any) -> float | None:
    """Return a float or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None
