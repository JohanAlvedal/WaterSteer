"""End-to-end safety tests through the WaterSteer config entry."""

from custom_components.watersteer.const import (
    CONF_ABSOLUTE_MINIMUM,
    CONF_COMFORT_MINIMUM,
    CONF_DHW_TEMPERATURE_ENTITY,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_NORMAL_TARGET,
    CONF_PRECHARGE_TARGET,
    CONF_SYSTEM_TYPE,
    DOMAIN,
    SYSTEM_TYPE_HEAT_PUMP,
)
from homeassistant.const import Platform, UnitOfTemperature
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

TEMP = "sensor.dhw_temperature"
PRICE = "sensor.electricity_price"


def _entry(**extra) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=3,
        data={
            CONF_SYSTEM_TYPE: SYSTEM_TYPE_HEAT_PUMP,
            CONF_DHW_TEMPERATURE_ENTITY: TEMP,
            CONF_ELECTRICITY_PRICE_ENTITY: PRICE,
            **extra,
        },
    )


async def _setup(hass, entry: MockConfigEntry, temperature: str) -> dict:
    hass.states.async_set(
        TEMP,
        temperature,
        {"unit_of_measurement": UnitOfTemperature.CELSIUS},
    )
    hass.states.async_set(PRICE, "1.20")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data.data


async def test_low_tank_publishes_force_heat(hass) -> None:
    """The 38.9 °C scenario produces force_heat with default thresholds."""
    entry = _entry()
    data = await _setup(hass, entry, "38.9")

    assert data["control_request"] == "force_heat"
    assert data["force_request"] is True
    assert data["dhw_allowed"] is True
    await hass.config_entries.async_unload(entry.entry_id)


async def test_invalid_thresholds_keep_safety_protection(hass) -> None:
    """A broken threshold set must not disable critical recovery."""
    entry = _entry(
        **{
            CONF_ABSOLUTE_MINIMUM: 40.0,
            CONF_COMFORT_MINIMUM: 45.0,
            CONF_NORMAL_TARGET: 50.0,
            CONF_PRECHARGE_TARGET: 50.0,
        }
    )
    data = await _setup(hass, entry, "38.9")

    assert data["control_request"] == "force_heat"
    assert data["threshold_configuration_valid"] is False
    assert "invalid_threshold_configuration" in data["safety_warnings"]
    assert data["mode"] == "safety"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_missing_temperature_fails_open(hass) -> None:
    """An unavailable sensor never results in a hold."""
    entry = _entry()
    data = await _setup(hass, entry, "unavailable")

    assert data["control_request"] == "normal"
    assert data["dhw_allowed"] is True
    await hass.config_entries.async_unload(entry.entry_id)


async def test_migration_reenables_thermal_learning_confidence(hass) -> None:
    """Version 2 disabled an entity that external automations depend on."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={
            CONF_SYSTEM_TYPE: SYSTEM_TYPE_HEAT_PUMP,
            CONF_DHW_TEMPERATURE_ENTITY: TEMP,
            CONF_ELECTRICITY_PRICE_ENTITY: PRICE,
        },
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    confidence = registry.async_get_or_create(
        Platform.SENSOR,
        DOMAIN,
        f"{entry.entry_id}_learning_confidence",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    user_disabled = registry.async_get_or_create(
        Platform.SENSOR,
        DOMAIN,
        f"{entry.entry_id}_standby_loss",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    hass.states.async_set(
        TEMP, "50.0", {"unit_of_measurement": UnitOfTemperature.CELSIUS}
    )
    hass.states.async_set(PRICE, "1.20")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 3
    assert registry.async_get(confidence.entity_id).disabled_by is None
    assert (
        registry.async_get(user_disabled.entity_id).disabled_by
        is er.RegistryEntryDisabler.USER
    )
    await hass.config_entries.async_unload(entry.entry_id)
