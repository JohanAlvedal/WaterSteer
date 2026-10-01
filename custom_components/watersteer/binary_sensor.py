"""Binary sensor platform for WaterSteer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WaterSteerDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class WaterSteerBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a WaterSteer binary sensor."""

    data_key: str


BINARY_SENSORS: tuple[WaterSteerBinarySensorDescription, ...] = (
    WaterSteerBinarySensorDescription(
        key="dhw_allowed",
        translation_key="dhw_allowed",
        data_key="dhw_allowed",
    ),
    WaterSteerBinarySensorDescription(
        key="dhw_request",
        translation_key="dhw_request",
        data_key="dhw_request",
    ),
    WaterSteerBinarySensorDescription(
        key="force_request",
        translation_key="force_request",
        data_key="force_request",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up WaterSteer binary sensors."""
    coordinator: WaterSteerDataUpdateCoordinator = entry.runtime_data
    async_add_entities(
        WaterSteerDecisionBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSORS
    )


class WaterSteerDecisionBinarySensor(
    CoordinatorEntity[WaterSteerDataUpdateCoordinator], BinarySensorEntity
):
    """Represent one WaterSteer shadow-control boolean."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WaterSteerDataUpdateCoordinator,
        entry: ConfigEntry,
        description: WaterSteerBinarySensorDescription,
    ) -> None:
        """Initialize a WaterSteer decision binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="WaterSteer",
            manufacturer="WaterSteer",
            model="DHW optimization controller",
        )

    @property
    def is_on(self) -> bool:
        """Return the current decision boolean."""
        return bool(self.coordinator.data[self.entity_description.data_key])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return decision details useful for diagnostics."""
        data = self.coordinator.data
        return {
            "shadow_mode": data["shadow_mode"],
            "decision": data["decision"],
            "reason": data["decision_reason"],
            "mode": data["mode"],
            "system_type": data["system_type"],
            "current_temperature": data["dhw_temperature"],
            "absolute_minimum": data["absolute_minimum"],
            "comfort_minimum": data["comfort_minimum"],
            "normal_target": data["normal_target"],
            "precharge_target": data["precharge_target"],
            "electricity_price": data["electricity_price"],
            "dhw_allowed": data["dhw_allowed"],
            "dhw_request": data["dhw_request"],
            "force_request": data["force_request"],
            "heat_pump_dhw_available_state": data["heat_pump_dhw_available_state"],
        }
