# WaterSteer

## Smart varmvattenoptimering för Home Assistant

WaterSteer är en Home Assistant custom integration för intelligent styrning och optimering av tappvarmvatten i värmepumpar.

Målet är att flytta varmvattenproduktionen till ekonomiskt och termiskt lämpliga tidpunkter utan att försämra varmvattenkomforten eller störa husets uppvärmning mer än nödvändigt.

WaterSteer ska kunna lära sig hur varmvattenberedaren beter sig över tid, upptäcka användningsmönster och planera framtida varmvattenproduktion baserat på:

- aktuell varmvatten­temperatur
- temperaturens förändring över tid
- varmvattenanvändning
- värmarens uppvärmningshastighet
- elpris
- kommande elpriser
- förväntad varmvattenanvändning
- eventuell konkurrens med husvärmen
- värmepumpens aktuella driftläge

WaterSteer ska vara fullt lokal och inte vara beroende av någon molntjänst.

---

# Grundprincip

WaterSteer ska inte vara en vanlig timer.

Systemet ska försöka besvara frågan:

> När behöver varmvattenberedaren nästa gång laddas, och när är den bästa tidpunkten att göra detta?

Det innebär att billig el i sig aldrig ska vara ett tillräckligt skäl för att värma varmvatten.

Om det redan finns tillräckligt med lagrad varmvattenenergi ska WaterSteer vänta även om elpriset är lågt.

På motsvarande sätt ska WaterSteer kunna värma varmvatten även under ett dyrt elpris om varmvattenkomforten annars riskerar att bli för låg.

---

# Problem som WaterSteer löser

I många bergvärmepumpar används samma kompressor för:

- husvärme
- tappvarmvatten

Varmvattenproduktionen konkurrerar därför med husets uppvärmning.

Att endast avblockera varmvatten innebär dessutom inte nödvändigtvis att värmepumpen börjar producera varmvatten direkt.

Många värmepumpar har däremot funktioner som exempelvis:

- Extra varmvatten
- Temporary luxury
- DHW boost
- Hot water boost
- Force DHW

WaterSteer ska kunna använda sådana funktioner för att aktivt starta varmvattenproduktion när det är ekonomiskt och termiskt lämpligt.

---

# Styrnivåer

WaterSteer bör stödja två separata styrsignaler.

## DHW Allow / Block

Bestämmer om normal varmvattenproduktion är tillåten.

Exempel:

```text
ALLOW_DHW = ON
ALLOW_DHW = OFF
```

Detta kan användas för värmepumpar där Home Assistant kan blockera varmvattenproduktion.

## DHW Force / Boost

Begär att värmepumpen aktivt börjar producera varmvatten.

Exempel:

```text
FORCE_DHW = ON
```

eller genom:

```text
button.press
select.select_option
switch.turn_on
number.set_value
```

beroende på värmepump och integration.

WaterSteer ska därför inte vara låst till en specifik tillverkare.

---

# Generiskt Action-system

WaterSteer ska kunna konfigureras mot olika typer av Home Assistant-entiteter och actions.

Exempel:

```text
DHW Boost Action
DHW Block Action
DHW Normal Action
```

Action kan exempelvis vara:

```text
switch
button
select
number
service
script
```

Det gör integrationen möjlig att använda med exempelvis:

- Nibe
- IVT
- Bosch
- Thermia
- CTC
- Mitsubishi
- Panasonic
- andra värmepumpar där Home Assistant har tillgång till motsvarande funktioner

---

# Temperaturmodell

WaterSteer ska kontinuerligt observera varmvattenberedaren.

Tre grundläggande beteenden ska läras.

## Standby loss

Hur snabbt varmvattenberedaren tappar temperatur när inget varmvatten används.

Exempel:

```text
58.0 °C
57.6 °C
57.2 °C
56.8 °C
```

Ger ungefär:

```text
standby_loss = 0.4 °C/h
```

---

# Usage drop

Snabba temperaturfall ska identifieras som sannolik varmvattenanvändning.

Exempel:

```text
57 °C → 49 °C på 12 minuter
```

Detta ska inte blandas ihop med normal värmeförlust från tanken.

WaterSteer ska registrera:

```text
timestamp
temperature_before
temperature_after
drop
duration
```

---

# Heating rate

När värmepumpen producerar varmvatten ska WaterSteer observera hur snabbt temperaturen återhämtas.

Exempel:

```text
49 °C → 58 °C på 80 minuter
```

Det ger systemet möjlighet att uppskatta hur långt före ett framtida behov som laddningen måste börja.

---

# Användningsinlärning

WaterSteer ska över tid bygga ett användningsmönster.

Det behövs ingen black-box Machine Learning.

Ett statistiskt rullande schema är tillräckligt och gör besluten förklarbara.

Exempel:

```text
Weekdays

05:30   8 %
06:00  34 %
06:30  82 %
07:00  91 %
07:30  46 %
08:00  12 %

17:00  25 %
18:00  58 %
19:00  76 %
20:00  41 %
```

Systemet kan därmed börja förstå att det normalt behövs mycket varmvatten omkring exempelvis 06:30–07:30.

