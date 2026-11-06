"""Deterministic DHW decision logic for WaterSteer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DhwThresholds:
    """Temperature thresholds used by the DHW classifier."""

    absolute_minimum: float
    comfort_minimum: float
    normal_target: float
    precharge_target: float

    @property
    def valid(self) -> bool:
        """Return whether the temperature thresholds are strictly ordered."""
        return (
            self.absolute_minimum
            < self.comfort_minimum
            < self.normal_target
            < self.precharge_target
        )


def effective_thresholds(
    configured: DhwThresholds,
    fallback: DhwThresholds,
) -> tuple[DhwThresholds, bool]:
    """Return thresholds safe to act on, and whether the configured set was used.

    An invalid configuration must never disable safety protection. WaterSteer
    then keeps protecting comfort with the built-in defaults while price
    optimization is suspended by the caller.
    """
    if configured.valid:
        return configured, True
    return fallback, False


@dataclass(frozen=True, slots=True)
class DhwDecision:
    """Describe one deterministic shadow-control decision."""

    classification: str
    reason: str
    allowed: bool
    request: bool
    force_request: bool


def classify_dhw_temperature(
    temperature: float | None,
    thresholds: DhwThresholds,
) -> DhwDecision:
    """Classify DHW temperature without executing any physical control."""
    if temperature is None:
        return DhwDecision(
            classification="safety_fallback",
            reason="invalid_temperature",
            allowed=True,
            request=False,
            force_request=False,
        )

    if not thresholds.valid:
        return DhwDecision(
            classification="safety_fallback",
            reason="invalid_threshold_configuration",
            allowed=True,
            request=False,
            force_request=False,
        )

    if temperature <= thresholds.absolute_minimum:
        return DhwDecision(
            classification="force_heat",
            reason="at_or_below_absolute_minimum",
            allowed=True,
            request=True,
            force_request=True,
        )

    if temperature < thresholds.comfort_minimum:
        return DhwDecision(
            classification="comfort_recovery",
            reason="below_comfort_minimum",
            allowed=True,
            request=True,
            force_request=False,
        )

    if temperature < thresholds.normal_target:
        return DhwDecision(
            classification="normal_operation",
            reason="within_comfort_band",
            allowed=True,
            request=False,
            force_request=False,
        )

    return DhwDecision(
        classification="temperature_hold",
        reason="normal_target_reached",
        allowed=False,
        request=False,
        force_request=False,
    )


def apply_thermal_confidence_guard(
    decision: DhwDecision,
    *,
    thermal_confidence: int,
    minimum_confidence: int,
) -> DhwDecision:
    """Prevent DHW braking until the thermal model is sufficiently trusted."""
    if decision.allowed or thermal_confidence >= minimum_confidence:
        return decision

    return DhwDecision(
        classification="learning_guard",
        reason="thermal_confidence_below_minimum",
        allowed=True,
        request=False,
        force_request=False,
    )
