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


def test_max_hold_only_counts_time_below_normal_target() -> None:
    """A warm tank is never released on a timer.

    Field data (IVT, 5 Nov 2026): a 12 h hold expired at 51.8 °C in the most
    expensive hour of the day and the heat pump ran for nothing.
    """
    supervisor = DhwSafetySupervisor(max_hold_hours=2)

    def hold(now: float, temperature: float):
        return supervisor.evaluate(
            now=now,
            temperature=temperature,
            absolute_minimum=ABS,
            comfort_minimum=COMFORT,
            proposed_intent="hold",
            proposed_reason="optimizer",
            normal_target=50.0,
        )

    assert hold(0, 52.0).intent == "hold"
    assert hold(180 * MINUTE, 50.1).intent == "hold"
    # The two hours count from the last moment at or above normal target.
    assert hold(181 * MINUTE, 49.9).intent == "hold"
    assert hold(299 * MINUTE, 49.0).intent == "hold"
    released = hold(300 * MINUTE, 49.0)
    assert released.intent == "normal"
    assert released.reason == "max_hold_duration_reached"

    restarted = DhwSafetySupervisor(max_hold_hours=2)
    restarted.restore(supervisor.as_dict())
    assert restarted.hold_counted_since is None


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


def test_planned_charge_finishes_even_if_plan_flips_to_hold() -> None:
    """A started cheap charge runs to its target instead of dithering."""
    from custom_components.watersteer.safety import ChargeController

    charge = ChargeController()
    targets = {"heat": 52.5, "precharge": 55.0}

    first = charge.evaluate(
        now=0, intent="heat", reason="window", temperature=47.0, target_for=targets
    )
    flipped = charge.evaluate(
        now=600,
        intent="hold",
        reason="safe_to_hold_for_price_plan",
        temperature=50.5,
        target_for=targets,
    )
    done = charge.evaluate(
        now=1200, intent="hold", reason="x", temperature=52.6, target_for=targets
    )

    assert first.intent == "heat"
    assert flipped.intent == "heat"
    assert flipped.reason == "finishing_planned_charge"
    assert done.intent == "hold"


def test_charge_requests_extra_hot_water_when_pump_does_not_start() -> None:
    """Unblocking alone may not start the heat pump; assist after the wait."""
    from custom_components.watersteer.safety import ChargeController

    charge = ChargeController()
    targets = {"heat": 52.5, "precharge": 55.0}

    assert charge.assist_after_minutes == 30
    assert not charge.evaluate(
        now=0, intent="precharge", reason="w", temperature=48.0, target_for=targets
    ).assist
    assert not charge.evaluate(
        now=21 * MINUTE,
        intent="precharge",
        reason="w",
        temperature=47.9,
        target_for=targets,
    ).assist
    assert charge.evaluate(
        now=30 * MINUTE,
        intent="precharge",
        reason="w",
        temperature=47.9,
        target_for=targets,
    ).assist


def test_charge_does_not_override_hold_limits() -> None:
    """Safety releases of a hold are never turned back into heating."""
    from custom_components.watersteer.safety import ChargeController

    charge = ChargeController()
    targets = {"heat": 52.5, "precharge": 55.0}
    charge.evaluate(
        now=0, intent="heat", reason="w", temperature=47.0, target_for=targets
    )

    result = charge.evaluate(
        now=60,
        intent="force_heat",
        reason="absolute_minimum_requires_immediate_heat",
        temperature=39.0,
        target_for=targets,
    )
    assert result.intent == "force_heat"
    assert charge.intent is None


def _charge_cycle(charge, base, *, starts, targets, reason="w"):
    """Run one charge; the tank warms by itself only if ``starts``."""
    charge.evaluate(
        now=base, intent="heat", reason=reason, temperature=47.0, target_for=targets
    )
    second = charge.evaluate(
        now=base + 10 * MINUTE,
        intent="heat",
        reason=reason,
        temperature=48.0 if starts else 47.0,
        target_for=targets,
    )
    timeout = charge.evaluate(
        now=base + 40 * MINUTE,
        intent="heat",
        reason=reason,
        temperature=50.0 if starts else 46.9,
        target_for=targets,
    )
    charge.evaluate(
        now=base + 90 * MINUTE,
        intent="hold",
        reason="x",
        temperature=53.0,
        target_for=targets,
    )
    return second, timeout


