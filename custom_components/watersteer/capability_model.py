"""Capability-based DHW margin estimation for WaterSteer."""

from __future__ import annotations

from dataclasses import dataclass

MIN_USAGE_CONFIDENCE_FOR_MARGIN_ADJUSTMENT = 50


@dataclass(frozen=True, slots=True)
class MarginEstimate:
    """Unified estimate of how long DHW can safely coast."""

    minutes: float | None
    confidence: int
    source: str
    usage_adjusted: bool
    usage_confidence: int
    reason: str


def estimate_safe_margin(
    *,
    passive_autonomy_minutes: float | None,
    predicted_autonomy_minutes: float | None,
    thermal_confidence: int,
    usage_confidence: int,
    cycle_margin_minutes: float | None = None,
    cycle_confidence: int = 0,
    simple_margin_minutes: float | None = None,
    simple_confidence: int = 0,
) -> MarginEstimate:
    """Choose the best available DHW margin estimate.

    Thermal autonomy is the preferred source when available. Usage learning may
    reduce that margin only after it has reached its own confidence threshold.
    A weak optional usage model must never reduce confidence in a strong thermal
    model.

    Cycle and simple estimates share the same interface and can take over when
    temperature data is unavailable.
    """
    if passive_autonomy_minutes is not None and thermal_confidence > 0:
        if (
            predicted_autonomy_minutes is not None
            and usage_confidence >= MIN_USAGE_CONFIDENCE_FOR_MARGIN_ADJUSTMENT
        ):
            return MarginEstimate(
                minutes=min(passive_autonomy_minutes, predicted_autonomy_minutes),
                confidence=thermal_confidence,
                source="thermal",
                usage_adjusted=True,
                usage_confidence=usage_confidence,
                reason="thermal_margin_with_trusted_usage_adjustment",
            )

        return MarginEstimate(
            minutes=passive_autonomy_minutes,
            confidence=thermal_confidence,
            source="thermal",
            usage_adjusted=False,
            usage_confidence=usage_confidence,
            reason="thermal_margin_usage_not_trusted",
        )

    if cycle_margin_minutes is not None and cycle_confidence > 0:
        return MarginEstimate(
            minutes=cycle_margin_minutes,
            confidence=cycle_confidence,
            source="cycle",
            usage_adjusted=False,
            usage_confidence=usage_confidence,
            reason="cycle_margin",
        )

    if simple_margin_minutes is not None and simple_confidence > 0:
        return MarginEstimate(
            minutes=simple_margin_minutes,
            confidence=simple_confidence,
            source="simple",
            usage_adjusted=False,
            usage_confidence=usage_confidence,
            reason="simple_margin",
        )

    return MarginEstimate(
        minutes=None,
        confidence=0,
        source="unavailable",
        usage_adjusted=False,
        usage_confidence=usage_confidence,
        reason="no_margin_estimator_available",
    )
