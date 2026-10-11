"""Tests for WaterSteer's demand-aware horizon optimizer."""

from datetime import UTC, datetime, timedelta

from custom_components.watersteer.demand_predictor import (
    DemandBucket,
    DemandForecast,
)
from custom_components.watersteer.horizon_optimizer import optimize_horizon
from custom_components.watersteer.price_planner import PricePlan


def _demand(
    now: datetime,
    *,
    probability: float,
    drop: float,
    confidence: int = 80,
) -> DemandForecast:
    buckets = tuple(
        DemandBucket(
            start=now + timedelta(hours=offset),
            probability=probability,
            expected_drop_c=drop,
        )
        for offset in range(4)
    )
    return DemandForecast(
        backend="statistical",
        confidence=confidence,
        buckets=buckets,
        peak_probability=probability,
        expected_drop_c=drop * len(buckets),
        high_demand_hours=sum(probability >= 0.55 for _ in buckets),
    )


def _plan(
    now: datetime,
    *,
    status: str,
    active: bool,
) -> PricePlan:
    return PricePlan(
        status=status,
        reason="test",
        next_charge=now if active else now + timedelta(hours=1),
        charge_end=now + timedelta(hours=2),
        expected_charge_minutes=30.0,
        planned_target=55.0,
        selected_price=0.5,
        current_price=0.5,
        savings_vs_current=0.0,
        price_slot_count=8,
        planning_deadline=now + timedelta(hours=2),
        confidence=90,
        window_active_now=active,
        next_peak_start=now + timedelta(hours=1),
        next_peak_end=now + timedelta(hours=4),
        next_peak_price=2.5,
        peak_avoidance_active=True,
    )


def test_missing_temperature_fails_open() -> None:
    """Missing thermal input must never result in blocking."""
    now = datetime(2026, 10, 9, 12, tzinfo=UTC)
    result = optimize_horizon(
        now=now,
        current_temperature=None,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        safe_margin_minutes=None,
        safe_margin_confidence=0,
        demand=_demand(now, probability=0.8, drop=2.0),
        occupancy=True,
        price_plan=_plan(now, status="price_hold", active=False),
        price_input_valid=True,
        safety_allowed=True,
        safety_request=False,
        safety_force_request=False,
    )

    assert result.intent == "normal"
    assert result.reason == "fail_open_missing_temperature"


def test_missing_price_fails_open() -> None:
    """Missing live price input must never result in blocking."""
    now = datetime(2026, 10, 9, 12, tzinfo=UTC)
    result = optimize_horizon(
        now=now,
        current_temperature=52.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        safe_margin_minutes=400.0,
        safe_margin_confidence=90,
        demand=_demand(now, probability=0.1, drop=0.1),
        occupancy=True,
        price_plan=_plan(now, status="price_hold", active=False),
        price_input_valid=False,
        safety_allowed=False,
        safety_request=False,
        safety_force_request=False,
    )

    assert result.intent == "normal"


def test_future_precharge_window_does_not_precharge_early() -> None:
    """A planned future precharge remains a hold until its window starts."""
    now = datetime(2026, 10, 9, 12, tzinfo=UTC)
    result = optimize_horizon(
        now=now,
        current_temperature=48.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        safe_margin_minutes=180.0,
        safe_margin_confidence=90,
        demand=_demand(now, probability=0.3, drop=0.2),
        occupancy=True,
        price_plan=_plan(now, status="peak_precharge", active=False),
        price_input_valid=True,
        safety_allowed=True,
        safety_request=False,
        safety_force_request=False,
    )

    assert result.intent == "hold"
    assert result.reason == "waiting_for_planned_precharge_window"


