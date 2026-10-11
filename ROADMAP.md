# WaterSteer Roadmap

This roadmap describes both implemented functionality and planned development.

## 0.1 — Foundation and safe advisory control

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

Implemented improvements:

- hybrid usage detection using both direct temperature drops and early recovery cycles
- infer DHW heating from temperature rise when no explicit DHW-active signal is available
- compare recovery timing against learned standby loss before inferring usage
- suppress duplicate recovery events after a recent direct draw
- expose direct vs recovery event diagnostics
- group consecutive temperature-drop segments into one draw event
- distinguish small, medium, and large draw impact
- use separate confidence for weekday and weekend learning
- expose a six-hour hourly demand forecast
- estimate expected thermal usage impact over the next six hours
- expose the next expected usage probability and typical impact
- classify near-term demand as low, medium, or high
- expose richer profile diagnostics

Next validation work:

- validate recovery-inferred events against known real DHW usage
- tune early-recovery thresholds from real installations
- validate draw-size thresholds against real installations
- validate weekday/weekend confidence growth
- tune probability and demand-level thresholds from real data
- improve recurring demand-window detection beyond one-hour buckets
- optionally learn holiday/away behaviour

## 0.4 — Capability-based safe margin

Status: **foundation implemented / cycle and simple estimators next**

- unified `safe_margin` interface for the planner
- thermal estimator preferred when temperature data is available
- weak usage learning no longer reduces strong thermal confidence
- usage adjustment only applied after its own confidence threshold
- cycle estimator interface reserved for installations without temperature
- simple estimator interface reserved for minimal-telemetry installations
- DHW temperature is optional in configuration
- standalone physical control is optional in configuration
- advisory operation is the default when no active control is selected
- simplified default Home Assistant entity surface
- advanced learning and diagnostic entities disabled by default
- unified `control_request`: `hold`, `normal`, `heat`, `force_heat`, `precharge`, or `boost`

### Thermal autonomy


Status: **implemented in advisory mode / validation next**

- passive autonomy from current DHW temperature and learned standby loss
- demand-adjusted autonomy from the six-hour learned usage forecast
- predicted DHW temperature after six hours
- autonomy confidence
- explicit prediction basis diagnostics
- demand adjustment only after minimum usage-learning confidence
- thermal-only fallback while usage learning is immature
- no physical control output from the autonomy model

Next validation work:

- compare predicted autonomy against real temperature trajectories
- tune the minimum usage-confidence threshold from real installations
- evaluate conservative handling of expected demand within hourly buckets
- extend beyond the current six-hour learned demand horizon

## 0.5 — Price planner and peak avoidance

Status: **advisory implementation in progress / field validation next**

The price planner combines:

- current DHW temperature
- projected thermal decay
- time to comfort minimum
- learned usage probability
- next expected usage
- occupancy modifier
- heating-rate estimate
- expected charge duration
- current and future electricity prices

Implemented entities:

```text
sensor.watersteer_dhw_price_plan_status
sensor.watersteer_next_planned_dhw_charge
sensor.watersteer_expected_dhw_charge_duration
sensor.watersteer_planned_dhw_target
sensor.watersteer_selected_dhw_charge_price
```

Advisory plan states:

```text
learning
unavailable
temperature_hold
price_hold
price_charge_window
peak_precharge
comfort_recovery
normal_operation
```

Rules:

- cheap electricity alone must never trigger heating
- comfort always overrides price
- low-confidence models must be conservative
- price hold is only allowed when thermal margin is sufficient
- learned usage risk must be considered before delaying DHW
- the selected charge window must fit before the predicted comfort deadline
- a safety reserve is kept before that deadline
- a learned DHW heating rate is required for timed price planning
- no physical control action is executed unless active control is explicitly enabled
- detect clear price peaks relative to the future-price baseline
- avoid planning normal charge windows inside detected peaks
- precharge before a peak when the safe margin would otherwise expire during the peak

Field-validation focus before active control:

- verify the selected price window against the actual price entity
- compare predicted charge duration with actual DHW heating cycles
- compare planning deadline with observed comfort-floor crossings
- watch for false `price_hold` decisions around real morning/evening draws
- verify behavior when tomorrow's prices are not published yet

## 0.5.1 — Demand predictor and rolling horizon optimizer

Status: **implemented in advisory form / validation next**

- 24-hour statistical DHW demand forecast
- weekday/weekend profile remains the deterministic fallback
- explicit occupancy modifier
- optional local Random Forest backend when scikit-learn is available and training history is sufficient
- automatic statistical fallback when ML is unavailable or immature
- rolling horizon policy combines safe margin, demand, occupancy, price plan and peak timing
- missing DHW temperature fails open to `normal`
- missing current price input fails open to `normal`
- future `peak_precharge` windows do not trigger early
- precharge is suppressed at or above the precharge target
- `precharge` means normal DHW production moved earlier in time
- `force_heat` means normal DHW heating now regardless of price
- `force_heat` latches critical recovery after the absolute minimum is reached and remains active until the comfort minimum recovers
- heat-pump integrations may map `force_heat` to their emergency/Extra Hot Water action
- extraordinary `boost` is a separate last-resort pre-peak intent
- boost requires explicit occupancy, trusted demand forecast and evidence that normal precharge cannot bridge the expensive block

Validation focus:

- compare 24-hour predicted demand with actual DHW use
- validate occupancy suppression during workday-away periods
- validate that precharge starts only inside the selected window
- validate boost remains rare and only appears in genuine high-risk peak scenarios
- compare statistical and ML backends once sufficient history is available

## 0.6 — Active control

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

Active control is a separate explicit mode. Advisory planning remains fully functional without selecting any physical control path.

## 0.7 — PumpSteer cooperation

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

## 0.8 — Explainability and long-term diagnostics

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
