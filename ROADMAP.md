# WaterSteer roadmap

Status legend: **production-ready** · **implemented / validating** · **incomplete** · **experimental** · **planned**.

Nothing is marked production-ready yet: every part below still needs field validation on real installations before a 1.0 release. WaterSteer is under development; running it, and in particular Active control, is at your own risk (see the warning in the [README](README.md)).

## Implemented / validating

| Area | Content |
| --- | --- |
| Integration | Config and options flow, diagnostics, HACS layout, English and Swedish translations |
| Thermal learning | Persistent 72 h history; standby loss fitted over whole cooling runs (linear, or Newton cooling with room temperature estimate); heating rate; confidence with leave-one-out prediction error |
| Usage learning | Persistent 42-day history; direct and recovery-inferred draws without double counting; weekday/weekend hourly profiles; optional occupancy |
| Demand forecast | 24 h statistical forecast |
| Price planning | Cheapest safe window before the comfort deadline; spread-based peak detection; precharge before peaks |
| Shadow price planner | 15-minute simulation of normal operation vs WaterSteer's plan; vetoes holds that would breach comfort; relative expected saving |
| Safety supervisor | Persistent critical-recovery latch; comfort-recovery escalation; maximum continuous hold below the normal target, with lockout; no hold below comfort; fail-open on missing temperature; safe defaults on invalid limits |
| Charging | Planned charges finish at their target (hysteresis); extra hot water assists only after the heat pump has had its learned start delay to start on its own (rolling self-start history), optionally never for planned charges; hold hysteresis and minimum charge size prevent cycling |
| Closed-loop test | Four simulated days in Active control against a tank and heat-pump model, for low- and high-start heat pumps: tank stays above 43 °C after learning, < 20 % of heat in the most expensive hours, few lever changes per day |
| Arbitration | One decision point mapping to two physical levers (block, extra hot water), a user status and a human explanation; external heat source (iBoost) suppresses optional preheating |
| Active control | Optional Mode select; idempotent, rate-limited blocking, immediate safety direction; respects manual extra hot water; releases on mode change, unload and Home Assistant stop |
| Entity surface | Status, Mode, Hot water remaining, Thermal learning confidence, Expected saving, Safety, Control request; everything else disabled diagnostic for new installs |

## Experimental

- Random Forest demand backend — present in code, disabled. Only to be re-enabled if it beats the statistical profile on held-out weeks (Brier score and simulated comfort breaches) and runs off the event loop.

## Known limitations and bugs

- The shadow planner's model of "normal heat-pump behaviour" (start halfway between comfort and normal target, stop at normal target) is an approximation; the saving figure is relative and unvalidated.
- Cost is expressed as heated degrees × price; tank volume and COP are not modelled, so there is no saving in kronor yet.
- A hold can delay the heat pump's legionella program by up to the maximum hold time.
- If Home Assistant crashes (no stop event) a block set in Active control stays until Home Assistant is back.
- The cycle- and schedule-based margin estimators for installations without a temperature sensor are interfaces only.
- Demand profiles use one-hour buckets.

## Planned

1. **Field validation** — compare predicted temperature 6 h ahead with the outcome and show the error as a diagnostic trend; tune defaults.
2. **Savings in kronor** — optional tank volume and COP (or measured heat-pump energy) to turn the relative saving into money, and a realized-savings counter.
3. **Legionella awareness** — optional entity or schedule so WaterSteer never holds during the legionella cycle.
4. **PumpSteer cooperation** — avoid optional DHW precharge when space-heating demand is high; never delay DHW at the comfort floor.
5. **Repairs** — Home Assistant repair issues for deprecated entities one release before they are disabled.
6. **1.0** — after a full heating season of advisory and active data.

## Principles

- Comfort and safety are never traded for price.
- Learn the system, not the controller: models estimate, rules decide.
- Fail open: when in doubt, the heat pump runs on its own.
- Everything optional must stay optional.
