"""Constants for WaterSteer."""

from datetime import timedelta

DOMAIN = "watersteer"

CONF_SYSTEM_TYPE = "system_type"
CONF_DHW_TEMPERATURE_ENTITY = "dhw_temperature_entity"
CONF_ELECTRICITY_PRICE_ENTITY = "electricity_price_entity"

CONF_STANDALONE_CONTROL_SWITCH = "standalone_control_switch"
CONF_STANDALONE_POWER_SENSOR = "standalone_power_sensor"

CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY = "heat_pump_dhw_active_entity"
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
