"""Tests for WaterSteer's final arbitration."""

import pytest
from custom_components.watersteer.decision import (
    ExplanationContext,
    arbitrate,
)

CTX = ExplanationContext(
    temperature=48.0,
    absolute_minimum=40.0,
    comfort_minimum=45.0,
    normal_target=50.0,
    thermal_confidence=80,
    minimum_confidence=50,
)


def _arb(intent: str, reason: str = "x", **kwargs):
    params = {
        "mode": "advisory",
        "safety_intent": intent,
        "safety_reason": reason,
        "warnings": (),
        "external_heating_active": False,
        "optimization_ready": True,
        "context": CTX,
    }
    params.update(kwargs)
    return arbitrate(**params)


@pytest.mark.parametrize(
    ("intent", "block", "extra", "status"),
    [
        ("hold", True, False, "holding"),
        ("normal", False, False, "allowing"),
        ("heat", False, False, "heating"),
        ("precharge", False, False, "preheating"),
        ("boost", False, True, "preheating"),
        ("force_heat", False, True, "protecting"),
    ],
)
def test_intent_maps_to_two_levers(intent, block, extra, status) -> None:
    """Every intent maps to exactly one block/extra-hot-water combination."""
    output = _arb(intent)

    assert (output.block, output.extra_hot_water, output.status) == (
        block,
        extra,
        status,
    )
    assert output.explanation


def test_mode_off_releases_everything() -> None:
    """Off overrides even critical recovery; the heat pump is on its own."""
    output = _arb("force_heat", mode="off")

    assert output.intent == "normal"
    assert not output.block
    assert not output.extra_hot_water
    assert output.status == "off"


def test_external_heating_drops_optional_preheating_only() -> None:
    """iBoost replaces preheating but never critical recovery."""
    assert _arb("boost", external_heating_active=True).intent == "normal"
    assert _arb("precharge", external_heating_active=True).intent == "normal"
    assert _arb("force_heat", external_heating_active=True).intent == "force_heat"
    assert _arb("hold", external_heating_active=True).intent == "hold"


def test_learning_and_fallback_status() -> None:
    """Users see learning before optimization and fallback on bad inputs."""
    assert _arb("normal", optimization_ready=False).status == "learning"
    fallback = _arb(
        "normal",
        warnings=("dhw_temperature_unavailable",),
        context=ExplanationContext(
            temperature=None,
            absolute_minimum=40.0,
            comfort_minimum=45.0,
            normal_target=50.0,
        ),
    )
    assert fallback.status == "fallback"
    assert "unavailable" in fallback.explanation
