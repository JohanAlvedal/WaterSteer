"""Tests for the WaterSteer data coordinator helpers."""

from custom_components.watersteer.coordinator import (
    _as_float,
    _occupancy_hint,
    _temperature_celsius,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import State


def test_as_float_valid_number() -> None:
    """Numeric state strings are converted to float."""
    assert _as_float("52.4") == 52.4


def test_as_float_invalid_states() -> None:
    """Unavailable and non-numeric states return None."""
    assert _as_float(None) is None
    assert _as_float("unknown") is None
    assert _as_float("unavailable") is None
    assert _as_float("not-a-number") is None


def test_temperature_celsius_from_celsius() -> None:
    """Celsius input remains unchanged."""
    state = State(
        "sensor.dhw_temperature",
        "55.0",
        {"unit_of_measurement": UnitOfTemperature.CELSIUS},
    )

    assert _temperature_celsius(state) == 55.0


def test_temperature_celsius_from_fahrenheit() -> None:
    """Fahrenheit input is normalized to Celsius."""
    state = State(
        "sensor.dhw_temperature",
        "131.0",
        {"unit_of_measurement": UnitOfTemperature.FAHRENHEIT},
    )

    assert _temperature_celsius(state) == 55.0


def test_temperature_celsius_requires_unit() -> None:
    """A temperature without a unit is rejected."""
    state = State("sensor.dhw_temperature", "55.0")

    assert _temperature_celsius(state) is None


def test_occupancy_hint_supports_binary_and_person_entities() -> None:
    """Optional occupancy entities are normalized without becoming required."""
    assert _occupancy_hint(State("binary_sensor.home", "on")) is True
    assert _occupancy_hint(State("binary_sensor.home", "off")) is False
    assert _occupancy_hint(State("person.someone", "home")) is True
    assert _occupancy_hint(State("person.someone", "work")) is False
    assert _occupancy_hint(State("person.someone", "unavailable")) is None
