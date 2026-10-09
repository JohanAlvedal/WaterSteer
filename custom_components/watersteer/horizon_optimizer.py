"""Demand-aware horizon optimization for WaterSteer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .demand_predictor import DemandForecast
from .price_planner import PricePlan

MIN_OPTIMIZER_CONFIDENCE = 50
BOOST_MIN_DEMAND_CONFIDENCE = 50
BOOST_MIN_PROBABILITY = 0.55
BOOST_MIN_EXPECTED_DROP_C = 2.5
BOOST_RESERVE_MINUTES = 30.0


@dataclass(frozen=True, slots=True)
class HorizonDecision:
    """One explainable current control intent from the rolling horizon."""

    intent: str
    reason: str
    confidence: int
    demand_risk: float
    demand_expected_drop_c: float
    normal_precharge_margin_minutes: float | None
    boost_recommended: bool


def optimize_horizon(
    *,
    now: datetime,
    current_temperature: float | None,
    comfort_minimum: float,
    normal_target: float,
    precharge_target: float,
    safe_margin_minutes: float | None,
    safe_margin_confidence: int,
    demand: DemandForecast,
    occupancy: bool | None,
    price_plan: PricePlan,
    price_input_valid: bool,
    safety_allowed: bool,
    safety_request: bool,
    safety_force_request: bool,
) -> HorizonDecision:
    """Choose the current advisory intent using safety, demand, and prices."""
    if current_temperature is None:
        return _decision(
            "normal",
            "fail_open_missing_temperature",
            safe_margin_confidence,
            demand,
        )

    if not price_input_valid:
        return _decision(
            "normal",
            "fail_open_missing_price_input",
            safe_margin_confidence,
            demand,
        )

    if safety_force_request:
        return _decision(
            "force_heat",
            "absolute_minimum_requires_immediate_heat",
            safe_margin_confidence,
            demand,
        )

    if safety_request:
        return _decision(
            "heat",
            "comfort_recovery_requires_heat",
            safe_margin_confidence,
            demand,
        )

    if safe_margin_confidence < MIN_OPTIMIZER_CONFIDENCE:
        return _decision(
            "normal",
            "fail_open_low_margin_confidence",
            safe_margin_confidence,
            demand,
        )

    if price_plan.status in {"unavailable", "learning"}:
        return _decision(
            "normal",
            f"fail_open_price_plan_{price_plan.status}",
            safe_margin_confidence,
            demand,
        )

    if price_plan.status == "peak_precharge":
        if current_temperature >= precharge_target:
            return _decision(
                "hold" if not safety_allowed else "normal",
                "precharge_target_already_satisfied",
                safe_margin_confidence,
                demand,
            )

        if not price_plan.window_active_now:
            return _decision(
                "hold",
                "waiting_for_planned_precharge_window",
                safe_margin_confidence,
                demand,
            )

        boost, normal_margin, risk, expected_drop = _boost_needed(
            now=now,
            current_temperature=current_temperature,
            comfort_minimum=comfort_minimum,
            normal_target=normal_target,
            precharge_target=precharge_target,
            safe_margin_minutes=safe_margin_minutes,
            demand=demand,
            occupancy=occupancy,
            peak_end=price_plan.next_peak_end,
        )
        if boost:
            return HorizonDecision(
                intent="boost",
                reason="normal_precharge_cannot_safely_bridge_peak_with_expected_demand",
                confidence=min(safe_margin_confidence, demand.confidence),
                demand_risk=risk,
                demand_expected_drop_c=expected_drop,
                normal_precharge_margin_minutes=normal_margin,
                boost_recommended=True,
            )

        return HorizonDecision(
            intent="precharge",
            reason="planned_precharge_window_active",
            confidence=safe_margin_confidence,
            demand_risk=risk,
            demand_expected_drop_c=expected_drop,
            normal_precharge_margin_minutes=normal_margin,
            boost_recommended=False,
        )

    if price_plan.status == "price_charge_window":
        return _decision(
            "heat",
            "selected_price_window_active",
            safe_margin_confidence,
            demand,
        )

    if price_plan.status in {"price_hold", "temperature_hold"}:
        return _decision(
            "hold",
            "safe_to_hold_for_price_plan",
            safe_margin_confidence,
            demand,
        )

    if not safety_allowed:
        return _decision(
            "hold",
            "normal_target_satisfied",
            safe_margin_confidence,
            demand,
        )

    return _decision(
        "normal",
        "no_optimized_action_required",
        safe_margin_confidence,
        demand,
    )


def _boost_needed(
    *,
    now: datetime,
    current_temperature: float,
    comfort_minimum: float,
    normal_target: float,
    precharge_target: float,
    safe_margin_minutes: float | None,
    demand: DemandForecast,
    occupancy: bool | None,
    peak_end: datetime | None,
) -> tuple[bool, float | None, float, float]:
    """Return whether extraordinary boost is justified as a last resort."""
    if (
        occupancy is not True
        or demand.confidence < BOOST_MIN_DEMAND_CONFIDENCE
        or safe_margin_minutes is None
        or peak_end is None
        or current_temperature >= normal_target
    ):
        risk, expected_drop = _demand_before(demand, peak_end)
        return False, None, risk, expected_drop

    risk, expected_drop = _demand_before(demand, peak_end)
    high_demand = (
        risk >= BOOST_MIN_PROBABILITY
        or expected_drop >= BOOST_MIN_EXPECTED_DROP_C
    )
    if not high_demand:
        return False, None, risk, expected_drop

    thermal_band = max(1.0, current_temperature - comfort_minimum)
    minutes_per_degree = safe_margin_minutes / thermal_band
    normal_gain = max(0.0, precharge_target - current_temperature) * minutes_per_degree
    demand_penalty = expected_drop * minutes_per_degree
    normal_margin = max(
        0.0,
        safe_margin_minutes + normal_gain - demand_penalty,
    )
    minutes_to_peak_end = max(0.0, (peak_end - now).total_seconds() / 60)

    boost_needed = normal_margin < minutes_to_peak_end + BOOST_RESERVE_MINUTES
    return boost_needed, normal_margin, risk, expected_drop


def _demand_before(
    demand: DemandForecast,
    end: datetime,
) -> tuple[float, float]:
    """Summarize demand forecast up to the end of the relevant price peak."""
    buckets = [bucket for bucket in demand.buckets if bucket.start < end]
    probability = max((bucket.probability for bucket in buckets), default=0.0)
    expected_drop = sum(bucket.expected_drop_c for bucket in buckets)
    return probability, expected_drop


def _decision(
    intent: str,
    reason: str,
    confidence: int,
    demand: DemandForecast,
) -> HorizonDecision:
    """Return a simple horizon decision with common demand diagnostics."""
    return HorizonDecision(
        intent=intent,
        reason=reason,
        confidence=confidence,
        demand_risk=demand.peak_probability,
        demand_expected_drop_c=demand.expected_drop_c,
        normal_precharge_margin_minutes=None,
        boost_recommended=False,
    )
