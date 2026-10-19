# WaterSteer

WaterSteer is a local Home Assistant integration that heats your domestic hot water when electricity is cheap — without ever letting you run out of hot water.

It learns how your tank cools down, how fast it heats up and when your household uses hot water, and uses that together with upcoming electricity prices to decide when heating can wait and when it cannot.

> Comfort always wins. Cheap electricity alone never starts heating, and WaterSteer never holds heating when the tank is below your comfort temperature.

## What you see

| Entity | What it tells you |
| --- | --- |
| **Status** | What WaterSteer is doing right now, with a one-sentence explanation in the `explanation` attribute. |
| **Mode** | Advisory, Active control or Off (see below). |
| **Hot water remaining** | Hours until the tank reaches your comfort temperature, including expected use. |
| **Thermal learning confidence** | How well WaterSteer knows your tank. Price optimization starts at 50 % by default. |
| **Expected saving** | Simulated saving over the price horizon compared with letting the heat pump run on its own. Empty until WaterSteer has learned enough. |
| **Safety** | On when something needs attention (missing sensor, safety override, control problem). The `warnings` attribute says what. |
| **Control request** | The machine-readable decision for your own automations: `hold`, `normal`, `heat`, `force_heat`, `precharge`, `boost`. |

Status values:

| Status | Meaning |
| --- | --- |
| Learning | Still learning; the heat pump runs normally. |
| Normal operation | Nothing to optimize right now. |
| Holding heating | Enough hot water to wait for cheaper electricity. |
| Heating | Heating in a cheap period, or recovering comfort. |
| Preheating | Heating ahead of an expensive period. |
| Protecting hot water | The tank is too cold; extra hot water is requested. |
| Fallback | An input is missing or invalid; the heat pump runs on its own. |
| Off | WaterSteer is switched off. |

Everything else (learned loss rates, usage profiles, planner details) is available as disabled diagnostic entities and in the diagnostics download.

## Modes

| Mode | What WaterSteer does |
| --- | --- |
| **Advisory** (default) | Learns and publishes decisions. Switches nothing. |
| **Active control** | Switches the *Block hot water* and *Extra hot water* entities you selected. |
| **Off** | Releases everything and publishes `normal`. |

Active control only happens after you select it yourself. WaterSteer then:

- sends a command only when the entity is not already in the wanted state;
- unblocks and requests extra hot water immediately when the tank needs it;
- finishes a planned cheap charge to its target instead of stopping half-way;
- learns whether the heat pump starts hot water by itself when unblocked. Ground-source heat pumps usually do not, so after the first charge WaterSteer requests extra hot water at the start of every planned charge and every comfort recovery instead of waiting;
- learns how long the heat pump needs before the tank starts warming and includes that delay when choosing charge windows;
- blocks at most once every 10 minutes, so it never toggles the heat pump rapidly;
- never switches off extra hot water that you turned on yourself;
- releases the block and its own extra hot water when you change mode, reload the integration or stop Home Assistant.

If Home Assistant crashes, nothing can release the block. If your heat pump supports it, give the block function its own timeout.

## Setup

1. Install through HACS (custom repository) and restart Home Assistant.
2. Add the WaterSteer integration.
3. Choose heat pump or standalone water heater.
4. Select the hot water temperature sensor and the electricity price sensor. Future prices are read from common attributes (`raw_today`/`raw_tomorrow`, `today`/`tomorrow`, `prices`, `forecast`). Optionally select an occupancy entity and an "other heat source" entity such as an iBoost.
5. Check the temperature limits (defaults below).
6. Optionally select the switch that blocks hot water and the switch that starts extra hot water.

Leave Mode on Advisory for the first days and watch Status and Hot water remaining.

### Temperature limits

| Limit | Default | Meaning |
| --- | --- | --- |
| Absolute minimum | 40 °C | At or below: extra hot water now, until the comfort minimum is reached again. |
| Comfort minimum | 45 °C | Below: heating is never held, regardless of price. |
| Normal target | 50 °C | At or above: hot water is sufficient, heating may wait for cheaper electricity. |
| Precharge target | 55 °C | Target when heating ahead of an expensive period. |
| Maximum continuous hold | 6 h | After this, normal operation for at least one hour. |
| Comfort recovery escalation | 45 min | If the tank stays below comfort this long without warming, extra hot water is requested. |

