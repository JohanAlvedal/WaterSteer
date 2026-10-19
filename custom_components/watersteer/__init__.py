"""WaterSteer integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .coordinator import WaterSteerDataUpdateCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

_ADVANCED_SENSOR_KEYS = (
    "decision",
    "standby_loss",
    "heating_rate",
    "projected_temperature_1h",
    "time_to_comfort",
    "passive_autonomy",
    "predicted_autonomy",
    "predicted_temperature_6h",
    "autonomy_confidence",
    "safe_margin_confidence",
    "expected_charge_duration",
    "planned_target",
    "selected_price",
    "usage_probability_next_6h",
    "expected_usage_drop_next_6h",
    "demand_level",
    "next_expected_usage",
    "typical_usage_drop",
    "usage_learning_confidence",
)

_ADVANCED_BINARY_SENSOR_KEYS = (
    "dhw_request",
    "usage_detected",
)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older WaterSteer config entries."""
    if entry.version < 2:
        registry = er.async_get(hass)

        for platform, keys in (
            (Platform.SENSOR, _ADVANCED_SENSOR_KEYS),
            (Platform.BINARY_SENSOR, _ADVANCED_BINARY_SENSOR_KEYS),
        ):
            for key in keys:
                entity_id = registry.async_get_entity_id(
                    platform,
                    "watersteer",
                    f"{entry.entry_id}_{key}",
                )
                if entity_id is not None:
                    registry.async_update_entity(
                        entity_id,
                        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
                    )

        hass.config_entries.async_update_entry(entry, version=2)

    if entry.version < 3:
        # Version 2 disabled the thermal learning confidence sensor, but
        # sensor.watersteer_thermal_learning_confidence is used by external
        # automations. Re-enable it only when WaterSteer itself disabled it, so
        # an explicit user choice is preserved.
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            Platform.SENSOR,
            "watersteer",
            f"{entry.entry_id}_learning_confidence",
        )
        if entity_id is not None:
            registry_entry = registry.async_get(entity_id)
            if (
                registry_entry is not None
                and registry_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
            ):
                registry.async_update_entity(entity_id, disabled_by=None)

        hass.config_entries.async_update_entry(entry, version=3)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WaterSteer from a config entry."""
    coordinator = WaterSteerDataUpdateCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a WaterSteer config entry."""
    coordinator: WaterSteerDataUpdateCoordinator = entry.runtime_data
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await coordinator.async_shutdown()
    return unload_ok
