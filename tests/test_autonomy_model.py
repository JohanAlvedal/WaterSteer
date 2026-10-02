"""Tests for WaterSteer's DHW autonomy prediction."""

from datetime import UTC, datetime

from custom_components.watersteer.autonomy_model import estimate_autonomy
from custom_components.watersteer.usage_model import UsageForecastBucket
import pytest


def _bucket(hour: int, expected_drop_c: float) -> UsageForecastBucket:
    """Create one deterministic forecast bucket."""
    return UsageForecastBucket(
        start=datetime(2026, 10, 2, hour, tzinfo=UTC),
        probability=0.5,
        typical_drop_c=expected_drop_c,
        expected_drop_c=expected_drop_c,
    )


def test_low_usage_confidence_uses_thermal_only_autonomy() -> None:
    """Untrusted usage learning must not alter autonomy."""
    result = estimate_autonomy(
        current_temperature=51.0,
        comfort_minimum=45.0,
        standby_loss_c_per_hour=0.5,
        thermal_confidence=70,
        usage_confidence=10,
        usage_forecast=(_bucket(7, 4.0),),
    )

    assert result.demand_adjusted is False
    assert result.basis == "thermal_only"
    assert result.passive_minutes == pytest.approx(720.0)
    assert result.predicted_minutes == pytest.approx(720.0)
    assert result.confidence == 70


def test_learned_demand_reduces_predicted_autonomy() -> None:
    """Trusted expected draws reduce autonomy relative to passive loss alone."""
    result = estimate_autonomy(
        current_temperature=51.0,
        comfort_minimum=45.0,
        standby_loss_c_per_hour=0.5,
        thermal_confidence=80,
        usage_confidence=60,
        usage_forecast=(
            _bucket(7, 2.0),
            _bucket(8, 1.0),
        ),
    )

    assert result.demand_adjusted is True
    assert result.basis == "thermal_and_learned_demand"
    assert result.predicted_minutes < result.passive_minutes
    assert result.confidence == 60


def test_comfort_floor_returns_zero_autonomy() -> None:
    """No autonomy remains once the comfort minimum is reached."""
    result = estimate_autonomy(
        current_temperature=45.0,
        comfort_minimum=45.0,
        standby_loss_c_per_hour=0.5,
        thermal_confidence=75,
        usage_confidence=75,
        usage_forecast=(_bucket(7, 2.0),),
    )

    assert result.passive_minutes == 0.0
    assert result.predicted_minutes == 0.0
    assert result.basis == "comfort_floor_reached"


def test_missing_thermal_model_returns_unknown_autonomy() -> None:
    """Autonomy stays unknown until passive loss has been learned."""
    result = estimate_autonomy(
        current_temperature=51.0,
        comfort_minimum=45.0,
        standby_loss_c_per_hour=None,
        thermal_confidence=0,
        usage_confidence=60,
        usage_forecast=(_bucket(7, 2.0),),
    )

    assert result.passive_minutes is None
    assert result.predicted_minutes is None
    assert result.confidence == 0
    assert result.basis == "insufficient_thermal_data"
