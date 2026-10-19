# WaterSteer

WaterSteer is a local-first Home Assistant custom integration for intelligent domestic hot water (DHW) optimization.

Its goal is to shift DHW production to thermally and economically suitable periods without sacrificing hot-water comfort or interfering with space heating more than necessary.

WaterSteer is designed to work with both:

- heat pumps with integrated DHW
- standalone electric water heaters

The project is manufacturer-independent and uses Home Assistant entities and actions as its integration layer.

## Core principle

Cheap electricity alone must never be enough to trigger DHW heating.

WaterSteer should answer three questions:

1. **When will hot water probably be needed?**
2. **How much useful hot water is likely to remain until then?**
3. **When is the best safe time to replenish it?**

Comfort and safety always take priority over price optimization.

## Current capabilities

WaterSteer currently runs in **advisory mode** unless active control is explicitly added in a later step. Planning and learning run normally; the absence of configured control is not treated as a special shadow state.

### Configuration

- Select standalone water heater or heat-pump-integrated DHW
- Optionally select a DHW temperature sensor
- Select electricity price sensor
- Optional occupancy input:
  - binary sensor
  - input boolean
  - person entity
- Configure DHW temperature thresholds
- Configure the minimum thermal-learning confidence required before braking is allowed
- Configure standalone control switch and optional power sensor
- Configure optional heat-pump DHW availability and production-active signals
- Configure generic Boost, Block, and Normal actions for future active control
- Reconfigure everything through Home Assistant Options Flow

### Capability-based estimation

WaterSteer is moving to a capability-based architecture. The planner consumes one common concept: **safe DHW margin**.

The best available estimator is selected without weakening a stronger model just because an optional model is immature:

- `thermal` when DHW temperature and learned thermal behaviour are available
- `cycle` for future cycle/runtime learning when temperature is unavailable
- `simple` for a future conservative schedule/feedback model with minimal telemetry

Usage learning is an optional adjustment to thermal margin, not a hard dependency. A weak usage model must not reduce confidence in a strong thermal model.

### Thermal learning

WaterSteer keeps a persistent rolling thermal history and learns:

- standby heat loss in °C/h
- DHW heating rate in °C/h
- projected temperature one hour ahead
- estimated time to the comfort minimum
- thermal learning confidence
- heating confidence

The model samples at a controlled interval and ignores temperature changes that do not fit plausible passive-loss or heating behaviour.

Thermal history survives Home Assistant restarts.

### Predicted autonomy

WaterSteer now calculates DHW autonomy in advisory mode.

It exposes both:

- passive autonomy based only on current temperature and learned standby loss
- predicted autonomy adjusted by the learned six-hour demand forecast
- predicted DHW temperature after six hours
- autonomy confidence
- the model basis used for the current prediction

Demand adjustment is deliberately gated. If usage-learning confidence is below 20%, WaterSteer falls back to `thermal_only` autonomy instead of pretending that an immature demand profile is reliable.

The autonomy model is analytics only. It does not issue Block, Normal, or Boost commands.

### Usage learning

WaterSteer also learns explainable DHW usage patterns.

It detects likely hot-water draws using a hybrid approach:

- direct detection from rapid unexplained temperature drops
- recovery-based detection when a DHW heating cycle starts significantly earlier than learned standby loss can explain
- inferred DHW-heating detection from a clear temperature rise when no explicit DHW-active signal is available

Recovery-based events are only created when the recharge is materially earlier than the passive thermal model predicts, and recent direct draw events suppress duplicate recovery events. WaterSteer does not require an explicit DHW-active entity for this path; a sufficiently clear temperature rise can be used as a fallback heating signal.

The model then builds separate time-of-day profiles for:

- weekdays
- weekends

The model currently learns:

- recent DHW usage detection
- grouped direct draw events, so a longer shower is not counted as several separate uses
- recovery-inferred usage events for installations where the DHW sensor reacts slowly to draws
- separate direct-event and recovery-event diagnostics
- small, medium, and large draw impact
- separate weekday and weekend confidence
- hourly usage probability over the next six hours
- expected thermal usage impact over the next six hours
- next expected DHW usage window, probability, and typical impact
- near-term demand level: low, medium, or high
- typical temperature drop caused by usage
- usage-learning confidence based on exposure to the relevant day type
- number of observed usage events and days
- an explainable six-hour hourly demand forecast in sensor attributes

Occupancy is optional. If an occupancy entity is configured, an explicit away state reduces expected demand. WaterSteer still works without any presence data.

Usage learning is persistent and survives Home Assistant restarts.

## Safety and confidence gating

WaterSteer is intentionally conservative while learning.

The temperature classifier may identify a theoretical hold condition, but **DHW braking is not allowed until thermal learning confidence reaches the configured minimum**.

