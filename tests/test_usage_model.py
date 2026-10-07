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


def test_consecutive_drop_segments_are_grouped_as_one_draw() -> None:
    """A long draw is learned as one event instead of repeated events."""
    model = DhwUsageModel()
    start = _weekday(0, 7)

    for minutes, temperature in ((0, 54.0), (5, 51.5), (10, 48.5)):
        moment = start + timedelta(minutes=minutes)
        model.add_observation(
            timestamp=moment.timestamp(),
            temperature=temperature,
            local_datetime=moment,
            heating_active=False,
        )

    estimate = model.estimate(
        now_local=start + timedelta(minutes=10),
        occupancy=True,
    )

    assert estimate.event_count == 1
    assert estimate.typical_usage_drop == pytest.approx(5.5)
    assert estimate.medium_event_count == 1


def test_large_grouped_draw_is_classified_as_large() -> None:
    """Grouped temperature impact is classified after segments are merged."""
    model = DhwUsageModel()
    start = _weekday(0, 18)

    for minutes, temperature in ((0, 56.0), (5, 52.0), (10, 49.0)):
        moment = start + timedelta(minutes=minutes)
        model.add_observation(
            timestamp=moment.timestamp(),
            temperature=temperature,
            local_datetime=moment,
            heating_active=False,
        )

    estimate = model.estimate(
        now_local=start + timedelta(minutes=10),
        occupancy=True,
    )

    assert estimate.event_count == 1
    assert estimate.large_event_count == 1
    assert estimate.typical_usage_drop == pytest.approx(7.0)


