"""Tests for WaterSteer's demand predictor."""

from datetime import UTC, datetime, timedelta

from custom_components.watersteer.demand_predictor import DhwDemandPredictor
from custom_components.watersteer.usage_model import DhwUsageModel


def _add_weekday_usage(model: DhwUsageModel, week: int, hour: int) -> None:
    start = datetime(2026, 9, 28, hour, tzinfo=UTC) + timedelta(weeks=week)
    model.add_observation(
        timestamp=start.timestamp(),
        temperature=54.0,
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


def test_statistical_predictor_returns_24_hour_horizon() -> None:
    """The fallback predictor exposes a full day without requiring ML."""
    model = DhwUsageModel()
    for week in range(4):
        _add_weekday_usage(model, week, 7)

    now = datetime(2026, 10, 26, 6, tzinfo=UTC)
    predictor = DhwDemandPredictor(enable_ml=False)

    result = predictor.predict(
        usage_model=model,
        now_local=now,
        occupancy=True,
        statistical_confidence=40,
        hours=24,
    )

    assert result.backend == "statistical"
    assert len(result.buckets) == 24
    assert result.confidence == 40
    assert result.peak_probability > 0


def test_away_state_reduces_statistical_demand() -> None:
    """Explicit away state lowers the demand forecast used by the optimizer."""
    model = DhwUsageModel()
    for week in range(4):
        _add_weekday_usage(model, week, 7)

    now = datetime(2026, 10, 26, 6, tzinfo=UTC)
    predictor = DhwDemandPredictor(enable_ml=False)

    home = predictor.predict(
        usage_model=model,
        now_local=now,
        occupancy=True,
        statistical_confidence=40,
        hours=24,
    )
    away = predictor.predict(
        usage_model=model,
        now_local=now,
        occupancy=False,
        statistical_confidence=40,
        hours=24,
    )

    assert away.peak_probability < home.peak_probability
    assert away.expected_drop_c < home.expected_drop_c
