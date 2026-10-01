"""Thermal learning model for domestic hot water."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

MIN_SAMPLE_INTERVAL_SECONDS = 300
MAX_HISTORY_AGE_SECONDS = 72 * 60 * 60
MIN_SEGMENT_SECONDS = 120
MAX_SEGMENT_SECONDS = 30 * 60

MIN_PASSIVE_LOSS_RATE = 0.02
MAX_PASSIVE_LOSS_RATE = 1.5
MIN_HEATING_RATE = 0.75
MAX_HEATING_RATE = 30.0


@dataclass(frozen=True, slots=True)
class ThermalObservation:
    """One sampled DHW temperature observation."""

    timestamp: float
    temperature: float
    heating_active: bool | None = None


@dataclass(frozen=True, slots=True)
class ThermalEstimate:
    """Calculated thermal properties based on observation history."""

    standby_loss_c_per_hour: float | None
    heating_rate_c_per_hour: float | None
    projected_temperature_1h: float | None
    minutes_to_comfort: float | None
    loss_confidence: int
    heating_confidence: int
    observation_count: int
    observation_hours: float
    passive_segment_count: int
    heating_segment_count: int


class DhwThermalModel:
    """Learn simple explainable DHW thermal behaviour."""

    def __init__(self) -> None:
        """Initialize an empty thermal model."""
        self._observations: list[ThermalObservation] = []

    @property
    def observation_count(self) -> int:
        """Return the number of retained observations."""
        return len(self._observations)

    def add_observation(
        self,
        timestamp: float,
        temperature: float,
        heating_active: bool | None = None,
    ) -> bool:
        """Add an observation if enough time has passed since the last sample."""
        if self._observations:
            last = self._observations[-1]
            if timestamp <= last.timestamp:
                return False
            if timestamp - last.timestamp < MIN_SAMPLE_INTERVAL_SECONDS:
                return False

        self._observations.append(
            ThermalObservation(
                timestamp=timestamp,
                temperature=temperature,
                heating_active=heating_active,
            )
        )
        self._purge_old(timestamp)
        return True

    def _purge_old(self, now: float) -> None:
        """Remove observations outside the rolling history window."""
        cutoff = now - MAX_HISTORY_AGE_SECONDS
        self._observations = [
            observation
            for observation in self._observations
            if observation.timestamp >= cutoff
        ]

    def estimate(
        self,
        current_temperature: float | None,
        comfort_minimum: float,
    ) -> ThermalEstimate:
        """Estimate thermal rates and remaining comfort time."""
        passive_rates: list[float] = []
        heating_rates: list[float] = []

        for previous, current in zip(
            self._observations,
            self._observations[1:],
            strict=False,
        ):
            elapsed_seconds = current.timestamp - previous.timestamp
            if not MIN_SEGMENT_SECONDS <= elapsed_seconds <= MAX_SEGMENT_SECONDS:
                continue

            elapsed_hours = elapsed_seconds / 3600
            rate = (current.temperature - previous.temperature) / elapsed_hours

            heating_hint = previous.heating_active or current.heating_active

            if heating_hint is True:
                if MIN_HEATING_RATE <= rate <= MAX_HEATING_RATE:
                    heating_rates.append(rate)
                continue

            if MIN_HEATING_RATE <= rate <= MAX_HEATING_RATE:
                heating_rates.append(rate)
                continue

            loss_rate = -rate
            if MIN_PASSIVE_LOSS_RATE <= loss_rate <= MAX_PASSIVE_LOSS_RATE:
                passive_rates.append(loss_rate)

        standby_loss = median(passive_rates) if passive_rates else None
        heating_rate = median(heating_rates) if heating_rates else None

        observation_hours = 0.0
        if len(self._observations) >= 2:
            observation_hours = (
                self._observations[-1].timestamp - self._observations[0].timestamp
            ) / 3600

        loss_confidence = self._confidence(
            len(passive_rates),
            observation_hours,
            required_segments=24,
            required_hours=24,
        )
        heating_confidence = min(100, len(heating_rates) * 20)

        projected_temperature_1h = None
        minutes_to_comfort = None
        if current_temperature is not None and standby_loss is not None:
            projected_temperature_1h = current_temperature - standby_loss

            if current_temperature <= comfort_minimum:
                minutes_to_comfort = 0.0
            elif standby_loss > 0:
                minutes_to_comfort = (
                    (current_temperature - comfort_minimum) / standby_loss * 60
                )

        return ThermalEstimate(
            standby_loss_c_per_hour=standby_loss,
            heating_rate_c_per_hour=heating_rate,
            projected_temperature_1h=projected_temperature_1h,
            minutes_to_comfort=minutes_to_comfort,
            loss_confidence=loss_confidence,
            heating_confidence=heating_confidence,
            observation_count=len(self._observations),
            observation_hours=observation_hours,
            passive_segment_count=len(passive_rates),
            heating_segment_count=len(heating_rates),
        )

    @staticmethod
    def _confidence(
        segment_count: int,
        observation_hours: float,
        *,
        required_segments: int,
        required_hours: float,
    ) -> int:
        """Return a conservative, explainable confidence percentage."""
        if segment_count == 0 or observation_hours <= 0:
            return 0

        segment_score = min(1.0, segment_count / required_segments)
        time_score = min(1.0, observation_hours / required_hours)
        return round(min(segment_score, time_score) * 100)

    def as_dict(self) -> dict[str, Any]:
        """Serialize the retained observations."""
        return {
            "observations": [
                {
                    "timestamp": observation.timestamp,
                    "temperature": observation.temperature,
                    "heating_active": observation.heating_active,
                }
                for observation in self._observations
            ]
        }

    def restore(self, data: dict[str, Any] | None) -> None:
        """Restore valid observations from persisted model data."""
        if not isinstance(data, dict):
            return

        restored: list[ThermalObservation] = []
        for item in data.get("observations", []):
            if not isinstance(item, dict):
                continue
            try:
                timestamp = float(item["timestamp"])
                temperature = float(item["temperature"])
            except KeyError, TypeError, ValueError:
                continue

            heating_active = item.get("heating_active")
            if heating_active not in (True, False, None):
                heating_active = None

            restored.append(
                ThermalObservation(
                    timestamp=timestamp,
                    temperature=temperature,
                    heating_active=heating_active,
                )
            )

        restored.sort(key=lambda observation: observation.timestamp)
        self._observations = restored
        if restored:
            self._purge_old(restored[-1].timestamp)
