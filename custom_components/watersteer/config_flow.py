"""Config flow for WaterSteer."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_ABSOLUTE_MINIMUM,
    CONF_BLOCK_ENTITY,
    CONF_COMFORT_ESCALATION_MINUTES,
    CONF_COMFORT_MINIMUM,
    CONF_DHW_TEMPERATURE_ENTITY,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_EXTERNAL_HEATING_ENTITY,
    CONF_EXTRA_HOT_WATER_ENTITY,
    CONF_HEAT_PUMP_BLOCK_ACTION,
    CONF_HEAT_PUMP_BOOST_ACTION,
    CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY,
    CONF_HEAT_PUMP_DHW_AVAILABLE_ENTITY,
    CONF_HEAT_PUMP_NORMAL_ACTION,
    CONF_MAX_HOLD_HOURS,
    CONF_MIN_THERMAL_CONFIDENCE,
    CONF_NORMAL_TARGET,
    CONF_OCCUPANCY_ENTITY,
    CONF_PRECHARGE_TARGET,
    CONF_STANDALONE_CONTROL_SWITCH,
    CONF_STANDALONE_POWER_SENSOR,
    CONF_SYSTEM_TYPE,
    DEFAULT_ABSOLUTE_MINIMUM,
    DEFAULT_COMFORT_ESCALATION_MINUTES,
    DEFAULT_COMFORT_MINIMUM,
    DEFAULT_MAX_HOLD_HOURS,
    DEFAULT_MIN_THERMAL_CONFIDENCE,
    DEFAULT_NORMAL_TARGET,
    DEFAULT_PRECHARGE_TARGET,
    DOMAIN,
    SYSTEM_TYPE_STANDALONE,
    SYSTEM_TYPES,
)

CONTROL_KEYS = (
    CONF_BLOCK_ENTITY,
    CONF_EXTRA_HOT_WATER_ENTITY,
    CONF_STANDALONE_CONTROL_SWITCH,
    CONF_STANDALONE_POWER_SENSOR,
    CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY,
    CONF_HEAT_PUMP_DHW_AVAILABLE_ENTITY,
    CONF_HEAT_PUMP_BOOST_ACTION,
    CONF_HEAT_PUMP_BLOCK_ACTION,
    CONF_HEAT_PUMP_NORMAL_ACTION,
)


def _primary_schema() -> vol.Schema:
    """Return the common WaterSteer configuration schema."""
    return vol.Schema(
        {
            vol.Required(CONF_SYSTEM_TYPE): SelectSelector(
                SelectSelectorConfig(
                    options=list(SYSTEM_TYPES),
                    translation_key=CONF_SYSTEM_TYPE,
                    mode=SelectSelectorMode.LIST,
                )
            ),
            vol.Optional(CONF_DHW_TEMPERATURE_ENTITY): EntitySelector(
                EntitySelectorConfig(
                    domain="sensor",
                    device_class="temperature",
                )
            ),
            vol.Required(CONF_ELECTRICITY_PRICE_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_OCCUPANCY_ENTITY): EntitySelector(
                EntitySelectorConfig(
                    domain=["binary_sensor", "input_boolean", "person"]
                )
            ),
            vol.Optional(CONF_EXTERNAL_HEATING_ENTITY): EntitySelector(
                EntitySelectorConfig(
                    domain=["binary_sensor", "input_boolean", "switch"]
                )
            ),
        }
    )


def _threshold_schema() -> vol.Schema:
    """Return the DHW temperature threshold schema."""
    selector = NumberSelector(
        NumberSelectorConfig(
            min=20,
            max=80,
            step=0.5,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="°C",
        )
    )
    confidence_selector = NumberSelector(
        NumberSelectorConfig(
            min=10,
            max=100,
            step=5,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="%",
        )
    )
    return vol.Schema(
        {
            vol.Required(
                CONF_ABSOLUTE_MINIMUM,
                default=DEFAULT_ABSOLUTE_MINIMUM,
            ): selector,
            vol.Required(
                CONF_COMFORT_MINIMUM,
                default=DEFAULT_COMFORT_MINIMUM,
            ): selector,
            vol.Required(
                CONF_NORMAL_TARGET,
                default=DEFAULT_NORMAL_TARGET,
            ): selector,
            vol.Required(
                CONF_PRECHARGE_TARGET,
                default=DEFAULT_PRECHARGE_TARGET,
            ): selector,
            vol.Required(
                CONF_MIN_THERMAL_CONFIDENCE,
                default=DEFAULT_MIN_THERMAL_CONFIDENCE,
            ): confidence_selector,
            vol.Required(
                CONF_MAX_HOLD_HOURS,
                default=DEFAULT_MAX_HOLD_HOURS,
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=24,
                    step=0.5,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="h",
                )
            ),
            vol.Required(
                CONF_COMFORT_ESCALATION_MINUTES,
                default=DEFAULT_COMFORT_ESCALATION_MINUTES,
            ): NumberSelector(
                NumberSelectorConfig(
                    min=15,
                    max=240,
                    step=5,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            ),
        }
    )


def _thresholds_valid(values: dict[str, Any]) -> bool:
    """Return whether configured thresholds are strictly ordered."""
    return (
        float(values[CONF_ABSOLUTE_MINIMUM])
        < float(values[CONF_COMFORT_MINIMUM])
        < float(values[CONF_NORMAL_TARGET])
        < float(values[CONF_PRECHARGE_TARGET])
    )


def _standalone_schema() -> vol.Schema:
    """Return the standalone water-heater control schema."""
    return vol.Schema(
        {
            vol.Optional(CONF_STANDALONE_CONTROL_SWITCH): EntitySelector(
                EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(CONF_STANDALONE_POWER_SENSOR): EntitySelector(
                EntitySelectorConfig(
                    domain="sensor",
                    device_class="power",
                )
            ),
        }
    )


def _heat_pump_schema() -> vol.Schema:
    """Return the heat-pump control schema."""
    return vol.Schema(
        {
            vol.Optional(CONF_BLOCK_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=["switch", "input_boolean"])
            ),
            vol.Optional(CONF_EXTRA_HOT_WATER_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=["switch", "input_boolean"])
            ),
            vol.Optional(CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=["binary_sensor", "sensor"])
            ),
        }
    )


class WaterSteerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WaterSteer."""

    VERSION = 3

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WaterSteerOptionsFlow:
        """Create the WaterSteer options flow."""
        return WaterSteerOptionsFlow()

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
            return await self.async_step_thresholds()

        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_DHW_TEMPERATURE_ENTITY): EntitySelector(
                        EntitySelectorConfig(
                            domain="sensor",
                            device_class="temperature",
                        )
                    ),
                    vol.Required(CONF_ELECTRICITY_PRICE_ENTITY): EntitySelector(
                        EntitySelectorConfig(domain="sensor")
                    ),
                    vol.Optional(CONF_OCCUPANCY_ENTITY): EntitySelector(
                        EntitySelectorConfig(
                            domain=["binary_sensor", "input_boolean", "person"]
                        )
                    ),
                    vol.Optional(CONF_EXTERNAL_HEATING_ENTITY): EntitySelector(
                        EntitySelectorConfig(
                            domain=["binary_sensor", "input_boolean", "switch"]
                        )
                    ),
                }
            ),
        )

    async def async_step_thresholds(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure DHW temperature thresholds."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if _thresholds_valid(user_input):
                self._data.update(user_input)

                if self._data[CONF_SYSTEM_TYPE] == SYSTEM_TYPE_STANDALONE:
                    return await self.async_step_standalone_control()

                return await self.async_step_heat_pump_control()

            errors["base"] = "invalid_threshold_order"

        return self.async_show_form(
            step_id="thresholds",
            data_schema=_threshold_schema(),
            errors=errors,
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
            data_schema=_standalone_schema(),
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
            data_schema=_heat_pump_schema(),
        )

    def _create_entry(self) -> ConfigFlowResult:
        """Create the WaterSteer config entry."""
        return self.async_create_entry(title="WaterSteer", data=self._data)


class WaterSteerOptionsFlow(OptionsFlowWithReload):
    """Allow WaterSteer configuration to be changed after setup."""

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._options: dict[str, Any] = {}

    def _current_config(self) -> dict[str, Any]:
        """Return config-entry data overlaid with saved options."""
        return {**self.config_entry.data, **self.config_entry.options}

    def _threshold_defaults(self) -> dict[str, float]:
        """Return current threshold values with defaults for older entries."""
        current = self._current_config()
        return {
            CONF_ABSOLUTE_MINIMUM: float(
                current.get(CONF_ABSOLUTE_MINIMUM, DEFAULT_ABSOLUTE_MINIMUM)
            ),
            CONF_COMFORT_MINIMUM: float(
                current.get(CONF_COMFORT_MINIMUM, DEFAULT_COMFORT_MINIMUM)
            ),
            CONF_NORMAL_TARGET: float(
                current.get(CONF_NORMAL_TARGET, DEFAULT_NORMAL_TARGET)
            ),
            CONF_PRECHARGE_TARGET: float(
                current.get(CONF_PRECHARGE_TARGET, DEFAULT_PRECHARGE_TARGET)
            ),
            CONF_MIN_THERMAL_CONFIDENCE: float(
                current.get(
                    CONF_MIN_THERMAL_CONFIDENCE,
                    DEFAULT_MIN_THERMAL_CONFIDENCE,
                )
            ),
            CONF_MAX_HOLD_HOURS: float(
                current.get(CONF_MAX_HOLD_HOURS, DEFAULT_MAX_HOLD_HOURS)
            ),
            CONF_COMFORT_ESCALATION_MINUTES: float(
                current.get(
                    CONF_COMFORT_ESCALATION_MINUTES,
                    DEFAULT_COMFORT_ESCALATION_MINUTES,
                )
            ),
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure common WaterSteer settings."""
        current = self._current_config()

        if user_input is not None:
            self._options = dict(self.config_entry.options)
            self._options.update(user_input)

            for key in CONTROL_KEYS:
                self._options[key] = None

            return await self.async_step_thresholds()

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _primary_schema(),
                current,
            ),
        )

    async def async_step_thresholds(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure DHW temperature thresholds."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if _thresholds_valid(user_input):
                self._options.update(user_input)

                if self._options[CONF_SYSTEM_TYPE] == SYSTEM_TYPE_STANDALONE:
                    return await self.async_step_standalone_control()

                return await self.async_step_heat_pump_control()

            errors["base"] = "invalid_threshold_order"

        return self.async_show_form(
            step_id="thresholds",
            data_schema=self.add_suggested_values_to_schema(
                _threshold_schema(),
                self._threshold_defaults(),
            ),
            errors=errors,
        )

    async def async_step_standalone_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure standalone water-heater options."""
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(data=self._options)

        return self.async_show_form(
            step_id="standalone_control",
            data_schema=self.add_suggested_values_to_schema(
                _standalone_schema(),
                self._current_config(),
            ),
        )

    async def async_step_heat_pump_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure heat-pump options."""
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(data=self._options)

        return self.async_show_form(
            step_id="heat_pump_control",
            data_schema=self.add_suggested_values_to_schema(
                _heat_pump_schema(),
                self._current_config(),
            ),
        )
