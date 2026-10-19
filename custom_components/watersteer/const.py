"""Constants for WaterSteer."""

from datetime import timedelta

DOMAIN = "watersteer"

CONF_SYSTEM_TYPE = "system_type"
CONF_DHW_TEMPERATURE_ENTITY = "dhw_temperature_entity"
CONF_ELECTRICITY_PRICE_ENTITY = "electricity_price_entity"
CONF_OCCUPANCY_ENTITY = "occupancy_entity"

CONF_ABSOLUTE_MINIMUM = "absolute_minimum"
CONF_COMFORT_MINIMUM = "comfort_minimum"
CONF_NORMAL_TARGET = "normal_target"
CONF_PRECHARGE_TARGET = "precharge_target"
CONF_MIN_THERMAL_CONFIDENCE = "min_thermal_confidence"

DEFAULT_ABSOLUTE_MINIMUM = 40.0
DEFAULT_COMFORT_MINIMUM = 45.0
DEFAULT_NORMAL_TARGET = 50.0
DEFAULT_PRECHARGE_TARGET = 55.0
DEFAULT_MIN_THERMAL_CONFIDENCE = 50

CONF_MAX_HOLD_HOURS = "max_hold_hours"
CONF_COMFORT_ESCALATION_MINUTES = "comfort_escalation_minutes"

DEFAULT_MAX_HOLD_HOURS = 6.0
DEFAULT_COMFORT_ESCALATION_MINUTES = 45.0

CONF_STANDALONE_CONTROL_SWITCH = "standalone_control_switch"
CONF_STANDALONE_POWER_SENSOR = "standalone_power_sensor"

CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY = "heat_pump_dhw_active_entity"
CONF_HEAT_PUMP_DHW_AVAILABLE_ENTITY = "heat_pump_dhw_available_entity"
CONF_HEAT_PUMP_BOOST_ACTION = "heat_pump_boost_action"
CONF_HEAT_PUMP_BLOCK_ACTION = "heat_pump_block_action"
CONF_HEAT_PUMP_NORMAL_ACTION = "heat_pump_normal_action"

SYSTEM_TYPE_STANDALONE = "standalone_water_heater"
SYSTEM_TYPE_HEAT_PUMP = "heat_pump_integrated_dhw"
SYSTEM_TYPES = (
    SYSTEM_TYPE_STANDALONE,
    SYSTEM_TYPE_HEAT_PUMP,
)

MODE_LEARNING = "learning"
MODE_SAFETY = "safety"

DEFAULT_UPDATE_INTERVAL = timedelta(seconds=30)

CONF_BLOCK_ENTITY = "block_entity"
CONF_EXTRA_HOT_WATER_ENTITY = "extra_hot_water_entity"
CONF_EXTERNAL_HEATING_ENTITY = "external_heating_entity"