def test_self_start_is_a_rolling_history_not_a_latch() -> None:
    """One slow start must not make every later charge use extra hot water.

    Field data (IVT, Nov 2026): a single charge where the heat pump took longer
    than 15 minutes latched "does not start by itself"; from then on every
    planned charge used extra hot water (the immersion heater on that model)
    from the first second, although the heat pump started by itself in 5 of 6
    releases.
    """
    from custom_components.watersteer.safety import ChargeController

    charge = ChargeController()
    targets = {"heat": 52.5, "precharge": 55.0}

    _second, timeout = _charge_cycle(charge, 0, starts=False, targets=targets)
    assert timeout.assist
    assert charge.pump_starts_on_its_own is False

    # The next charge still gives the heat pump its chance first.
    second, _timeout = _charge_cycle(charge, 600 * MINUTE, starts=True, targets=targets)
    assert not second.assist
    assert charge.self_start_history == [False, True]
    assert charge.pump_starts_on_its_own is True

    restarted = ChargeController()
    restarted.restore(charge.as_dict())
    assert restarted.self_start_history == [False, True]
    first = restarted.evaluate(
        now=1200 * MINUTE,
        intent="precharge",
        reason="w",
        temperature=48.0,
        target_for=targets,
    )
    assert first.assist is False


def test_old_latched_storage_is_only_one_observation() -> None:
    """A persisted ``pump_starts_on_its_own: false`` can be overturned."""
    from custom_components.watersteer.safety import ChargeController

    charge = ChargeController()
    charge.restore({"pump_starts_on_its_own": False})
    assert charge.self_start_history == [False]
    targets = {"heat": 52.5, "precharge": 55.0}
    second, _timeout = _charge_cycle(charge, 0, starts=True, targets=targets)
    assert not second.assist
    assert charge.pump_starts_on_its_own is True


def test_planned_charge_without_extra_hot_water_gives_up() -> None:
    """With the option off, a planned charge the pump ignores is abandoned."""
    from custom_components.watersteer.safety import ChargeController

    charge = ChargeController()
    charge.assist_planned = False
    targets = {"heat": 52.5, "precharge": 55.0}

    charge.evaluate(
        now=0, intent="heat", reason="w", temperature=48.0, target_for=targets
    )
    gave_up = charge.evaluate(
        now=30 * MINUTE, intent="heat", reason="w", temperature=48.0, target_for=targets
    )
    later = charge.evaluate(
        now=45 * MINUTE, intent="heat", reason="w", temperature=48.0, target_for=targets
    )
    assert not gave_up.assist
    assert not later.assist
    assert charge.intent is None
    assert charge.given_up

    # The next planned charge (after the plan left heating) starts afresh.
    charge.evaluate(
        now=60 * MINUTE, intent="hold", reason="x", temperature=48.0, target_for=targets
    )
    assert not charge.given_up


def test_comfort_recovery_still_gets_extra_hot_water_when_option_off() -> None:
    """Extra hot water for planned charges off never weakens comfort recovery."""
    from custom_components.watersteer.safety import ChargeController

    charge = ChargeController()
    charge.assist_planned = False
    targets = {"heat": 46.0, "precharge": 55.0}
    reason = "comfort_recovery_requires_heat"
    charge.evaluate(
        now=0, intent="heat", reason=reason, temperature=44.5, target_for=targets
    )
    result = charge.evaluate(
        now=30 * MINUTE,
        intent="heat",
        reason=reason,
        temperature=44.4,
        target_for=targets,
    )
    assert result.assist


def test_stall_without_extra_hot_water_ends_charge() -> None:
    """Pump stops at 51.7 °C below a 55 °C precharge: accept it if option off."""
    from custom_components.watersteer.safety import ChargeController

    charge = ChargeController()
    charge.assist_planned = False
    targets = {"heat": 52.5, "precharge": 55.0}
    results = [
        charge.evaluate(
            now=step * 5 * MINUTE,
            intent="precharge",
            reason="w",
            temperature=temp,
            target_for=targets,
        )
        for step, temp in enumerate([48.0, 50.0, 51.7, 51.7, 51.7, 51.7, 51.7])
    ]
    assert not any(result.assist for result in results)
    assert charge.given_up


