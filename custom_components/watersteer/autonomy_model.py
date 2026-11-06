"""Demand-adjusted DHW autonomy prediction for WaterSteer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

MIN_USAGE_CONFIDENCE_FOR_DEMAND = 20
MAX_AUTONOMY_HOURS = 48.0


class ForecastBucket(Protocol):
    """Minimal usage-forecast interface required by the autonomy model."""

    start: datetime
    expected_drop_c: float


@dataclass(frozen=True, slots=True)
class AutonomyEstimate:
    """Predicted time until the DHW comfort minimum is reached."""

    passive_minutes: float | None
    predicted_minutes: float | None
    predicted_temperature_6h: float | None
    confidence: int
    basis: str
    demand_adjusted: bool


def estimate_autonomy(
    *,
    current_temperature: float | None,
    comfort_minimum: float,
    standby_loss_c_per_hour: float | None,
    thermal_confidence: int,
    usage_confidence: int,
    usage_forecast: tuple[ForecastBucket, ...],
) -> AutonomyEstimate:
    """Estimate passive and learned-demand-adjusted DHW autonomy.

    Demand is only included after usage learning has reached a minimum
    confidence. Until then, WaterSteer exposes thermal-only autonomy.
    """
    if (
        current_temperature is None
        or standby_loss_c_per_hour is None
        or standby_loss_c_per_hour <= 0
    ):
        return AutonomyEstimate(
            passive_minutes=None,
            predicted_minutes=None,
            predicted_temperature_6h=None,
            confidence=0,
            basis="insufficient_thermal_data",
            demand_adjusted=False,
        )

    if current_temperature <= comfort_minimum:
        return AutonomyEstimate(
            passive_minutes=0.0,
            predicted_minutes=0.0,
            predicted_temperature_6h=current_temperature,
            confidence=thermal_confidence,
            basis="comfort_floor_reached",
            demand_adjusted=False,
        )

    passive_hours = min(
        MAX_AUTONOMY_HOURS,
        (current_temperature - comfort_minimum) / standby_loss_c_per_hour,
    )
    passive_minutes = passive_hours * 60

    if usage_confidence < MIN_USAGE_CONFIDENCE_FOR_DEMAND or not usage_forecast:
        projected_6h = max(
            comfort_minimum,
            current_temperature - standby_loss_c_per_hour * 6,
        )
        return AutonomyEstimate(
            passive_minutes=passive_minutes,
            predicted_minutes=passive_minutes,
            predicted_temperature_6h=projected_6h,
            confidence=thermal_confidence,
            basis="thermal_only",
            demand_adjusted=False,
        )

    temperature = current_temperature
    elapsed_hours = 0.0
    predicted_hours: float | None = None

    for bucket in usage_forecast:
        expected_drop = max(0.0, float(bucket.expected_drop_c))
        temperature -= expected_drop

        if temperature <= comfort_minimum:
            predicted_hours = elapsed_hours
            temperature = comfort_minimum
            break

        after_passive = temperature - standby_loss_c_per_hour
        if after_passive <= comfort_minimum:
            remaining_c = temperature - comfort_minimum
            predicted_hours = elapsed_hours + remaining_c / standby_loss_c_per_hour
            temperature = comfort_minimum
            break

        temperature = after_passive
        elapsed_hours += 1.0

    predicted_temperature_6h = temperature

    if predicted_hours is None:
        remaining_c = temperature - comfort_minimum
        additional_hours = remaining_c / standby_loss_c_per_hour
        predicted_hours = min(
            MAX_AUTONOMY_HOURS,
            elapsed_hours + additional_hours,
        )

    return AutonomyEstimate(
        passive_minutes=passive_minutes,
        predicted_minutes=predicted_hours * 60,
        predicted_temperature_6h=predicted_temperature_6h,
        confidence=min(thermal_confidence, usage_confidence),
        basis="thermal_and_learned_demand",
        demand_adjusted=True,
    )
