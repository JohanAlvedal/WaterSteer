"""Persistent safety supervisor for WaterSteer control intents.

The supervisor runs after the horizon optimizer and has the final word on the
published control request. It only ever makes the request *safer*:

* it latches critical recovery (``force_heat``) across restarts,
* it escalates a comfort recovery that is not producing any temperature rise,
* it limits how long heating may be held continuously.

All state is plain data so it can be persisted with Home Assistant storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_COMFORT_ESCALATION_MINUTES = 45.0
DEFAULT_MAX_HOLD_HOURS = 6.0
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

        if hold_minutes >= self.max_hold_hours * 60:
            self.hold_since = None
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

    def as_dict(self) -> dict[str, Any]:
        """Serialize supervisor state."""
        return {
            "force_latched": self.force_latched,
            "below_comfort_since": self.below_comfort_since,
            "below_comfort_min_temperature": self.below_comfort_min_temperature,
            "hold_since": self.hold_since,
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
        self.hold_lockout_until = _optional_float(data.get("hold_lockout_until"))


HEATING_ASSIST_MINUTES = 15.0
MAX_CHARGE_HOURS = 3.0
CHARGE_INTENTS = frozenset({"heat", "precharge"})


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
    * If the tank has not started warming within ``HEATING_ASSIST_MINUTES``,
      extra hot water is requested: many heat pumps only start DHW far below
      the planned target, so unblocking alone does nothing.

    Only ever extends heating, so it is applied after the safety supervisor.
    """

    def __init__(self) -> None:
        """Initialize without an active charge."""
        self.intent: str | None = None
        self.target: float | None = None
        self.since: float | None = None
        self.start_temperature: float | None = None
        self.assist = False

    def evaluate(
        self,
        *,
        now: float,
        intent: str,
        reason: str,
        temperature: float | None,
        target_for: dict[str, float],
    ) -> ChargeResult:
        """Return the intent after charge latching and assist."""
        if temperature is None or intent in {"force_heat", "boost"}:
            self._reset()
            return ChargeResult(intent, reason, False, None)

        if intent in CHARGE_INTENTS and self.intent is None:
            self.intent = intent
            self.target = target_for[intent]
            self.since = now
            self.start_temperature = temperature
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

        if (
            not self.assist
            and self.start_temperature is not None
            and now - self.since >= HEATING_ASSIST_MINUTES * 60
            and temperature < self.start_temperature + RECOVERY_RISE_C
        ):
            self.assist = True

        return ChargeResult(intent, reason, self.assist, self.target)

    def _reset(self) -> None:
        self.intent = None
        self.target = None
        self.since = None
        self.start_temperature = None
        self.assist = False

    def as_dict(self) -> dict[str, Any]:
        """Serialize charge state."""
        return {
            "intent": self.intent,
            "target": self.target,
            "since": self.since,
            "start_temperature": self.start_temperature,
            "assist": self.assist,
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


def _optional_float(value: Any) -> float | None:
    """Return a float or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None
