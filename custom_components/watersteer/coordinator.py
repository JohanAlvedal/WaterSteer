"""Data coordinator for WaterSteer."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_DHW_TEMPERATURE_ENTITY,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_SYSTEM_TYPE,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MODE_LEARNING,
    MODE_SAFETY,
)


def _as_float(value: str | None) -> float | None:
    """Convert a Home Assistant state to float when possible."""
    if value is None or value in {"unknown", "unavailable"}:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class WaterSteerDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Collect and normalize WaterSteer input data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the WaterSteer coordinator."""
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self.entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        """Read WaterSteer inputs from the Home Assistant state machine."""
        temperature_entity = self.entry.data[CONF_DHW_TEMPERATURE_ENTITY]
        price_entity = self.entry.data[CONF_ELECTRICITY_PRICE_ENTITY]

        temperature_state = self.hass.states.get(temperature_entity)
        price_state = self.hass.states.get(price_entity)

        dhw_temperature = _as_float(
            temperature_state.state if temperature_state is not None else None
        )
        electricity_price = _as_float(
            price_state.state if price_state is not None else None
        )

        data_valid = dhw_temperature is not None

        return {
            "mode": MODE_LEARNING if data_valid else MODE_SAFETY,
            "data_valid": data_valid,
            "system_type": self.entry.data[CONF_SYSTEM_TYPE],
            "dhw_temperature": dhw_temperature,
            "electricity_price": electricity_price,
            "dhw_temperature_entity": temperature_entity,
            "electricity_price_entity": price_entity,
        }
