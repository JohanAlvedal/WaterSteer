"""Explainable DHW usage learning for WaterSteer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import prod
from statistics import median
from typing import Any

MIN_SAMPLE_INTERVAL_SECONDS = 300
MAX_HISTORY_DAYS = 42
MAX_EVENT_DURATION_SECONDS = 30 * 60
USAGE_DROP_MIN_C = 1.5
USAGE_DROP_RATE_MIN_C_PER_HOUR = 3.0
EVENT_COOLDOWN_SECONDS = 45 * 60
RECENT_USAGE_SECONDS = 20 * 60
PROFILE_HORIZON_HOURS = 6
EXPECTED_USAGE_PROBABILITY = 0.30
AWAY_PROBABILITY_FACTOR = 0.25


@dataclass(frozen=True, slots=True)
class UsageSample:
    """One sampled DHW temperature observation for usage learning."""

    timestamp: float
    temperature: float
    day_type: str
    hour: int
    date_key: str
    heating_active: bool | None


@dataclass(frozen=True, slots=True)
class UsageEvent:
    """One inferred DHW usage event."""

    timestamp: float
    day_type: str
    hour: int
    date_key: str
    drop_c: float


@dataclass(frozen=True, slots=True)
class UsageEstimate:
    """Current usage-learning result."""

    usage_detected: bool
    usage_probability_next_6h: float
    next_expected_usage: datetime | None
    typical_usage_drop: float | None
    confidence: int
    event_count: int
    observed_days: int
    occupancy_state: str


class DhwUsageModel:
    """Learn weekday/weekend and time-of-day DHW usage patterns."""

    def __init__(self) -> None:
        """Initialize an empty usage model."""
        self._samples: list[UsageSample] = []
        self._events: list[UsageEvent] = []
        self._last_event_timestamp: float | None = None

    def add_observation(
        self,
        *,
        timestamp: float,
        temperature: float,
        local_datetime: datetime,
        heating_active: bool | None,
    ) -> bool:
        """Sample temperature and infer large usage drops."""
        if self._samples:
            last = self._samples[-1]
            if timestamp <= last.timestamp:
                return False
            if timestamp - last.timestamp < MIN_SAMPLE_INTERVAL_SECONDS:
                return False

        sample = UsageSample(
            timestamp=timestamp,
            temperature=temperature,
            day_type=self._day_type(local_datetime),
            hour=local_datetime.hour,
            date_key=local_datetime.date().isoformat(),
            heating_active=heating_active,
        )

        if self._samples:
            self._detect_usage_event(self._samples[-1], sample)

        self._samples.append(sample)
        self._purge_old(timestamp)
        return True

    def _detect_usage_event(self, previous: UsageSample, current: UsageSample) -> None:
        """Infer a DHW draw from a rapid temperature drop."""
        elapsed_seconds = current.timestamp - previous.timestamp
        if not 0 < elapsed_seconds <= MAX_EVENT_DURATION_SECONDS:
            return
        if previous.heating_active is True or current.heating_active is True:
            return

        drop_c = previous.temperature - current.temperature
        if drop_c < USAGE_DROP_MIN_C:
            return

        drop_rate = drop_c / (elapsed_seconds / 3600)
        if drop_rate < USAGE_DROP_RATE_MIN_C_PER_HOUR:
            return

        if (
            self._last_event_timestamp is not None
            and current.timestamp - self._last_event_timestamp < EVENT_COOLDOWN_SECONDS
        ):
            return

        self._events.append(
            UsageEvent(
                timestamp=current.timestamp,
                day_type=current.day_type,
                hour=current.hour,
                date_key=current.date_key,
                drop_c=drop_c,
            )
        )
        self._last_event_timestamp = current.timestamp

    def estimate(
        self,
        *,
        now_local: datetime,
        occupancy: bool | None,
    ) -> UsageEstimate:
        """Estimate near-term usage from learned weekday/weekend profiles."""
        observed_days = len({sample.date_key for sample in self._samples})
        confidence = min(100, round(observed_days / 30 * 100))

        probabilities: list[float] = []
        expected_usage: datetime | None = None

        for offset in range(PROFILE_HORIZON_HOURS):
            target = now_local + timedelta(hours=offset)
            probability = self._bucket_probability(
                self._day_type(target),
                target.hour,
            )
            probability = self._apply_occupancy(probability, occupancy)
            probabilities.append(probability)

            if (
                expected_usage is None
                and confidence >= 10
                and probability >= EXPECTED_USAGE_PROBABILITY
            ):
                expected_usage = target.replace(minute=0, second=0, microsecond=0)

        combined_probability = 0.0
        if probabilities:
            combined_probability = 1.0 - prod(1.0 - value for value in probabilities)

        latest_event = self._events[-1] if self._events else None
        usage_detected = bool(
            latest_event
            and now_local.timestamp() - latest_event.timestamp <= RECENT_USAGE_SECONDS
        )
        typical_drop = (
            median(event.drop_c for event in self._events) if self._events else None
        )

        return UsageEstimate(
            usage_detected=usage_detected,
            usage_probability_next_6h=combined_probability * 100,
            next_expected_usage=expected_usage,
            typical_usage_drop=typical_drop,
            confidence=confidence,
            event_count=len(self._events),
            observed_days=observed_days,
            occupancy_state=self._occupancy_state(occupancy),
        )

    def _bucket_probability(self, day_type: str, hour: int) -> float:
        """Return historical event probability for a day-type/hour bucket."""
        exposure_days = {
            sample.date_key
            for sample in self._samples
            if sample.day_type == day_type and sample.hour == hour
        }
        if not exposure_days:
            return 0.0

        event_days = {
            event.date_key
            for event in self._events
            if event.day_type == day_type and event.hour == hour
        }
        return min(1.0, len(event_days) / len(exposure_days))

    @staticmethod
    def _apply_occupancy(probability: float, occupancy: bool | None) -> float:
        """Reduce learned demand while the home is explicitly away."""
        if occupancy is False:
            return probability * AWAY_PROBABILITY_FACTOR
        return probability

    @staticmethod
    def _occupancy_state(occupancy: bool | None) -> str:
        """Return a diagnostic occupancy label."""
        if occupancy is True:
            return "home"
        if occupancy is False:
            return "away"
        return "unknown"

    @staticmethod
    def _day_type(value: datetime) -> str:
        """Return weekday or weekend."""
        return "weekend" if value.weekday() >= 5 else "weekday"

    def _purge_old(self, now: float) -> None:
        """Keep only the rolling usage-learning window."""
        cutoff = now - MAX_HISTORY_DAYS * 24 * 60 * 60
        self._samples = [
            sample for sample in self._samples if sample.timestamp >= cutoff
        ]
        self._events = [event for event in self._events if event.timestamp >= cutoff]
        self._last_event_timestamp = (
            self._events[-1].timestamp if self._events else None
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize usage-learning state."""
        return {
            "samples": [
                {
                    "timestamp": item.timestamp,
                    "temperature": item.temperature,
                    "day_type": item.day_type,
                    "hour": item.hour,
                    "date_key": item.date_key,
                    "heating_active": item.heating_active,
                }
                for item in self._samples
            ],
            "events": [
                {
                    "timestamp": item.timestamp,
                    "day_type": item.day_type,
                    "hour": item.hour,
                    "date_key": item.date_key,
                    "drop_c": item.drop_c,
                }
                for item in self._events
            ],
        }

    def restore(self, data: dict[str, Any] | None) -> None:
        """Restore persisted usage-learning state."""
        if not isinstance(data, dict):
            return

        samples: list[UsageSample] = []
        for item in data.get("samples", []):
            if not isinstance(item, dict):
                continue
            try:
                samples.append(
                    UsageSample(
                        timestamp=float(item["timestamp"]),
                        temperature=float(item["temperature"]),
                        day_type=str(item["day_type"]),
                        hour=int(item["hour"]),
                        date_key=str(item["date_key"]),
                        heating_active=item.get("heating_active"),
                    )
                )
            except KeyError, TypeError, ValueError:
                continue

        events: list[UsageEvent] = []
        for item in data.get("events", []):
            if not isinstance(item, dict):
                continue
            try:
                events.append(
                    UsageEvent(
                        timestamp=float(item["timestamp"]),
                        day_type=str(item["day_type"]),
                        hour=int(item["hour"]),
                        date_key=str(item["date_key"]),
                        drop_c=float(item["drop_c"]),
                    )
                )
            except KeyError, TypeError, ValueError:
                continue

        samples.sort(key=lambda item: item.timestamp)
        events.sort(key=lambda item: item.timestamp)
        self._samples = samples
        self._events = events
        self._last_event_timestamp = events[-1].timestamp if events else None

        newest = max(
            [item.timestamp for item in samples] + [item.timestamp for item in events],
            default=None,
        )
        if newest is not None:
            self._purge_old(newest)
