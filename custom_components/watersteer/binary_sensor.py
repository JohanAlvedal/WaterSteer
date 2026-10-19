"""Binary sensor platform for WaterSteer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import WaterSteerDataUpdateCoordinator
from .entity import device_info


@dataclass(frozen=True, kw_only=True)
class WaterSteerBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a WaterSteer binary sensor."""

    data_key: str


BINARY_SENSORS: tuple[WaterSteerBinarySensorDescription, ...] = (
    WaterSteerBinarySensorDescription(
        key="safety",
        translation_key="safety",
        device_class=BinarySensorDeviceClass.PROBLEM,
        data_key="safety_problem",
    ),
    # The two physical levers, for users who drive the heat pump with their
    # own automations instead of WaterSteer's active mode.
    WaterSteerBinarySensorDescription(
        key="dhw_allowed",
        translation_key="dhw_allowed",
        entity_registry_enabled_default=False,
        data_key="dhw_allowed",
    ),
    WaterSteerBinarySensorDescription(
        key="extra_hot_water",
        translation_key="extra_hot_water",
        entity_registry_enabled_default=False,
        data_key="extra_hot_water",
    ),
    WaterSteerBinarySensorDescription(
        key="force_request",
        translation_key="force_request",
        entity_registry_enabled_default=False,
        data_key="force_request",
    ),
    WaterSteerBinarySensorDescription(
        key="dhw_request",
        translation_key="dhw_request",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="dhw_request",
    ),
    WaterSteerBinarySensorDescription(
        key="usage_detected",
        translation_key="usage_detected",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="usage_detected",
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
    """Represent one WaterSteer boolean output."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WaterSteerDataUpdateCoordinator,
        entry: ConfigEntry,
        description: WaterSteerBinarySensorDescription,
    ) -> None:
        """Initialize a WaterSteer binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool:
        """Return the current boolean state."""
        return bool(self.coordinator.data[self.entity_description.data_key])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return only what explains this boolean."""
        data = self.coordinator.data
        if self.entity_description.key == "safety":
            return {"warnings": data["safety_warnings"]}
        return {
            "control_request": data["control_request"],
            "reason": data["control_request_reason"],
        }
