# WaterSteer audit — October 2026

> **Historical document.** This audit describes the code as it was in
> October 2026. Phases 1–5 of the roadmap below have since been implemented
> and merged into `main` (PR #2): safety supervisor, single arbitration point
> with two physical levers, optional Active control, the simplified entity
> surface (sections 3–4), corrected thermal learning and the shadow price
> planner. Statements such as "no actuation" and the phase statuses in
> section 6 are therefore out of date, and the default maximum hold is now
> 12 h (see B18), not 6 h. See [ROADMAP.md](../ROADMAP.md) and the
> [README](../README.md) for the current state.

Scope: branch `feat/0.1-foundation` (50 commits ahead of `main`; `main` only
contains the 0.1 skeleton). Audit performed against commit `dd019af`.

## 1. Codebase audit

### What exists

| Module | Role | State |
| --- | --- | --- |
| `coordinator.py` | 30 s polling, persistence, glue for every model | Works, but is a 490-line "god function" that builds a ~110-key dict |
| `thermal_model.py` | Standby loss and heating rate from 5-min samples, 72 h window | Sound, explainable, persisted |
| `usage_model.py` | Draw detection (direct + recovery-inferred), weekday/weekend hourly profiles, 42 days | Sound, persisted; profile lookups are O(n) over all samples every cycle |
| `demand_predictor.py` | 24 h statistical forecast, optional Random Forest | Statistical path OK; ML path unsafe (see below) |
| `autonomy_model.py`, `capability_model.py` | Time until comfort minimum, "safe margin" | OK; cycle/simple estimators are interface stubs only |
| `price_planner.py` | Peak detection, cheapest window, precharge before peak | OK; peak detection breaks with negative median prices |
| `horizon_optimizer.py` | Picks the published intent | OK after fixes below |
| `controller.py` | Threshold classifier and confidence guard | OK after fixes below |
| `safety.py` | **New** — persistent safety supervisor | Added in this audit |

### What does not exist (despite configuration or docs implying it)

- **No actuation.** Boost / Block / Normal actions are collected in the config
  flow but never executed. All physical control (`switch.blockera_varmvatten`,
  `input_boolean.hp_extra_warm_water`) happens in external Home Assistant
  automations that read `sensor.watersteer_control_request`. Safety therefore
  depends on two layers: this integration *and* those automations.
- No Mode control entity. `sensor.watersteer_control_mode` is the constant
  string `advisory`.
- No iBoost / PreDBat / solar / Huawei input. `binary_sensor.predbat_iboost_active`
  is not referenced anywhere in the code.
- No legionella awareness. WaterSteer can request a hold while the heat pump's
  own legionella cycle is due. It does not block it physically, but an external
  automation that maps `hold` to `switch.blockera_varmvatten = ON` can.
- No savings calculation. `savings_vs_current` is a price difference in
  currency/kWh, not money saved.
- No `actions.py`, `switch.py`, `sv.json` although they are listed in docs.

### Bugs and weaknesses found

| # | Severity | Finding | Status |
| --- | --- | --- | --- |
| B1 | **Critical** | Invalid threshold ordering made the classifier return `safety_fallback` with no request and no force, while the optimizer continued to plan. Result: `hold` at 52 °C and **no `force_heat` at 38.9 °C**. | Fixed |
| B2 | **Critical** | Between absolute minimum and comfort minimum the only intent was `heat`, which on a heat pump means *unblock*. If the heat pump's own start threshold is lower, the tank keeps falling with no escalation until the absolute minimum. | Fixed (escalation) |
| B3 | High | Critical-recovery latch was in memory only; a restart between 40 and 45 °C dropped `force_heat` to `heat`. | Fixed (persisted) |
| B4 | High | No upper limit on continuous `hold`. | Fixed (`max_hold_hours`, default 6 h, then 60 min lockout) |
| B5 | High | Config-entry migration v1→v2 disabled `sensor.watersteer_thermal_learning_confidence`, which external automations use, while the README stated existing registry choices are preserved. | Fixed (v3 migration re-enables it only when WaterSteer disabled it) |
| B6 | High | Random Forest training and the `sklearn` import ran inside `_async_update_data`, i.e. on the event loop. scikit-learn is not in `requirements`, so the path was also effectively untested. | Disabled by default |
| B7 | Medium | `binary_sensor.watersteer_dhw_allowed` came from the temperature classifier while `control_request` came from the optimizer; they could disagree (e.g. allowed=off while request=normal). | Fixed: `dhw_allowed = control_request != "hold"` |
| B8 | Medium | Recorder load: `control_request` carries a 24-element forecast list, every binary sensor carries ~22 attributes including the live temperature, so each temperature change writes four large rows. | Fixed: attributes trimmed, forecasts and explanations not recorded |
| B9 | Low | `_find_next_peak` uses `median * 1.5`; with zero/negative prices every slot qualifies or none does. | Fixed: spread-based threshold |
| B10 | Low | Temperature sensors without `unit_of_measurement` are treated as missing → permanent `normal`, silently. | Surfaced: Safety entity and Status = Fallback |
| B11 | Low | Threshold warning would log every 30 s. | Fixed: logged once |
| B12 | **High** | Standby loss was the median of 5-minute steps. With a 0.1 °C sensor each step is 0 or 1.2 °C/h, so the model always reported 1.2 °C/h at 100 % confidence (true value ~0.3–0.8); with a 0.5 °C sensor it never learned. Autonomy was underestimated by 2–4×. | Fixed: fitted over cooling runs, tested at 0.1 and 0.5 °C resolution |
| B13 | Medium | A detected draw followed by an early reheat was counted twice (direct + recovery event) when the reheat came more than 60 min later. | Fixed |
| B14 | Low | Coordinator overrode `async_shutdown` without calling the base class, so refresh timers were not cancelled on unload. | Fixed |
| B15 | **High** | `heat` and `precharge` only meant *unblock*. On a heat pump that starts hot water far below the plan's target (closed-loop test: 42 °C), planned cheap charges did nothing, and the tank was later recovered by `force_heat` in expensive hours (47 % of heat in peak hours, minimum 38.6 °C). | Fixed: charges finish to target and use extra hot water when the pump does not start; 11 % of heat in peak hours, minimum 44.8 °C |
| B16 | Medium | No hysteresis around the normal target: hold and 0.5 °C charges alternated every hour (60 block changes in 4 days). | Fixed: hold hysteresis and minimum charge size (13 changes) |
| B17 | Medium | Charge windows and the simulation assumed heating starts the moment it is requested. Heat pumps need a while (compressor start, switching valve, finishing a heating cycle). | Fixed: start delay learned from real charges (default 20 min) and added to windows and simulation |
| B18 | **High** | Field data (IVT, 20 Oct): after a 6 h hold the block was released at 48.4 °C; waits were only allowed at or above the normal target, so the heat pump started by itself at 47.4 °C in the most expensive hour of the day (2.5–2.7 SEK/kWh) while the evening was 1.0 SEK/kWh and 11 h of margin remained. | Fixed: planned waits allowed down to comfort + 1.5 °C (planner deadline, shadow veto and supervisor still apply); default maximum hold 12 h. Replay of this installation: 1.99 → 1.17 SEK per heated °C |
| B19 | Medium | A planned charge stalled when the heat pump's own cycle stopped below the plan's target (51.7 °C vs 55 °C); WaterSteer kept "finishing" for up to 3 h without heating. | Fixed: stall detection requests extra hot water, and ends the charge if that does not help either |
| B20 | Low | Shadow veto flickered when the simulated minimum sat on the comfort limit (41 block changes in 4 simulated days). | Fixed: veto hysteresis |
| B21 | **High** | Field data (IVT, 1–6 Nov): "heat pump does not start by itself" was a one-way latch set after a single charge where the heat pump took more than 15 min (its real start delay is up to ~21 min). From then on every planned charge requested extra hot water from the first second, which on this model runs the immersion heater (0.19 °C/min, no compressor power vs 0.45 °C/min on the compressor), although the heat pump started by itself in 5 of 6 releases. | Fixed: rolling history of the last 6 charges, the heat pump always gets the learned start delay × 1.5 (15–45 min) first; option to never use extra hot water for planned charges |
| B22 | Medium | A cheap window only started a charge below normal target − 2 °C (48 °C), while the charge heats to 52.5 °C. The 02:30 window (0.97 SEK) was skipped at 49 °C and the charge fired at 05:50 when the tank crossed 48 °C, just before the morning peak. | Fixed: window charges start 1 °C below normal target (replay unchanged, field case charges in the cheap window) |
| B23 | Medium | The maximum hold released a warm tank on a timer: at 51.8 °C in the most expensive hour of the day, and the heat pump ran for 20 min for nothing. | Fixed: only time below the normal target counts towards the maximum hold |

## 2. The 38.9 °C incident

Replaying the decision chain with the code as it was:

| Tank | Configured thresholds valid | Published request |
| --- | --- | --- |
| 44–41 °C | yes | `heat` (unblock only) |
| ≤ 40 °C | yes | `force_heat` |
| 38.9 °C | **no** | `normal` — no force |
| 52 °C | **no** | `hold` |

So with valid default thresholds and a valid sensor, the integration itself
published `force_heat` at 40 °C. A drop to 38.9 °C without heating is then
explained by one of:

1. **Threshold or sensor problem (B1/B10)** — WaterSteer never published
   `force_heat`. Check the history of `sensor.watersteer_control_request` and
   `sensor.watersteer_mode` (`safety` means invalid inputs) at the time.
2. **Allow-only recovery (B2)** — the tank spent a long time in 40–45 °C with
   `heat`, the heat pump did not start on its own, and a draw took it from just
   above 40 °C to 38.9 °C before Extra hot water had any effect.
3. **Automation layer** — `force_heat` was published but the automation did not
   turn on `input_boolean.hp_extra_warm_water` or turn off
   `switch.blockera_varmvatten` (trigger missed after restart, condition on an
   entity that the v2 migration disabled (B5), iBoost condition, `for:` delay).

Points 1 and 2 are fixed in code. Point 3 can only be confirmed with the
automation YAML and the history from that day; the reference automation in
section 5 is designed to remove that class of failure.

## 3. Entity audit

Entity IDs below are the defaults generated from the translated names.
"Enabled" refers to the default for new installations.

| Entity | Enabled | Used by external automation | Purpose | Recommendation |
| --- | --- | --- | --- | --- |
| `sensor.watersteer_control_request` | yes | **yes** | Single control intent | **KEEP** — the control contract. Attributes trimmed to reason, override and safety fields over time |
| `sensor.watersteer_thermal_learning_confidence` | yes (re-enabled) | **yes** | Thermal model confidence | **KEEP** — becomes the primary *Learning* entity; usage/autonomy confidences become its attributes |
| `binary_sensor.watersteer_force_request` | yes | possibly | `control_request == force_heat` | KEEP for compatibility, then **MERGE** into Status; deprecate in 0.8 |
| `binary_sensor.watersteer_dhw_allowed` | yes | possibly | `control_request != hold` | KEEP for compatibility, **DEPRECATE** in 0.8 |
| `sensor.watersteer_mode` | yes | unknown | Only `learning` / `safety` | **MERGE** into Status; deprecate |
| `sensor.watersteer_control_mode` | yes | no | Constant `advisory` | **DEPRECATE**; replaced by a Mode `select` when active control exists |
| `sensor.watersteer_dhw_temperature` | yes | unknown | Copy of the source sensor | **DISABLE BY DEFAULT** for new installs (duplicate data in recorder) |
| `sensor.watersteer_safe_dhw_margin` | yes | no | Minutes until comfort minimum incl. demand | **KEEP**, renamed in UI to *Hot water forecast* (hours of hot water left); entity ID unchanged |
| `sensor.watersteer_dhw_price_plan_status` | yes | no | Planner state | **MERGE** into Status / Optimization |
| `sensor.watersteer_next_planned_dhw_charge` | yes | no | Next window start | **MERGE** into Optimization (`next_change` attribute) |
| `sensor.watersteer_decision` | no | no | Raw classifier | **INTERNALIZE** (diagnostics download) |
| `sensor.watersteer_standby_heat_loss` | no | no | °C/h | DISABLE BY DEFAULT, `entity_category: diagnostic` |
| `sensor.watersteer_heating_rate` | no | no | °C/h | DISABLE BY DEFAULT, diagnostic |
| `sensor.watersteer_projected_temperature_in_1_hour` | no | no | | **INTERNALIZE** |
| `sensor.watersteer_estimated_time_to_comfort_minimum` | no | no | Passive time to comfort | **MERGE** into Hot water forecast |
| `sensor.watersteer_passive_dhw_autonomy` | no | no | | **MERGE** into Hot water forecast |
| `sensor.watersteer_predicted_dhw_autonomy` | no | no | | **MERGE** into Hot water forecast |
| `sensor.watersteer_predicted_dhw_temperature_in_6_hours` | no | no | | **MERGE** (attribute) |
| `sensor.watersteer_dhw_autonomy_confidence` | no | no | | **MERGE** into Learning |
| `sensor.watersteer_safe_margin_confidence` | no | no | | **MERGE** into Learning |
| `sensor.watersteer_usage_learning_confidence` | no | no | | **MERGE** into Learning |
| `sensor.watersteer_expected_dhw_charge_duration` | no | no | | **INTERNALIZE** |
| `sensor.watersteer_planned_dhw_target` | no | no | | **INTERNALIZE** |
| `sensor.watersteer_selected_dhw_charge_price` | no | no | | **INTERNALIZE** |
| `sensor.watersteer_dhw_usage_probability_next_6_hours` | no | no | | **INTERNALIZE** |
| `sensor.watersteer_expected_dhw_usage_impact_next_6_hours` | no | no | | **INTERNALIZE** |
| `sensor.watersteer_dhw_demand_level` | no | no | low/medium/high | **MERGE** into Hot water forecast |
| `sensor.watersteer_next_expected_dhw_usage` | no | no | | **MERGE** into Hot water forecast |
| `sensor.watersteer_typical_dhw_usage_drop` | no | no | | **INTERNALIZE** |
| `binary_sensor.watersteer_dhw_request` | no | no | Raw classifier request | **DEPRECATE** |
| `binary_sensor.watersteer_usage_detected` | no | no | Recent draw | DISABLE BY DEFAULT, diagnostic |

"Used by external automation" is based on what is known; before any entity is
removed, all automations, scripts and dashboards must be searched for
`watersteer_`.

## 4. Target user-facing entity architecture

Five primary entities, everything else in a diagnostics download or disabled
diagnostic entities:

| Entity | Type | State | Key attributes |
| --- | --- | --- | --- |
| **Status** (new) | enum sensor | `learning`, `allowing`, `holding`, `heating`, `preheating`, `protecting`, `fallback` | `explanation` (one human sentence), `next_change` |
| **Control request** (existing) | enum sensor | `hold`, `normal`, `heat`, `force_heat`, `precharge`, `boost` | `reason`, `safety_override` — machine contract for automations, unchanged |
| **Hot water forecast** (existing `safe_margin`) | duration sensor | hours until comfort minimum | `demand_level`, `next_expected_usage`, `temperature_in_6h` |
| **Learning** (existing `thermal_learning_confidence`) | % sensor | thermal confidence | `usage_confidence`, `phase`, `days_observed` |
| **Safety** (new) | binary sensor, `problem` | on when degraded | `warnings` list: `dhw_temperature_unavailable`, `invalid_threshold_configuration`, `comfort_recovery_escalated`, `max_hold_duration_reached`, … |

An *Optimization* entity is deliberately postponed until a real cost
calculation exists (energy per °C from the learned heating rate × price
difference). Publishing a price difference as "savings" would be misleading.

A Mode `select` (Auto / Shadow / Manual / Off) belongs with active control
(0.6); today it would only expose one meaningful option.

Migration strategy: new entities are added first; old ones get a deprecation
note in the README and a repair issue one release before they are disabled;
entity IDs and unique IDs of kept entities never change.

## 5. Safety assessment

### Priority order (implemented in `safety.py`)

1. Missing temperature → `normal` (hand control back to the heat pump). Latch
   and timers are remembered, not reset.
2. Temperature ≤ absolute minimum → `force_heat`, latched until comfort
   minimum, persisted across restarts.
3. Below comfort minimum for `comfort_escalation_minutes` (default 45) without
   rising 0.5 °C above the lowest value seen → `force_heat` (escalation).
4. `hold` is never published below comfort minimum.
5. `hold` is limited to `max_hold_hours` (default 6 h), followed by 60 min of
   `normal`. Timer persisted across restarts.
6. Invalid thresholds → built-in defaults for protection, optimization
   suspended, `mode = safety`.

### Remaining risk — the automation layer

WaterSteer publishes intent; the automation performs it. The automation must:

- trigger on every state change of `sensor.watersteer_control_request` **and**
  on Home Assistant start, and re-apply the current state (idempotent);
- treat `unavailable` / `unknown` as `normal` → `switch.blockera_varmvatten`
  OFF;
- map `force_heat` → blockera OFF **and** `hp_extra_warm_water` ON, and turn
  `hp_extra_warm_water` OFF when the request leaves `force_heat`/`boost`;
- never put a condition on a WaterSteer diagnostic entity in the force path;
- let `force_heat` win over iBoost/PreDBat conditions.

Arbitration with external systems (proposed, not yet implemented):

| Priority | Source | Effect |
| --- | --- | --- |
| 1 | Heat pump internal safety / legionella | Never blocked by WaterSteer |
| 2 | WaterSteer `force_heat` | Overrides everything below |
| 3 | iBoost active (`binary_sensor.predbat_iboost_active`) | Counts as heating; WaterSteer avoids `precharge`/`boost` while active |
| 4 | WaterSteer `hold` / `precharge` / `heat` | Price optimization |
| 5 | Heat pump default | Fallback |

## 6. Roadmap

| Phase | Content | Status |
| --- | --- | --- |
| 1 | Audit | Done (this document) |
| 2 | Critical safety fixes | **Done** in this branch (B1–B7, B11) |
| 3 | Status + Safety entities, trim attributes, disable duplicate temperature entity for new installs, Basic/Advanced options split | Next |
| 4 | Verify persistent thermal learning against real history; precompute usage profile buckets | Next |
| 5 | Shadow Price Planner: simulate allow / block / force / precharge over 24 h with learned model and report expected cost and minimum temperature for each | Planned |
| 6 | Behavioural demand forecast validation (predicted vs actual draws) | Planned |
| 7 | Controlled live optimization: optional built-in actuation with deduplication, min run time, anti-cycling, iBoost arbitration | Planned — requires explicit authorization |
| 8 | Optional external ML (AppDaemon on NUC) only if it beats the statistical profile on held-out weeks | Evaluation only |

### ML evaluation criteria

The statistical weekday/weekend × hour profile is the baseline. An external
model (RandomForest, MLP) is only worth adding if, on at least four held-out
weeks, it lowers the Brier score of hourly draw probability *and* reduces the
number of comfort-floor crossings in the shadow simulation. SciPy/PuLP are a
better fit than ML for the planner itself: the 24–48 h horizon with hourly
slots is a small MILP that solves in milliseconds, but the current greedy
window search is close to optimal for a single tank and is far easier to
explain. Recommendation: keep the core statistical, revisit after phase 5
produces measurable baselines.
