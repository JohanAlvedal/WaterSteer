"""Tests for WaterSteer binary sensors."""

from unittest.mock import Mock

from custom_components.watersteer.binary_sensor import (
    BINARY_SENSORS,
    WaterSteerDecisionBinarySensor,
)


def _coordinator_data() -> dict:
    """Return representative WaterSteer shadow-control data."""
    return {
        "control_mode": "advisory",
        "decision": "learning_guard",
        "decision_reason": "thermal_confidence_below_minimum",
        "raw_temperature_decision": "temperature_hold",
        "mode": "learning",
        "system_type": "heat_pump_integrated_dhw",
        "dhw_temperature": 50.7,
        "electricity_price": 0.84,
        "absolute_minimum": 40.0,
        "comfort_minimum": 45.0,
        "normal_target": 50.0,
        "precharge_target": 55.0,
        "learning_confidence": 35,
        "minimum_thermal_confidence": 50,
        "braking_confidence_ready": False,
        "usage_probability_next_6h": 20.0,
        "usage_learning_confidence": 15,
        "occupancy_state": "away",
        "dhw_allowed": True,
        "dhw_request": False,
        "force_request": False,
        "usage_detected": False,
        "heat_pump_dhw_available_state": "on",
    }


def test_dhw_allowed_remains_on_while_learning_confidence_is_low() -> None:
    """DHW allowed remains on while the thermal confidence guard is active."""
    coordinator = Mock()
    coordinator.data = _coordinator_data()
    entry = Mock()
    entry.entry_id = "test_entry"

    entity = WaterSteerDecisionBinarySensor(coordinator, entry, BINARY_SENSORS[0])

    assert entity.is_on is True
    assert entity.extra_state_attributes["decision"] == "learning_guard"
    assert entity.extra_state_attributes["raw_temperature_decision"] == (
        "temperature_hold"
    )
    assert entity.extra_state_attributes["braking_confidence_ready"] is False


def test_dhw_request_on_below_comfort() -> None:
    """DHW request is on when temperature is below the comfort minimum."""
    coordinator = Mock()
    coordinator.data = _coordinator_data()
    coordinator.data.update(
        {
            "decision": "comfort_recovery",
            "decision_reason": "below_comfort_minimum",
            "raw_temperature_decision": "comfort_recovery",
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


def test_usage_detected_binary_sensor() -> None:
    """Usage detection is exposed as a separate binary sensor."""
    coordinator = Mock()
    coordinator.data = _coordinator_data()
    coordinator.data["usage_detected"] = True
    entry = Mock()
    entry.entry_id = "test_entry"

    entity = WaterSteerDecisionBinarySensor(coordinator, entry, BINARY_SENSORS[3])

    assert entity.is_on is True
