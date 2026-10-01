"""Tests for WaterSteer DHW decision logic."""

import pytest

from custom_components.watersteer.controller import (
    DhwThresholds,
    classify_dhw_temperature,
)


@pytest.fixture
def thresholds() -> DhwThresholds:
    """Return standard classifier thresholds."""
    return DhwThresholds(
        absolute_minimum=40.0,
        comfort_minimum=45.0,
        normal_target=50.0,
        precharge_target=55.0,
    )


@pytest.mark.parametrize(
    (
        "temperature",
        "classification",
        "allowed",
        "request_expected",
        "force_request_expected",
    ),
    [
        (39.0, "force_heat", True, True, True),
        (40.0, "force_heat", True, True, True),
        (42.0, "comfort_recovery", True, True, False),
        (45.0, "normal_operation", True, False, False),
        (49.5, "normal_operation", True, False, False),
        (50.0, "temperature_hold", False, False, False),
        (55.0, "temperature_hold", False, False, False),
    ],
)
def test_temperature_classification(
    thresholds: DhwThresholds,
    temperature: float,
    classification: str,
    allowed: bool,
    request_expected: bool,
    force_request_expected: bool,
) -> None:
    """Temperature bands produce deterministic shadow decisions."""
    decision = classify_dhw_temperature(temperature, thresholds)

    assert decision.classification == classification
    assert decision.allowed is allowed
    assert decision.request is request_expected
    assert decision.force_request is force_request_expected


def test_missing_temperature_fails_safe(thresholds: DhwThresholds) -> None:
    """Missing temperature never causes WaterSteer to block DHW."""
    decision = classify_dhw_temperature(None, thresholds)

    assert decision.classification == "safety_fallback"
    assert decision.allowed is True
    assert decision.request is False
    assert decision.force_request is False


def test_invalid_thresholds_fail_safe() -> None:
    """Invalid threshold ordering never causes WaterSteer to block DHW."""
    thresholds = DhwThresholds(
        absolute_minimum=45.0,
        comfort_minimum=40.0,
        normal_target=50.0,
        precharge_target=55.0,
    )

    decision = classify_dhw_temperature(48.0, thresholds)

    assert decision.classification == "safety_fallback"
    assert decision.reason == "invalid_threshold_configuration"
    assert decision.allowed is True
