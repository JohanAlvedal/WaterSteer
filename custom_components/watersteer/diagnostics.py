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

    return {
        "config_entry": {
            "title": entry.title,
            "system_type": entry.data.get("system_type"),
            "configured_inputs": {
                key: value
                for key, value in entry.data.items()
                if not key.endswith("_action")
            },
            "configured_actions": [
                key for key in entry.data if key.endswith("_action")
            ],
        },
        "coordinator": dict(coordinator.data),
    }
