"""Tests for WaterSteer binary sensors."""

from unittest.mock import Mock

from custom_components.watersteer.binary_sensor import (
    WaterSteerDhwAllowedBinarySensor,
)


def test_dhw_allowed_binary_sensor_debug_attributes() -> None:
    """DHW allowed is on when WaterSteer is not braking production."""
    coordinator = Mock()
    coordinator.data = {
        "dhw_allowed": True,
        "dhw_allowed_reason": "learning_observation",
        "mode": "learning",
        "system_type": "heat_pump_integrated_dhw",
        "dhw_temperature": 50.7,
        "electricity_price": 0.84,
    }
    entry = Mock()
    entry.entry_id = "test_entry"

    entity = WaterSteerDhwAllowedBinarySensor(coordinator, entry)

    assert entity.is_on is True
    assert entity.extra_state_attributes["reason"] == "learning_observation"
    assert entity.extra_state_attributes["current_temperature"] == 50.7


def test_dhw_allowed_binary_sensor_off_means_braking() -> None:
    """DHW allowed is off when future control logic is braking production."""
    coordinator = Mock()
    coordinator.data = {
        "dhw_allowed": False,
        "dhw_allowed_reason": "high_price_hold",
        "mode": "price_hold",
        "system_type": "heat_pump_integrated_dhw",
        "dhw_temperature": 55.0,
        "electricity_price": 2.10,
    }
    entry = Mock()
    entry.entry_id = "test_entry"

    entity = WaterSteerDhwAllowedBinarySensor(coordinator, entry)

    assert entity.is_on is False
    assert entity.extra_state_attributes["reason"] == "high_price_hold"
