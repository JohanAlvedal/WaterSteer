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

WaterSteer currently runs in **shadow mode**. It observes, learns, classifies, and exposes decisions, but does not execute physical DHW control yet.

### Configuration

- Select standalone water heater or heat-pump-integrated DHW
- Select DHW temperature sensor
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

WaterSteer now calculates DHW autonomy in shadow mode.

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

It detects likely hot-water draws from rapid temperature drops and builds separate time-of-day profiles for:

- weekdays
- weekends

The model currently learns:

- recent DHW usage detection
- grouped draw events, so a longer shower is not counted as several separate uses
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

## Current shadow decisions

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
| 40–45 °C | `comfort_recovery` | ON | OFF |
| 45–50 °C | `normal_operation` | OFF | OFF |
| >= 50 °C | `temperature_hold` | OFF | OFF |

A `temperature_hold` only becomes an actual WaterSteer `DHW allowed = OFF` shadow decision after the thermal-confidence gate has been satisfied.

## Home Assistant entities

Current entities include:

```text
sensor.watersteer_mode
sensor.watersteer_decision
sensor.watersteer_dhw_temperature

sensor.watersteer_standby_heat_loss
sensor.watersteer_heating_rate
sensor.watersteer_projected_temperature_in_1_hour
sensor.watersteer_estimated_time_to_comfort_minimum
sensor.watersteer_thermal_learning_confidence
sensor.watersteer_passive_dhw_autonomy
sensor.watersteer_predicted_dhw_autonomy
sensor.watersteer_predicted_dhw_temperature_in_6_hours
sensor.watersteer_dhw_autonomy_confidence

sensor.watersteer_dhw_usage_probability_next_6_hours
sensor.watersteer_expected_dhw_usage_impact_next_6_hours
sensor.watersteer_dhw_demand_level
sensor.watersteer_next_expected_dhw_usage
sensor.watersteer_typical_dhw_usage_drop
sensor.watersteer_usage_learning_confidence

binary_sensor.watersteer_dhw_allowed
binary_sensor.watersteer_dhw_request
binary_sensor.watersteer_force_request
binary_sensor.watersteer_dhw_usage_detected
```

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

autonomy_model.py
  -> passive and demand-adjusted time-to-comfort prediction

controller.py
  -> deterministic temperature decisions and safety guards

price_planner.py
  -> future price planning (next major step)

actions.py
  -> physical output execution (future active-control step)
```

The learning models estimate system behaviour. They do not rewrite the controller.

> Learn the system, not the controller.

## Planned price optimization

The next major planning layer will combine:

- thermal time-to-comfort
- learned usage probability
- weekday/weekend pattern
- optional occupancy
- future electricity prices
- learned heating duration

Example future reasoning:

```text
Current DHW temperature: 50.7 °C
Estimated time to comfort minimum: 14.5 h
Expected DHW usage before 17:00: low
Occupancy: away
Cheaper price window starts in 5 h
Thermal confidence: 72%

Decision: price_hold
Reason: sufficient thermal margin until cheaper period
```

The same temperature on a weekend with high learned usage probability may result in normal operation instead.

## Active control

Physical Block / Normal / Boost actions are intentionally not enabled yet.

Active control will only be introduced after:

- thermal decisions have been validated in shadow mode
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

WaterSteer is under active development and should currently be treated as experimental shadow-control software.
