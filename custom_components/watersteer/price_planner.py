"""Explainable advisory price planning for WaterSteer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Any

MIN_PLANNING_CONFIDENCE = 50
MIN_RESERVE_MINUTES = 30
MAX_PRICE_HORIZON_HOURS = 48
PEAK_PRICE_MULTIPLIER = 1.5


@dataclass(frozen=True, slots=True)
class PriceSlot:
    """One future electricity-price interval."""

    start: datetime
    end: datetime
    price: float


@dataclass(frozen=True, slots=True)
class PricePlan:
    """One explainable advisory DHW price plan."""

    status: str
    reason: str
    next_charge: datetime | None
    charge_end: datetime | None
    expected_charge_minutes: float | None
    planned_target: float | None
    selected_price: float | None
    current_price: float | None
    savings_vs_current: float | None
    price_slot_count: int
    planning_deadline: datetime | None
    confidence: int
    window_active_now: bool
    next_peak_start: datetime | None
    next_peak_end: datetime | None
    next_peak_price: float | None
    peak_avoidance_active: bool


def extract_price_slots(
    *,
    now: datetime,
    attributes: dict[str, Any],
) -> tuple[PriceSlot, ...]:
    """Extract future price slots from common Home Assistant price attributes."""
    slots: list[PriceSlot] = []

    for key in ("raw_today", "raw_tomorrow"):
        value = attributes.get(key)
        if isinstance(value, list):
            slots.extend(_parse_dated_items(value))

    if not slots:
        today = attributes.get("today")
        tomorrow = attributes.get("tomorrow")
        if isinstance(today, list):
            slots.extend(_parse_numeric_day(now, today, day_offset=0))
        if isinstance(tomorrow, list):
            slots.extend(_parse_numeric_day(now, tomorrow, day_offset=1))

    if not slots:
        for key in ("prices", "price_data", "forecast"):
            value = attributes.get(key)
            if isinstance(value, list):
                slots.extend(_parse_dated_items(value))

    unique: dict[tuple[datetime, datetime], PriceSlot] = {}
    horizon = now + timedelta(hours=MAX_PRICE_HORIZON_HOURS)
    for slot in slots:
        if slot.end <= now or slot.start >= horizon:
            continue
        unique[(slot.start, slot.end)] = slot

    return tuple(sorted(unique.values(), key=lambda item: item.start))


def plan_price_window(
    *,
    now: datetime,
    current_temperature: float | None,
    comfort_minimum: float,
    normal_target: float,
    precharge_target: float,
    predicted_autonomy_minutes: float | None,
    autonomy_confidence: int,
    heating_rate_c_per_hour: float | None,
    current_price: float | None,
    price_slots: tuple[PriceSlot, ...],
    minimum_confidence: int = MIN_PLANNING_CONFIDENCE,
) -> PricePlan:
    """Build a conservative advisory plan without issuing control commands."""
    if current_temperature is None:
        return _empty_plan(
            "unavailable",
            "missing_dhw_temperature",
            current_price,
            price_slots,
        )

    if current_temperature <= comfort_minimum:
        return PricePlan(
            status="comfort_recovery",
            reason="comfort_minimum_reached",
            next_charge=None,
            charge_end=None,
            expected_charge_minutes=None,
            planned_target=normal_target,
            selected_price=current_price,
            current_price=current_price,
            savings_vs_current=0.0,
            price_slot_count=len(price_slots),
            planning_deadline=None,
            confidence=autonomy_confidence,
            window_active_now=True,
            next_peak_start=None,
            next_peak_end=None,
            next_peak_price=None,
            peak_avoidance_active=False,
        )

    if autonomy_confidence < minimum_confidence:
        return _empty_plan(
            "learning",
            "autonomy_confidence_below_minimum",
            current_price,
            price_slots,
            confidence=autonomy_confidence,
        )

    if predicted_autonomy_minutes is None:
        return _empty_plan(
            "unavailable",
            "missing_autonomy",
            current_price,
            price_slots,
            confidence=autonomy_confidence,
        )

    if heating_rate_c_per_hour is None or heating_rate_c_per_hour <= 0:
        return _empty_plan(
            "learning",
            "heating_rate_not_learned",
            current_price,
            price_slots,
            confidence=autonomy_confidence,
        )

    if not price_slots:
        return _empty_plan(
            "unavailable",
            "future_prices_unavailable",
            current_price,
            price_slots,
            confidence=autonomy_confidence,
        )

    peak = _find_next_peak(price_slots, now)
    peak_start = peak[0] if peak is not None else None
    peak_end = peak[1] if peak is not None else None
    peak_price = peak[2] if peak is not None else None

    temperature_deficit = max(0.0, normal_target - current_temperature)
    charge_minutes = temperature_deficit / heating_rate_c_per_hour * 60

    # If the tank is already at or above its normal target, cheap electricity
    # alone must not create a charge request. We can still plan the next
    # replenishment using a minimum one-degree recovery estimate.
    planning_charge_minutes = max(
        charge_minutes,
        60 / heating_rate_c_per_hour,
    )

    reserve_minutes = max(
        MIN_RESERVE_MINUTES,
        min(120.0, predicted_autonomy_minutes * 0.15),
    )
    usable_autonomy = max(0.0, predicted_autonomy_minutes - reserve_minutes)
    deadline = now + timedelta(minutes=usable_autonomy)

    if (
        peak is not None
        and peak_start is not None
        and peak_end is not None
        and peak_start > now
        and deadline < peak_end
        and current_temperature < precharge_target
    ):
        precharge_deficit = precharge_target - current_temperature
        precharge_minutes = precharge_deficit / heating_rate_c_per_hour * 60
        pre_peak_slots = tuple(slot for slot in price_slots if slot.end <= peak_start)
        precharge_window = _cheapest_contiguous_window(
            slots=pre_peak_slots,
            now=now,
            deadline=peak_start,
            required_minutes=precharge_minutes,
        )
        if precharge_window is not None:
            window_start, window_end, weighted_price = precharge_window
            savings = None
            if current_price is not None:
                savings = current_price - weighted_price
            return PricePlan(
                status="peak_precharge",
                reason="precharge_needed_to_bridge_price_peak",
                next_charge=window_start,
                charge_end=window_end,
                expected_charge_minutes=precharge_minutes,
                planned_target=precharge_target,
                selected_price=weighted_price,
                current_price=current_price,
                savings_vs_current=savings,
                price_slot_count=len(price_slots),
                planning_deadline=deadline,
                confidence=autonomy_confidence,
                window_active_now=window_start <= now < window_end,
                next_peak_start=peak_start,
                next_peak_end=peak_end,
                next_peak_price=peak_price,
                peak_avoidance_active=True,
            )

    candidate_slots = price_slots
    if peak is not None and peak_start is not None and peak_end is not None:
        candidate_slots = tuple(
            slot
            for slot in price_slots
            if slot.end <= peak_start or slot.start >= peak_end
        )

    window = _cheapest_contiguous_window(
        slots=candidate_slots,
        now=now,
        deadline=deadline,
        required_minutes=planning_charge_minutes,
    )
    if window is None:
        return PricePlan(
            status="normal_operation",
            reason="no_safe_price_window_before_deadline",
            next_charge=None,
            charge_end=None,
            expected_charge_minutes=charge_minutes,
            planned_target=normal_target,
            selected_price=None,
            current_price=current_price,
            savings_vs_current=None,
            price_slot_count=len(price_slots),
            planning_deadline=deadline,
            confidence=autonomy_confidence,
            window_active_now=False,
            next_peak_start=peak_start,
            next_peak_end=peak_end,
            next_peak_price=peak_price,
            peak_avoidance_active=peak is not None,
        )

    window_start, window_end, weighted_price = window
    active_now = window_start <= now < window_end
    already_sufficient = current_temperature >= normal_target

    if already_sufficient:
        status = "temperature_hold"
        reason = "normal_target_satisfied_future_window_planned"
    elif active_now:
        status = "price_charge_window"
        reason = "selected_price_window_active"
    else:
        status = "price_hold"
        reason = "safe_to_wait_for_selected_price_window"

    savings = None
    if current_price is not None:
        savings = current_price - weighted_price

    return PricePlan(
        status=status,
        reason=reason,
        next_charge=window_start,
        charge_end=window_end,
        expected_charge_minutes=charge_minutes,
        planned_target=normal_target,
        selected_price=weighted_price,
        current_price=current_price,
        savings_vs_current=savings,
        price_slot_count=len(price_slots),
        planning_deadline=deadline,
        confidence=autonomy_confidence,
        window_active_now=active_now,
        next_peak_start=peak_start,
        next_peak_end=peak_end,
        next_peak_price=peak_price,
        peak_avoidance_active=peak is not None,
    )


def _find_next_peak(
    slots: tuple[PriceSlot, ...],
    now: datetime,
) -> tuple[datetime, datetime, float] | None:
    """Return the next contiguous price peak relative to the forecast median."""
    future = [slot for slot in slots if slot.end > now]
    if len(future) < 3:
        return None

    baseline = median(slot.price for slot in future)
    threshold = baseline * PEAK_PRICE_MULTIPLIER
    peak_slots = [slot for slot in future if slot.price >= threshold]
    if not peak_slots:
        return None

    first = peak_slots[0]
    start = first.start
    end = first.end
    prices = [first.price]

    for slot in peak_slots[1:]:
        if slot.start > end + timedelta(seconds=1):
            break
        end = max(end, slot.end)
        prices.append(slot.price)

    return start, end, sum(prices) / len(prices)


def _cheapest_contiguous_window(
    *,
    slots: tuple[PriceSlot, ...],
    now: datetime,
    deadline: datetime,
    required_minutes: float,
) -> tuple[datetime, datetime, float] | None:
    """Find the cheapest contiguous window that fits before the deadline."""
    required_seconds = max(60.0, required_minutes * 60)
    best: tuple[float, datetime, datetime] | None = None

    for start_index, first in enumerate(slots):
        start = max(now, first.start)
        if start >= deadline:
            continue

        duration = 0.0
        cost_seconds = 0.0
        cursor = start

        for slot in slots[start_index:]:
            if slot.end <= cursor:
                continue
            if slot.start > cursor + timedelta(seconds=1):
                break

            segment_start = max(cursor, slot.start)
            segment_end = min(slot.end, deadline)
            if segment_end <= segment_start:
                continue

            available = (segment_end - segment_start).total_seconds()
            needed = required_seconds - duration
            used = min(available, needed)
            duration += used
            cost_seconds += used * slot.price
            cursor = segment_start + timedelta(seconds=used)

            if duration >= required_seconds:
                average_price = cost_seconds / duration
                candidate = (average_price, start, cursor)
                if best is None or candidate[0] < best[0]:
                    best = candidate
                break

            cursor = segment_end
            if cursor >= deadline:
                break

    if best is None:
        return None

    return best[1], best[2], best[0]


def _parse_dated_items(items: list[Any]) -> list[PriceSlot]:
    """Parse dict-based price items with timestamps and a numeric value."""
    slots: list[PriceSlot] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        start = _as_datetime(
            item.get("start")
            or item.get("start_time")
            or item.get("from")
            or item.get("time")
        )
        end = _as_datetime(item.get("end") or item.get("end_time") or item.get("to"))
        price = _as_price(
            item.get("value")
            if "value" in item
            else item.get("price", item.get("total"))
        )
        if start is None or price is None:
            continue
        if end is None:
            end = start + timedelta(hours=1)
        if end <= start:
            continue
        slots.append(PriceSlot(start=start, end=end, price=price))
    return slots


def _parse_numeric_day(
    now: datetime,
    values: list[Any],
    *,
    day_offset: int,
) -> list[PriceSlot]:
    """Parse numeric hourly or quarter-hour day arrays."""
    prices = [_as_price(value) for value in values]
    if not prices or any(value is None for value in prices):
        return []

    count = len(prices)
    if count == 24:
        interval_minutes = 60
    elif count in {92, 96, 100}:
        interval_minutes = 15
    else:
        return []

    local_midnight = (now + timedelta(days=day_offset)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return [
        PriceSlot(
            start=local_midnight + timedelta(minutes=index * interval_minutes),
            end=local_midnight + timedelta(minutes=(index + 1) * interval_minutes),
            price=float(price),
        )
        for index, price in enumerate(prices)
        if price is not None
    ]


def _as_datetime(value: Any) -> datetime | None:
    """Parse an aware datetime or ISO-8601 string."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _as_price(value: Any) -> float | None:
    """Return a finite numeric price value."""
    try:
        parsed = float(value)
    except TypeError, ValueError:
        return None
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return parsed


def _empty_plan(
    status: str,
    reason: str,
    current_price: float | None,
    price_slots: tuple[PriceSlot, ...],
    *,
    confidence: int = 0,
) -> PricePlan:
    """Return a plan without a selected future window."""
    return PricePlan(
        status=status,
        reason=reason,
        next_charge=None,
        charge_end=None,
        expected_charge_minutes=None,
        planned_target=None,
        selected_price=None,
        current_price=current_price,
        savings_vs_current=None,
        price_slot_count=len(price_slots),
        planning_deadline=None,
        confidence=confidence,
        window_active_now=False,
        next_peak_start=None,
        next_peak_end=None,
        next_peak_price=None,
        peak_avoidance_active=False,
    )
