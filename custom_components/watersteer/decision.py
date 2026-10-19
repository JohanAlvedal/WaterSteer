"""Final arbitration: one place that turns WaterSteer's analysis into output.

Order of precedence (highest first):

1. Mode ``off``                → release everything, publish ``normal``.
2. Safety supervisor result    → already contains critical recovery,
                                 escalation, fail-open and hold limits.
3. External heating (iBoost)   → optional pre-heating is dropped while another
                                 heat source is already charging the tank.
4. Optimizer intent            → hold / heat / precharge / boost.

The result is expressed both as the historical ``intent`` and as two physical
levers that match real hardware: *block DHW production* and *request extra hot
water*.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

MODE_ADVISORY = "advisory"
MODE_ACTIVE = "active"
MODE_OFF = "off"
MODES = (MODE_ADVISORY, MODE_ACTIVE, MODE_OFF)

STATUS_OFF = "off"
STATUS_FALLBACK = "fallback"
STATUS_PROTECTING = "protecting"
STATUS_HOLDING = "holding"
STATUS_PREHEATING = "preheating"
STATUS_HEATING = "heating"
STATUS_LEARNING = "learning"
STATUS_ALLOWING = "allowing"
STATUSES = (
    STATUS_OFF,
    STATUS_FALLBACK,
    STATUS_PROTECTING,
    STATUS_HOLDING,
    STATUS_PREHEATING,
    STATUS_HEATING,
    STATUS_LEARNING,
    STATUS_ALLOWING,
)

_FALLBACK_WARNINGS = {
    "dhw_temperature_unavailable",
    "invalid_threshold_configuration",
}


@dataclass(frozen=True, slots=True)
class ControlOutput:
    """Everything a user, an automation or the actuator needs to know."""

    intent: str
    block: bool
    extra_hot_water: bool
    status: str
    explanation: str
    reason: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExplanationContext:
    """Values used to phrase a human-readable explanation."""

    temperature: float | None
    absolute_minimum: float
    comfort_minimum: float
    normal_target: float
    hold_minutes: float | None = None
    max_hold_hours: float | None = None
    next_charge: datetime | None = None
    thermal_confidence: int = 0
    minimum_confidence: int = 0


def arbitrate(
    *,
    mode: str,
    safety_intent: str,
    safety_reason: str,
    warnings: tuple[str, ...],
    external_heating_active: bool,
    optimization_ready: bool,
    context: ExplanationContext,
) -> ControlOutput:
    """Return the single final output for this update cycle."""
    if mode == MODE_OFF:
        return ControlOutput(
            intent="normal",
            block=False,
            extra_hot_water=False,
            status=STATUS_OFF,
            explanation="WaterSteer is switched off; the heat pump runs on its own.",
            reason="mode_off",
            warnings=warnings,
        )

    intent = safety_intent
    reason = safety_reason
    if external_heating_active and intent in {"precharge", "boost"}:
        intent = "normal"
        reason = "external_heating_active"

    status = _status(intent, reason, warnings, optimization_ready)
    return ControlOutput(
        intent=intent,
        block=intent == "hold",
        extra_hot_water=intent in {"force_heat", "boost"},
        status=status,
        explanation=_explain(status, reason, context),
        reason=reason,
        warnings=warnings,
    )


def _status(
    intent: str,
    reason: str,
    warnings: tuple[str, ...],
    optimization_ready: bool,
) -> str:
    if intent == "force_heat":
        return STATUS_PROTECTING
    if _FALLBACK_WARNINGS.intersection(warnings):
        return STATUS_FALLBACK
    if intent == "hold":
        return STATUS_HOLDING
    if intent in {"precharge", "boost"}:
        return STATUS_PREHEATING
    if intent == "heat":
        return STATUS_HEATING
    if not optimization_ready or reason.startswith("fail_open_price_plan_learning"):
        return STATUS_LEARNING
    return STATUS_ALLOWING


def _fmt(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1f} °C"


def _explain(status: str, reason: str, ctx: ExplanationContext) -> str:
    temp = _fmt(ctx.temperature)

    if status == STATUS_PROTECTING:
        if reason == "comfort_recovery_not_progressing":
            return (
                f"Hot water is {temp} and has not recovered on its own; "
                "extra hot water is requested."
            )
        return (
            f"Hot water is {temp}; extra hot water is requested until it is "
            f"back above {_fmt(ctx.comfort_minimum)}."
        )
    if status == STATUS_FALLBACK:
        if ctx.temperature is None:
            return (
                "The hot water temperature is unavailable; the heat pump runs "
                "on its own until it returns."
            )
        return (
            "The temperature limits are not in order; built-in safe limits "
            "are used and price optimization is paused."
        )
    if status == STATUS_HOLDING:
        text = f"Hot water is {temp}, enough to wait for cheaper electricity."
        if ctx.next_charge is not None:
            text += f" Next planned heating {ctx.next_charge:%H:%M}."
        return text
    if status == STATUS_PREHEATING:
        if reason == "normal_precharge_cannot_safely_bridge_peak_with_expected_demand":
            return (
                f"Hot water is {temp}; heating extra before an expensive "
                "period when high use is expected."
            )
        return f"Hot water is {temp}; heating now, before an expensive period."
    if status == STATUS_HEATING:
        if reason == "comfort_recovery_requires_heat":
            return (
                f"Hot water is {temp}, below {_fmt(ctx.comfort_minimum)}; "
                "heating is allowed regardless of price."
            )
        return f"Hot water is {temp}; heating in a cheap period."
    if status == STATUS_LEARNING:
        return (
            f"Hot water is {temp}. Still learning how the tank behaves "
            f"({ctx.thermal_confidence}% of {ctx.minimum_confidence}% needed); "
            "the heat pump runs normally."
        )
    if status == STATUS_OFF:
        return "WaterSteer is switched off; the heat pump runs on its own."
    if reason == "max_hold_duration_reached" or reason.startswith("hold_lockout"):
        return (
            f"Hot water is {temp}. Holding reached its time limit; normal "
            "operation for a while."
        )
    if reason == "external_heating_active":
        return f"Hot water is {temp}; another heat source is already heating."
    return f"Hot water is {temp}; normal operation, nothing to optimize now."