Default:

```text
Minimum thermal confidence for braking: 50%
```

Before that threshold is reached:

```text
Decision: learning_guard
DHW allowed: ON
Reason: thermal_confidence_below_minimum
```

This rule is designed to prevent WaterSteer from withholding normal DHW production before it understands the thermal behaviour well enough.

If required sensor data is invalid, WaterSteer fails safe and allows normal DHW operation.

### Safety supervisor

Every published control request passes a persistent safety supervisor last. It can only make the request safer:

| Rule | Result |
| --- | --- |
| DHW temperature unavailable | `normal` — control returns to the heat pump |
| Temperature at or below absolute minimum | `force_heat`, latched until the comfort minimum is reached |
| Below comfort minimum for *Comfort recovery escalation* minutes (default 45) without warming at least 0.5 °C | `force_heat` (escalation) |
| Optimizer proposes `hold` below comfort minimum | `normal` |
| `hold` lasted *Maximum continuous hold* (default 6 h) | `normal` for at least 60 minutes |
| Thresholds not strictly ordered | built-in default thresholds protect comfort, price optimization is suspended, `mode = safety` |

The latch, the comfort-deficit timer and the hold timer are stored and survive Home Assistant restarts.

WaterSteer does not execute physical actions itself. Automations that act on `sensor.watersteer_control_request` should trigger on every state change and on Home Assistant start, treat `unavailable` as `normal`, and never place a condition on a diagnostic WaterSteer entity in the `force_heat` path. See [docs/AUDIT.md](docs/AUDIT.md).

## Current advisory decisions

With the default thresholds:

```text
Absolute minimum: 40 °C
Comfort minimum: 45 °C
Normal target: 50 °C
Precharge target: 55 °C
```

the raw temperature classifier behaves as follows:

| DHW temperature | Raw decision | Request | Force |
| --- | --- | --- | --- |
| <= 40 °C | `force_heat` | ON | ON |
| 40–45 °C | `comfort_recovery` | ON | OFF (escalates to ON after the escalation time without progress) |
| 45–50 °C | `normal_operation` | OFF | OFF |
| >= 50 °C | `temperature_hold` | OFF | OFF |

A `temperature_hold` only becomes an actual WaterSteer `DHW allowed = OFF` advisory decision after the thermal-confidence gate has been satisfied.

## Home Assistant entities

WaterSteer keeps the default entity surface intentionally small.

Enabled by default:

```text
sensor.watersteer_mode
sensor.watersteer_control_mode
sensor.watersteer_control_request
sensor.watersteer_dhw_temperature
sensor.watersteer_safe_dhw_margin
sensor.watersteer_dhw_price_plan_status
sensor.watersteer_next_planned_dhw_charge
sensor.watersteer_thermal_learning_confidence

binary_sensor.watersteer_dhw_allowed
binary_sensor.watersteer_force_request
```

`sensor.watersteer_control_request` is the single human-readable control intent:

```text
hold
normal
heat
force_heat
precharge
boost
```

The intents deliberately distinguish normal DHW production from extraordinary boost:

- `hold` blocks or postpones normal DHW production while the margin is safe.
- `normal` leaves the heat pump or heater in normal operation.
- `heat` requests normal DHW production in a selected charge window.
- `force_heat` is a latched critical-recovery request. On heat-pump installations where Extra Hot Water is the available emergency action, it may map to that boost and remains active until the comfort minimum has recovered.
- `precharge` advances normal DHW production before an expensive price block.
- `boost` is a last-resort extraordinary pre-peak request for installations where a boost means substantially hotter water. It is not used merely because electricity is cheap or a peak exists.

Advanced learning, usage, autonomy, planner-detail and diagnostic entities are still available but are disabled by default in the Home Assistant entity registry. They can be enabled individually when troubleshooting or developing WaterSteer.

`binary_sensor.watersteer_dhw_allowed` is off exactly when `control_request` is `hold`, and `binary_sensor.watersteer_force_request` is on exactly when it is `force_heat`.

Config-entry version 2 disabled `sensor.watersteer_thermal_learning_confidence` on existing installations. Version 3 re-enables it when WaterSteer (not the user) disabled it, because external automations depend on it. A planned simplification to about five primary entities is described in [docs/AUDIT.md](docs/AUDIT.md).

Entity IDs may receive Home Assistant suffixes if conflicting entities already exist.

## Heat-pump signal model

WaterSteer keeps these two concepts separate:

### DHW production available

The heat pump is allowed or able to produce DHW.

This does **not** mean it is currently heating DHW.

### DHW production active

The heat pump is actually producing DHW now.

This signal is optional and treated as an advanced enhancement because many heat pumps do not expose it. WaterSteer must remain functional without it.

