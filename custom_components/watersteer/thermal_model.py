"""Thermal learning model for domestic hot water."""

from __future__ import annotations

import math
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

# Passive loss is learned from whole cooling runs rather than from 5-minute
# steps. A typical sensor reports in 0.1 °C steps while a tank loses ~0.5 °C/h,
# so single 5-minute steps are either 0 or 1.2 °C/h and their median is
# meaningless. A run ends at heating, at a draw, or at a gap in the data.
MIN_RUN_SECONDS = 60 * 60
RUN_RISE_TOLERANCE_C = 0.6
RUN_DRAW_MIN_C = 1.0
RUN_DRAW_RATE_C_PER_HOUR = 3.0
REQUIRED_PASSIVE_HOURS = 24.0
REQUIRED_RUNS = 4

# Newton cooling (loss proportional to tank minus room temperature) is used
# when runs cover enough temperature spread to fit it reliably.
NEWTON_MIN_RUNS = 4
NEWTON_MIN_SPREAD_C = 3.0
NEWTON_AMBIENT_RANGE_C = (0.0, 35.0)

# Confidence is reduced when the learned loss does not predict held-out runs:
# the error is the leave-one-out difference in temperature drop over 6 hours.
VALIDATION_HORIZON_HOURS = 6.0
VALIDATION_GOOD_ERROR_C = 0.75
VALIDATION_BAD_ERROR_C = 2.5
VALIDATION_MIN_FACTOR = 0.3


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
    passive_hours: float = 0.0
    ambient_estimate_c: float | None = None
    loss_model: str = "none"
    validation_error_c: float | None = None


@dataclass(frozen=True, slots=True)
class PassiveRun:
    """One uninterrupted passive cooling run."""

    rate_c_per_hour: float
    hours: float
    mean_temperature: float


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

    def passive_runs(self) -> list[PassiveRun]:
        """Split the history into passive cooling runs and fit each one."""
        runs: list[PassiveRun] = []
        current: list[ThermalObservation] = []

        def finish() -> None:
            run = _fit_run(current)
            if run is not None:
                runs.append(run)

        for previous, observation in zip(
            self._observations,
            self._observations[1:],
            strict=False,
        ):
            elapsed = observation.timestamp - previous.timestamp
            delta = observation.temperature - previous.temperature
            heating = (
                previous.heating_active is True or observation.heating_active is True
            )
            draw = (
                -delta >= RUN_DRAW_MIN_C
                and elapsed > 0
                and -delta / (elapsed / 3600) >= RUN_DRAW_RATE_C_PER_HOUR
            )
            if (
                elapsed > MAX_SEGMENT_SECONDS
                or heating
                or delta > RUN_RISE_TOLERANCE_C
                or draw
            ):
                finish()
                current = [] if heating else [observation]
                continue
            if not current:
                current = [previous]
            current.append(observation)

        finish()
        return runs

    def estimate(
        self,
        current_temperature: float | None,
        comfort_minimum: float,
    ) -> ThermalEstimate:
        """Estimate thermal rates and remaining comfort time."""
        heating_rates: list[float] = []

        for previous, current in zip(
            self._observations,
            self._observations[1:],
            strict=False,
        ):
            elapsed_seconds = current.timestamp - previous.timestamp
            if not MIN_SEGMENT_SECONDS <= elapsed_seconds <= MAX_SEGMENT_SECONDS:
                continue
            if previous.heating_active is False and current.heating_active is False:
                continue
            rate = (current.temperature - previous.temperature) / (
                elapsed_seconds / 3600
            )
            if MIN_HEATING_RATE <= rate <= MAX_HEATING_RATE:
                heating_rates.append(rate)

        runs = self.passive_runs()
        passive_hours = sum(run.hours for run in runs)
        newton = _fit_newton(runs)

        standby_loss: float | None = None
        loss_model = "none"
        if runs:
            standby_loss = _weighted_median(
                [(run.rate_c_per_hour, run.hours) for run in runs]
            )
            loss_model = "linear"
        if newton is not None:
            loss_model = "newton"

        heating_rate = median(heating_rates) if heating_rates else None

        observation_hours = 0.0
        if len(self._observations) >= 2:
            observation_hours = (
                self._observations[-1].timestamp - self._observations[0].timestamp
            ) / 3600

        loss_confidence = 0
        if runs:
            loss_confidence = round(
                min(
                    1.0,
                    passive_hours / REQUIRED_PASSIVE_HOURS,
                    len(runs) / REQUIRED_RUNS,
                )
                * 100
            )
        validation_error = _validation_error(runs)
        if validation_error is not None:
            loss_confidence = round(
                loss_confidence * _validation_factor(validation_error)
            )
        heating_confidence = min(100, len(heating_rates) * 20)

        projected_temperature_1h = None
        minutes_to_comfort = None
        if current_temperature is not None and standby_loss is not None:
            if newton is not None:
                k, ambient = newton
                projected_temperature_1h = ambient + (
                    current_temperature - ambient
                ) * math.exp(-k)
                if current_temperature <= comfort_minimum:
                    minutes_to_comfort = 0.0
                elif comfort_minimum > ambient:
                    hours = (
                        math.log(
                            (current_temperature - ambient)
                            / (comfort_minimum - ambient)
                        )
                        / k
                    )
                    minutes_to_comfort = hours * 60
                    # Effective average loss between now and the comfort floor,
                    # so every consumer of a constant rate stays consistent.
                    standby_loss = (current_temperature - comfort_minimum) / hours
            else:
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
            passive_segment_count=len(runs),
            heating_segment_count=len(heating_rates),
            passive_hours=passive_hours,
            ambient_estimate_c=newton[1] if newton is not None else None,
            loss_model=loss_model,
            validation_error_c=validation_error,
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