def test_away_home_never_uses_extra_boost() -> None:
    """Extra-hot-water boost is suppressed while explicitly away."""
    now = datetime(2026, 10, 9, 12, tzinfo=UTC)
    result = optimize_horizon(
        now=now,
        current_temperature=47.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        safe_margin_minutes=90.0,
        safe_margin_confidence=90,
        demand=_demand(now, probability=0.9, drop=1.0),
        occupancy=False,
        price_plan=_plan(now, status="peak_precharge", active=True),
        price_input_valid=True,
        safety_allowed=True,
        safety_request=False,
        safety_force_request=False,
    )

    assert result.intent == "precharge"
    assert result.boost_recommended is False


def test_boost_is_last_resort_for_high_home_demand() -> None:
    """Boost is allowed only when normal precharge cannot bridge a risky peak."""
    now = datetime(2026, 10, 9, 12, tzinfo=UTC)
    result = optimize_horizon(
        now=now,
        current_temperature=47.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        safe_margin_minutes=60.0,
        safe_margin_confidence=90,
        demand=_demand(now, probability=0.9, drop=1.5),
        occupancy=True,
        price_plan=_plan(now, status="peak_precharge", active=True),
        price_input_valid=True,
        safety_allowed=True,
        safety_request=False,
        safety_force_request=False,
    )

    assert result.intent == "boost"
    assert result.boost_recommended is True


def test_force_heat_remains_normal_heat_not_extra_boost() -> None:
    """Safety force bypasses price but does not imply an extraordinary boost."""
    now = datetime(2026, 10, 9, 12, tzinfo=UTC)
    result = optimize_horizon(
        now=now,
        current_temperature=39.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        safe_margin_minutes=0.0,
        safe_margin_confidence=90,
        demand=_demand(now, probability=0.9, drop=2.0),
        occupancy=True,
        price_plan=_plan(now, status="peak_precharge", active=True),
        price_input_valid=True,
        safety_allowed=True,
        safety_request=True,
        safety_force_request=True,
    )

    assert result.intent == "force_heat"
    assert result.boost_recommended is False


def test_force_heat_overrides_missing_price_input() -> None:
    """Critical DHW temperature must override missing price data."""
    now = datetime(2026, 10, 9, 12, tzinfo=UTC)
    result = optimize_horizon(
        now=now,
        current_temperature=39.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        safe_margin_minutes=0.0,
        safe_margin_confidence=90,
        demand=_demand(now, probability=0.1, drop=0.1),
        occupancy=True,
        price_plan=_plan(now, status="unavailable", active=False),
        price_input_valid=False,
        safety_allowed=True,
        safety_request=True,
        safety_force_request=True,
    )

    assert result.intent == "force_heat"
    assert result.reason == "absolute_minimum_requires_immediate_heat"


def test_price_hold_below_normal_target_fails_open_to_normal() -> None:
    """Physical blocking is not allowed below the configured normal target."""
    now = datetime(2026, 10, 11, 12, tzinfo=UTC)
    result = optimize_horizon(
        now=now,
        current_temperature=48.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        safe_margin_minutes=240.0,
        safe_margin_confidence=90,
        demand=_demand(now, probability=0.1, drop=0.1),
        occupancy=True,
        price_plan=_plan(now, status="price_hold", active=False),
        price_input_valid=True,
        safety_allowed=True,
        safety_request=False,
        safety_force_request=False,
    )

    assert result.intent == "normal"
    assert result.reason == "hold_guard_below_normal_target"


def test_waiting_precharge_below_normal_target_does_not_block() -> None:
    """Waiting for a future precharge window must not block a cooling tank."""
    now = datetime(2026, 10, 11, 12, tzinfo=UTC)
    result = optimize_horizon(
        now=now,
        current_temperature=48.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        safe_margin_minutes=240.0,
        safe_margin_confidence=90,
        demand=_demand(now, probability=0.2, drop=0.1),
        occupancy=True,
        price_plan=_plan(now, status="peak_precharge", active=False),
        price_input_valid=True,
        safety_allowed=True,
        safety_request=False,
        safety_force_request=False,
    )

    assert result.intent == "normal"
    assert result.reason == "precharge_wait_below_normal_target"
