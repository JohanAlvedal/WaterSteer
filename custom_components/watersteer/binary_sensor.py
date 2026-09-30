"""Binary sensor platform for WaterSteer."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WaterSteerDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up WaterSteer binary sensors."""
    coordinator: WaterSteerDataUpdateCoordinator = entry.runtime_data
    async_add_entities([WaterSteerDhwAllowedBinarySensor(coordinator, entry)])


class WaterSteerDhwAllowedBinarySensor(
    CoordinatorEntity[WaterSteerDataUpdateCoordinator], BinarySensorEntity
):
    """Show whether WaterSteer currently allows DHW production."""

    _attr_has_entity_name = True
    _attr_translation_key = "dhw_allowed"

    def __init__(
        self,
        coordinator: WaterSteerDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the DHW allowed binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_dhw_allowed"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="WaterSteer",
            manufacturer="WaterSteer",
            model="DHW optimization controller",
        )

    @property
    def is_on(self) -> bool:
        """Return True when DHW production is allowed."""
        return bool(self.coordinator.data["dhw_allowed"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return decision details useful for diagnostics."""
        data = self.coordinator.data
        return {
            "reason": data["dhw_allowed_reason"],
            "mode": data["mode"],
            "system_type": data["system_type"],
            "current_temperature": data["dhw_temperature"],
            "electricity_price": data["electricity_price"],
        }