Helger och vardagar bör kunna få olika profiler.

---

# Prognos

WaterSteer ska kunna beräkna förväntad framtida VVB-temperatur.

Förenklad princip:

```text
predicted_temperature =
current_temperature
- expected_standby_loss
- expected_usage
+ planned_heating
```

Exempel:

```text
Current temperature:     58 °C
Standby loss:            0.7 °C/h
Time until shower:       5 h
Expected usage drop:    10 °C

58 - (5 × 0.7) - 10
= 44.5 °C
```

Om komfortgränsen är 48 °C vet WaterSteer att varmvatten behöver produceras innan dess.

---

# Prisoptimering

WaterSteer ska använda framtida elpriser för att välja bästa laddningstid.

Planeringshorisonten bör vara cirka:

```text
12–24 timmar
```

snarare än PumpSteers kortare värmeregleringshorisont.

Exempel:

```text
04:00–06:00   cheap
06:00–09:00   expensive

Expected DHW usage: 06:45
Predicted temp:      45 °C
Required minimum:    48 °C
Heating time:        55 min
```

WaterSteer kan då planera:

```text
Start DHW boost: 04:45
Estimated finish: 05:40
```

---

# Temperaturgränser

WaterSteer bör skilja mellan olika nivåer.

Exempel:

```text
Absolute minimum
Comfort minimum
Normal target
Precharge target
```

Princip:

```text
Temperature < absolute minimum
→ Immediate DHW production

Temperature < comfort minimum
→ High DHW priority

Comfort minimum – normal target
→ Planner decides

Temperature >= normal target
→ Normally wait

Cheap electricity + expected future demand
→ Optional precharge
```

De exakta temperaturerna ska vara konfigurerbara och beroende av värmepump och installation.

WaterSteer ska inte ersätta värmepumpens egna säkerhets- eller legionellafunktioner.

---

# Driftlägen

WaterSteer bör ha tydliga och förklarbara driftlägen.

## learning

Systemet samlar data och bygger baslinje.

Ingen avancerad prisoptimering görs ännu.

## idle

Tillräckligt varmvatten finns.

Ingen laddning behövs.

## charging

Normal varmvattenproduktion behövs.

## price_charging

WaterSteer tidigarelägger varmvattenproduktionen eftersom ett lämpligt billigt prisfönster finns.

## price_hold

Tillräckligt varmvatten finns för att vänta igenom ett dyrt prisfönster.

## comfort_recovery

Temperaturen eller prognosen är för låg.

Komfort prioriteras före elpris.

## forced_boost

WaterSteer har aktivt begärt exempelvis Extra varmvatten.

## safety

Nödvändiga sensorer saknas eller innehåller ogiltiga värden.

Prisoptimering avbryts och värmepumpens normala styrning får ta över.

---

# Home Assistant-entiteter

Första versionen bör åtminstone exponera:

```text
sensor.watersteer_mode

sensor.watersteer_dhw_temperature

sensor.watersteer_predicted_temperature

sensor.watersteer_heat_loss

sensor.watersteer_heating_rate

sensor.watersteer_next_expected_usage

sensor.watersteer_next_charge

sensor.watersteer_expected_charge_duration
```

Binära sensorer:

```text
binary_sensor.watersteer_dhw_request

binary_sensor.watersteer_force_request

binary_sensor.watersteer_usage_detected
```

Senare kan även exempelvis följande läggas till:

```text
sensor.watersteer_usage_probability

sensor.watersteer_daily_dhw_cycles

sensor.watersteer_saved_cost

sensor.watersteer_learning_confidence
```

---

# Förklarbara beslut

Precis som PumpSteer ska WaterSteer alltid kunna visa varför ett beslut fattades.

Exempel:

```text
Mode: PRICE_CHARGING

DHW temperature: 52.4 °C
Normal target: 55 °C
Comfort minimum: 48 °C

Predicted temperature at 07:00:
45.8 °C

Expected usage:
06:40–07:20

Current electricity price:
0.42 SEK/kWh

Price 06:00–09:00:
1.85 SEK/kWh

Estimated heating time:
52 minutes

Decision:
Start DHW boost now.
```

---

# Learning

WaterSteer får lära sig fysiska egenskaper och användningsmönster.

Exempel på värden som får läras:

```text
standby_loss
heating_rate
typical_usage_drop
usage_probability
typical_charge_duration
```

Men själva beslutsreglerna ska vara deterministiska och begripliga.

WaterSteer ska alltså:

> learn the system, not rewrite the controller.

---

# Inlärningsperiod

Vid en ny installation bör WaterSteer initialt observera systemet.

Exempel:

```text
0–24 h
Basic temperature observation

1–7 days
Initial heat-loss and heating-rate estimation

7–30 days
Usage pattern becomes increasingly reliable

30+ days
Mature usage profile
```

Prisoptimering behöver inte vara helt avstängd under hela perioden, men systemet ska vara försiktigare när confidence är låg.

---

# Samarbete med PumpSteer

WaterSteer ska fungera helt fristående.

PumpSteer ska inte vara ett krav.