## Architecture

The code is split into explainable components:

```text
coordinator.py
  -> Home Assistant I/O, persistence and update cycle

thermal_model.py
  -> standby loss, heating rate and thermal projection

usage_model.py
  -> DHW draw detection and weekday/weekend demand learning

demand_predictor.py
  -> 24-hour statistical demand forecast with optional local Random Forest backend

autonomy_model.py
  -> passive and demand-adjusted time-to-comfort prediction

horizon_optimizer.py
  -> demand-aware current intent across the rolling price horizon

controller.py
  -> deterministic temperature decisions and safety guards

capability_model.py
  -> select the best available safe-margin estimator

price_planner.py
  -> safe advisory planning, peak avoidance and precharge timing

actions.py
  -> physical output execution (future active-control step)
```

The learning models estimate system behaviour. They do not rewrite the controller.

> Learn the system, not the controller.

## Shadow price planning

WaterSteer includes an explainable advisory price planner. It actively identifies expensive price peaks and tries to bridge them safely by waiting through the peak or precharging before it when necessary.

The planner combines:

- current DHW temperature
- predicted autonomy
- autonomy confidence
- learned DHW heating rate
- current electricity price
- future electricity-price intervals
- a safety reserve before the predicted comfort deadline

It selects a safe charge window before the predicted margin expires, avoids detected price peaks, and may select a precharge window before a peak when that is required to bridge the expensive period.

Important safeguards:

- price planning is disabled while autonomy confidence is below the configured thermal-confidence threshold
- future price data must be available in a recognized Home Assistant attribute format
- the learned heating rate must be available before a timed charge window can be planned
- the planner keeps a reserve before the predicted comfort deadline
- reaching the comfort minimum always overrides price
- cheap electricity alone never creates a charge request when the normal DHW target is already satisfied
- clear price peaks are treated as periods to avoid whenever the safe margin allows it
- precharge before a peak is preferred when the available margin would otherwise expire inside the expensive period
- no Block, Normal, or Boost action is executed

Supported future-price attribute shapes currently include timestamped `raw_today` / `raw_tomorrow`, numeric `today` / `tomorrow` arrays, and timestamped `prices`, `price_data`, or `forecast` lists.

Example shadow reasoning:

```text
Current DHW temperature: 50.7 °C
Estimated time to comfort minimum: 14.5 h
Expected DHW usage before 17:00: low
Occupancy: away
Cheaper price window starts in 5 h
Thermal confidence: 72%

Price plan: price_hold
Reason: safe_to_wait_for_selected_price_window
Next planned charge: 14:00
Planning deadline: 16:35
```

The same temperature on a weekend with high learned usage probability may result in normal operation instead.

## Demand prediction and horizon optimization

WaterSteer now separates demand prediction from control.

The predictor extends the learned weekday/weekend profile to a 24-hour hourly forecast. An experimental local Random Forest backend exists in the code but is disabled: training ran on the Home Assistant event loop and no measurable benefit over the statistical profile has been shown yet.

The rolling horizon optimizer combines:

- safe DHW margin and its confidence
- current DHW temperature
- the 24-hour demand forecast
- explicit home/away state when available
- future electricity prices and detected price peaks
- the selected precharge window

The optimizer never allows ML to bypass the safety controller. Missing temperature or current price input fails open to `normal`.

Extra-hot-water `boost` is deliberately restrictive. It is only considered during an active peak-precharge window when the home is explicitly occupied, demand confidence is sufficient, current temperature is in the lower range, and normal precharge is estimated to be insufficient to bridge the expensive period with reserve.

## Active control

Physical Block / Normal / Boost actions are not executed unless a future active-control mode is explicitly enabled. With no active control selected, WaterSteer simply remains advisory.

Active control will only be introduced after:

- thermal decisions have been validated in advisory mode
- usage learning has been validated
- future-price planning is stable
- minimum runtime, cooldown and anti-cycling rules are implemented
- fail-safe recovery has been verified

See [ROADMAP.md](ROADMAP.md) for the detailed development plan.

## Design principles

WaterSteer shall be:

- local-first
- deterministic
- explainable
- conservative while learning
- manufacturer-independent where possible
- safe on sensor failure
- usable without occupancy data
- usable without an explicit DHW-active sensor
- usable without PumpSteer
- able to cooperate with PumpSteer through normal Home Assistant entities

WaterSteer shall not:

- replace the heat pump's internal safety systems
- replace legionella protection
- heat solely because electricity is cheap
- sacrifice minimum DHW comfort for savings
- use unexplained black-box decisions
- rapidly toggle heat-pump functions

## Project status

WaterSteer is under active development and should currently be treated as experimental advisory software.
