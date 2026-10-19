"""Tests for the WaterSteer safety supervisor."""

from custom_components.watersteer.safety import DhwSafetySupervisor

ABS = 40.0
COMFORT = 45.0
MINUTE = 60.0


def _eval(
    supervisor: DhwSafetySupervisor,
    now: float,
    temperature: float | None,
    intent: str = "normal",
):
    return supervisor.evaluate(
        now=now,
        temperature=temperature,
        absolute_minimum=ABS,
        comfort_minimum=COMFORT,
        proposed_intent=intent,
        proposed_reason="optimizer",
    )


def test_absolute_minimum_forces_heat_even_if_optimizer_holds() -> None:
    """Critical temperature always overrides a price hold."""
    result = _eval(DhwSafetySupervisor(), 0, 38.9, "hold")

    assert result.intent == "force_heat"
    assert result.overridden is True
    assert result.reason == "absolute_minimum_requires_immediate_heat"


def test_force_latch_holds_until_comfort_and_survives_restart() -> None:
    """The critical-recovery latch is persisted and released at comfort."""
    supervisor = DhwSafetySupervisor()
    _eval(supervisor, 0, 39.5)

    restarted = DhwSafetySupervisor()
    restarted.restore(supervisor.as_dict())

    assert _eval(restarted, 5 * MINUTE, 42.0).intent == "force_heat"
    assert _eval(restarted, 10 * MINUTE, 44.9).intent == "force_heat"
    assert _eval(restarted, 15 * MINUTE, 45.0).intent == "normal"
    assert restarted.force_latched is False


def test_comfort_recovery_without_progress_escalates_to_force_heat() -> None:
    """Allow-only recovery that does not warm the tank escalates."""
    supervisor = DhwSafetySupervisor(comfort_escalation_minutes=45)

    assert _eval(supervisor, 0, 44.0, "heat").intent == "heat"
    assert _eval(supervisor, 30 * MINUTE, 43.5, "heat").intent == "heat"
    result = _eval(supervisor, 45 * MINUTE, 43.2, "heat")

    assert result.intent == "force_heat"
    assert result.reason == "comfort_recovery_not_progressing"
    assert "comfort_recovery_escalated" in result.warnings


def test_comfort_recovery_that_progresses_is_not_escalated() -> None:
    """A rising tank shows the heat pump is responding."""
    supervisor = DhwSafetySupervisor(comfort_escalation_minutes=45)

    _eval(supervisor, 0, 43.0, "heat")
    result = _eval(supervisor, 50 * MINUTE, 44.0, "heat")

    assert result.intent == "heat"
    assert supervisor.force_latched is False


def test_escalation_timer_survives_restart() -> None:
    """A restart must not reset an already running comfort deficit timer."""
    supervisor = DhwSafetySupervisor(comfort_escalation_minutes=45)
    _eval(supervisor, 0, 44.0, "heat")

    restarted = DhwSafetySupervisor(comfort_escalation_minutes=45)
    restarted.restore(supervisor.as_dict())

    assert _eval(restarted, 46 * MINUTE, 43.8, "heat").intent == "force_heat"


def test_hold_is_limited_to_max_duration_then_locked_out() -> None:
    """Continuous holding is capped and followed by a normal-operation period."""
    supervisor = DhwSafetySupervisor(max_hold_hours=2)

    assert _eval(supervisor, 0, 52.0, "hold").intent == "hold"
    assert _eval(supervisor, 119 * MINUTE, 51.0, "hold").intent == "hold"

    released = _eval(supervisor, 120 * MINUTE, 51.0, "hold")
    assert released.intent == "normal"
    assert released.reason == "max_hold_duration_reached"

    locked = _eval(supervisor, 150 * MINUTE, 51.0, "hold")
    assert locked.intent == "normal"
    assert locked.reason == "hold_lockout_after_max_hold_duration"

    assert _eval(supervisor, 181 * MINUTE, 51.0, "hold").intent == "hold"


def test_hold_duration_survives_restart() -> None:
    """A restart must not reset the continuous hold timer."""
    supervisor = DhwSafetySupervisor(max_hold_hours=2)
    _eval(supervisor, 0, 52.0, "hold")

    restarted = DhwSafetySupervisor(max_hold_hours=2)
    restarted.restore(supervisor.as_dict())

    assert _eval(restarted, 121 * MINUTE, 51.0, "hold").intent == "normal"


def test_hold_is_never_published_below_comfort_minimum() -> None:
    """Defense in depth against an optimizer bug."""
    result = _eval(DhwSafetySupervisor(), 0, 44.0, "hold")

    assert result.intent == "normal"
    assert result.reason == "hold_rejected_below_comfort_minimum"


def test_missing_temperature_fails_open_and_keeps_latch() -> None:
    """Sensor loss returns control to the heat pump but remembers the deficit."""
    supervisor = DhwSafetySupervisor()
    _eval(supervisor, 0, 39.0)

    result = _eval(supervisor, MINUTE, None, "hold")

    assert result.intent == "normal"
    assert "dhw_temperature_unavailable" in result.warnings
    assert supervisor.force_latched is True
    assert _eval(supervisor, 2 * MINUTE, 41.0).intent == "force_heat"


def test_restore_ignores_malformed_state() -> None:
    """Corrupt storage never raises and never latches."""
    supervisor = DhwSafetySupervisor()
    supervisor.restore({"force_latched": "yes", "hold_since": "abc"})

    assert supervisor.force_latched is False
    assert supervisor.hold_since is None
