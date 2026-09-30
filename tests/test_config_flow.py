"""Tests for the WaterSteer config flow."""

from custom_components.watersteer.const import (
    CONF_DHW_TEMPERATURE_ENTITY,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_HEAT_PUMP_BOOST_ACTION,
    CONF_STANDALONE_CONTROL_SWITCH,
    CONF_SYSTEM_TYPE,
    DOMAIN,
    SYSTEM_TYPE_HEAT_PUMP,
    SYSTEM_TYPE_STANDALONE,
)
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_standalone_config_flow(hass) -> None:
    """Standalone setup asks for a control switch and creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SYSTEM_TYPE: SYSTEM_TYPE_STANDALONE},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "sensors"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_DHW_TEMPERATURE_ENTITY: "sensor.dhw_temperature",
            CONF_ELECTRICITY_PRICE_ENTITY: "sensor.electricity_price",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "standalone_control"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_STANDALONE_CONTROL_SWITCH: "switch.water_heater"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SYSTEM_TYPE] == SYSTEM_TYPE_STANDALONE
    assert result["data"][CONF_STANDALONE_CONTROL_SWITCH] == "switch.water_heater"


async def test_heat_pump_config_flow(hass) -> None:
    """Heat-pump setup accepts generic Home Assistant actions."""
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
    assert result["step_id"] == "heat_pump_control"

    boost_action = [
        {
            "action": "switch.turn_on",
            "target": {"entity_id": "switch.dhw_boost"},
        }
    ]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HEAT_PUMP_BOOST_ACTION: boost_action},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SYSTEM_TYPE] == SYSTEM_TYPE_HEAT_PUMP
    assert result["data"][CONF_HEAT_PUMP_BOOST_ACTION] == boost_action


async def test_options_flow_changes_heat_pump_configuration(hass) -> None:
    """Options flow allows an existing WaterSteer entry to be reconfigured."""
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
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SYSTEM_TYPE: SYSTEM_TYPE_HEAT_PUMP,
            CONF_DHW_TEMPERATURE_ENTITY: "sensor.new_dhw_temperature",
            CONF_ELECTRICITY_PRICE_ENTITY: "sensor.new_electricity_price",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "heat_pump_control"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SYSTEM_TYPE] == SYSTEM_TYPE_HEAT_PUMP
    assert (
        result["data"][CONF_DHW_TEMPERATURE_ENTITY]
        == "sensor.new_dhw_temperature"
    )
