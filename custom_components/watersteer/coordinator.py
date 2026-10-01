"""Data coordinator for WaterSteer."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_DHW_TEMPERATURE_ENTITY,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY,
    CONF_HEAT_PUMP_DHW_AVAILABLE_ENTITY,
    CONF_STANDALONE_CONTROL_SWITCH,
    CONF_STANDALONE_POWER_SENSOR,
    CONF_SYSTEM_TYPE,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MODE_LEARNING,
    MODE_SAFETY,
)

_LOGGER = logging.getLogger(__name__)


def _as_float(value: str | None) -> float | None:
    """Convert a Home Assistant state to float when possible."""
    if value is None or value in {"unknown", "unavailable"}:
        return None

    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _temperature_celsius(state: State | None) -> float | None:
    """Return a temperature state normalized to degrees Celsius."""
    if state is None:
        return None

    value = _as_float(state.state)
    if value is None:
        return None

    unit = state.attributes.get("unit_of_measurement")
    if unit is None:
        return None

    try:
        return TemperatureConverter.convert(
            value,
            unit,
            UnitOfTemperature.CELSIUS,
        )
    except TypeError, ValueError:
        return None


class WaterSteerDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Collect and normalize WaterSteer input data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the WaterSteer coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self.entry = entry

    def _config(self) -> dict[str, Any]:
        """Return effective configuration with options overriding setup data."""
        return {**self.entry.data, **self.entry.options}

    async def _async_update_data(self) -> dict[str, Any]:
        """Read WaterSteer inputs from the Home Assistant state machine."""
        config = self._config()
        temperature_entity = config[CONF_DHW_TEMPERATURE_ENTITY]
        price_entity = config[CONF_ELECTRICITY_PRICE_ENTITY]

        temperature_state = self.hass.states.get(temperature_entity)
        price_state = self.hass.states.get(price_entity)

        dhw_temperature = _temperature_celsius(temperature_state)
        electricity_price = _as_float(
            price_state.state if price_state is not None else None
        )

        standalone_switch = config.get(CONF_STANDALONE_CONTROL_SWITCH)
        standalone_power_sensor = config.get(CONF_STANDALONE_POWER_SENSOR)
        dhw_active_entity = config.get(CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY)
        dhw_available_entity = config.get(CONF_HEAT_PUMP_DHW_AVAILABLE_ENTITY)

        standalone_switch_state = (
            self.hass.states.get(standalone_switch) if standalone_switch else None
        )
        standalone_power_state = (
            self.hass.states.get(standalone_power_sensor)
            if standalone_power_sensor
            else None
        )
        dhw_active_state = (
            self.hass.states.get(dhw_active_entity) if dhw_active_entity else None
        )
        dhw_available_state = (
            self.hass.states.get(dhw_available_entity)
            if dhw_available_entity
            else None
        )

        data_valid = dhw_temperature is not None
        mode = MODE_LEARNING if data_valid else MODE_SAFETY

        # WaterSteer 0.1 never actively blocks DHW production. This explicit
        # allow state is the fail-safe baseline for later planner/controller logic.
        dhw_allowed = True
        dhw_allowed_reason = "learning_observation" if data_valid else "safety_fallback"

        return {
            "mode": mode,
            "data_valid": data_valid,
            "system_type": config[CONF_SYSTEM_TYPE],
            "dhw_allowed": dhw_allowed,
            "dhw_allowed_reason": dhw_allowed_reason,
            "dhw_temperature": dhw_temperature,
            "dhw_temperature_source_unit": (
                temperature_state.attributes.get("unit_of_measurement")
                if temperature_state is not None
                else None
            ),
            "electricity_price": electricity_price,
            "dhw_temperature_entity": temperature_entity,
            "electricity_price_entity": price_entity,
            "standalone_control_switch": standalone_switch,
            "standalone_control_switch_state": (
                standalone_switch_state.state
                if standalone_switch_state is not None
                else None
            ),
            "standalone_power_sensor": standalone_power_sensor,
            "standalone_power": _as_float(
                standalone_power_state.state
                if standalone_power_state is not None
                else None
            ),
            "heat_pump_dhw_active_entity": dhw_active_entity,
            "heat_pump_dhw_active_state": (
                dhw_active_state.state if dhw_active_state is not None else None
            ),
            "heat_pump_dhw_available_entity": dhw_available_entity,
            "heat_pump_dhw_available_state": (
                dhw_available_state.state
                if dhw_available_state is not None
                else None
            ),
        }
