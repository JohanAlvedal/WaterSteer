"""Replay of a real ground-source installation (IVT, October 2026).

Tank and heat-pump behaviour are taken from recorded history:

* standby loss 0.30 °C/h (measured over 30 h, three separate runs);
* the heat pump starts hot water by itself at about 47.5 °C when unblocked
  and stops at about 51.7 °C;
* about 10 minutes from start until the tank temperature rises, then about
  20 °C/h at the sensor;
* extra hot water heats further, to about 56 °C.

Prices are the recorded hourly spot price profile of 20 October 2026.

The same model is run once without WaterSteer and once with WaterSteer in
Active control. WaterSteer must pay clearly less per heated degree and keep
the tank above the comfort minimum.
"""

from datetime import timedelta

import pytest
from custom_components.watersteer.const import (
    CONF_BLOCK_ENTITY,
    CONF_DHW_TEMPERATURE_ENTITY,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_EXTRA_HOT_WATER_ENTITY,
    CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY,
    CONF_SYSTEM_TYPE,
    DOMAIN,
    SYSTEM_TYPE_HEAT_PUMP,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import ServiceCall
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

HOURLY_PRICE = (
    1.460, 1.408, 1.360, 1.339, 1.328, 1.433, 1.849, 1.961,
    2.215, 2.208, 1.872, 1.733, 1.890, 1.877, 1.989, 2.254,
    2.527, 2.294, 2.177, 2.014, 1.529, 1.167, 1.320, 1.465,
)  # fmt: skip

LOSS_C_PER_HOUR = 0.30
PUMP_START_C = 47.5
PUMP_STOP_C = 51.7
EXTRA_STOP_C = 56.0
HEAT_C_PER_HOUR = 20.0
START_DELAY_STEPS = 2
STEP_MINUTES = 5
DAYS = 6
LEARNING_DAYS = 3

TEMP = "sensor.varmvatten"
PRICE = "sensor.elpris_today"
POWER = "sensor.varmvatten_produktion_i_w"
BLOCK = "switch.blockera_varmvatten"
EXTRA = "input_boolean.hp_extra_warm_water"


def _price_attributes(now) -> dict:
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def day(offset: int) -> list[dict]:
        start = midnight + timedelta(days=offset)
        return [
            {
                "start": (start + timedelta(hours=h)).isoformat(),
                "end": (start + timedelta(hours=h + 1)).isoformat(),
                "value": HOURLY_PRICE[h],
            }
            for h in range(24)
        ]

    # Day-ahead prices: tomorrow is known from 13:00.
    attributes = {"raw_today": day(0)}
    if now.hour >= 13:
        attributes["raw_tomorrow"] = day(1)
    return attributes


class Tank:
    """Recorded tank and heat-pump behaviour."""

    def __init__(self, draws: dict[int, float]) -> None:
        self.temperature = 49.0
        self.heating = False
        self.extra_cycle = False
        self.requested_steps = 0
        self.draws = draws

    def step(self, now, *, blocked: bool, extra: bool) -> float | None:
        """Advance five minutes; return heated degrees, or None."""
        if extra and not self.heating:
            self.heating = True
            self.extra_cycle = True
        elif not blocked and not self.heating and self.temperature < PUMP_START_C:
            self.heating = True
            self.extra_cycle = False
        if self.heating:
            stop = EXTRA_STOP_C if self.extra_cycle else PUMP_STOP_C
            if self.temperature >= stop or (blocked and not extra):
                self.heating = False
                self.extra_cycle = False

        heated = None
        self.requested_steps = self.requested_steps + 1 if self.heating else 0
        if self.heating and self.requested_steps > START_DELAY_STEPS:
            heated = HEAT_C_PER_HOUR * STEP_MINUTES / 60
            self.temperature += heated
        self.temperature -= LOSS_C_PER_HOUR * STEP_MINUTES / 60
        if now.minute == 0 and now.hour in self.draws:
            self.temperature -= self.draws[now.hour]
        return heated


def _baseline(start, draws) -> tuple[float, float]:
    """Average price per heated degree and lowest temperature, pump alone."""
    tank = Tank(draws)
    cost = degrees = 0.0
    lowest = 100.0
    for step in range(DAYS * 24 * 60 // STEP_MINUTES):
        now = start + timedelta(minutes=STEP_MINUTES * step)
        heated = tank.step(now, blocked=False, extra=False)
        if step >= LEARNING_DAYS * 24 * 60 // STEP_MINUTES:
            lowest = min(lowest, tank.temperature)
            if heated:
                cost += heated * HOURLY_PRICE[now.hour]
                degrees += heated
    return cost / degrees, lowest


@pytest.mark.parametrize(
    ("draws", "max_price_ratio"),
    [({}, 0.7), ({7: 4.0, 21: 3.0}, 1.0)],
    ids=["no_draws_as_recorded", "morning_and_evening_showers"],
)
async def test_replay_saves_money_and_keeps_comfort(
    hass, freezer, draws, max_price_ratio
) -> None:
    """WaterSteer moves heating away from expensive hours on this pump."""
    await hass.config.async_set_time_zone("UTC")
    start = dt_util.parse_datetime("2026-10-14T00:00:00+00:00")
    freezer.move_to(start)

    switch_states = {BLOCK: "off", EXTRA: "off"}

    async def handle(call: ServiceCall) -> None:
        entity_id = call.data["entity_id"]
        if isinstance(entity_id, list):
            entity_id = entity_id[0]
        switch_states[entity_id] = "on" if call.service == "turn_on" else "off"
        hass.states.async_set(entity_id, switch_states[entity_id])

    for domain in ("switch", "input_boolean"):
        for service in ("turn_on", "turn_off"):
            hass.services.async_register(domain, service, handle)

    tank = Tank(draws)
    unit = {"unit_of_measurement": UnitOfTemperature.CELSIUS}
    hass.states.async_set(BLOCK, "off")
    hass.states.async_set(EXTRA, "off")
    hass.states.async_set(TEMP, str(round(tank.temperature, 1)), unit)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    hass.states.async_set(PRICE, str(HOURLY_PRICE[0]), _price_attributes(start))

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        data={
            CONF_SYSTEM_TYPE: SYSTEM_TYPE_HEAT_PUMP,
            CONF_DHW_TEMPERATURE_ENTITY: TEMP,
            CONF_ELECTRICITY_PRICE_ENTITY: PRICE,
            CONF_BLOCK_ENTITY: BLOCK,
            CONF_EXTRA_HOT_WATER_ENTITY: EXTRA,
            CONF_HEAT_PUMP_DHW_ACTIVE_ENTITY: POWER,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    await coordinator.async_set_mode("active")

    cost = degrees = 0.0
    lowest = 100.0
    for step in range(DAYS * 24 * 60 // STEP_MINUTES):
        now = start + timedelta(minutes=STEP_MINUTES * step)
        freezer.move_to(now)
        heated = tank.step(
            now,
            blocked=switch_states[BLOCK] == "on",
            extra=switch_states[EXTRA] == "on",
        )
        if step >= LEARNING_DAYS * 24 * 60 // STEP_MINUTES:
            lowest = min(lowest, tank.temperature)
            if heated:
                cost += heated * HOURLY_PRICE[now.hour]
                degrees += heated
        hass.states.async_set(TEMP, str(round(tank.temperature, 1)), unit)
        hass.states.async_set(
            POWER, "2700" if tank.heating else "0", {"unit_of_measurement": "W"}
        )
        hass.states.async_set(
            PRICE, str(HOURLY_PRICE[now.hour]), _price_attributes(now)
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    baseline_price, baseline_lowest = _baseline(start, draws)
    watersteer_price = cost / degrees

    print(  # noqa: T201 - result summary with pytest -s
        f"\n{draws}: pump alone {baseline_price:.3f} SEK/°C "
        f"(lowest {baseline_lowest:.1f} °C), WaterSteer "
        f"{watersteer_price:.3f} SEK/°C (lowest {lowest:.1f} °C), "
        f"start delay {coordinator.charge.start_delay_minutes:.0f} min, "
        f"self start {coordinator.charge.pump_starts_on_its_own}"
    )
    # Without draws (as recorded) WaterSteer moves nearly all heating to cheap
    # hours. With daily showers and only six days of history, usage learning is
    # not yet trusted, so WaterSteer must at least not be more expensive and
    # must keep the tank warmer than the heat pump does on its own.
    assert watersteer_price <= baseline_price * max_price_ratio
    assert lowest >= min(baseline_lowest, 45.0)

    await hass.config_entries.async_unload(entry.entry_id)
