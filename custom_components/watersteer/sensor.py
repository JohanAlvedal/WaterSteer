"""Sensor platform for WaterSteer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WaterSteerDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class WaterSteerSensorEntityDescription(SensorEntityDescription):
    """Describe a WaterSteer sensor."""

    value_fn: Callable[[dict[str, Any]], Any]


SENSORS: tuple[WaterSteerSensorEntityDescription, ...] = (
    WaterSteerSensorEntityDescription(
        key="mode",
        translation_key="mode",
        value_fn=lambda data: data["mode"],
    ),
    WaterSteerSensorEntityDescription(
        key="decision",
        translation_key="decision",
        value_fn=lambda data: data["decision"],
    ),
    WaterSteerSensorEntityDescription(
        key="dhw_temperature",
        translation_key="dhw_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data["dhw_temperature"],
    ),
    WaterSteerSensorEntityDescription(
        key="standby_loss",
        translation_key="standby_loss",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data["standby_loss"],
    ),
    WaterSteerSensorEntityDescription(
        key="heating_rate",
        translation_key="heating_rate",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data["heating_rate"],
    ),
    WaterSteerSensorEntityDescription(
        key="projected_temperature_1h",
        translation_key="projected_temperature_1h",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data["projected_temperature_1h"],
    ),
    WaterSteerSensorEntityDescription(
        key="time_to_comfort",
        translation_key="time_to_comfort",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data["minutes_to_comfort"],
    ),
    WaterSteerSensorEntityDescription(
        key="learning_confidence",
        translation_key="learning_confidence",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data["learning_confidence"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up WaterSteer sensors."""
    coordinator: WaterSteerDataUpdateCoordinator = entry.runtime_data
    async_add_entities(
        WaterSteerSensor(coordinator, entry, description) for description in SENSORS
    )


class WaterSteerSensor(
    CoordinatorEntity[WaterSteerDataUpdateCoordinator], SensorEntity
):
    """Representation of a WaterSteer sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WaterSteerDataUpdateCoordinator,
        entry: ConfigEntry,
        description: WaterSteerSensorEntityDescription,
    ) -> None:
        """Initialize a WaterSteer sensor."""
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
    def native_value(self) -> Any:
        """Return the current sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return thermal-learning details on learning-related sensors."""
        if self.entity_description.key not in {
            "standby_loss",
            "heating_rate",
            "time_to_comfort",
            "learning_confidence",
        }:
            return None

        data = self.coordinator.data
        return {
            "observation_count": data["thermal_observation_count"],
            "observation_hours": round(data["thermal_observation_hours"], 2),
            "passive_segment_count": data["passive_segment_count"],
            "heating_segment_count": data["heating_segment_count"],
            "heating_confidence": data["heating_confidence"],
        }
