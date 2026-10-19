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

from .actuator import DhwActuator, Lever
from .autonomy_model import estimate_autonomy
from .capability_model import estimate_safe_margin
from .const import (
    CONF_ABSOLUTE_MINIMUM,
    CONF_BLOCK_ENTITY,
    CONF_COMFORT_ESCALATION_MINUTES,
    CONF_COMFORT_MINIMUM,
    CONF_DHW_TEMPERATURE_ENTITY,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_EXTERNAL_HEATING_ENTITY,
    CONF_EXTRA_HOT_WATER_ENTITY,
    CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY,
    CONF_HEAT_PUMP_DHW_AVAILABLE_ENTITY,
    CONF_MAX_HOLD_HOURS,
    CONF_MIN_THERMAL_CONFIDENCE,
    CONF_NORMAL_TARGET,
    CONF_OCCUPANCY_ENTITY,
    CONF_PRECHARGE_TARGET,
    CONF_STANDALONE_CONTROL_SWITCH,
    CONF_STANDALONE_POWER_SENSOR,
    CONF_SYSTEM_TYPE,
    DEFAULT_ABSOLUTE_MINIMUM,
    DEFAULT_COMFORT_ESCALATION_MINUTES,
    DEFAULT_COMFORT_MINIMUM,
    DEFAULT_MAX_HOLD_HOURS,
    DEFAULT_MIN_THERMAL_CONFIDENCE,
    DEFAULT_NORMAL_TARGET,
    DEFAULT_PRECHARGE_TARGET,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MODE_LEARNING,
    MODE_SAFETY,
    SYSTEM_TYPE_STANDALONE,
)
from .controller import (
    DhwThresholds,
    apply_thermal_confidence_guard,
    classify_dhw_temperature,
    effective_thresholds,
)
from .decision import (
    MODE_ADVISORY,
    MODES,
    ControlOutput,
    ExplanationContext,
    arbitrate,
)
from .demand_predictor import DhwDemandPredictor
from .horizon_optimizer import optimize_horizon
from .price_planner import extract_price_slots, plan_price_window
from .safety import DhwSafetySupervisor
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
        # The optional Random Forest backend is disabled: it has not shown a
        # measurable benefit over the statistical profile and training it would
        # block the event loop. See docs/AUDIT.md.
        self.demand_predictor = DhwDemandPredictor(enable_ml=False)
        self.safety = DhwSafetySupervisor()
        self.actuator = DhwActuator(hass)
        self.mode = MODE_ADVISORY
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
        self._safety_store: Store[dict[str, Any]] = Store(
            hass,
            _STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}.safety_state",
        )
        self._last_store_save = None
        self._threshold_warning_logged = False

    async def async_initialize(self) -> None:
        """Restore persisted learning history."""
        thermal_data = await self._thermal_store.async_load()
        usage_data = await self._usage_store.async_load()
        self.thermal_model.restore(thermal_data)
        self.usage_model.restore(usage_data)
        self._restore_control_state(await self._safety_store.async_load())

    def _restore_control_state(self, data: dict[str, Any] | None) -> None:
        """Restore safety, actuator and mode state (with legacy format)."""
        if not isinstance(data, dict):
            return
        if "safety" not in data:
            self.safety.restore(data)
            return
        self.safety.restore(data.get("safety"))
        self.actuator.restore(data.get("actuator"))
        if data.get("mode") in MODES:
            self.mode = data["mode"]

    def _control_state(self) -> dict[str, Any]:
        """Return persisted control state."""
        return {
            "safety": self.safety.as_dict(),
            "actuator": self.actuator.as_dict(),
            "mode": self.mode,
        }

    def levers(self) -> tuple[Lever | None, Lever | None]:
        """Return the configured block and extra-hot-water levers."""
        config = self._config()
        if config.get(CONF_SYSTEM_TYPE) == SYSTEM_TYPE_STANDALONE:
            switch = config.get(CONF_STANDALONE_CONTROL_SWITCH)
            return (Lever(switch, on_means_block=False) if switch else None), None
        block = config.get(CONF_BLOCK_ENTITY)
        extra = config.get(CONF_EXTRA_HOT_WATER_ENTITY)
        return (
            Lever(block) if block else None,
            Lever(extra) if extra else None,
        )

    async def async_set_mode(self, mode: str) -> None:
        """Change the control mode and apply it immediately."""
        if mode not in MODES:
            raise ValueError(mode)
        self.mode = mode
        await self._safety_store.async_save(self._control_state())
        await self.async_refresh()

    async def async_release(self) -> None:
        """Release all levers WaterSteer holds and persist that."""
        block, extra = self.levers()
        await self.actuator.release(block, extra)
        await self._safety_store.async_save(self._control_state())

    async def async_shutdown(self) -> None:
        """Stop updates, release levers and persist learning history."""
        await super().async_shutdown()
        await self._thermal_store.async_save(self.thermal_model.as_dict())
        await self._usage_store.async_save(self.usage_model.as_dict())
        await self.async_release()

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

        configured_thresholds = DhwThresholds(
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
        thresholds, thresholds_valid = effective_thresholds(
            configured_thresholds,
            DhwThresholds(
                absolute_minimum=DEFAULT_ABSOLUTE_MINIMUM,
                comfort_minimum=DEFAULT_COMFORT_MINIMUM,
                normal_target=DEFAULT_NORMAL_TARGET,
                precharge_target=DEFAULT_PRECHARGE_TARGET,
            ),
        )
        if not thresholds_valid and not self._threshold_warning_logged:
            self._threshold_warning_logged = True
            _LOGGER.warning(
                "WaterSteer thresholds are not strictly ordered; using safe "
                "defaults and suspending price optimization"
            )
        self.safety.max_hold_hours = float(
            config.get(CONF_MAX_HOLD_HOURS, DEFAULT_MAX_HOLD_HOURS)
        )
        self.safety.comfort_escalation_minutes = float(
            config.get(
                CONF_COMFORT_ESCALATION_MINUTES,
                DEFAULT_COMFORT_ESCALATION_MINUTES,
            )
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

        occupancy = _occupancy_hint(occupancy_state)
        usage = self.usage_model.estimate(
            now_local=now_local,
            occupancy=occupancy,
        )
        demand_forecast = self.demand_predictor.predict(
            usage_model=self.usage_model,
            now_local=now_local,
            occupancy=occupancy,
            statistical_confidence=usage.confidence,
            hours=24,
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

        horizon_decision = optimize_horizon(
            now=now_local,
            current_temperature=dhw_temperature,
            comfort_minimum=thresholds.comfort_minimum,
            normal_target=thresholds.normal_target,
            precharge_target=thresholds.precharge_target,
            safe_margin_minutes=safe_margin.minutes,
            safe_margin_confidence=safe_margin.confidence,
            demand=demand_forecast,
            occupancy=occupancy,
            price_plan=price_plan,
            price_input_valid=electricity_price is not None,
            safety_allowed=decision.allowed,
            safety_request=decision.request,
            safety_force_request=(decision.force_request or self.safety.force_latched),
            optimization_allowed=thresholds_valid,
        )
        safety_before = self.safety.as_dict()
        safety_result = self.safety.evaluate(
            now=now.timestamp(),
            temperature=dhw_temperature,
            absolute_minimum=thresholds.absolute_minimum,
            comfort_minimum=thresholds.comfort_minimum,
            proposed_intent=horizon_decision.intent,
            proposed_reason=horizon_decision.reason,
            warnings=(() if thresholds_valid else ("invalid_threshold_configuration",)),
        )
        external_heating_entity = config.get(CONF_EXTERNAL_HEATING_ENTITY)
        external_heating_active = (
            _binary_state_hint(self.hass.states.get(external_heating_entity)) is True
            if external_heating_entity
            else False
        )
        optimization_ready = (
            thresholds_valid and thermal.loss_confidence >= minimum_thermal_confidence
        )
        output: ControlOutput = arbitrate(
            mode=self.mode,
            safety_intent=safety_result.intent,
            safety_reason=safety_result.reason,
            warnings=safety_result.warnings,
            external_heating_active=external_heating_active,
            optimization_ready=optimization_ready,
            context=ExplanationContext(
                temperature=dhw_temperature,
                absolute_minimum=thresholds.absolute_minimum,
                comfort_minimum=thresholds.comfort_minimum,
                normal_target=thresholds.normal_target,
                hold_minutes=safety_result.hold_minutes,
                max_hold_hours=self.safety.max_hold_hours,
                next_charge=price_plan.next_charge,
                thermal_confidence=thermal.loss_confidence,
                minimum_confidence=minimum_thermal_confidence,
            ),
        )
        actuator_before = self.actuator.as_dict()
        block_lever, extra_lever = self.levers()
        actuator_report = await self.actuator.apply(
            now=now.timestamp(),
            mode=self.mode,
            output=output,
            block_lever=block_lever,
            extra_lever=extra_lever,
        )
        control_request = output.intent
        warnings = tuple(dict.fromkeys(output.warnings + actuator_report.warnings))
        if (
            self.safety.as_dict() != safety_before
            or self.actuator.as_dict() != actuator_before
        ):
            await self._safety_store.async_save(self._control_state())

        if (thermal_observation_added or usage_observation_added) and (
            self._last_store_save is None
            or now - self._last_store_save >= _STORAGE_SAVE_INTERVAL
        ):
            await self._thermal_store.async_save(self.thermal_model.as_dict())
            await self._usage_store.async_save(self.usage_model.as_dict())
            self._last_store_save = now

        data_valid = dhw_temperature is not None
        mode = MODE_LEARNING if data_valid and thresholds_valid else MODE_SAFETY

        return {
            "mode": mode,
            "data_valid": data_valid,
            "control_mode": self.mode,
            "status": output.status,
            "explanation": output.explanation,
            "block": output.block,
            "extra_hot_water": output.extra_hot_water,
            "external_heating_active": external_heating_active,
            "optimization_ready": optimization_ready,
            "actuator_active": actuator_report.active,
            "actuator_commands": list(actuator_report.commands),
            "safety_problem": bool(warnings),
            "system_type": config[CONF_SYSTEM_TYPE],
            "decision": decision.classification,
            "decision_reason": decision.reason,
            "control_request": control_request,
            "control_request_reason": output.reason,
            "control_request_optimizer_intent": horizon_decision.intent,
            "control_request_optimizer_reason": horizon_decision.reason,
            "control_request_safety_override": safety_result.overridden,
            "safety_warnings": list(warnings),
            "hold_minutes": safety_result.hold_minutes,
            "max_hold_hours": self.safety.max_hold_hours,
            "comfort_escalation_minutes": self.safety.comfort_escalation_minutes,
            "threshold_configuration_valid": thresholds_valid,
            "control_request_confidence": horizon_decision.confidence,
            "control_request_demand_risk": horizon_decision.demand_risk * 100,
            "control_request_expected_demand_drop": (
                horizon_decision.demand_expected_drop_c
            ),
            "control_request_normal_precharge_margin": (
                horizon_decision.normal_precharge_margin_minutes
            ),
            "control_request_boost_recommended": horizon_decision.boost_recommended,
            "demand_prediction_backend": demand_forecast.backend,
            "demand_prediction_confidence": demand_forecast.confidence,
            "demand_prediction_peak_probability": (
                demand_forecast.peak_probability * 100
            ),
            "demand_prediction_expected_drop_24h": demand_forecast.expected_drop_c,
            "demand_prediction_high_demand_hours": demand_forecast.high_demand_hours,
            "demand_prediction_forecast": [
                {
                    "start": bucket.start.isoformat(),
                    "probability": round(bucket.probability * 100, 1),
                    "expected_drop_c": round(bucket.expected_drop_c, 2),
                }
                for bucket in demand_forecast.buckets
            ],
            "raw_temperature_decision": raw_decision.classification,
            "dhw_allowed": not output.block,
            "dhw_request": decision.request,
            "force_request": control_request == "force_heat",
            "force_recovery_active": safety_result.force_latched,
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
            "thermal_passive_hours": thermal.passive_hours,
            "thermal_loss_model": thermal.loss_model,
            "thermal_ambient_estimate": thermal.ambient_estimate_c,
            "thermal_validation_error": thermal.validation_error_c,
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
