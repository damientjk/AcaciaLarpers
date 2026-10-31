# Checker, cost and fallback inputs (Person B)

`models.py` leaves `Scenario.simulated[agent]` as a free dict. This file lists the keys that
`checker.py`, `costs.py` and `fallback.py` read from the state that `scenario.py` (Ashvin) emits, and
how each rule and cost uses them. Everything here is **simulated** state and is labelled so in the UI.

A missing or malformed required key **fails** the rule that needs it (the `CheckResult` explanation
starts with `Cannot evaluate: ...`). Nothing passes silently. The checker never raises on bad state.

## Time values

ISO datetimes (`2015-01-06T20:22`, naive, destination local time) as scenario.py writes them. `"HH:MM"`
is also accepted and resolved on the `issue_time` date, rolling to the next day when more than 12 h
before the issue time. `Candidate.landing`, `gate_arrival` and `gate_release` are `"HH:MM"`.

## `simulated.atc`

| Key | Used by |
|---|---|
| `base_eta` | costs (delay), G-3 (holding = landing - base ETA), heuristic |
| `own_wake` (`heavy` / `large` / `small`) | W-1 |
| `slots[]` with `slot_id`, `time`, `occupant`, `occupant_wake`, `occupant_flexible` | R-1 (slot must exist and be unoccupied), W-1 (last occupied slot before landing) |
| `runway_capacity_per_hour` | R-1 (occupied slots in the landing's clock hour + this flight) |
| `closed_taxiways` | T-1 |

W-1 reads the separation profile from `config.simulation.wake_separation_s` (seconds, keyed
`leader-follower`). An absent pair fails.

## `simulated.pilot`

| Key | Used by |
|---|---|
| `fuel_on_board_kg`, `cruise_burn_kg_per_min` | F-1: fuel at base ETA = on board - cruise burn x (base ETA - issue time) |
| `holding_burn_kg_per_min` | F-1, costs (holding fuel) |
| `reserve_kg` | F-1 (equality passes). A scenario parameter inspired by 14 CFR 121.639, not a compliance figure |
| `connections[]` with `departure_time`, `min_connect_min`, `passengers` | costs (missed connections) |
| `fuel_safe_holding_min`, `comfortable_holding_min` | agents and `scenario.apply_concessions` only |

## `simulated.ground`

| Key | Used by |
|---|---|
| `aircraft_class` (`regional` < `narrowbody` < `widebody`) | G-1 |
| `gates[]` with `gate_id`, `max_class`, `taxi_route`, `taxi_in_min`, `occupancy[]{start,end,occupant}` | G-1, T-1, G-3, G-2 |
| `turnaround_min`, `gate_buffer_min` (fallback: `config.simulation`) | G-3, G-2, costs (overtime window) |
| `crews[]` with `crew_id`, `assigned_gate`, `shift_start`, `shift_end` (+ `reassigned_from` after a move) | C-1, costs (overtime) |
| `planned_gate`, `next_departure` | heuristic |

## Rules

| Rule | Predicate (equality passes) |
|---|---|
| F-1 | fuel at base ETA - extra_holding x holding burn >= reserve_kg |
| W-1 | seconds from the last occupied slot before landing >= profile[leader wake - own wake] |
| R-1 | landing is an offered slot, that slot is unoccupied, occupied slots in the clock hour + 1 <= capacity |
| T-1 | gate taxi_route has no segment in closed_taxiways |
| G-1 | gate max_class rank >= aircraft_class rank |
| G-2 | [gate_arrival, gate_release + buffer) overlaps no occupancy [start, end + buffer); half-open |
| G-3 | landing >= issue time and >= base ETA; extra_holding == landing - base ETA; gate_arrival == landing + taxi_in; release - arrival >= turnaround |
| C-1 | a crew with assigned_gate == gate is on shift at gate arrival (shift_start <= arrival <= shift_end) |

C-1 deliberately checks presence at arrival rather than the whole service window: work past the
shift end is a soft cost (overtime), not a hard violation. This matches options.py's crew logic and
keeps "ground crew overtime" a meaningful cost.

## Concessions

The coordinator applies concessions with `scenario.apply_concessions(scenario, [{"agent","id","target"}])`
(Ashvin), which returns a new Scenario and records `applied_concessions` / `rejected_concessions` in each
agent's state. Recheck every candidate on the returned scenario; the source scenario is never mutated.

## Costs (`costs.py`)

| Component | Unit | Formula |
|---|---|---|
| `delay_min` | min | `landing - atc.base_eta` (= extra holding for options.py candidates). The historical recorded delay is never added. |
| `holding_fuel_kg` | kg | `extra_holding_min x holding_burn_kg_per_min` |
| `overtime_min` | min | `(gate_arrival + turnaround_min) - shift_end` of the serving crew, floored at 0 |
| `missed_connections` | pax | sum of `passengers` on connections with `departure_time < gate_arrival + min_connect_min` |
| `total_usd` | USD-equivalent score | sum of component x `config.costs` weight |

`costs.breakdown(candidate, scenario, weights)` gives raw value, unit, weight and weighted value per
component for the UI, plus `inputs.delay_vs_schedule_min` for display.

## Calls teammates make

```python
import checker, costs, fallback, scenario as S
cfg = checker.load_config()
checks = checker.check_all(candidates, scenario, cfg)            # {id: [CheckResult x 8]}
results = checker.check(candidate, scenario)                     # one candidate (coordinator uses this)
cost_map = costs.cost_all(candidates, scenario, cfg["costs"])    # {id: CandidateCost}
one = costs.cost(candidate, scenario, cfg["costs"])              # coordinator uses this
best = fallback.solve(candidates, checks, cost_map)              # id or None (escalate)
block = fallback.decide(candidates, checks, cost_map)            # log-ready dict, outcome fallback | escalation
after = S.apply_concessions(scenario, offered)                   # new state version; recheck on it
baseline = fallback.heuristic(scenario, cfg)                     # heuristic block for the log
result = fallback.run_pipeline(candidates, scenario, cfg)        # checks + costs + decision, no LLM
```

`python benchmark.py` runs demo-001 plus the 50 seeded scenarios deterministically and the four
failure tests; `--agents N` adds coordinator runs with fake agents (no API); `--live` uses Claude.