def _fit_run(run: list[ThermalObservation]) -> PassiveRun | None:
    """Least-squares cooling rate for one run, or None if unusable."""
    if len(run) < 3:
        return None
    duration = run[-1].timestamp - run[0].timestamp
    if duration < MIN_RUN_SECONDS:
        return None
    times = [(item.timestamp - run[0].timestamp) / 3600 for item in run]
    temps = [item.temperature for item in run]
    mean_t = sum(times) / len(times)
    mean_temp = sum(temps) / len(temps)
    var = sum((t - mean_t) ** 2 for t in times)
    if var <= 0:
        return None
    slope = (
        sum(
            (t - mean_t) * (temp - mean_temp)
            for t, temp in zip(times, temps, strict=True)
        )
        / var
    )
    rate = -slope
    if not MIN_PASSIVE_LOSS_RATE <= rate <= MAX_PASSIVE_LOSS_RATE:
        return None
    return PassiveRun(
        rate_c_per_hour=rate,
        hours=duration / 3600,
        mean_temperature=mean_temp,
    )


def _fit_newton(runs: list[PassiveRun]) -> tuple[float, float] | None:
    """Fit rate = k * (T - ambient) weighted by run length."""
    if len(runs) < NEWTON_MIN_RUNS:
        return None
    temps = [run.mean_temperature for run in runs]
    if max(temps) - min(temps) < NEWTON_MIN_SPREAD_C:
        return None
    weights = [run.hours for run in runs]
    total = sum(weights)
    mean_x = sum(w * run.mean_temperature for w, run in zip(weights, runs, strict=True))
    mean_x /= total
    mean_y = sum(w * run.rate_c_per_hour for w, run in zip(weights, runs, strict=True))
    mean_y /= total
    var = sum(
        w * (run.mean_temperature - mean_x) ** 2
        for w, run in zip(weights, runs, strict=True)
    )
    if var <= 0:
        return None
    k = (
        sum(
            w * (run.mean_temperature - mean_x) * (run.rate_c_per_hour - mean_y)
            for w, run in zip(weights, runs, strict=True)
        )
        / var
    )
    if k <= 0:
        return None
    ambient = mean_x - mean_y / k
    low, high = NEWTON_AMBIENT_RANGE_C
    if not low <= ambient <= high:
        return None
    return k, ambient


def _weighted_median(values: list[tuple[float, float]]) -> float:
    """Return the weighted median of (value, weight) pairs."""
    ordered = sorted(values)
    half = sum(weight for _, weight in ordered) / 2
    running = 0.0
    for value, weight in ordered:
        running += weight
        if running >= half:
            return value
    return ordered[-1][0]


def _validation_error(runs: list[PassiveRun]) -> float | None:
    """Leave-one-out error of the learned loss, in °C over the horizon."""
    if len(runs) < 3:
        return None
    errors: list[tuple[float, float]] = []
    for index, run in enumerate(runs):
        others = [
            (other.rate_c_per_hour, other.hours)
            for position, other in enumerate(runs)
            if position != index
        ]
        predicted = _weighted_median(others)
        errors.append(
            (abs(predicted - run.rate_c_per_hour) * VALIDATION_HORIZON_HOURS, run.hours)
        )
    total = sum(weight for _, weight in errors)
    return sum(error * weight for error, weight in errors) / total


def _validation_factor(error_c: float) -> float:
    """Map validation error to a confidence multiplier."""
    if error_c <= VALIDATION_GOOD_ERROR_C:
        return 1.0
    if error_c >= VALIDATION_BAD_ERROR_C:
        return VALIDATION_MIN_FACTOR
    span = VALIDATION_BAD_ERROR_C - VALIDATION_GOOD_ERROR_C
    return 1.0 - (error_c - VALIDATION_GOOD_ERROR_C) / span * (
        1.0 - VALIDATION_MIN_FACTOR
    )
