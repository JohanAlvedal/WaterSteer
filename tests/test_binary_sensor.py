"""Tests for WaterSteer binary sensors."""

from unittest.mock import Mock

from custom_components.watersteer.binary_sensor import (
    BINARY_SENSORS,
    WaterSteerDecisionBinarySensor,
)


def _coordinator_data() -> dict:
    """Return representative WaterSteer shadow-control data."""
    return {
        "shadow_mode": True,
        "decision": "temperature_hold",
        "decision_reason": "normal_target_reached",
        "mode": "learning",
        "system_type": "heat_pump_integrated_dhw",
        "dhw_temperature": 50.7,
        "electricity_price": 0.84,
        "absolute_minimum": 40.0,
        "comfort_minimum": 45.0,
        "normal_target": 50.0,
        "precharge_target": 55.0,
        "dhw_allowed": False,
        "dhw_request": False,
        "force_request": False,
        "heat_pump_dhw_available_state": "on",
    }


def test_dhw_allowed_off_means_shadow_braking() -> None:
    """DHW allowed is off when the shadow classifier would brake production."""
    coordinator = Mock()
    coordinator.data = _coordinator_data()
    entry = Mock()
    entry.entry_id = "test_entry"

    entity = WaterSteerDecisionBinarySensor(coordinator, entry, BINARY_SENSORS[0])

    assert entity.is_on is False
    assert entity.extra_state_attributes["shadow_mode"] is True
    assert entity.extra_state_attributes["decision"] == "temperature_hold"
    assert entity.extra_state_attributes["reason"] == "normal_target_reached"


def test_dhw_request_on_below_comfort() -> None:
    """DHW request is on when temperature is below the comfort minimum."""
    coordinator = Mock()
    coordinator.data = _coordinator_data()
    coordinator.data.update(
        {
            "decision": "comfort_recovery",
            "decision_reason": "below_comfort_minimum",
            "dhw_temperature": 43.0,
            "dhw_allowed": True,
            "dhw_request": True,
        }
    )
    entry = Mock()
    entry.entry_id = "test_entry"

    entity = WaterSteerDecisionBinarySensor(coordinator, entry, BINARY_SENSORS[1])

    assert entity.is_on is True
    assert entity.extra_state_attributes["current_temperature"] == 43.0
