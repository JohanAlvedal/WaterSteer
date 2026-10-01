# WaterSteer Roadmap

This roadmap describes both implemented functionality and planned development.

## 0.1 — Foundation and safe shadow control

Status: **implemented / being validated**

- Home Assistant custom integration
- config flow
- options flow with reload
- standalone water-heater model
- heat-pump-integrated DHW model
- generic Boost / Block / Normal action configuration
- DHW temperature input
- electricity price input
- optional DHW availability signal
- optional DHW production-active signal
- diagnostics
- deterministic temperature classifier
- configurable Absolute / Comfort / Normal / Precharge thresholds
- `DHW allowed`, `DHW request`, and `Force request`
- fail-safe behaviour
- minimum thermal-confidence gate before any braking decision

### Safety rule

WaterSteer must not hold normal DHW production until the thermal-learning confidence reaches the configured threshold.

Default threshold:

```text
50%
```

## 0.2 — Thermal learning

Status: **implemented / collecting real-world data**

- persistent thermal history
- controlled five-minute sampling
- rolling 72-hour thermal window
- standby heat-loss estimation
- DHW heating-rate estimation
- heating-cycle inference without requiring a DHW-active sensor
- projected temperature one hour ahead
- estimated time to comfort minimum
- thermal confidence
- heating confidence
- filtering of implausible thermal segments

Next validation work:

- compare learned loss rate with real installations
- tune plausible loss/heating-rate bounds
- verify mixed-tank and stratified-tank behaviour
- improve projection beyond a fixed one-hour horizon

## 0.3 — Usage learning

Status: **implemented in first explainable version / validation next**

- detect likely DHW draws from rapid temperature drops
- persistent 42-day usage history
- separate weekday and weekend profiles
- time-of-day usage probability
- next expected usage window
- typical usage-drop estimation
- usage-learning confidence
- optional occupancy input
- reduced demand weighting while explicitly away
- no dependency on occupancy data

Planned improvements:

- distinguish small and large draws
- learn recurring morning/evening demand windows
- improve event grouping for long showers and repeated draws
- expose richer profile diagnostics
- optionally learn holiday/away behaviour

## 0.4 — Price planner

Status: **next major implementation**

The price planner will combine:

- current DHW temperature
- projected thermal decay
- time to comfort minimum
- learned usage probability
- next expected usage
- occupancy modifier
- heating-rate estimate
- expected charge duration
- current and future electricity prices

Planned entities:

```text
sensor.watersteer_next_charge
sensor.watersteer_expected_charge_duration
sensor.watersteer_planned_target
sensor.watersteer_price_window
```

Planned decisions:

```text
price_hold
price_charging
comfort_recovery
normal_operation
forced_boost
```

Rules:

- cheap electricity alone must never trigger heating
- comfort always overrides price
- low-confidence models must be conservative
- price hold is only allowed when thermal margin is sufficient
- learned usage risk must be considered before delaying DHW

## 0.5 — Active control

Status: **not yet enabled**

- execute generic Block action
- execute Normal action
- execute Boost action
- minimum runtime
- minimum hold duration
- cooldown
- anti-cycling
- command deduplication
- restore normal heat-pump operation after failure
- fail-open behaviour
- action result diagnostics

Active control must remain disabled until shadow planning is considered stable.

## 0.6 — PumpSteer cooperation

Status: **planned**

WaterSteer must remain independent from PumpSteer.

Optional cooperation will use normal Home Assistant entities.

Possible PumpSteer inputs:

```text
heating_demand
indoor_margin
braking
thermal_outlook
```

Possible WaterSteer outputs:

```text
dhw_demand
planned_dhw_start
expected_dhw_duration
dhw_active
```

Goal:

- avoid optional DHW precharge when building heating demand is high
- never delay DHW when the comfort floor is at risk

## 0.7 — Explainability and long-term diagnostics

Status: **planned**

- reason codes for every planner decision
- decision history
- learned-profile summaries
- daily DHW cycle count
- expected vs actual heating duration
- expected vs actual thermal decay
- savings estimates
- confidence trend
- planner quality diagnostics

## 1.0 — Stable release

Target characteristics:

- validated thermal learning
- validated usage learning
- future-price planning
- safe active control
- robust restart recovery
- complete diagnostics
- documented fail-safe behaviour
- HACS-ready public release
- stable configuration migration path
- comprehensive tests

## Long-term principle

WaterSteer should understand:

```text
WHEN will hot water probably be needed?
HOW MUCH useful hot water will remain?
WHEN is the safest and cheapest time to replenish it?
```

All optimization must remain subordinate to DHW comfort and system safety.
