"""Data coordinator for WaterSteer."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .autonomy_model import estimate_autonomy
from .capability_model import estimate_safe_margin
from .const import (
    CONF_ABSOLUTE_MINIMUM,
    CONF_COMFORT_MINIMUM,
    CONF_DHW_TEMPERATURE_ENTITY,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY,
    CONF_HEAT_PUMP_DHW_AVAILABLE_ENTITY,
    CONF_MIN_THERMAL_CONFIDENCE,
    CONF_NORMAL_TARGET,
    CONF_OCCUPANCY_ENTITY,
    CONF_PRECHARGE_TARGET,
    CONF_STANDALONE_CONTROL_SWITCH,
    CONF_STANDALONE_POWER_SENSOR,
    CONF_SYSTEM_TYPE,
    DEFAULT_ABSOLUTE_MINIMUM,
    DEFAULT_COMFORT_MINIMUM,
    DEFAULT_MIN_THERMAL_CONFIDENCE,
    DEFAULT_NORMAL_TARGET,
    DEFAULT_PRECHARGE_TARGET,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MODE_LEARNING,
    MODE_SAFETY,
)
from .controller import (
    DhwThresholds,
    apply_thermal_confidence_guard,
    classify_dhw_temperature,
)
from .price_planner import extract_price_slots, plan_price_window
from .thermal_model import DhwThermalModel
from .usage_model import DhwUsageModel

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1
_STORAGE_SAVE_INTERVAL = timedelta(minutes=15)


def _as_float(value: str | None) -> float | None:
    """Convert a Home Assistant state to float when possible."""
    if value is None or value in {"unknown", "unavailable"}:
        return None

    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _temperature_celsius(state: State | None) -> float | None:
    """Return a temperature state normalized to degrees Celsius."""
    if state is None:
        return None

    value = _as_float(state.state)
    if value is None:
        return None

    unit = state.attributes.get("unit_of_measurement")
    if unit is None:
        return None

    try:
        return TemperatureConverter.convert(
            value,
            unit,
            UnitOfTemperature.CELSIUS,
        )
    except TypeError, ValueError:
        return None


def _binary_state_hint(state: State | None) -> bool | None:
    """Return an optional boolean hint from a binary-style state."""
    if state is None:
        return None
    if state.state == STATE_ON:
        return True
    if state.state == STATE_OFF:
        return False
    return None


def _occupancy_hint(state: State | None) -> bool | None:
    """Normalize an optional Home Assistant occupancy entity."""
    if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
        return None
    if state.domain in {"binary_sensor", "input_boolean"}:
        return _binary_state_hint(state)
    if state.domain == "person":
        return state.state == "home"
    return None


class WaterSteerDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Collect inputs and maintain WaterSteer's learning models."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the WaterSteer coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self.entry = entry
        self.thermal_model = DhwThermalModel()
        self.usage_model = DhwUsageModel()
        self._thermal_store: Store[dict[str, Any]] = Store(
            hass,
            _STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}.thermal_model",
        )
        self._usage_store: Store[dict[str, Any]] = Store(
            hass,
            _STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}.usage_model",
        )
        self._last_store_save = None

    async def async_initialize(self) -> None:
        """Restore persisted learning history."""
        thermal_data = await self._thermal_store.async_load()
        usage_data = await self._usage_store.async_load()
        self.thermal_model.restore(thermal_data)
        self.usage_model.restore(usage_data)

    async def async_shutdown(self) -> None:
        """Persist learning history before the integration unloads."""
        await self._thermal_store.async_save(self.thermal_model.as_dict())
        await self._usage_store.async_save(self.usage_model.as_dict())

    def _config(self) -> dict[str, Any]:
        """Return effective configuration with options overriding setup data."""
        return {**self.entry.data, **self.entry.options}

    async def _async_update_data(self) -> dict[str, Any]:
        """Read inputs, update learning, and calculate advisory decisions."""
        config = self._config()
        temperature_entity = config.get(CONF_DHW_TEMPERATURE_ENTITY)
        price_entity = config[CONF_ELECTRICITY_PRICE_ENTITY]
        occupancy_entity = config.get(CONF_OCCUPANCY_ENTITY)

        temperature_state = (
            self.hass.states.get(temperature_entity) if temperature_entity else None
        )
        price_state = self.hass.states.get(price_entity)
        occupancy_state = (
            self.hass.states.get(occupancy_entity) if occupancy_entity else None
        )

        dhw_temperature = _temperature_celsius(temperature_state)
        electricity_price = _as_float(
            price_state.state if price_state is not None else None
        )

        thresholds = DhwThresholds(
            absolute_minimum=float(
                config.get(CONF_ABSOLUTE_MINIMUM, DEFAULT_ABSOLUTE_MINIMUM)
            ),
            comfort_minimum=float(
                config.get(CONF_COMFORT_MINIMUM, DEFAULT_COMFORT_MINIMUM)
            ),
            normal_target=float(config.get(CONF_NORMAL_TARGET, DEFAULT_NORMAL_TARGET)),
            precharge_target=float(
                config.get(CONF_PRECHARGE_TARGET, DEFAULT_PRECHARGE_TARGET)
            ),
        )
        minimum_thermal_confidence = int(
            float(
                config.get(
                    CONF_MIN_THERMAL_CONFIDENCE,
                    DEFAULT_MIN_THERMAL_CONFIDENCE,
                )
            )
        )

        standalone_switch = config.get(CONF_STANDALONE_CONTROL_SWITCH)
        standalone_power_sensor = config.get(CONF_STANDALONE_POWER_SENSOR)
        dhw_active_entity = config.get(CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY)
        dhw_available_entity = config.get(CONF_HEAT_PUMP_DHW_AVAILABLE_ENTITY)

        standalone_switch_state = (
            self.hass.states.get(standalone_switch) if standalone_switch else None
        )
        standalone_power_state = (
            self.hass.states.get(standalone_power_sensor)
            if standalone_power_sensor
            else None
        )
        dhw_active_state = (
            self.hass.states.get(dhw_active_entity) if dhw_active_entity else None
        )
        dhw_available_state = (
            self.hass.states.get(dhw_available_entity) if dhw_available_entity else None
        )

        now = dt_util.utcnow()
        now_local = dt_util.as_local(now)
        heating_hint = _binary_state_hint(dhw_active_state)
        thermal_observation_added = False
        usage_observation_added = False

        if dhw_temperature is not None:
            thermal_observation_added = self.thermal_model.add_observation(
                now.timestamp(),
                dhw_temperature,
                heating_hint,
            )

        thermal = self.thermal_model.estimate(
            dhw_temperature,
            thresholds.comfort_minimum,
        )

        if dhw_temperature is not None:
            usage_observation_added = self.usage_model.add_observation(
                timestamp=now.timestamp(),
                temperature=dhw_temperature,
                local_datetime=now_local,
                heating_active=heating_hint,
                standby_loss_c_per_hour=thermal.standby_loss_c_per_hour,
            )

        usage = self.usage_model.estimate(
            now_local=now_local,
            occupancy=_occupancy_hint(occupancy_state),
        )
        autonomy = estimate_autonomy(
            current_temperature=dhw_temperature,
            comfort_minimum=thresholds.comfort_minimum,
            standby_loss_c_per_hour=thermal.standby_loss_c_per_hour,
            thermal_confidence=thermal.loss_confidence,
            usage_confidence=usage.confidence,
            usage_forecast=usage.forecast,
        )
        safe_margin = estimate_safe_margin(
            passive_autonomy_minutes=autonomy.passive_minutes,
            predicted_autonomy_minutes=autonomy.predicted_minutes,
            thermal_confidence=thermal.loss_confidence,
            usage_confidence=usage.confidence,
        )
        price_slots = extract_price_slots(
            now=now_local,
            attributes=(
                dict(price_state.attributes) if price_state is not None else {}
            ),
        )
        price_plan = plan_price_window(
            now=now_local,
            current_temperature=dhw_temperature,
            comfort_minimum=thresholds.comfort_minimum,
            normal_target=thresholds.normal_target,
            precharge_target=thresholds.precharge_target,
            predicted_autonomy_minutes=safe_margin.minutes,
            autonomy_confidence=safe_margin.confidence,
            heating_rate_c_per_hour=thermal.heating_rate_c_per_hour,
            current_price=electricity_price,
            price_slots=price_slots,
            minimum_confidence=minimum_thermal_confidence,
        )

        raw_decision = classify_dhw_temperature(dhw_temperature, thresholds)
        decision = apply_thermal_confidence_guard(
            raw_decision,
            thermal_confidence=thermal.loss_confidence,
            minimum_confidence=minimum_thermal_confidence,
        )

        if (thermal_observation_added or usage_observation_added) and (
            self._last_store_save is None
            or now - self._last_store_save >= _STORAGE_SAVE_INTERVAL
        ):
            await self._thermal_store.async_save(self.thermal_model.as_dict())
            await self._usage_store.async_save(self.usage_model.as_dict())
            self._last_store_save = now

        data_valid = dhw_temperature is not None
        mode = MODE_LEARNING if data_valid and thresholds.valid else MODE_SAFETY

        return {
            "mode": mode,
            "data_valid": data_valid,
            "control_mode": "advisory",
            "system_type": config[CONF_SYSTEM_TYPE],
            "decision": decision.classification,
            "decision_reason": decision.reason,
            "raw_temperature_decision": raw_decision.classification,
            "dhw_allowed": decision.allowed,
            "dhw_request": decision.request,
            "force_request": decision.force_request,
            "absolute_minimum": thresholds.absolute_minimum,
            "comfort_minimum": thresholds.comfort_minimum,
            "normal_target": thresholds.normal_target,
            "precharge_target": thresholds.precharge_target,
            "minimum_thermal_confidence": minimum_thermal_confidence,
            "braking_confidence_ready": (
                thermal.loss_confidence >= minimum_thermal_confidence
            ),
            "dhw_temperature": dhw_temperature,
            "dhw_temperature_source_unit": (
                temperature_state.attributes.get("unit_of_measurement")
                if temperature_state is not None
                else None
            ),
            "electricity_price": electricity_price,
            "price_plan_status": price_plan.status,
            "price_plan_reason": price_plan.reason,
            "price_plan_next_charge": price_plan.next_charge,
            "price_plan_charge_end": price_plan.charge_end,
            "price_plan_expected_charge_minutes": (price_plan.expected_charge_minutes),
            "price_plan_target": price_plan.planned_target,
            "price_plan_selected_price": price_plan.selected_price,
            "price_plan_savings_vs_current": price_plan.savings_vs_current,
            "price_plan_slot_count": price_plan.price_slot_count,
            "price_plan_deadline": price_plan.planning_deadline,
            "price_plan_confidence": price_plan.confidence,
            "price_plan_window_active_now": price_plan.window_active_now,
            "price_plan_next_peak_start": price_plan.next_peak_start,
            "price_plan_next_peak_end": price_plan.next_peak_end,
            "price_plan_next_peak_price": price_plan.next_peak_price,
            "price_plan_peak_avoidance_active": price_plan.peak_avoidance_active,
            "standby_loss": thermal.standby_loss_c_per_hour,
            "heating_rate": thermal.heating_rate_c_per_hour,
            "projected_temperature_1h": thermal.projected_temperature_1h,
            "minutes_to_comfort": thermal.minutes_to_comfort,
            "passive_autonomy_minutes": autonomy.passive_minutes,
            "predicted_autonomy_minutes": autonomy.predicted_minutes,
            "predicted_temperature_6h": autonomy.predicted_temperature_6h,
            "autonomy_confidence": autonomy.confidence,
            "autonomy_basis": autonomy.basis,
            "autonomy_demand_adjusted": autonomy.demand_adjusted,
            "safe_margin_minutes": safe_margin.minutes,
            "safe_margin_confidence": safe_margin.confidence,
            "safe_margin_source": safe_margin.source,
            "safe_margin_usage_adjusted": safe_margin.usage_adjusted,
            "safe_margin_reason": safe_margin.reason,
            "learning_confidence": thermal.loss_confidence,
            "heating_confidence": thermal.heating_confidence,
            "thermal_observation_count": thermal.observation_count,
            "thermal_observation_hours": thermal.observation_hours,
            "passive_segment_count": thermal.passive_segment_count,
            "heating_segment_count": thermal.heating_segment_count,
            "usage_detected": usage.usage_detected,
            "usage_probability_next_6h": usage.usage_probability_next_6h,
            "expected_usage_drop_next_6h": usage.expected_usage_drop_next_6h,
            "next_expected_usage": usage.next_expected_usage,
            "next_expected_usage_probability": usage.next_expected_usage_probability,
            "next_expected_usage_drop": usage.next_expected_usage_drop,
            "demand_level": usage.demand_level,
            "typical_usage_drop": usage.typical_usage_drop,
            "usage_learning_confidence": usage.confidence,
            "usage_event_count": usage.event_count,
            "usage_observed_days": usage.observed_days,
            "usage_relevant_observed_days": usage.relevant_observed_days,
            "usage_small_event_count": usage.small_event_count,
            "usage_medium_event_count": usage.medium_event_count,
            "usage_large_event_count": usage.large_event_count,
            "usage_direct_event_count": usage.direct_event_count,
            "usage_recovery_event_count": usage.recovery_event_count,
            "usage_profile_day_type": usage.profile_day_type,
            "usage_forecast": [
                {
                    "start": bucket.start.isoformat(),
                    "probability": round(bucket.probability * 100, 1),
                    "typical_drop_c": (
                        round(bucket.typical_drop_c, 2)
                        if bucket.typical_drop_c is not None
                        else None
                    ),
                    "expected_drop_c": round(bucket.expected_drop_c, 2),
                }
                for bucket in usage.forecast
            ],
            "occupancy_state": usage.occupancy_state,
            "occupancy_entity": occupancy_entity,
            "dhw_temperature_entity": temperature_entity,
            "electricity_price_entity": price_entity,
            "standalone_control_switch": standalone_switch,
            "standalone_control_switch_state": (
                standalone_switch_state.state
                if standalone_switch_state is not None
                else None
            ),
            "standalone_power_sensor": standalone_power_sensor,
            "standalone_power": _as_float(
                standalone_power_state.state
                if standalone_power_state is not None
                else None
            ),
            "heat_pump_dhw_active_entity": dhw_active_entity,
            "heat_pump_dhw_active_state": (
                dhw_active_state.state if dhw_active_state is not None else None
            ),
            "heat_pump_dhw_available_entity": dhw_available_entity,
            "heat_pump_dhw_available_state": (
                dhw_available_state.state if dhw_available_state is not None else None
            ),
        }