def test_forecast_exposes_probability_and_expected_thermal_impact() -> None:
    """Repeated demand creates an explainable hourly six-hour forecast."""
    model = DhwUsageModel()

    for week in range(5):
        start = _weekday(week, 7)
        model.add_observation(
            timestamp=start.timestamp(),
            temperature=53.0,
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

    assert len(estimate.forecast) == 6
    assert estimate.forecast[0].probability > 0
    assert estimate.forecast[0].typical_drop_c == pytest.approx(4.0)
    assert estimate.expected_usage_drop_next_6h > 0
    assert estimate.next_expected_usage_probability is not None
    assert estimate.next_expected_usage_drop == pytest.approx(4.0)
    assert estimate.demand_level in {"medium", "high"}


def test_confidence_uses_relevant_day_type_exposure() -> None:
    """Weekday observations do not falsely create weekend confidence."""
    model = DhwUsageModel()

    for week in range(5):
        start = _weekday(week, 12)
        model.add_observation(
            timestamp=start.timestamp(),
            temperature=52.0,
            local_datetime=start,
            heating_active=False,
        )

    weekday_estimate = model.estimate(
        now_local=_weekday(5, 12),
        occupancy=True,
    )
    weekend = datetime(2026, 10, 3, 12, tzinfo=UTC)
    weekend_estimate = model.estimate(now_local=weekend, occupancy=True)

    assert weekday_estimate.confidence > 0
    assert weekend_estimate.confidence == 0
    assert weekend_estimate.relevant_observed_days == 0


def test_restore_accepts_legacy_events_without_grouping_fields() -> None:
    """Stored data from the first usage model version remains loadable."""
    start = _weekday(0, 7)
    model = DhwUsageModel()
    model.restore(
        {
            "samples": [],
            "events": [
                {
                    "timestamp": start.timestamp(),
                    "day_type": "weekday",
                    "hour": 7,
                    "date_key": start.date().isoformat(),
                    "drop_c": 6.5,
                }
            ],
        }
    )

    estimate = model.estimate(now_local=start, occupancy=None)

    assert estimate.event_count == 1
    assert estimate.large_event_count == 1


def test_early_recovery_cycle_creates_usage_event() -> None:
    """An unexpectedly early recovery cycle is learned as probable DHW usage."""
    model = DhwUsageModel()
    start = _weekday(0, 6)

    model.add_observation(
        timestamp=start.timestamp(),
        temperature=55.0,
        local_datetime=start,
        heating_active=True,
        standby_loss_c_per_hour=0.5,
    )
    baseline = start + timedelta(minutes=5)
    model.add_observation(
        timestamp=baseline.timestamp(),
        temperature=55.0,
        local_datetime=baseline,
        heating_active=False,
        standby_loss_c_per_hour=0.5,
    )
    before_recovery = baseline + timedelta(hours=2)
    model.add_observation(
        timestamp=before_recovery.timestamp(),
        temperature=53.0,
        local_datetime=before_recovery,
        heating_active=False,
        standby_loss_c_per_hour=0.5,
    )
    recovery = before_recovery + timedelta(minutes=5)
    model.add_observation(
        timestamp=recovery.timestamp(),
        temperature=53.0,
        local_datetime=recovery,
        heating_active=True,
        standby_loss_c_per_hour=0.5,
    )

    estimate = model.estimate(now_local=recovery, occupancy=True)

    assert estimate.event_count == 1
    assert estimate.recovery_event_count == 1
    assert estimate.direct_event_count == 0
    assert estimate.usage_detected is True


def test_normal_passive_recovery_is_not_usage() -> None:
    """A recovery cycle consistent with learned standby loss is not usage."""
    model = DhwUsageModel()
    start = _weekday(0, 6)

    model.add_observation(
        timestamp=start.timestamp(),
        temperature=55.0,
        local_datetime=start,
        heating_active=True,
        standby_loss_c_per_hour=0.5,
    )
    baseline = start + timedelta(minutes=5)
    model.add_observation(
        timestamp=baseline.timestamp(),
        temperature=55.0,
        local_datetime=baseline,
        heating_active=False,
        standby_loss_c_per_hour=0.5,
    )
    before_recovery = baseline + timedelta(hours=4)
    model.add_observation(
        timestamp=before_recovery.timestamp(),
        temperature=53.0,
        local_datetime=before_recovery,
        heating_active=False,
        standby_loss_c_per_hour=0.5,
    )
    recovery = before_recovery + timedelta(minutes=5)
    model.add_observation(
        timestamp=recovery.timestamp(),
        temperature=53.0,
        local_datetime=recovery,
        heating_active=True,
        standby_loss_c_per_hour=0.5,
    )

    estimate = model.estimate(now_local=recovery, occupancy=True)

    assert estimate.event_count == 0
    assert estimate.recovery_event_count == 0


def test_recovery_does_not_duplicate_recent_direct_draw() -> None:
    """A recovery shortly after a direct draw must not count the same demand twice."""
    model = DhwUsageModel()
    start = _weekday(0, 6)

    model.add_observation(
        timestamp=start.timestamp(),
        temperature=55.0,
        local_datetime=start,
        heating_active=True,
        standby_loss_c_per_hour=0.5,
    )
    baseline = start + timedelta(minutes=5)
    model.add_observation(
        timestamp=baseline.timestamp(),
        temperature=55.0,
        local_datetime=baseline,
        heating_active=False,
        standby_loss_c_per_hour=0.5,
    )
    before_draw = baseline + timedelta(minutes=45)
    model.add_observation(
        timestamp=before_draw.timestamp(),
        temperature=55.0,
        local_datetime=before_draw,
        heating_active=False,
        standby_loss_c_per_hour=0.5,
    )
    draw = before_draw + timedelta(minutes=5)
    model.add_observation(
        timestamp=draw.timestamp(),
        temperature=52.0,
        local_datetime=draw,
        heating_active=False,
        standby_loss_c_per_hour=0.5,
    )
    recovery = draw + timedelta(minutes=5)
    model.add_observation(
        timestamp=recovery.timestamp(),
        temperature=52.0,
        local_datetime=recovery,
        heating_active=True,
        standby_loss_c_per_hour=0.5,
    )

    estimate = model.estimate(now_local=recovery, occupancy=True)

    assert estimate.event_count == 1
    assert estimate.direct_event_count == 1
    assert estimate.recovery_event_count == 0


def test_recovery_learning_infers_heating_without_explicit_signal() -> None:
    """Recovery learning works when DHW heating must be inferred from temperature."""
    model = DhwUsageModel()
    start = _weekday(0, 6)

    model.add_observation(
        timestamp=start.timestamp(),
        temperature=54.0,
        local_datetime=start,
        heating_active=None,
        standby_loss_c_per_hour=0.5,
    )
    heating = start + timedelta(minutes=5)
    model.add_observation(
        timestamp=heating.timestamp(),
        temperature=55.5,
        local_datetime=heating,
        heating_active=None,
        standby_loss_c_per_hour=0.5,
    )
    baseline = heating + timedelta(minutes=5)
    model.add_observation(
        timestamp=baseline.timestamp(),
        temperature=55.5,
        local_datetime=baseline,
        heating_active=None,
        standby_loss_c_per_hour=0.5,
    )
    before_recovery = baseline + timedelta(hours=2)
    model.add_observation(
        timestamp=before_recovery.timestamp(),
        temperature=53.5,
        local_datetime=before_recovery,
        heating_active=None,
        standby_loss_c_per_hour=0.5,
    )
    recovery = before_recovery + timedelta(minutes=5)
    model.add_observation(
        timestamp=recovery.timestamp(),
        temperature=54.5,
        local_datetime=recovery,
        heating_active=None,
        standby_loss_c_per_hour=0.5,
    )

    estimate = model.estimate(now_local=recovery, occupancy=True)

    assert estimate.event_count == 1
    assert estimate.recovery_event_count == 1
