"""Demand prediction backends for WaterSteer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from typing import Any

from .usage_model import AWAY_PROBABILITY_FACTOR, DhwUsageModel

DEFAULT_FORECAST_HOURS = 24
MIN_ML_TRAINING_ROWS = 14 * 12
MIN_ML_POSITIVE_ROWS = 8


@dataclass(frozen=True, slots=True)
class DemandBucket:
    """One hourly predicted DHW demand bucket."""

    start: datetime
    probability: float
    expected_drop_c: float


@dataclass(frozen=True, slots=True)
class DemandForecast:
    """One explainable DHW demand forecast."""

    backend: str
    confidence: int
    buckets: tuple[DemandBucket, ...]
    peak_probability: float
    expected_drop_c: float
    high_demand_hours: int


class DhwDemandPredictor:
    """Predict future DHW demand with statistical and optional ML backends."""

    def __init__(self, *, enable_ml: bool = True) -> None:
        """Initialize the predictor."""
        self._enable_ml = enable_ml
        self._ml_signature: tuple[int, int] | None = None
        self._probability_model: Any | None = None
        self._drop_model: Any | None = None

    def predict(
        self,
        *,
        usage_model: DhwUsageModel,
        now_local: datetime,
        occupancy: bool | None,
        statistical_confidence: int,
        hours: int = DEFAULT_FORECAST_HOURS,
    ) -> DemandForecast:
        """Return the best available local demand forecast."""
        statistical = usage_model.forecast_horizon(
            now_local=now_local,
            occupancy=occupancy,
            hours=hours,
        )
        rows = usage_model.ml_training_rows()

        if self._enable_ml and self._prepare_ml(rows):
            buckets = self._predict_ml(
                now_local=now_local,
                hours=hours,
                occupancy=occupancy,
            )
            backend = "ml_random_forest"
        else:
            buckets = tuple(
                DemandBucket(
                    start=item.start,
                    probability=item.probability,
                    expected_drop_c=item.expected_drop_c,
                )
                for item in statistical
            )
            backend = "statistical"

        peak_probability = max(
            (bucket.probability for bucket in buckets),
            default=0.0,
        )
        expected_drop = sum(bucket.expected_drop_c for bucket in buckets)
        high_demand_hours = sum(bucket.probability >= 0.55 for bucket in buckets)

        return DemandForecast(
            backend=backend,
            confidence=statistical_confidence,
            buckets=buckets,
            peak_probability=peak_probability,
            expected_drop_c=expected_drop,
            high_demand_hours=high_demand_hours,
        )

    def _prepare_ml(self, rows: tuple[tuple[float, ...], ...]) -> bool:
        """Train or reuse optional Random Forest models when enough data exists."""
        positive_rows = sum(row[3] > 0 for row in rows)
        if (
            len(rows) < MIN_ML_TRAINING_ROWS
            or positive_rows < MIN_ML_POSITIVE_ROWS
        ):
            return False

        signature = (len(rows), positive_rows)
        if (
            self._ml_signature == signature
            and self._probability_model is not None
            and self._drop_model is not None
        ):
            return True

        try:
            ensemble = import_module("sklearn.ensemble")
            model_class = ensemble.RandomForestRegressor
        except (ImportError, AttributeError):
            self._probability_model = None
            self._drop_model = None
            self._ml_signature = None
            return False

        features = [list(row[:3]) for row in rows]
        probability_target = [row[3] for row in rows]
        drop_target = [row[4] for row in rows]

        probability_model = model_class(
            n_estimators=80,
            max_depth=6,
            min_samples_leaf=3,
            random_state=42,
            n_jobs=1,
        )
        drop_model = model_class(
            n_estimators=80,
            max_depth=6,
            min_samples_leaf=3,
            random_state=43,
            n_jobs=1,
        )
        probability_model.fit(features, probability_target)
        drop_model.fit(features, drop_target)

        self._probability_model = probability_model
        self._drop_model = drop_model
        self._ml_signature = signature
        return True

    def _predict_ml(
        self,
        *,
        now_local: datetime,
        hours: int,
        occupancy: bool | None,
    ) -> tuple[DemandBucket, ...]:
        """Predict hourly demand using the trained local Random Forest models."""
        if self._probability_model is None or self._drop_model is None:
            return ()

        buckets: list[DemandBucket] = []
        occupancy_factor = AWAY_PROBABILITY_FACTOR if occupancy is False else 1.0

        for offset in range(max(1, hours)):
            target = now_local + __import__("datetime").timedelta(hours=offset)
            weekday = target.weekday()
            features = [[
                float(target.hour),
                float(weekday),
                1.0 if weekday >= 5 else 0.0,
            ]]
            probability = float(self._probability_model.predict(features)[0])
            expected_drop = float(self._drop_model.predict(features)[0])
            probability = max(0.0, min(1.0, probability)) * occupancy_factor
            expected_drop = max(0.0, expected_drop) * occupancy_factor

            buckets.append(
                DemandBucket(
                    start=target.replace(minute=0, second=0, microsecond=0),
                    probability=probability,
                    expected_drop_c=expected_drop,
                )
            )

        return tuple(buckets)
