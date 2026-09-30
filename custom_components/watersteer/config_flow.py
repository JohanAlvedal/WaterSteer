"""Config flow for WaterSteer."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    ActionSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_DHW_TEMPERATURE_ENTITY,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_HEAT_PUMP_BLOCK_ACTION,
    CONF_HEAT_PUMP_BOOST_ACTION,
    CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY,
    CONF_HEAT_PUMP_NORMAL_ACTION,
    CONF_STANDALONE_CONTROL_SWITCH,
    CONF_STANDALONE_POWER_SENSOR,
    CONF_SYSTEM_TYPE,
    DOMAIN,
    SYSTEM_TYPE_HEAT_PUMP,
    SYSTEM_TYPE_STANDALONE,
    SYSTEM_TYPES,
)


class WaterSteerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WaterSteer."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the domestic hot water system type."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_sensors()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SYSTEM_TYPE): SelectSelector(
                        SelectSelectorConfig(
                            options=list(SYSTEM_TYPES),
                            translation_key=CONF_SYSTEM_TYPE,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the required WaterSteer input sensors."""
        if user_input is not None:
            self._data.update(user_input)

            if self._data[CONF_SYSTEM_TYPE] == SYSTEM_TYPE_STANDALONE:
                return await self.async_step_standalone_control()

            if self._data[CONF_SYSTEM_TYPE] == SYSTEM_TYPE_HEAT_PUMP:
                return await self.async_step_heat_pump_control()

        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DHW_TEMPERATURE_ENTITY): EntitySelector(
                        EntitySelectorConfig(domain="sensor")
                    ),
                    vol.Required(CONF_ELECTRICITY_PRICE_ENTITY): EntitySelector(
                        EntitySelectorConfig(domain="sensor")
                    ),
                }
            ),
        )

    async def async_step_standalone_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a standalone water heater."""
        if user_input is not None:
            self._data.update(user_input)
            return self._create_entry()

        return self.async_show_form(
            step_id="standalone_control",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STANDALONE_CONTROL_SWITCH): EntitySelector(
                        EntitySelectorConfig(domain="switch")
                    ),
                    vol.Optional(CONF_STANDALONE_POWER_SENSOR): EntitySelector(
                        EntitySelectorConfig(domain="sensor")
                    ),
                }
            ),
        )

    async def async_step_heat_pump_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure heat-pump domestic hot water integration points."""
        if user_input is not None:
            self._data.update(user_input)
            return self._create_entry()

        return self.async_show_form(
            step_id="heat_pump_control",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY): EntitySelector(
                        EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                    ),
                    vol.Optional(CONF_HEAT_PUMP_BOOST_ACTION): ActionSelector(),
                    vol.Optional(CONF_HEAT_PUMP_BLOCK_ACTION): ActionSelector(),
                    vol.Optional(CONF_HEAT_PUMP_NORMAL_ACTION): ActionSelector(),
                }
            ),
        )

    def _create_entry(self) -> ConfigFlowResult:
        """Create the WaterSteer config entry."""
        return self.async_create_entry(title="WaterSteer", data=self._data)
