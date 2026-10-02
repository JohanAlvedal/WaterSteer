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
    WaterSteerSensorEntityDescription(
        key="passive_autonomy",
        translation_key="passive_autonomy",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data["passive_autonomy_minutes"],
    ),
    WaterSteerSensorEntityDescription(
        key="predicted_autonomy",
        translation_key="predicted_autonomy",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data["predicted_autonomy_minutes"],
    ),
    WaterSteerSensorEntityDescription(
        key="predicted_temperature_6h",
        translation_key="predicted_temperature_6h",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data["predicted_temperature_6h"],
    ),
    WaterSteerSensorEntityDescription(
        key="autonomy_confidence",
        translation_key="autonomy_confidence",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data["autonomy_confidence"],
    ),
    WaterSteerSensorEntityDescription(
        key="price_plan_status",
        translation_key="price_plan_status",
        value_fn=lambda data: data["price_plan_status"],
    ),
    WaterSteerSensorEntityDescription(
        key="next_charge",
        translation_key="next_charge",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data["price_plan_next_charge"],
    ),
    WaterSteerSensorEntityDescription(
        key="expected_charge_duration",
        translation_key="expected_charge_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data["price_plan_expected_charge_minutes"],
    ),
    WaterSteerSensorEntityDescription(
        key="planned_target",
        translation_key="planned_target",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data["price_plan_target"],
    ),
    WaterSteerSensorEntityDescription(
        key="selected_price",
        translation_key="selected_price",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda data: data["price_plan_selected_price"],
    ),
    WaterSteerSensorEntityDescription(
        key="usage_probability_next_6h",
        translation_key="usage_probability_next_6h",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data["usage_probability_next_6h"],
    ),
    WaterSteerSensorEntityDescription(
        key="expected_usage_drop_next_6h",
        translation_key="expected_usage_drop_next_6h",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data["expected_usage_drop_next_6h"],
    ),
    WaterSteerSensorEntityDescription(
        key="demand_level",
        translation_key="demand_level",
        value_fn=lambda data: data["demand_level"],
    ),
    WaterSteerSensorEntityDescription(
        key="next_expected_usage",
        translation_key="next_expected_usage",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data["next_expected_usage"],
    ),
    WaterSteerSensorEntityDescription(
        key="typical_usage_drop",
        translation_key="typical_usage_drop",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data["typical_usage_drop"],
    ),
    WaterSteerSensorEntityDescription(
        key="usage_learning_confidence",
        translation_key="usage_learning_confidence",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data["usage_learning_confidence"],
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
        """Return learning details on learning-related sensors."""
        data = self.coordinator.data

        if self.entity_description.key in {
            "standby_loss",
            "heating_rate",
            "time_to_comfort",
            "learning_confidence",
            "passive_autonomy",
            "predicted_autonomy",
            "predicted_temperature_6h",
            "autonomy_confidence",
        }:
            return {
                "observation_count": data["thermal_observation_count"],
                "observation_hours": round(data["thermal_observation_hours"], 2),
                "passive_segment_count": data["passive_segment_count"],
                "heating_segment_count": data["heating_segment_count"],
                "heating_confidence": data["heating_confidence"],
                "minimum_braking_confidence": data["minimum_thermal_confidence"],
                "braking_confidence_ready": data["braking_confidence_ready"],
                "autonomy_basis": data["autonomy_basis"],
                "demand_adjusted": data["autonomy_demand_adjusted"],
                "usage_learning_confidence": data["usage_learning_confidence"],
            }

        if self.entity_description.key in {
            "price_plan_status",
            "next_charge",
            "expected_charge_duration",
            "planned_target",
            "selected_price",
        }:
            return {
                "reason": data["price_plan_reason"],
                "charge_end": data["price_plan_charge_end"],
                "planning_deadline": data["price_plan_deadline"],
                "current_price": data["electricity_price"],
                "selected_price": data["price_plan_selected_price"],
                "savings_vs_current": data["price_plan_savings_vs_current"],
                "price_slot_count": data["price_plan_slot_count"],
                "planner_confidence": data["price_plan_confidence"],
                "window_active_now": data["price_plan_window_active_now"],
                "shadow_mode": data["shadow_mode"],
            }

        if self.entity_description.key in {
            "usage_probability_next_6h",
            "expected_usage_drop_next_6h",
            "demand_level",
            "next_expected_usage",
            "typical_usage_drop",
            "usage_learning_confidence",
        }:
            return {
                "usage_event_count": data["usage_event_count"],
                "observed_days": data["usage_observed_days"],
                "relevant_observed_days": data["usage_relevant_observed_days"],
                "profile_day_type": data["usage_profile_day_type"],
                "small_event_count": data["usage_small_event_count"],
                "medium_event_count": data["usage_medium_event_count"],
                "large_event_count": data["usage_large_event_count"],
                "next_expected_usage_probability": data[
                    "next_expected_usage_probability"
                ],
                "next_expected_usage_drop": data["next_expected_usage_drop"],
                "occupancy_state": data["occupancy_state"],
                "hourly_forecast": data["usage_forecast"],
            }

        return None
