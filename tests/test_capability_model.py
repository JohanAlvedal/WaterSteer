"""Tests for WaterSteer's capability-based safe margin model."""

import pytest

from custom_components.watersteer.capability_model import estimate_safe_margin


def test_strong_thermal_margin_is_not_reduced_by_weak_usage_confidence() -> None:
    """Optional usage learning must not weaken a trusted thermal estimator."""
    result = estimate_safe_margin(
        passive_autonomy_minutes=420.0,
        predicted_autonomy_minutes=240.0,
        thermal_confidence=100,
        usage_confidence=33,
    )

    assert result.minutes == pytest.approx(420.0)
    assert result.confidence == 100
    assert result.source == "thermal"
    assert result.usage_adjusted is False
    assert result.reason == "thermal_margin_usage_not_trusted"


def test_trusted_usage_can_reduce_thermal_margin_without_reducing_confidence() -> None:
    """Trusted usage may shorten margin while thermal confidence remains primary."""
    result = estimate_safe_margin(
        passive_autonomy_minutes=420.0,
        predicted_autonomy_minutes=300.0,
        thermal_confidence=90,
        usage_confidence=70,
    )

    assert result.minutes == pytest.approx(300.0)
    assert result.confidence == 90
    assert result.source == "thermal"
    assert result.usage_adjusted is True


def test_cycle_estimator_is_used_when_thermal_data_is_unavailable() -> None:
    """Cycle data can provide the same planner interface without temperature."""
    result = estimate_safe_margin(
        passive_autonomy_minutes=None,
        predicted_autonomy_minutes=None,
        thermal_confidence=0,
        usage_confidence=0,
        cycle_margin_minutes=360.0,
        cycle_confidence=75,
    )

    assert result.minutes == pytest.approx(360.0)
    assert result.confidence == 75
    assert result.source == "cycle"


def test_simple_estimator_is_last_resort() -> None:
    """A conservative simple estimate can keep WaterSteer useful with little data."""
    result = estimate_safe_margin(
        passive_autonomy_minutes=None,
        predicted_autonomy_minutes=None,
        thermal_confidence=0,
        usage_confidence=0,
        simple_margin_minutes=180.0,
        simple_confidence=40,
    )

    assert result.minutes == pytest.approx(180.0)
    assert result.confidence == 40
    assert result.source == "simple"