## Safety rules

Every decision passes a safety supervisor last. It can only make a decision safer:

| Situation | Result |
| --- | --- |
| Temperature sensor unavailable | Normal operation; the heat pump decides. |
| At or below absolute minimum | Extra hot water until the comfort minimum is reached. Survives restarts. |
| Below comfort minimum without warming | Extra hot water after the escalation time. |
| Hold requested below comfort minimum | Rejected. |
| Hold longer than the maximum | Released, then normal operation for one hour. |
| Shadow simulation predicts the plan would drop below comfort | No hold. |
| Temperature limits not in order | Built-in safe limits are used; price optimization is paused. |
| Other heat source active | Optional preheating is skipped; safety heating still happens. |
| Not enough learning yet | No holding at all. |

WaterSteer does not replace the heat pump's own safety functions or legionella program. A hold can delay a scheduled legionella cycle by up to the maximum hold time.

## Using your own automations instead of Active control

Keep Mode on Advisory and mirror the two levers that WaterSteer publishes as attributes of `sensor.watersteer_control_request`: `block` and `extra_hot_water`. (The same values are available as the *DHW allowed* and *Extra hot water request* binary sensors, disabled by default.) Use the levers rather than mapping the request names yourself: `heat` and `precharge` also need extra hot water when the heat pump does not start on its own.

A robust automation:

- triggers on every change **and** on Home Assistant start;
- treats an unavailable WaterSteer as "not blocked, no extra hot water";
- has no extra conditions in the extra-hot-water path.

```yaml
automation:
  - alias: WaterSteer levers
    mode: queued
    triggers:
      - trigger: state
        entity_id: sensor.watersteer_control_request
        attribute: block
      - trigger: state
        entity_id: sensor.watersteer_control_request
        attribute: extra_hot_water
      - trigger: state
        entity_id: sensor.watersteer_control_request
      - trigger: homeassistant
        event: start
    actions:
      - variables:
          block: "{{ state_attr('sensor.watersteer_control_request', 'block') is true }}"
          extra: >-
            {{ state_attr('sensor.watersteer_control_request', 'extra_hot_water') is true }}
      - action: "switch.turn_{{ 'on' if block else 'off' }}"
        target:
          entity_id: switch.blockera_varmvatten
      - action: "input_boolean.turn_{{ 'on' if extra else 'off' }}"
        target:
          entity_id: input_boolean.hp_extra_warm_water
```

Do not run such an automation and Active control at the same time.

## How it works

```text
temperature, prices, occupancy
        │
thermal_model      standby loss (linear or Newton cooling, validated), heating rate
usage_model        draws, weekday/weekend hourly profiles
demand_predictor   24 h expected demand
price_planner      cheapest safe window, price peaks, precharge
horizon_optimizer  proposed intent
shadow_planner     simulates normal vs plan; vetoes unsafe holds; expected saving
safety             latch, escalation, hold limits, fail-open; finish and assist charges
decision           one final output: intent, block, extra hot water, status
actuator           optional Active control
```

Learning, planning, safety and control are separate, deterministic and explainable. There is no machine learning in the control path.

See [ROADMAP.md](ROADMAP.md) for status and [docs/AUDIT.md](docs/AUDIT.md) for the design audit.

## Upgrading from earlier development versions

- Existing entities keep their entity IDs and your enabled/disabled choices. New installations show a smaller set by default.
- `sensor.watersteer_thermal_learning_confidence` is re-enabled if an earlier version disabled it.
- `binary_sensor.watersteer_dhw_allowed` is off exactly when `control_request` is `hold`; `binary_sensor.watersteer_force_request` is on exactly when it is `force_heat`.
- The control request and lever sensors carry fewer attributes; details moved to diagnostics.
- The unused Boost/Block/Normal action selectors were replaced by entity selectors.
- Standby loss is now learned from whole cooling runs. Earlier versions reported about 1.2 °C/h for any sensor with 0.1 °C resolution; the stored history is re-evaluated at the first update, so expect a lower, correct value straight away.
- With Home Assistant set to Swedish, new installations get Swedish names and entity IDs, except `control_request` and `thermal_learning_confidence`, which keep their English IDs for compatibility.
