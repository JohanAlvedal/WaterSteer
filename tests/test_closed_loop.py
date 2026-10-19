"""Closed-loop simulation: WaterSteer in Active control against a tank model.

A simple heat-pump tank is simulated for several days. WaterSteer runs in
Active control and switches a block switch and an extra-hot-water boolean;
the simulated heat pump reacts to them. The test checks the outcomes that
matter to a household: hot water never runs out, the heat pump is not
toggled rapidly, and heating moves towards cheap hours once WaterSteer has
learned the tank.
"""

from datetime import timedelta

import pytest
from custom_components.watersteer.const import (
    CONF_BLOCK_ENTITY,
    CONF_DHW_TEMPERATURE_ENTITY,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_EXTRA_HOT_WATER_ENTITY,
    CONF_SYSTEM_TYPE,
    DOMAIN,
    SYSTEM_TYPE_HEAT_PUMP,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import ServiceCall
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

TEMP = "sensor.tank"
PRICE = "sensor.nordpool"
BLOCK = "switch.blockera_varmvatten"
EXTRA = "input_boolean.hp_extra_warm_water"


def _price(hour: int) -> float:
    if 7 <= hour < 10 or 17 <= hour < 20:
        return 3.0
    if 0 <= hour < 5:
        return 0.4
    return 1.0


def _price_attributes(now) -> dict:
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def day(offset: int) -> list[dict]:
        start = midnight + timedelta(days=offset)
        return [
            {
                "start": (start + timedelta(hours=h)).isoformat(),
                "end": (start + timedelta(hours=h + 1)).isoformat(),
                "value": _price(h),
            }
            for h in range(24)
        ]

    return {"raw_today": day(0), "raw_tomorrow": day(1)}


@pytest.mark.parametrize(
    ("pump_start", "start_delay_steps"),
    [(42.0, 4), (47.0, 0)],
    ids=["ground_source_slow_start", "starts_near_target"],
)
async def test_active_control_keeps_hot_water_and_does_not_cycle(
    hass, freezer, pump_start, start_delay_steps
) -> None:
    """Four simulated days in Active control.

    ``pump_start`` is the heat pump's own DHW start temperature: 42 °C is a
    pump that only starts low (unblocking alone does nothing), 47 °C one that
    starts close to the normal target. ``start_delay_steps`` (5 minutes each)
    is how long the heat pump needs after a request before the tank warms.
    """
    await hass.config.async_set_time_zone("UTC")
    start = dt_util.parse_datetime("2026-01-05T00:00:00+00:00")
    freezer.move_to(start)

    switch_states = {BLOCK: "off", EXTRA: "off"}
    toggles = {BLOCK: 0, EXTRA: 0}

    async def handle(call: ServiceCall) -> None:
        entity_id = call.data["entity_id"]
        if isinstance(entity_id, list):
            entity_id = entity_id[0]
        new = "on" if call.service == "turn_on" else "off"
        if switch_states[entity_id] != new:
            toggles[entity_id] += 1
        switch_states[entity_id] = new
        hass.states.async_set(entity_id, new)

    for domain in ("switch", "input_boolean"):
        for service in ("turn_on", "turn_off"):
            hass.services.async_register(domain, service, handle)

    tank = 50.0
    heating = False
    requested_steps = 0
    hass.states.async_set(BLOCK, "off")
    hass.states.async_set(EXTRA, "off")
    hass.states.async_set(
        TEMP, str(round(tank, 1)), {"unit_of_measurement": UnitOfTemperature.CELSIUS}
    )
    hass.states.async_set(PRICE, str(_price(0)), _price_attributes(start))

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        data={
            CONF_SYSTEM_TYPE: SYSTEM_TYPE_HEAT_PUMP,
            CONF_DHW_TEMPERATURE_ENTITY: TEMP,
            CONF_ELECTRICITY_PRICE_ENTITY: PRICE,
            CONF_BLOCK_ENTITY: BLOCK,
            CONF_EXTRA_HOT_WATER_ENTITY: EXTRA,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    await coordinator.async_set_mode("active")

    lowest_after_learning = 100.0
    heated_degrees_by_price: dict[float, float] = {}
    statuses: set[str] = set()
    now = start
    for step in range(4 * 24 * 12):
        now = start + timedelta(minutes=5 * step)
        freezer.move_to(now)

        # Simulated heat pump: starts below pump_start unless blocked, stops at 50;
        # extra hot water heats to 56 regardless of block.
        blocked = switch_states[BLOCK] == "on"
        extra = switch_states[EXTRA] == "on"
        if extra:
            heating = tank < 56.0
        elif blocked:
            heating = False
        elif tank < pump_start:
            heating = True
        elif tank >= 50.0:
            heating = False
        requested_steps = requested_steps + 1 if heating else 0
        if heating and requested_steps > start_delay_steps:
            tank += 8.0 / 12
            price = _price(now.hour)
            heated_degrees_by_price[price] = (
                heated_degrees_by_price.get(price, 0) + 8.0 / 12
            )
        tank -= 0.5 / 12
        if now.minute == 0 and now.hour in (7, 20):
            tank -= 6.0

        hass.states.async_set(
            TEMP,
            str(round(tank, 1)),
            {"unit_of_measurement": UnitOfTemperature.CELSIUS},
        )
        hass.states.async_set(PRICE, str(_price(now.hour)), _price_attributes(now))
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        statuses.add(coordinator.data["status"])
        if step > 2 * 24 * 12:
            lowest_after_learning = min(lowest_after_learning, tank)

    # Once learned, planned charges keep the tank above the absolute minimum
    # even right after the large daily draws.
    assert lowest_after_learning >= 43.0
    # Anti-cycling: each lever changes only a few times per day.
    assert toggles[BLOCK] <= 4 * 6
    assert toggles[EXTRA] <= 4 * 8
    # WaterSteer actually optimized at some point.
    assert "holding" in statuses or "preheating" in statuses
    # Heat is not concentrated in the most expensive hours.
    expensive = heated_degrees_by_price.get(3.0, 0.0)
    total = sum(heated_degrees_by_price.values())
    assert expensive / total < 0.2

    await hass.config_entries.async_unload(entry.entry_id)
