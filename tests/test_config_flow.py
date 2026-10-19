"""Tests for the WaterSteer config flow."""

from custom_components.watersteer.const import (
    CONF_ABSOLUTE_MINIMUM,
    CONF_BLOCK_ENTITY,
    CONF_COMFORT_MINIMUM,
    CONF_DHW_TEMPERATURE_ENTITY,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_EXTRA_HOT_WATER_ENTITY,
    CONF_MIN_THERMAL_CONFIDENCE,
    CONF_NORMAL_TARGET,
    CONF_OCCUPANCY_ENTITY,
    CONF_PRECHARGE_TARGET,
    CONF_STANDALONE_CONTROL_SWITCH,
    CONF_SYSTEM_TYPE,
    DOMAIN,
    SYSTEM_TYPE_HEAT_PUMP,
    SYSTEM_TYPE_STANDALONE,
)
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

THRESHOLDS = {
    CONF_ABSOLUTE_MINIMUM: 40.0,
    CONF_COMFORT_MINIMUM: 45.0,
    CONF_NORMAL_TARGET: 50.0,
    CONF_PRECHARGE_TARGET: 55.0,
    CONF_MIN_THERMAL_CONFIDENCE: 50,
}


async def test_standalone_config_flow(hass) -> None:
    """Standalone setup includes thresholds before control configuration."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SYSTEM_TYPE: SYSTEM_TYPE_STANDALONE},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_DHW_TEMPERATURE_ENTITY: "sensor.dhw_temperature",
            CONF_ELECTRICITY_PRICE_ENTITY: "sensor.electricity_price",
            CONF_OCCUPANCY_ENTITY: "binary_sensor.home_occupied",
        },
    )
    assert result["step_id"] == "thresholds"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        THRESHOLDS,
    )
    assert result["step_id"] == "standalone_control"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_STANDALONE_CONTROL_SWITCH: "switch.water_heater"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NORMAL_TARGET] == 50.0
    assert result["data"][CONF_MIN_THERMAL_CONFIDENCE] == 50
    assert result["data"][CONF_OCCUPANCY_ENTITY] == "binary_sensor.home_occupied"


async def test_heat_pump_config_flow_without_active_signal(hass) -> None:
    """Heat-pump setup works without an explicit production-active signal."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SYSTEM_TYPE: SYSTEM_TYPE_HEAT_PUMP},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_DHW_TEMPERATURE_ENTITY: "sensor.dhw_temperature",
            CONF_ELECTRICITY_PRICE_ENTITY: "sensor.electricity_price",
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        THRESHOLDS,
    )
    assert result["step_id"] == "heat_pump_control"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_BLOCK_ENTITY: "switch.blockera_varmvatten",
            CONF_EXTRA_HOT_WATER_ENTITY: "input_boolean.hp_extra_warm_water",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BLOCK_ENTITY] == "switch.blockera_varmvatten"
    assert (
        result["data"][CONF_EXTRA_HOT_WATER_ENTITY]
        == "input_boolean.hp_extra_warm_water"
    )


async def test_invalid_threshold_order_is_rejected(hass) -> None:
    """Invalid temperature threshold ordering keeps the user on the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SYSTEM_TYPE: SYSTEM_TYPE_HEAT_PUMP},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_DHW_TEMPERATURE_ENTITY: "sensor.dhw_temperature",
            CONF_ELECTRICITY_PRICE_ENTITY: "sensor.electricity_price",
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_ABSOLUTE_MINIMUM: 46.0,
            CONF_COMFORT_MINIMUM: 45.0,
            CONF_NORMAL_TARGET: 50.0,
            CONF_PRECHARGE_TARGET: 55.0,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "thresholds"
    assert result["errors"]["base"] == "invalid_threshold_order"


async def test_options_flow_adds_thresholds_to_existing_entry(hass) -> None:
    """Older entries receive configurable thresholds through Options Flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SYSTEM_TYPE: SYSTEM_TYPE_HEAT_PUMP,
            CONF_DHW_TEMPERATURE_ENTITY: "sensor.old_dhw_temperature",
            CONF_ELECTRICITY_PRICE_ENTITY: "sensor.old_electricity_price",
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SYSTEM_TYPE: SYSTEM_TYPE_HEAT_PUMP,
            CONF_DHW_TEMPERATURE_ENTITY: "sensor.new_dhw_temperature",
            CONF_ELECTRICITY_PRICE_ENTITY: "sensor.new_electricity_price",
        },
    )
    assert result["step_id"] == "thresholds"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        THRESHOLDS,
    )
    assert result["step_id"] == "heat_pump_control"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_BLOCK_ENTITY: "switch.blockera_varmvatten"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ABSOLUTE_MINIMUM] == 40.0
    assert result["data"][CONF_NORMAL_TARGET] == 50.0

    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
