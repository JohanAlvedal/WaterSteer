"""Shared entity helpers for WaterSteer."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the single WaterSteer device."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="WaterSteer",
        manufacturer="WaterSteer",
        model="DHW optimization controller",
    )
