"""Tests for WaterSteer's explainable DHW usage model."""

from datetime import UTC, datetime, timedelta

import pytest
from custom_components.watersteer.usage_model import DhwUsageModel


def _weekday(week: int, hour: int) -> datetime:
    """Return the same weekday in successive weeks."""
    return datetime(2026, 9, 28, hour, tzinfo=UTC) + timedelta(weeks=week)


def test_large_temperature_drop_creates_usage_event() -> None:
    """A rapid unexplained drop is learned as probable DHW usage."""
    model = DhwUsageModel()
    start = _weekday(0, 7)

    model.add_observation(
        timestamp=start.timestamp(),
        temperature=52.0,
        local_datetime=start,
        heating_active=False,
    )
    later = start + timedelta(minutes=5)
    model.add_observation(
        timestamp=later.timestamp(),
        temperature=49.0,
        local_datetime=later,
        heating_active=False,
    )

    estimate = model.estimate(now_local=later, occupancy=True)

    assert estimate.usage_detected is True
    assert estimate.event_count == 1
    assert estimate.typical_usage_drop == pytest.approx(3.0)


def test_heating_signal_prevents_false_usage_event() -> None:
    """Temperature movement while heating is active is not usage learning."""
    model = DhwUsageModel()
    start = _weekday(0, 7)

    model.add_observation(
        timestamp=start.timestamp(),
        temperature=52.0,
        local_datetime=start,
        heating_active=True,
    )
    later = start + timedelta(minutes=5)
    model.add_observation(
        timestamp=later.timestamp(),
        temperature=49.0,
        local_datetime=later,
        heating_active=True,
    )

    estimate = model.estimate(now_local=later, occupancy=True)

    assert estimate.event_count == 0
    assert estimate.usage_detected is False


def test_weekday_profile_learns_repeated_morning_usage() -> None:
    """Repeated weekday morning events raise the near-term probability."""
    model = DhwUsageModel()

    for week in range(5):
        start = _weekday(week, 7)
        model.add_observation(
            timestamp=start.timestamp(),
            temperature=52.0,
            local_datetime=start,
            heating_active=False,
        )
        later = start + timedelta(minutes=5)
        model.add_observation(
            timestamp=later.timestamp(),
            temperature=49.0,
            local_datetime=later,
            heating_active=False,
        )

    now = _weekday(5, 7)
    estimate = model.estimate(now_local=now, occupancy=True)

    assert estimate.usage_probability_next_6h > 0
    assert estimate.next_expected_usage is not None
    assert estimate.confidence > 0


def test_away_state_reduces_probability() -> None:
    """Optional occupancy state reduces demand probability while away."""
    model = DhwUsageModel()

    for week in range(5):
        start = _weekday(week, 7)
        model.add_observation(
            timestamp=start.timestamp(),
            temperature=52.0,
            local_datetime=start,
            heating_active=False,
        )
        later = start + timedelta(minutes=5)
        model.add_observation(
            timestamp=later.timestamp(),
            temperature=49.0,
            local_datetime=later,
            heating_active=False,
        )

    now = _weekday(5, 7)
    home = model.estimate(now_local=now, occupancy=True)
    away = model.estimate(now_local=now, occupancy=False)

    assert away.usage_probability_next_6h < home.usage_probability_next_6h
    assert away.occupancy_state == "away"


def test_serialization_round_trip() -> None:
    """Usage history survives Home Assistant restarts."""
    model = DhwUsageModel()
    start = _weekday(0, 18)
    model.add_observation(
        timestamp=start.timestamp(),
        temperature=53.0,
        local_datetime=start,
        heating_active=False,
    )
    later = start + timedelta(minutes=5)
    model.add_observation(
        timestamp=later.timestamp(),
        temperature=50.0,
        local_datetime=later,
        heating_active=False,
    )

    restored = DhwUsageModel()
    restored.restore(model.as_dict())
    estimate = restored.estimate(now_local=later, occupancy=None)

    assert estimate.event_count == 1
    assert estimate.typical_usage_drop == pytest.approx(3.0)
