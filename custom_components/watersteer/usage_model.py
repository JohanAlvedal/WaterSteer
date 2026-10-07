"""Explainable DHW usage learning for WaterSteer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import prod
from statistics import median
from typing import Any

MIN_SAMPLE_INTERVAL_SECONDS = 300
MAX_HISTORY_DAYS = 42
MAX_EVENT_SEGMENT_SECONDS = 30 * 60
USAGE_DROP_MIN_C = 1.5
USAGE_DROP_RATE_MIN_C_PER_HOUR = 3.0
INFERRED_HEATING_RATE_MIN_C_PER_HOUR = 0.75
EVENT_GROUP_GAP_SECONDS = 20 * 60
RECOVERY_DUPLICATE_GAP_SECONDS = 60 * 60
RECOVERY_MIN_BASELINE_AGE_SECONDS = 45 * 60
RECOVERY_MAX_BASELINE_AGE_SECONDS = 24 * 60 * 60
RECOVERY_MIN_EARLY_MINUTES = 30
RECOVERY_MAX_PASSIVE_FRACTION = 0.75
RECOVERY_MIN_INFERRED_DROP_C = 1.0
RECENT_USAGE_SECONDS = 20 * 60
PROFILE_HORIZON_HOURS = 6
EXPECTED_USAGE_PROBABILITY = 0.30
AWAY_PROBABILITY_FACTOR = 0.25

SMALL_DRAW_MAX_C = 3.0
LARGE_DRAW_MIN_C = 6.0

WEEKDAY_CONFIDENCE_DAYS = 15
WEEKEND_CONFIDENCE_DAYS = 6


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
    """One inferred and grouped DHW usage event."""

    timestamp: float
    end_timestamp: float
    day_type: str
    hour: int
    date_key: str
    drop_c: float
    draw_size: str
    source: str


@dataclass(frozen=True, slots=True)
class UsageForecastBucket:
    """One hourly bucket in the near-term demand forecast."""

    start: datetime
    probability: float
    typical_drop_c: float | None
    expected_drop_c: float


@dataclass(frozen=True, slots=True)
class UsageEstimate:
    """Current usage-learning and demand-forecast result."""

    usage_detected: bool
    usage_probability_next_6h: float
    expected_usage_drop_next_6h: float
    next_expected_usage: datetime | None
    next_expected_usage_probability: float | None
    next_expected_usage_drop: float | None
    demand_level: str
    typical_usage_drop: float | None
    confidence: int
    event_count: int
    observed_days: int
    relevant_observed_days: int
    small_event_count: int
    medium_event_count: int
    large_event_count: int
    direct_event_count: int
    recovery_event_count: int
    occupancy_state: str
    profile_day_type: str
    forecast: tuple[UsageForecastBucket, ...]


class DhwUsageModel:
    """Learn explainable weekday/weekend and time-of-day DHW demand."""

    def __init__(self) -> None:
        """Initialize an empty usage model."""
        self._samples: list[UsageSample] = []
        self._events: list[UsageEvent] = []

    def add_observation(
        self,
        *,
        timestamp: float,
        temperature: float,
        local_datetime: datetime,
        heating_active: bool | None,
        standby_loss_c_per_hour: float | None = None,
    ) -> bool:
        """Sample temperature and infer grouped DHW usage events."""
        if self._samples:
            last = self._samples[-1]
            if timestamp <= last.timestamp:
                return False
            if timestamp - last.timestamp < MIN_SAMPLE_INTERVAL_SECONDS:
                return False

        previous = self._samples[-1] if self._samples else None
        resolved_heating_active = self._resolve_heating_active(
            previous=previous,
            timestamp=timestamp,
            temperature=temperature,
            explicit=heating_active,
        )
        sample = UsageSample(
            timestamp=timestamp,
            temperature=temperature,
            day_type=self._day_type(local_datetime),
            hour=local_datetime.hour,
            date_key=local_datetime.date().isoformat(),
            heating_active=resolved_heating_active,
        )

        if previous is not None:
            if resolved_heating_active is True and previous.heating_active is not True:
                self._detect_recovery_event(
                    current=sample,
                    pre_heating_temperature=previous.temperature,
                    standby_loss_c_per_hour=standby_loss_c_per_hour,
                )
            self._detect_usage_segment(previous, sample)

        self._samples.append(sample)
        self._purge_old(timestamp)
        return True

    @staticmethod
    def _resolve_heating_active(
        *,
        previous: UsageSample | None,
        timestamp: float,
        temperature: float,
        explicit: bool | None,
    ) -> bool | None:
        """Use an explicit heating signal or infer heating from temperature rise."""
        if explicit is not None:
            return explicit
        if previous is None:
            return None

        elapsed_seconds = timestamp - previous.timestamp
        if elapsed_seconds <= 0 or elapsed_seconds > MAX_EVENT_SEGMENT_SECONDS:
            return None

        rise_c = temperature - previous.temperature
        rise_rate = rise_c / (elapsed_seconds / 3600)
        return rise_rate >= INFERRED_HEATING_RATE_MIN_C_PER_HOUR

    def _detect_usage_segment(
        self,
        previous: UsageSample,
        current: UsageSample,
    ) -> None:
        """Infer a draw segment and merge consecutive segments into one event."""
        elapsed_seconds = current.timestamp - previous.timestamp
        if not 0 < elapsed_seconds <= MAX_EVENT_SEGMENT_SECONDS:
            return
        if previous.heating_active is True or current.heating_active is True:
            return

        drop_c = previous.temperature - current.temperature
        if drop_c < USAGE_DROP_MIN_C:
            return

        drop_rate = drop_c / (elapsed_seconds / 3600)
        if drop_rate < USAGE_DROP_RATE_MIN_C_PER_HOUR:
            return

        if self._events:
            last_event = self._events[-1]
            if (
                current.timestamp - last_event.end_timestamp <= EVENT_GROUP_GAP_SECONDS
                and current.date_key == last_event.date_key
            ):
                combined_drop = last_event.drop_c + drop_c
                self._events[-1] = UsageEvent(
                    timestamp=last_event.timestamp,
                    end_timestamp=current.timestamp,
                    day_type=last_event.day_type,
                    hour=last_event.hour,
                    date_key=last_event.date_key,
                    drop_c=combined_drop,
                    draw_size=self._draw_size(combined_drop),
                    source=last_event.source,
                )
                return

        self._events.append(
            UsageEvent(
                timestamp=current.timestamp,
                end_timestamp=current.timestamp,
                day_type=current.day_type,
                hour=current.hour,
                date_key=current.date_key,
                drop_c=drop_c,
                draw_size=self._draw_size(drop_c),
                source="direct",
            )
        )

    def _detect_recovery_event(
        self,
        *,
        current: UsageSample,
        pre_heating_temperature: float,
        standby_loss_c_per_hour: float | None,
    ) -> None:
        """Infer usage from an unexpectedly early DHW recovery cycle."""
        if standby_loss_c_per_hour is None or standby_loss_c_per_hour <= 0:
            return

        baseline = self._latest_post_heating_sample()
        if baseline is None:
            return

        elapsed_seconds = current.timestamp - baseline.timestamp
        if not (
            RECOVERY_MIN_BASELINE_AGE_SECONDS
            <= elapsed_seconds
            <= RECOVERY_MAX_BASELINE_AGE_SECONDS
        ):
            return

        temperature_drop = baseline.temperature - pre_heating_temperature
        if temperature_drop <= 0:
            return

        expected_passive_hours = temperature_drop / standby_loss_c_per_hour
        actual_hours = elapsed_seconds / 3600
        early_minutes = (expected_passive_hours - actual_hours) * 60

        if early_minutes < RECOVERY_MIN_EARLY_MINUTES:
            return
        if actual_hours > expected_passive_hours * RECOVERY_MAX_PASSIVE_FRACTION:
            return

        if self._events:
            latest = self._events[-1]
            if (
                current.timestamp - latest.end_timestamp
                <= RECOVERY_DUPLICATE_GAP_SECONDS
            ):
                return

        expected_passive_drop = standby_loss_c_per_hour * actual_hours
        inferred_drop = max(
            RECOVERY_MIN_INFERRED_DROP_C,
            temperature_drop - expected_passive_drop,
        )
        self._events.append(
            UsageEvent(
                timestamp=current.timestamp,
                end_timestamp=current.timestamp,
                day_type=current.day_type,
                hour=current.hour,
                date_key=current.date_key,
                drop_c=inferred_drop,
                draw_size=self._draw_size(inferred_drop),
                source="recovery",
            )
        )

    def _latest_post_heating_sample(self) -> UsageSample | None:
        """Return the latest sample immediately after a completed heating cycle."""
        for index in range(len(self._samples) - 1, 0, -1):
            current = self._samples[index]
            previous = self._samples[index - 1]
            if previous.heating_active is True and current.heating_active is False:
                return current
        return None

    def estimate(
        self,
        *,
        now_local: datetime,
        occupancy: bool | None,
    ) -> UsageEstimate:
        """Estimate near-term demand from learned day-type/hour profiles."""
        observed_days = len({sample.date_key for sample in self._samples})
        profile_day_type = self._day_type(now_local)
        relevant_observed_days = self._observed_days_for_type(profile_day_type)
        confidence = self._confidence(profile_day_type, relevant_observed_days)

        forecast: list[UsageForecastBucket] = []
        expected_usage: datetime | None = None
        expected_usage_probability: float | None = None
        expected_usage_drop: float | None = None

        for offset in range(PROFILE_HORIZON_HOURS):
            target = now_local + timedelta(hours=offset)
            day_type = self._day_type(target)
            hour = target.hour
            probability = self._apply_occupancy(
                self._bucket_probability(day_type, hour),
                occupancy,
            )
            typical_drop = self._bucket_typical_drop(day_type, hour)
            expected_drop = probability * (typical_drop or 0.0)
            bucket_start = target.replace(minute=0, second=0, microsecond=0)

            forecast.append(
                UsageForecastBucket(
                    start=bucket_start,
                    probability=probability,
                    typical_drop_c=typical_drop,
                    expected_drop_c=expected_drop,
                )
            )

            if (
                expected_usage is None
                and confidence >= 10
                and probability >= EXPECTED_USAGE_PROBABILITY
            ):
                expected_usage = bucket_start
                expected_usage_probability = probability
                expected_usage_drop = typical_drop

        combined_probability = 0.0
        if forecast:
            combined_probability = 1.0 - prod(
                1.0 - bucket.probability for bucket in forecast
            )

        expected_drop_next_6h = sum(bucket.expected_drop_c for bucket in forecast)
        latest_event = self._events[-1] if self._events else None
        usage_detected = bool(
            latest_event
            and now_local.timestamp() - latest_event.end_timestamp
            <= RECENT_USAGE_SECONDS
        )
        typical_drop = (
            median(event.drop_c for event in self._events) if self._events else None
        )

        size_counts = {
            "small": sum(event.draw_size == "small" for event in self._events),
            "medium": sum(event.draw_size == "medium" for event in self._events),
            "large": sum(event.draw_size == "large" for event in self._events),
        }

        return UsageEstimate(
            usage_detected=usage_detected,
            usage_probability_next_6h=combined_probability * 100,
            expected_usage_drop_next_6h=expected_drop_next_6h,
            next_expected_usage=expected_usage,
            next_expected_usage_probability=(
                expected_usage_probability * 100
                if expected_usage_probability is not None
                else None
            ),
            next_expected_usage_drop=expected_usage_drop,
            demand_level=self._demand_level(
                combined_probability,
                expected_drop_next_6h,
            ),
            typical_usage_drop=typical_drop,
            confidence=confidence,
            event_count=len(self._events),
            observed_days=observed_days,
            relevant_observed_days=relevant_observed_days,
            small_event_count=size_counts["small"],
            medium_event_count=size_counts["medium"],
            large_event_count=size_counts["large"],
            direct_event_count=sum(event.source == "direct" for event in self._events),
            recovery_event_count=sum(
                event.source == "recovery" for event in self._events
            ),
            occupancy_state=self._occupancy_state(occupancy),
            profile_day_type=profile_day_type,
            forecast=tuple(forecast),
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

    def _bucket_typical_drop(self, day_type: str, hour: int) -> float | None:
        """Return the median learned event size for one profile bucket."""
        drops = [
            event.drop_c
            for event in self._events
            if event.day_type == day_type and event.hour == hour
        ]
        return median(drops) if drops else None

    def _observed_days_for_type(self, day_type: str) -> int:
        """Return distinct observed dates for the selected day type."""
        return len(
            {sample.date_key for sample in self._samples if sample.day_type == day_type}
        )

    @staticmethod
    def _confidence(day_type: str, observed_days: int) -> int:
        """Return confidence based on repeated exposure to the relevant day type."""
        required_days = (
            WEEKEND_CONFIDENCE_DAYS
            if day_type == "weekend"
            else WEEKDAY_CONFIDENCE_DAYS
        )
        return min(100, round(observed_days / required_days * 100))

    @staticmethod
    def _draw_size(drop_c: float) -> str:
        """Classify the relative thermal impact of one inferred draw."""
        if drop_c < SMALL_DRAW_MAX_C:
            return "small"
        if drop_c >= LARGE_DRAW_MIN_C:
            return "large"
        return "medium"

    @staticmethod
    def _demand_level(probability: float, expected_drop_c: float) -> str:
        """Return a simple explainable near-term demand level."""
        if probability >= 0.70 or expected_drop_c >= 4.0:
            return "high"
        if probability >= 0.35 or expected_drop_c >= 1.5:
            return "medium"
        return "low"

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
        self._events = [
            event for event in self._events if event.end_timestamp >= cutoff
        ]

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
                    "end_timestamp": item.end_timestamp,
                    "day_type": item.day_type,
                    "hour": item.hour,
                    "date_key": item.date_key,
                    "drop_c": item.drop_c,
                    "draw_size": item.draw_size,
                    "source": item.source,
                }
                for item in self._events
            ],
        }

    def restore(self, data: dict[str, Any] | None) -> None:
        """Restore persisted usage-learning state, including legacy events."""
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
                timestamp = float(item["timestamp"])
                drop_c = float(item["drop_c"])
                events.append(
                    UsageEvent(
                        timestamp=timestamp,
                        end_timestamp=float(item.get("end_timestamp", timestamp)),
                        day_type=str(item["day_type"]),
                        hour=int(item["hour"]),
                        date_key=str(item["date_key"]),
                        drop_c=drop_c,
                        draw_size=str(item.get("draw_size", self._draw_size(drop_c))),
                        source=str(item.get("source", "direct")),
                    )
                )
            except KeyError, TypeError, ValueError:
                continue

        samples.sort(key=lambda item: item.timestamp)
        events.sort(key=lambda item: item.timestamp)
        self._samples = samples
        self._events = events

        newest = max(
            [item.timestamp for item in samples]
            + [item.end_timestamp for item in events],
            default=None,
        )
        if newest is not None:
            self._purge_old(newest)
