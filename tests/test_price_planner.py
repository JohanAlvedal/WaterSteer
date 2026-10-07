"""Tests for WaterSteer's shadow price planner."""

from datetime import UTC, datetime, timedelta

import pytest
from custom_components.watersteer.price_planner import (
    PriceSlot,
    extract_price_slots,
    plan_price_window,
)


def _slot(start: datetime, price: float, minutes: int = 60) -> PriceSlot:
    """Create one deterministic price slot."""
    return PriceSlot(
        start=start,
        end=start + timedelta(minutes=minutes),
        price=price,
    )


def test_extract_raw_price_items() -> None:
    """Timestamped raw price data is converted to future slots."""
    now = datetime(2026, 10, 2, 8, 30, tzinfo=UTC)
    attributes = {
        "raw_today": [
            {
                "start": "2026-10-02T08:00:00+00:00",
                "end": "2026-10-02T09:00:00+00:00",
                "value": 1.2,
            },
            {
                "start": "2026-10-02T09:00:00+00:00",
                "end": "2026-10-02T10:00:00+00:00",
                "value": 0.5,
            },
        ]
    }

    slots = extract_price_slots(now=now, attributes=attributes)

    assert len(slots) == 2
    assert slots[1].price == pytest.approx(0.5)


def test_extract_numeric_hourly_today_prices() -> None:
    """A 24-value today array is interpreted as hourly prices."""
    now = datetime(2026, 10, 2, 8, 30, tzinfo=UTC)
    attributes = {"today": [float(hour) for hour in range(24)]}

    slots = extract_price_slots(now=now, attributes=attributes)

    assert slots
    assert slots[0].end > now
    assert slots[0].price == pytest.approx(8.0)


def test_low_confidence_prevents_price_planning() -> None:
    """The planner must remain in learning mode below confidence threshold."""
    now = datetime(2026, 10, 2, 8, tzinfo=UTC)
    result = plan_price_window(
        now=now,
        current_temperature=48.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        predicted_autonomy_minutes=360.0,
        autonomy_confidence=30,
        heating_rate_c_per_hour=4.0,
        current_price=1.5,
        price_slots=(_slot(now, 1.5), _slot(now + timedelta(hours=1), 0.5)),
        minimum_confidence=50,
    )

    assert result.status == "learning"
    assert result.reason == "autonomy_confidence_below_minimum"
    assert result.next_charge is None


def test_cheapest_safe_future_window_creates_price_hold() -> None:
    """A cheaper safe future window produces a shadow price hold."""
    now = datetime(2026, 10, 2, 8, tzinfo=UTC)
    result = plan_price_window(
        now=now,
        current_temperature=48.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        predicted_autonomy_minutes=360.0,
        autonomy_confidence=80,
        heating_rate_c_per_hour=4.0,
        current_price=1.5,
        price_slots=(
            _slot(now, 1.5),
            _slot(now + timedelta(hours=1), 1.2),
            _slot(now + timedelta(hours=2), 0.4),
            _slot(now + timedelta(hours=3), 0.7),
        ),
        minimum_confidence=50,
    )

    assert result.status == "price_hold"
    assert result.reason == "safe_to_wait_for_selected_price_window"
    assert result.next_charge == now + timedelta(hours=2)
    assert result.selected_price == pytest.approx(0.4)
    assert result.savings_vs_current == pytest.approx(1.1)


def test_current_selected_window_is_shadow_charge_window() -> None:
    """The planner reports when the selected safe window is active now."""
    now = datetime(2026, 10, 2, 8, tzinfo=UTC)
    result = plan_price_window(
        now=now,
        current_temperature=48.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        predicted_autonomy_minutes=180.0,
        autonomy_confidence=80,
        heating_rate_c_per_hour=4.0,
        current_price=0.3,
        price_slots=(
            _slot(now, 0.3),
            _slot(now + timedelta(hours=1), 1.2),
        ),
        minimum_confidence=50,
    )

    assert result.status == "price_charge_window"
    assert result.window_active_now is True
    assert result.next_charge == now


