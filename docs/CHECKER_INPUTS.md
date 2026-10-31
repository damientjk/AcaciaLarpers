# Checker, cost and fallback inputs (Person B contract)

`models.py` leaves `Scenario.simulated[agent]` as a free dict. This file lists the keys that
`checker.py`, `costs.py` and `fallback.py` read from it. Person A's `scenario.py` must produce
them; everything here is **simulated** state and must be labelled so in the UI.

A missing or malformed required key **fails** the rule that needs it (the `CheckResult` says
`Cannot evaluate: ...`). Nothing passes silently.

## Time values

Every clock value is `"HH:MM"` on the scenario's `issue_time` date, in one local time zone.
A value more than 12 h before the issue time rolls to the next day (overnight arrivals).
Full ISO datetimes (`2015-01-01T20:40`) are also accepted. `Candidate.landing`,
`gate_arrival` and `gate_release` use the same convention.

## `simulated.atc`

| Key | Type / unit | Used by |
|---|---|---|
| `baseline_eta` | `"HH:MM"`: simulated ETA at issue time with no extra holding | costs (delay), heuristic |
| `runway` | `{"id", "capacity_per_interval": int, "interval_min": int}`; intervals are fixed bins from midnight | R-1 |
| `slots` | list of `"HH:MM"` arrival slots offered to this flight | R-1 |
| `other_arrivals` | list of `{"callsign", "time": "HH:MM", "wake_category"}`; **never** includes the focal flight | R-1, W-1 |
| `wake_category` | focal aircraft category, e.g. `"M"` | W-1 |
| `wake_separation_s` | `{"LEADER-FOLLOWER": seconds}`; an absent pair fails W-1 | W-1 |
| `closed_taxiways` | list of segment ids | T-1 |
| `taxi_routes` | `{gate: [segment, ...]}` runway-to-gate route per gate | T-1 |
| `taxi_in_min` | int; if present G-3 requires `gate_arrival == landing + taxi_in_min` | G-3, heuristic |
| `resequence_options` | list of `{"slot": "HH:MM", "moves": [{"callsign", "to": "HH:MM"}]}` the ATC agent may offer | ATC_EARLIER_SLOT |

## `simulated.pilot`

| Key | Type / unit | Used by |
|---|---|---|
| `fuel_at_baseline_eta_kg` | kg of fuel on board at the baseline ETA | F-1 |
| `holding_burn_kg_per_min` | kg per minute of extra holding | F-1, costs |
| `reserve_kg` | scenario reserve in kg (a parameter inspired by 14 CFR 121.639, **not** a compliance figure) | F-1 |
| `max_extra_holding_min` | pilot preference bound (not a hard rule); raised by PILOT_EXTRA_HOLDING up to the fuel-safe limit | agents |
| `aircraft_type` | display only | UI |

## `simulated.ground`

| Key | Type / unit | Used by |
|---|---|---|
| `aircraft_class` | e.g. `"narrowbody"`; explicit, never guessed from the tail number | G-1 |
| `gates` | `{gate: {"classes": [...], "bookings": [{"id", "flight", "start", "end"}]}}` | G-1, G-2 |
| `own_booking_id` | optional; a booking with this id is this flight's replaced plan and is excluded from G-2 | G-2 |
| `gate_buffer_min`, `turnaround_min` | optional overrides of `config.simulation` | G-2, G-3 |
| `planned_gate` | gate of the original plan | heuristic |
| `crews` | list of `{"id", "gates": [...], "shift_start", "shift_end", "regular_end", "assignments": [{"id", "gate", "start", "end"}], "can_reassign_to": [...]}` | C-1, costs (overtime) |
| `connections` | list of `{"flight", "departure": "HH:MM", "min_connect_min", "pax"}` | costs (missed) |

## Candidate

The agreed `models.Candidate`. `gate_arrival` and `gate_release` are authoritative; G-3 verifies
`gate_release - gate_arrival >= turnaround_min`, `gate_arrival >= landing` (`== landing + taxi_in_min`
when declared) and `landing >= issue_time`. `extra_holding_min` must be a non-negative integer.

## Concessions (`checker.apply_concessions`)

The source scenario is never mutated. `apply_concessions(scenario, concessions, state_version)` returns
`AdjustedState(scenario, state_version, applied, rejected)`; the version increases by one when at
least one concession changed the state. Recheck every candidate on the new scenario.

| Concession | `target` | Effect on the copy |
|---|---|---|
| `ATC_EARLIER_SLOT` | `"HH:MM"` listed in `atc.resequence_options` | slot added to `atc.slots`; declared neighbour moves applied to `other_arrivals`. R-1/W-1 still enforce capacity and spacing. |
| `GROUND_REASSIGN_CREW` | gate id | each crew with that gate in `can_reassign_to` gains it in `gates`. Assignments are kept, so an overlapping job still fails C-1. |
| `PILOT_EXTRA_HOLDING` | `"12"` or `"12 min"` | `pilot.max_extra_holding_min = min(target, fuel-safe limit)`. Preference only; F-1 stays the hard rule. |

A concession whose target is not declared in the state is reported in `rejected` and changes nothing.

## Costs (`costs.py`)

| Component | Unit | Formula |
|---|---|---|
| `delay_min` | min | `landing - atc.baseline_eta` (signed; earlier than baseline is negative). The historical recorded delay is never added. |
| `holding_fuel_kg` | kg | `extra_holding_min x holding_burn_kg_per_min` |
| `overtime_min` | min | service minutes after the serving crew's `regular_end` (first eligible crew by id) |
| `missed_connections` | pax | sum of `pax` on connections with `departure < gate_arrival + min_connect_min` |
| `total_usd` | USD-equivalent score | sum of component x `config.costs` weight |

`costs.breakdown(candidate, scenario, weights)` returns raw, unit, weight and weighted value per
component for the UI. `inputs.delay_vs_schedule_min` is also reported for display.

## Calls teammates make

```python
import checker, costs, fallback
cfg = checker.load_config()
checks = checker.check_all(candidates, scenario, cfg)            # {id: [CheckResult x 8]}
cost_map = costs.cost_all(candidates, scenario, cfg["costs"])    # {id: CandidateCost}
best = fallback.solve(candidates, checks, cost_map)              # id or None (escalate)
block = fallback.decide(candidates, checks, cost_map)            # log-ready dict, 'outcome' = fallback | escalation
adj = checker.apply_concessions(scenario, offers_concessions, state_version=1)
checks_after = checker.check_all(candidates, adj.scenario, cfg)  # recheck on the new version
baseline = fallback.heuristic(scenario, cfg)                     # heuristic block for the log
result = fallback.run_pipeline(candidates, scenario, cfg)        # all of the above, no LLM
```
