"""Tests for WaterSteer binary sensors."""

from unittest.mock import Mock

from custom_components.watersteer.binary_sensor import (
    BINARY_SENSORS,
    WaterSteerDecisionBinarySensor,
)

_BY_KEY = {description.key: description for description in BINARY_SENSORS}


def _entity(key: str, **data) -> WaterSteerDecisionBinarySensor:
    coordinator = Mock()
    coordinator.data = {
        "control_request": "normal",
        "control_request_reason": "no_optimized_action_required",
        "safety_warnings": [],
        "safety_problem": False,
        "dhw_allowed": True,
        "extra_hot_water": False,
        "force_request": False,
        "dhw_request": False,
        "usage_detected": False,
        **data,
    }
    entry = Mock()
    entry.entry_id = "test_entry"
    return WaterSteerDecisionBinarySensor(coordinator, entry, _BY_KEY[key])


def test_safety_problem_lists_warnings() -> None:
    """The Safety entity is on with actionable warnings."""
    entity = _entity(
        "safety",
        safety_problem=True,
        safety_warnings=["dhw_temperature_unavailable"],
    )

    assert entity.is_on is True
    assert entity.extra_state_attributes == {
        "warnings": ["dhw_temperature_unavailable"]
    }


def test_levers_follow_control_request() -> None:
    """The two physical levers mirror the published request."""
    blocked = _entity("dhw_allowed", dhw_allowed=False, control_request="hold")
    extra = _entity(
        "extra_hot_water",
        extra_hot_water=True,
        control_request="force_heat",
    )

    assert blocked.is_on is False
    assert extra.is_on is True
    assert extra.extra_state_attributes["control_request"] == "force_heat"


def test_primary_surface_is_small_by_default() -> None:
    """Only the Safety binary sensor is enabled for new installations."""
    enabled = [d.key for d in BINARY_SENSORS if d.entity_registry_enabled_default]

    assert enabled == ["safety"]


def test_usage_detected_binary_sensor() -> None:
    """Usage detection remains available as a diagnostic entity."""
    assert _entity("usage_detected", usage_detected=True).is_on is True
