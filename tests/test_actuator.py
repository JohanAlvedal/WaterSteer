"""Tests for WaterSteer's optional built-in actuation."""

from custom_components.watersteer.actuator import (
    MIN_BLOCK_INTERVAL_SECONDS,
    DhwActuator,
    Lever,
)
from custom_components.watersteer.decision import ControlOutput
from pytest_homeassistant_custom_component.common import async_mock_service

BLOCK = Lever("switch.blockera_varmvatten")
EXTRA = Lever("input_boolean.hp_extra_warm_water")


def _out(block: bool = False, extra: bool = False) -> ControlOutput:
    return ControlOutput(
        intent="hold" if block else ("force_heat" if extra else "normal"),
        block=block,
        extra_hot_water=extra,
        status="x",
        explanation="x",
        reason="x",
        warnings=(),
    )


def _mock(hass):
    calls = {
        (domain, service): async_mock_service(hass, domain, service)
        for domain in ("switch", "input_boolean")
        for service in ("turn_on", "turn_off")
    }
    return calls


async def test_advisory_mode_never_switches(hass) -> None:
    """Advisory mode only publishes; it sends no commands."""
    calls = _mock(hass)
    hass.states.async_set(BLOCK.entity_id, "off")
    actuator = DhwActuator(hass)

    report = await actuator.apply(
        now=0,
        mode="advisory",
        output=_out(block=True),
        block_lever=BLOCK,
        extra_lever=EXTRA,
    )

    assert report.commands == ()
    assert not any(calls.values())


async def test_active_mode_blocks_and_is_idempotent(hass) -> None:
    """A command is only sent when the actual state differs."""
    calls = _mock(hass)
    hass.states.async_set(BLOCK.entity_id, "off")
    actuator = DhwActuator(hass)

    report = await actuator.apply(
        now=0,
        mode="active",
        output=_out(block=True),
        block_lever=BLOCK,
        extra_lever=None,
    )
    assert report.commands == ("block",)
    assert len(calls[("switch", "turn_on")]) == 1

    hass.states.async_set(BLOCK.entity_id, "on")
    report = await actuator.apply(
        now=60,
        mode="active",
        output=_out(block=True),
        block_lever=BLOCK,
        extra_lever=None,
    )
    assert report.commands == ()


async def test_unblock_is_immediate_but_reblock_is_rate_limited(hass) -> None:
    """Safety direction is instant; optimization direction cannot cycle."""
    calls = _mock(hass)
    hass.states.async_set(BLOCK.entity_id, "off")
    actuator = DhwActuator(hass)
    await actuator.apply(
        now=0,
        mode="active",
        output=_out(block=True),
        block_lever=BLOCK,
        extra_lever=None,
    )
    hass.states.async_set(BLOCK.entity_id, "on")

    report = await actuator.apply(
        now=30, mode="active", output=_out(), block_lever=BLOCK, extra_lever=None
    )
    assert report.commands == ("unblock",)
    hass.states.async_set(BLOCK.entity_id, "off")

    report = await actuator.apply(
        now=60,
        mode="active",
        output=_out(block=True),
        block_lever=BLOCK,
        extra_lever=None,
    )
    assert report.commands == ()

    report = await actuator.apply(
        now=30 + MIN_BLOCK_INTERVAL_SECONDS,
        mode="active",
        output=_out(block=True),
        block_lever=BLOCK,
        extra_lever=None,
    )
    assert report.commands == ("block",)
    assert len(calls[("switch", "turn_on")]) == 2


async def test_force_heat_unblocks_and_requests_extra_hot_water(hass) -> None:
    """Critical recovery releases a manual block and starts extra hot water."""
    calls = _mock(hass)
    hass.states.async_set(BLOCK.entity_id, "on")
    hass.states.async_set(EXTRA.entity_id, "off")
    actuator = DhwActuator(hass)

    report = await actuator.apply(
        now=0,
        mode="active",
        output=_out(extra=True),
        block_lever=BLOCK,
        extra_lever=EXTRA,
    )

    assert report.commands == ("unblock", "extra_hot_water_on")
    assert len(calls[("switch", "turn_off")]) == 1
    assert len(calls[("input_boolean", "turn_on")]) == 1


async def test_manual_extra_hot_water_is_respected(hass) -> None:
    """WaterSteer only turns off extra hot water that it turned on itself."""
    calls = _mock(hass)
    hass.states.async_set(EXTRA.entity_id, "on")
    actuator = DhwActuator(hass)

    report = await actuator.apply(
        now=0, mode="active", output=_out(), block_lever=None, extra_lever=EXTRA
    )

    assert report.commands == ()
    assert not calls[("input_boolean", "turn_off")]


async def test_leaving_active_mode_releases_owned_levers(hass) -> None:
    """Switching to advisory or off hands the heat pump back."""
    calls = _mock(hass)
    hass.states.async_set(BLOCK.entity_id, "off")
    actuator = DhwActuator(hass)
    await actuator.apply(
        now=0,
        mode="active",
        output=_out(block=True),
        block_lever=BLOCK,
        extra_lever=None,
    )
    hass.states.async_set(BLOCK.entity_id, "on")

    restarted = DhwActuator(hass)
    restarted.restore(actuator.as_dict())
    report = await restarted.apply(
        now=10,
        mode="advisory",
        output=_out(block=True),
        block_lever=BLOCK,
        extra_lever=None,
    )

    assert report.commands == ("unblock",)
    assert len(calls[("switch", "turn_off")]) == 1


async def test_unavailable_lever_is_reported(hass) -> None:
    """A missing control entity becomes a safety warning."""
    _mock(hass)
    actuator = DhwActuator(hass)

    report = await actuator.apply(
        now=0,
        mode="active",
        output=_out(block=True),
        block_lever=BLOCK,
        extra_lever=None,
    )

    assert "block_entity_unavailable" in report.warnings
