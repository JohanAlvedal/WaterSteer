"""Diagnostics support for WaterSteer."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import WaterSteerDataUpdateCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a WaterSteer config entry."""
    coordinator: WaterSteerDataUpdateCoordinator = entry.runtime_data
    config = {**entry.data, **entry.options}

    return {
        "config_entry": {
            "title": entry.title,
            "system_type": config.get("system_type"),
            "configured_inputs": {
                key: value
                for key, value in config.items()
                if not key.endswith("_action") and value is not None
            },
            "configured_actions": [
                key
                for key, value in config.items()
                if key.endswith("_action") and value is not None
            ],
        },
        "coordinator": dict(coordinator.data),
    }