def test_pump_that_starts_by_itself_is_not_assisted() -> None:
    """A heat pump that heats when unblocked never gets extra hot water."""
    from custom_components.watersteer.safety import ChargeController

    charge = ChargeController()
    targets = {"heat": 52.5, "precharge": 55.0}
    charge.evaluate(
        now=0, intent="heat", reason="w", temperature=47.0, target_for=targets
    )
    result = charge.evaluate(
        now=10 * MINUTE,
        intent="heat",
        reason="w",
        temperature=48.0,
        target_for=targets,
    )
    later = charge.evaluate(
        now=30 * MINUTE,
        intent="heat",
        reason="w",
        temperature=49.5,
        target_for=targets,
    )

    assert charge.pump_starts_on_its_own is True
    assert not result.assist
    assert not later.assist


def test_start_delay_is_learned_from_extra_hot_water_requests() -> None:
    """The time until the tank warms is measured and used for planning."""
    from custom_components.watersteer.safety import (
        DEFAULT_START_DELAY_MINUTES,
        ChargeController,
    )

    charge = ChargeController()
    targets = {"heat": 52.5, "precharge": 55.0}
    assert charge.start_delay_minutes == DEFAULT_START_DELAY_MINUTES

    charge.pump_starts_on_its_own = False
    for start in (0, 1000, 2000):
        base = start * MINUTE
        wait = charge.assist_after_minutes * MINUTE
        charge.evaluate(
            now=base,
            intent="heat",
            reason="w",
            temperature=47.0,
            target_for=targets,
        )
        assist = charge.evaluate(
            now=base + wait,
            intent="heat",
            reason="w",
            temperature=47.1,
            target_for=targets,
        )
        assert assist.assist
        charge.evaluate(
            now=base + wait + 7 * MINUTE,
            intent="heat",
            reason="w",
            temperature=47.6,
            target_for=targets,
        )
        charge.evaluate(
            now=base + wait + 60 * MINUTE,
            intent="hold",
            reason="x",
            temperature=53.0,
            target_for=targets,
        )

    # Measured from the extra hot water request until the tank warms.
    assert charge.start_delay_minutes == 7
    assert charge.assist_after_minutes == 15
    restored = ChargeController()
    restored.restore(charge.as_dict())
    assert restored.start_delay_minutes == 7


def test_production_signal_marks_start_before_temperature_rises() -> None:
    """With a power signal the start delay is measured at production start."""
    from custom_components.watersteer.safety import ChargeController

    charge = ChargeController()
    targets = {"heat": 52.5, "precharge": 55.0}
    charge.evaluate(
        now=0,
        intent="heat",
        reason="w",
        temperature=47.0,
        target_for=targets,
        producing=False,
    )
    result = charge.evaluate(
        now=10 * MINUTE,
        intent="heat",
        reason="w",
        temperature=47.0,
        target_for=targets,
        producing=True,
    )

    assert not result.assist
    assert charge.pump_starts_on_its_own is True
    assert charge.start_delays == [10.0]


def test_charge_that_stalls_below_target_gets_extra_hot_water() -> None:
    """The heat pump's own cycle stops at ~51.7 °C; precharge wants 55 °C."""
    from custom_components.watersteer.safety import ChargeController

    charge = ChargeController()
    targets = {"heat": 52.5, "precharge": 55.0}
    temps = [48.0, 50.0, 51.7, 51.7, 51.6, 51.6]
    results = []
    for index, temp in enumerate(temps):
        results.append(
            charge.evaluate(
                now=index * 5 * MINUTE,
                intent="precharge",
                reason="w",
                temperature=temp,
                target_for=targets,
                producing=index < 3,
            )
        )
    stalled = charge.evaluate(
        now=30 * MINUTE,
        intent="precharge",
        reason="w",
        temperature=51.5,
        target_for=targets,
        producing=False,
    )

    assert not results[2].assist
    assert stalled.assist


def test_charge_gives_up_when_extra_hot_water_does_not_help() -> None:
    """If even extra hot water does not raise the tank, the charge ends."""
    from custom_components.watersteer.safety import ChargeController

    charge = ChargeController()
    targets = {"heat": 52.5, "precharge": 55.0}
    charge.evaluate(
        now=0,
        intent="precharge",
        reason="w",
        temperature=48.0,
        target_for=targets,
        producing=True,
    )
    for minute in range(5, 80, 5):
        result = charge.evaluate(
            now=minute * MINUTE,
            intent="hold",
            reason="safe_to_hold_for_price_plan",
            temperature=48.0,
            target_for=targets,
            producing=False,
        )

    assert result.intent == "hold"
    assert charge.intent is None
