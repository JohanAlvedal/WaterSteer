"""Shadow simulation of DHW strategies over the price horizon.

Before any price decision is trusted, WaterSteer simulates the next hours
twice with the learned tank model:

* ``normal``    — the heat pump keeps the tank on its own, ignoring prices;
* ``optimized`` — WaterSteer's plan: wait (hold) until the selected window,
                  heat there to the planned target, otherwise behave normally.

Both use the same learned standby loss, heating rate and expected demand. The
result gives the lowest predicted temperature of the plan (a safety check
that can veto a hold) and a relative cost comparison. Cost is expressed as
"heated degrees × price" because tank volume and COP are not known; the
relative saving is meaningful, the absolute number is not money.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

STEP_MINUTES = 15
DEFAULT_HORIZON_HOURS = 24


class _PriceSlot(Protocol):
    start: datetime
    end: datetime
    price: float


class _DemandBucket(Protocol):
    start: datetime
    expected_drop_c: float


@dataclass(frozen=True, slots=True)
class StrategyResult:
    """Outcome of one simulated strategy."""

    name: str
    cost_index: float
    min_temperature: float
    heating_hours: float
    final_temperature: float


@dataclass(frozen=True, slots=True)
class ShadowResult:
    """Comparison of normal operation and WaterSteer's plan."""

    normal: StrategyResult
    optimized: StrategyResult
    horizon_hours: float
    mean_price: float

    @property
    def saving_percent(self) -> float | None:
        """Relative saving of the plan versus normal operation.

        Heat still stored in the tank at the end of the horizon is credited at
        the mean price, so a plan that simply ends with a hotter tank does not
        look worse than it is.
        """
        if self.normal.cost_index <= 0:
            return None
        stored = self.optimized.final_temperature - self.normal.final_temperature
        adjusted = self.optimized.cost_index - stored * self.mean_price
        return (1 - adjusted / self.normal.cost_index) * 100


@dataclass(frozen=True, slots=True)
class TankModel:
    """Learned tank behaviour used by the simulation."""

    loss_c_per_hour: Callable[[float], float]
    heating_rate_c_per_hour: float
    comfort_minimum: float
    start_below: float
    stop_at: float


def simulate(
    *,
    now: datetime,
    temperature: float,
    tank: TankModel,
    price_slots: Sequence[_PriceSlot],
    demand: Sequence[_DemandBucket],
    hold_until: datetime | None,
    window_start: datetime | None,
    window_end: datetime | None,
    window_target: float | None,
    horizon_hours: float = DEFAULT_HORIZON_HOURS,
) -> ShadowResult | None:
    """Simulate both strategies; None when prices do not cover the horizon."""
    horizon_end = now + timedelta(hours=horizon_hours)
    covered = [slot for slot in price_slots if slot.end > now]
    if not covered:
        return None
    horizon_end = min(horizon_end, max(slot.end for slot in covered))
    if horizon_end - now < timedelta(hours=1):
        return None

    normal = _run(
        name="normal",
        now=now,
        end=horizon_end,
        temperature=temperature,
        tank=tank,
        price_slots=covered,
        demand=demand,
        hold_until=None,
        window=None,
    )
    window = (
        (window_start, window_end, window_target)
        if window_start is not None
        and window_end is not None
        and window_target is not None
        else None
    )
    optimized = _run(
        name="optimized",
        now=now,
        end=horizon_end,
        temperature=temperature,
        tank=tank,
        price_slots=covered,
        demand=demand,
        hold_until=hold_until,
        window=window,
    )
    return ShadowResult(
        normal=normal,
        optimized=optimized,
        horizon_hours=(horizon_end - now).total_seconds() / 3600,
        mean_price=sum(slot.price for slot in covered) / len(covered),
    )


def _run(
    *,
    name: str,
    now: datetime,
    end: datetime,
    temperature: float,
    tank: TankModel,
    price_slots: Sequence[_PriceSlot],
    demand: Sequence[_DemandBucket],
    hold_until: datetime | None,
    window: tuple[datetime, datetime, float] | None,
) -> StrategyResult:
    step = timedelta(minutes=STEP_MINUTES)
    step_hours = STEP_MINUTES / 60
    cursor = now
    temp = temperature
    heating = temp < tank.start_below
    cost = 0.0
    heated_hours = 0.0
    lowest = temp
    hold_broken = False

    while cursor < end:
        price = _price_at(price_slots, cursor)
        in_window = window is not None and window[0] <= cursor < window[1]
        holding = (
            hold_until is not None
            and cursor < hold_until
            and not in_window
            and not hold_broken
        )

        if in_window:
            heating = temp < window[2]
        elif holding and temp >= tank.comfort_minimum:
            heating = False
        else:
            if holding:
                # The safety supervisor ends a hold below the comfort floor;
                # from then on the heat pump runs normally.
                hold_broken = True
            if temp < tank.start_below:
                heating = True
            elif temp >= tank.stop_at:
                heating = False

        if heating:
            gain = tank.heating_rate_c_per_hour * step_hours
            temp += gain
            cost += gain * price
            heated_hours += step_hours
        temp -= tank.loss_c_per_hour(temp) * step_hours
        temp -= _demand_in_step(demand, cursor, step)
        lowest = min(lowest, temp)
        cursor += step

    return StrategyResult(
        name=name,
        cost_index=cost,
        min_temperature=lowest,
        heating_hours=heated_hours,
        final_temperature=temp,
    )


def _price_at(slots: Sequence[_PriceSlot], moment: datetime) -> float:
    for slot in slots:
        if slot.start <= moment < slot.end:
            return slot.price
    return slots[-1].price


def _demand_in_step(
    demand: Sequence[_DemandBucket],
    moment: datetime,
    step: timedelta,
) -> float:
    """Spread each hourly expected drop evenly over its steps."""
    for bucket in demand:
        if bucket.start <= moment < bucket.start + timedelta(hours=1):
            return bucket.expected_drop_c * (step / timedelta(hours=1))
    return 0.0