Om båda integrationerna finns kan de däremot samarbeta.

## PumpSteer kan exempelvis exponera

```text
heating_demand
indoor_margin
braking
thermal_outlook
```

## WaterSteer kan exponera

```text
dhw_demand
planned_dhw_start
expected_dhw_duration
dhw_active
```

WaterSteer kan då undvika onödig varmvattenförvärmning när huset redan har stort värmebehov.

Exempel:

```text
Indoor temperature: 20.1 °C
Target:             21.0 °C
Outdoor:           -15 °C

Heating demand: HIGH
DHW urgency: LOW
```

Resultat:

```text
Delay optional DHW precharge
```

Men:

```text
DHW projected below comfort minimum
```

ska fortfarande kunna ge varmvattenproduktion.

---

# Viktig arkitekturprincip

PumpSteer och WaterSteer ska inte direkt modifiera varandras interna regulatorer.

Kommunikation sker genom normala Home Assistant-entiteter.

Det ger:

- lös koppling
- enklare felsökning
- möjlighet att använda WaterSteer utan PumpSteer
- möjlighet att använda PumpSteer utan WaterSteer
- kompatibilitet med fler värmepumpar
- enklare framtida utveckling

---

# Föreslagen arkitektur

```text
                         Home Assistant
                               │
                    Electricity price data
                               │
                 ┌─────────────┴─────────────┐
                 │                           │
            PumpSteer                   WaterSteer
                 │                           │
        Space heating control          DHW planning
                 │                           │
       Fake outdoor temperature      Allow / Block / Boost
                 │                           │
                 └─────────────┬─────────────┘
                               │
                           Heat pump
                               │
                  ┌────────────┴────────────┐
                  │                         │
             Space heating                DHW
```

---

# Föreslagen kodstruktur

```text
custom_components/watersteer/
│
├── __init__.py
├── manifest.json
├── const.py
├── config_flow.py
├── coordinator.py
│
├── sensor.py
├── binary_sensor.py
├── switch.py
│
├── dhw_model.py
├── usage_model.py
├── price_planner.py
├── controller.py
├── actions.py
│
├── diagnostics.py
├── translations/
│   ├── en.json
│   └── sv.json
│
└── strings.json
```

Ansvarsområden:

```text
dhw_model.py
→ Tank temperature behaviour

usage_model.py
→ Usage event detection and usage history

price_planner.py
→ Electricity price planning

controller.py
→ Final decision/state machine

actions.py
→ Generic Home Assistant output actions

coordinator.py
→ Data collection and update cycle
```

---

# MVP – första fungerande version

Första versionen ska hållas relativt enkel.

## Inputs

- DHW temperature sensor
- electricity price sensor
- future electricity prices

Optional:

- compressor status
- DHW active
- heating active

## Learning

- passive heat loss
- heating rate
- detect large DHW usage events

## Planner

- 12–24 h price lookahead
- predicted DHW temperature
- comfort protection
- cheap-period precharge

## Outputs

```text
binary_sensor.watersteer_dhw_request

binary_sensor.watersteer_force_request

sensor.watersteer_mode

sensor.watersteer_predicted_temperature
```

## Control

Configurable Home Assistant action for:

```text
DHW boost
```

---

# Versionplan

## 0.1

Foundation

- HA integration
- config flow
- DHW temperature
- electricity price
- basic entities
- diagnostics

## 0.2

Thermal model

- heat-loss estimation
- heating-rate estimation
- detect heating cycles
- detect likely usage

## 0.3

Price planner

- future prices
- predicted temperature
- cheap-period charging
- comfort floor

## 0.4

Active control

- generic DHW boost action
- optional DHW block
- minimum runtime
- cooldown
- anti-cycling

## 0.5

Usage learning

- weekday/weekend profiles
- time-of-day usage probability
- expected consumption events
- confidence measurement

## 0.6

PumpSteer cooperation

- heating demand input
- indoor comfort margin
- DHW/heating conflict handling

## 1.0

Stable release

- full diagnostics
- restore after HA restart
- explainable decision attributes
- translations
- HACS compatible
- documented safety behaviour

---

# Design principles

WaterSteer shall be:

- local-first
- deterministic
- explainable
- manufacturer-independent where possible
- safe on sensor failure
- conservative when learning confidence is low
- able to operate without PumpSteer
- able to cooperate with PumpSteer when installed

WaterSteer shall not:

- replace the heat pump's internal safety systems
- replace legionella protection
- force heating solely because electricity is cheap
- sacrifice minimum DHW comfort for price savings
- use unexplained black-box decisions
- continuously toggle heat-pump functions

---

# Project goal

The long-term goal is that WaterSteer should understand three things:

```text
WHEN will hot water be needed?

HOW MUCH stored hot water will probably remain?

WHEN is the best time to replenish it?
```

The controller can then move DHW production in time while respecting both hot-water comfort and the heat pump's need to heat the building.

In combination:

```text
PumpSteer  = smart space-heating storage
WaterSteer = smart hot-water storage
```

Together they can optimize two thermal energy stores that compete for the same heat-pump compressor, while remaining independent Home Assistant integrations.
