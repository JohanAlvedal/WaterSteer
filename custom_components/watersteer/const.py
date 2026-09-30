"""Constants for WaterSteer."""

from datetime import timedelta

DOMAIN = "watersteer"

CONF_SYSTEM_TYPE = "system_type"
CONF_DHW_TEMPERATURE_ENTITY = "dhw_temperature_entity"
CONF_ELECTRICITY_PRICE_ENTITY = "electricity_price_entity"

SYSTEM_TYPE_STANDALONE = "standalone_water_heater"
SYSTEM_TYPE_HEAT_PUMP = "heat_pump_integrated_dhw"
SYSTEM_TYPES = (
    SYSTEM_TYPE_STANDALONE,
    SYSTEM_TYPE_HEAT_PUMP,
)

MODE_LEARNING = "learning"
MODE_SAFETY = "safety"

DEFAULT_UPDATE_INTERVAL = timedelta(seconds=30)
