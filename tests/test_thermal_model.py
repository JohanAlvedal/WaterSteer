"""Tests for WaterSteer's DHW thermal model."""

import math

import pytest
from custom_components.watersteer.thermal_model import DhwThermalModel


def _cool(model, start, temperature, hours, loss=0.6, resolution=None):
    """Add a passive cooling run sampled every five minutes."""
    steps = int(hours * 12)
    for index in range(steps + 1):
        value = temperature - index * loss / 12
        if resolution:
            value = round(value / resolution) * resolution
        model.add_observation(start + index * 300, value, False)
    return start + steps * 300, temperature - steps * loss / 12


def test_passive_loss_and_time_to_comfort() -> None:
    """Stable passive cooling produces a loss estimate and comfort horizon."""
    model = DhwThermalModel()
    _cool(model, 1_000_000.0, 52.0, 2)

    estimate = model.estimate(current_temperature=51.4, comfort_minimum=45.0)

    assert estimate.standby_loss_c_per_hour == pytest.approx(0.6)
    assert estimate.projected_temperature_1h == pytest.approx(50.8)
    assert estimate.minutes_to_comfort == pytest.approx(640)
    assert estimate.passive_segment_count == 1
    assert estimate.loss_confidence > 0


def test_large_draw_is_not_treated_as_standby_loss() -> None:
    """A rapid DHW draw splits cooling runs instead of entering the loss rate."""
    model = DhwThermalModel()
    end, temperature = _cool(model, 2_000_000.0, 52.0, 2)
    _cool(model, end + 300, temperature - 5.0, 2)

    estimate = model.estimate(current_temperature=46.0, comfort_minimum=45.0)

    assert estimate.standby_loss_c_per_hour == pytest.approx(0.6)
    assert estimate.passive_segment_count == 2


@pytest.mark.parametrize("resolution", [0.1, 0.5])
def test_sensor_resolution_does_not_bias_standby_loss(resolution) -> None:
    """Quantized sensors must not turn 0.5 °C/h into 1.2 °C/h."""
    model = DhwThermalModel()
    _cool(model, 2_500_000.0, 55.0, 18, loss=0.5, resolution=resolution)

    estimate = model.estimate(current_temperature=50.0, comfort_minimum=45.0)

    assert estimate.standby_loss_c_per_hour == pytest.approx(0.5, abs=0.03)


def test_newton_cooling_is_learned_with_temperature_spread() -> None:
    """Loss proportional to tank-room difference gives a longer horizon."""
    model = DhwThermalModel()
    k = 0.5 / 30
    start = 2_700_000.0
    for cycle in range(6):
        # Draws leave the tank at different temperatures before each run.
        temperature = (56.0, 51.0, 48.0)[cycle % 3]
        for _step in range(12 * 6):
            model.add_observation(start, round(temperature, 1), False)
            temperature = 20 + (temperature - 20) * math.exp(-k / 12)
            start += 300
        model.add_observation(start, 56.0, True)
        start += 300

    estimate = model.estimate(current_temperature=55.0, comfort_minimum=45.0)

    true_minutes = math.log(35 / 25) / k * 60
    assert estimate.loss_model == "newton"
    assert estimate.ambient_estimate_c == pytest.approx(20, abs=3)
    assert estimate.minutes_to_comfort == pytest.approx(true_minutes, rel=0.05)


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
    _cool(model, 5_000_000.0, 50.0, 2)

    restored = DhwThermalModel()
    restored.restore(model.as_dict())

    estimate = restored.estimate(current_temperature=49.0, comfort_minimum=45.0)

    assert restored.observation_count == 25
    assert estimate.standby_loss_c_per_hour == pytest.approx(0.6)


def test_sampling_interval_limits_history_density() -> None:
    """The model ignores repeated coordinator updates inside five minutes."""
    model = DhwThermalModel()

    assert model.add_observation(6_000_000.0, 50.0) is True
    assert model.add_observation(6_000_030.0, 49.99) is False
    assert model.add_observation(6_000_300.0, 49.95) is True
    assert model.observation_count == 2


def test_inconsistent_runs_reduce_confidence() -> None:
    """Confidence reflects whether the loss predicts other runs, not just volume."""
    steady = DhwThermalModel()
    noisy = DhwThermalModel()
    start = 7_000_000.0
    for index, loss in enumerate((0.5, 0.5, 0.5, 0.5, 0.5)):
        _cool(steady, start + index * 10 * 3600, 55.0, 6, loss=loss)
    for index, loss in enumerate((0.1, 1.3, 0.2, 1.2, 0.5)):
        _cool(noisy, start + index * 10 * 3600, 55.0, 6, loss=loss)

    good = steady.estimate(current_temperature=50.0, comfort_minimum=45.0)
    bad = noisy.estimate(current_temperature=50.0, comfort_minimum=45.0)

    assert good.validation_error_c == pytest.approx(0, abs=0.05)
    assert bad.validation_error_c > 2
    assert bad.loss_confidence < good.loss_confidence