def test_cheap_price_does_not_force_charge_above_normal_target() -> None:
    """Cheap electricity alone must not create a DHW charge request."""
    now = datetime(2026, 10, 2, 8, tzinfo=UTC)
    result = plan_price_window(
        now=now,
        current_temperature=52.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        predicted_autonomy_minutes=600.0,
        autonomy_confidence=80,
        heating_rate_c_per_hour=4.0,
        current_price=0.1,
        price_slots=(
            _slot(now, 0.1),
            _slot(now + timedelta(hours=1), 0.2),
        ),
        minimum_confidence=50,
    )

    assert result.status == "temperature_hold"
    assert result.reason == "normal_target_satisfied_future_window_planned"


def test_comfort_minimum_overrides_price() -> None:
    """Comfort recovery must override any future cheap-price opportunity."""
    now = datetime(2026, 10, 2, 8, tzinfo=UTC)
    result = plan_price_window(
        now=now,
        current_temperature=44.5,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        predicted_autonomy_minutes=0.0,
        autonomy_confidence=80,
        heating_rate_c_per_hour=4.0,
        current_price=2.0,
        price_slots=(_slot(now + timedelta(hours=1), 0.1),),
        minimum_confidence=50,
    )

    assert result.status == "comfort_recovery"
    assert result.next_charge is None
    assert result.window_active_now is True


def test_missing_future_prices_is_explicit() -> None:
    """The planner must not invent a window when future prices are unavailable."""
    now = datetime(2026, 10, 2, 8, tzinfo=UTC)
    result = plan_price_window(
        now=now,
        current_temperature=48.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        predicted_autonomy_minutes=360.0,
        autonomy_confidence=80,
        heating_rate_c_per_hour=4.0,
        current_price=1.5,
        price_slots=(),
        minimum_confidence=50,
    )

    assert result.status == "unavailable"
    assert result.reason == "future_prices_unavailable"


def test_peak_precharge_is_selected_when_margin_cannot_bridge_peak() -> None:
    """WaterSteer precharges before a peak when safe margin would otherwise expire."""
    now = datetime(2026, 10, 2, 15, tzinfo=UTC)
    slots = (
        _slot(now, 0.6),
        _slot(now + timedelta(hours=1), 0.7),
        _slot(now + timedelta(hours=2), 2.5),
        _slot(now + timedelta(hours=3), 2.7),
        _slot(now + timedelta(hours=4), 0.8),
    )

    result = plan_price_window(
        now=now,
        current_temperature=49.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        predicted_autonomy_minutes=210.0,
        autonomy_confidence=90,
        heating_rate_c_per_hour=12.0,
        current_price=0.6,
        price_slots=slots,
        minimum_confidence=50,
    )

    assert result.status == "peak_precharge"
    assert result.reason == "precharge_needed_to_bridge_price_peak"
    assert result.next_charge is not None
    assert result.next_charge < now + timedelta(hours=2)
    assert result.planned_target == pytest.approx(55.0)
    assert result.peak_avoidance_active is True
    assert result.next_peak_start == now + timedelta(hours=2)


def test_peak_slots_are_avoided_when_margin_can_bridge_peak() -> None:
    """A safe margin that spans the peak keeps normal planning out of peak slots."""
    now = datetime(2026, 10, 2, 15, tzinfo=UTC)
    slots = (
        _slot(now, 0.9),
        _slot(now + timedelta(hours=1), 0.8),
        _slot(now + timedelta(hours=2), 2.4),
        _slot(now + timedelta(hours=3), 2.6),
        _slot(now + timedelta(hours=4), 0.5),
        _slot(now + timedelta(hours=5), 0.6),
    )

    result = plan_price_window(
        now=now,
        current_temperature=48.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
        predicted_autonomy_minutes=420.0,
        autonomy_confidence=90,
        heating_rate_c_per_hour=12.0,
        current_price=0.9,
        price_slots=slots,
        minimum_confidence=50,
    )

    assert result.next_charge is not None
    assert not (
        now + timedelta(hours=2)
        <= result.next_charge
        < now + timedelta(hours=4)
    )
    assert result.peak_avoidance_active is True
