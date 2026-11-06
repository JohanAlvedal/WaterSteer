"""Tests for the shadow price planner simulation."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from custom_components.watersteer.shadow_planner import TankModel, simulate

NOW = datetime(2026, 1, 5, 0, tzinfo=UTC)


@dataclass
class Slot:
    start: datetime
    end: datetime
    price: float


@dataclass
class Bucket:
    start: datetime
    expected_drop_c: float


def _prices(*hourly: float) -> list[Slot]:
    return [
        Slot(NOW + timedelta(hours=i), NOW + timedelta(hours=i + 1), price)
        for i, price in enumerate(hourly)
    ]


TANK = TankModel(
    loss_c_per_hour=lambda _t: 0.5,
    heating_rate_c_per_hour=8.0,
    comfort_minimum=45.0,
    start_below=47.5,
    stop_at=50.0,
)


def test_holding_through_expensive_hours_saves_without_comfort_breach() -> None:
    """Waiting for the cheap hours is cheaper and keeps the tank above comfort."""
    prices = _prices(*([3.0] * 6 + [0.5] * 6))
    result = simulate(
        now=NOW,
        temperature=49.0,
        tank=TANK,
        price_slots=prices,
        demand=[],
        hold_until=NOW + timedelta(hours=6),
        window_start=NOW + timedelta(hours=6),
        window_end=NOW + timedelta(hours=7),
        window_target=50.0,
    )

    assert result is not None
    assert result.optimized.min_temperature >= 45.0
    assert result.saving_percent > 30


def test_hold_with_expected_demand_breaches_comfort() -> None:
    """A large expected draw during the hold is caught by the simulation."""
    prices = _prices(*([3.0] * 6 + [0.5] * 6))
    demand = [Bucket(NOW + timedelta(hours=2), 6.0)]
    result = simulate(
        now=NOW,
        temperature=49.0,
        tank=TANK,
        price_slots=prices,
        demand=demand,
        hold_until=NOW + timedelta(hours=6),
        window_start=NOW + timedelta(hours=6),
        window_end=NOW + timedelta(hours=7),
        window_target=50.0,
    )

    assert result is not None
    assert result.optimized.min_temperature < 45.0


def test_stored_heat_is_credited() -> None:
    """Ending with a hotter tank is not counted as wasted cost."""
    prices = _prices(*([1.0] * 12))
    result = simulate(
        now=NOW,
        temperature=48.0,
        tank=TANK,
        price_slots=prices,
        demand=[],
        hold_until=None,
        window_start=NOW + timedelta(hours=10),
        window_end=NOW + timedelta(hours=12),
        window_target=55.0,
    )

    assert result is not None
    assert result.saving_percent == pytest.approx(0, abs=15)


def test_no_prices_means_no_simulation() -> None:
    """Without future prices nothing is claimed."""
    assert (
        simulate(
            now=NOW,
            temperature=50.0,
            tank=TANK,
            price_slots=[],
            demand=[],
            hold_until=None,
            window_start=None,
            window_end=None,
            window_target=None,
        )
        is None
    )
