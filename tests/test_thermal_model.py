"""Tests for WaterSteer's DHW thermal model."""

import pytest
from custom_components.watersteer.thermal_model import DhwThermalModel


def test_passive_loss_and_time_to_comfort() -> None:
    """Stable passive cooling produces a loss estimate and comfort horizon."""
    model = DhwThermalModel()

    start = 1_000_000.0
    for index in range(13):
        model.add_observation(
            start + index * 300,
            52.0 - index * 0.05,
            False,
        )

    estimate = model.estimate(current_temperature=51.4, comfort_minimum=45.0)

    assert estimate.standby_loss_c_per_hour == pytest.approx(0.6)
    assert estimate.projected_temperature_1h == pytest.approx(50.8)
    assert estimate.minutes_to_comfort == pytest.approx(640)
    assert estimate.passive_segment_count == 12
    assert estimate.loss_confidence > 0


def test_large_draw_is_not_treated_as_standby_loss() -> None:
    """A rapid DHW draw is excluded from passive standby-loss learning."""
    model = DhwThermalModel()

    start = 2_000_000.0
    model.add_observation(start, 52.0, False)
    model.add_observation(start + 300, 51.95, False)
    model.add_observation(start + 600, 47.0, False)

    estimate = model.estimate(current_temperature=47.0, comfort_minimum=45.0)

    assert estimate.standby_loss_c_per_hour == pytest.approx(0.6)
    assert estimate.passive_segment_count == 1


def test_heating_rate_is_learned_without_active_sensor() -> None:
    """Strong positive temperature slope can identify heating without a hint."""
    model = DhwThermalModel()

    start = 3_000_000.0
    model.add_observation(start, 42.0)
    model.add_observation(start + 300, 42.5)
    model.add_observation(start + 600, 43.0)

    estimate = model.estimate(current_temperature=43.0, comfort_minimum=45.0)

    assert estimate.heating_rate_c_per_hour == pytest.approx(6.0)
    assert estimate.heating_segment_count == 2
    assert estimate.heating_confidence == 40


def test_active_heating_hint_excludes_segment_from_passive_learning() -> None:
    """Explicit heating-active hints prevent passive-loss classification."""
    model = DhwThermalModel()

    start = 4_000_000.0
    model.add_observation(start, 50.0, True)
    model.add_observation(start + 300, 49.95, True)

    estimate = model.estimate(current_temperature=49.95, comfort_minimum=45.0)

    assert estimate.standby_loss_c_per_hour is None
    assert estimate.passive_segment_count == 0


def test_model_serialization_round_trip() -> None:
    """Persisted observation history can be restored after a restart."""
    model = DhwThermalModel()
    model.add_observation(5_000_000.0, 50.0, False)
    model.add_observation(5_000_300.0, 49.95, False)

    restored = DhwThermalModel()
    restored.restore(model.as_dict())

    estimate = restored.estimate(current_temperature=49.95, comfort_minimum=45.0)

    assert restored.observation_count == 2
    assert estimate.standby_loss_c_per_hour == pytest.approx(0.6)


def test_sampling_interval_limits_history_density() -> None:
    """The model ignores repeated coordinator updates inside five minutes."""
    model = DhwThermalModel()

    assert model.add_observation(6_000_000.0, 50.0) is True
    assert model.add_observation(6_000_030.0, 49.99) is False
    assert model.add_observation(6_000_300.0, 49.95) is True
    assert model.observation_count == 2
