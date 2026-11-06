"""Mode select for WaterSteer."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import WaterSteerDataUpdateCoordinator
from .decision import MODES
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the WaterSteer mode select."""
    async_add_entities([WaterSteerModeSelect(entry.runtime_data, entry)])


class WaterSteerModeSelect(
    CoordinatorEntity[WaterSteerDataUpdateCoordinator], SelectEntity
):
    """Choose between advisory, active and off.

    The mode is persisted by the coordinator rather than restored by the
    entity, so the very first update after a restart already uses it and
    WaterSteer never toggles a lever during startup.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "operating_mode"
    _attr_options = list(MODES)

    def __init__(
        self,
        coordinator: WaterSteerDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_operating_mode"
        self._attr_device_info = device_info(entry)

    @property
    def current_option(self) -> str:
        """Return the active mode."""
        return self.coordinator.mode

    async def async_select_option(self, option: str) -> None:
        """Change the mode."""
        await self.coordinator.async_set_mode(option)
