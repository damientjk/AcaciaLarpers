# Sky Huddle

Three AI agents (ATC, Pilot, Ground Ops) negotiate a fix for a disrupted flight in two rounds.
Plain code checks every proposal, a rulebook decides if they don't agree, and a human duty manager approves.

Autonomous SG 2026, Airbus track, Challenge 2.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

The run picker lists `fixtures/cached/` first (4 saved runs for an offline demo), then `logs/`. Sample runs in
`fixtures/sample_logs/` are labelled SAMPLE and hidden once real runs exist. The sidebar buttons call
`coordinator.run(...)`: with `ANTHROPIC_API_KEY` set the agents are live Claude calls, without it they use fake
agents (labelled in the picker).

Pages: **Story** (problem, user, architecture, results), **Negotiation** (one run in full), **Pixel replay**
(the same run played back as pixel-art agents talking), **Metrics** (charts computed from the run logs) and
**Benchmark**.

### Live agents and the benchmark

```bash
export ANTHROPIC_API_KEY=...                       # never commit this
python -m pytest -q                                 # 144 tests, no API calls
python benchmark.py --agents 10 --live             # writes logs/benchmark.json
python -c "import coordinator; print(coordinator.run(flight='AA1344', date='2015-01-01')['outcome'])"
```

## Results

Measured inside the simulation on 51 seeded scenarios (20 weather only, 20 late aircraft only, 11 both).
Costs are USD-equivalent scores from `config.yaml` weights, not measured savings.

| | Result |
|---|---|
| Scenarios with a safe plan before any concession | 26 of 51 |
| Scenarios with a safe plan after agent concessions | **40 of 51** (concessions rescued 14) |
| Scenarios with no safe plan in the modelled options | 11 of 51, escalated to the duty manager |
| Unsafe plans accepted | **0** |
| Simple heuristic (delay by the recorded delay, keep the planned gate) | infeasible in 100% of scenarios |
| Live agent runs (10, `claude-haiku-5-5`, on the current simulation) | 8 consensus, 0 fallback, 2 escalation (both escalations are scenarios where the solver also finds nothing); 0 unsafe plans accepted; 5 retries; est. API cost $0.056 |
| Agent result vs all-knowing solver on the same options and cost table | 6 of 8 consensus runs matched the solver's pick; 2 chose a dearer safe plan ($1,219, $818); agents' total cost +12% vs the solver's across the 8 runs (mean per-run gap 114%, inflated by one run on a $135 base) |
| Failure tests (invalid proposal, impossible scenario, malformed reply, API timeout) | 4 of 4 handled |

**Why the 11 escalations are the right answer.** When none of the up to 8 modelled plans passes every hard check,
the system refuses to guess and hands the decision to the duty manager with the reasons. The checks most often
blocking plans are gate occupancy (G-2), crew availability (C-1) and fuel reserve (F-1).

### Demo run: AA1344 Denver to Dallas/Fort Worth, 1 Jan 2015

- Before concessions all 6 candidate plans fail at least one check (runway slot, gate, fuel or crew).
- Ava (ATC) frees an earlier slot, Pip (Pilot) accepts holding up to his fuel-safe 9 minutes, Gus (Ground) moves
  a crew from B9 to B7.
- Plan C2 becomes safe: land 22:24, gate B7, 7 min extra holding, cost score $943. All three agents accept it
  in round 2 and the final recheck passes.
- The simple heuristic (land 22:29 at the planned gate B4) fails fuel, runway slot and gate checks, at $11,653.

## How it works

1. A real delayed flight from `data/flights.csv` anchors the scenario.
2. Simulated, labelled state is added: arrival slots, fuel, gates, crew.
3. Up to 8 candidate plans (landing slot, extra holding, gate) are generated and checked.
4. **Round 1:** each agent, in its own LLM call with its own prompt and private state, returns a preferred
   plan, its acceptable plans, the checks it cites and any allowed concession.
5. **Coordinator (plain code):** applies concessions, rechecks, and freezes the cheapest plan that is feasible
   and in all three acceptable sets.
6. **Round 2:** each agent accepts or rejects that exact proposal.
7. **Outcome:** consensus (three accepts and the recheck passes), fallback (any reject, missing vote or timeout:
   lowest-cost feasible plan), or escalation (nothing feasible). A fallback is never shown as consensus.
8. The duty manager approves or rejects. Everything is written to a JSON audit log.

## Hard checks

| ID | Check | Basis |
|---|---|---|
| F-1 | Fuel at landing meets the reserve | Simplified; the reserve is a scenario parameter inspired by the 45-minute figure in 14 CFR 121.639, a dispatch-fuel rule, so this is not a landing-fuel compliance check |
| W-1 | Wake spacing behind the preceding aircraft | Simulated profile informed by FAA JO 7110.65 categories, not quoted minima |
| R-1 | Slot within runway capacity | Simulated |
| T-1 | Taxi route avoids closed taxiways | Simulated |
| G-1 | Aircraft fits the gate | Simulated |
| G-2 | Gate free for the full window plus buffer | Simulated |
| G-3 | Turnaround minimum respected | Assumption |
| C-1 | Ground crew available | Simulated |

These checks are simplified. They are not full FAA compliance.

## Data

- `data/flights.csv`: 358,774 delayed 2015 US flights (US DOT). Every row qualifies (weather delay > 15 min or
  late-aircraft delay > 20 min): 32,525 weather only, 316,762 late aircraft only, 9,487 both. It is a
  disruption-only extract, not a full schedule: no October, no cancellations or diversions, so it cannot be used
  to rebuild real runway, gate or aircraft rotations.
- `data/airports.csv`, `data/airlines.csv`: labels.

**What is real.** Carrier, flight, tail, route, date, scheduled and actual times, recorded delays and their causes,
distance and taxi-in time all come from the row unchanged. The unconstrained landing time (base ETA) is the row's
real wheels-on time; a plan only adds extra holding on top of it, so the recorded delay is counted once.

**Time handling.** DOT gives departures in origin local time and arrivals in destination local time. Everything
is converted to destination local time: the time-zone offset is inferred from scheduled departure + scheduled
block time vs scheduled arrival, and actual arrival = scheduled arrival + `ARRIVAL_DELAY`, which handles overnight
flights and `2400` without guessing dates. On 20,000 sampled rows this matches the file's `ARRIVAL_TIME` in every
case.

**What is simulated** (seeded by scenario ID, so any scenario rebuilds exactly from its ID; bounds in
`config.yaml` under `simulation:`; labelled "simulated" in the UI):

| Area | Simulated | Assumption behind it |
|---|---|---|
| Aircraft | Narrowbody / widebody and wake category | Inferred from distance (2,000 mi or more = widebody, heavy wake); DOT has no aircraft type |
| Runway | Arrival rate 30/h (20/h in weather), neighbouring traffic, wake categories, which neighbours ATC may move | Generic single arrival runway |
| Taxiways | 6 generic taxiways, each gate reached by 2; one may be closed (more often in weather) | Not the real airport layout |
| Fuel | Fuel on board, burn rates, 45 min reserve, fuel-safe and comfortable holding | Typical burn figures, not airline data |
| Gates | 2 or 3 generic gates (B4, B7, B9), size, occupancy | The planned gate is often still occupied, always for late-aircraft rows |
| Crew | Shifts and assignments; the planned gate's crew can follow its flight if that gate is blocked | Simplified ramp staffing |
| Passengers | 0 to 3 onward connections | Not from booking data |
| Turnaround | 35 min narrowbody, 75 min widebody; next departure after the scheduled arrival | Assumption |

`demo-001` uses a real row chosen by rule (an evening narrowbody arrival at ATL with both delay causes), with its
simulated state deliberately shaped so that preferences conflict. The code does not fix which plan wins. Every
other scenario uses the seeded generator unchanged.

## Sources

- Cost of aircraft time: $100.76 per block minute in 2024, Airlines for America,
  https://www.airlines.org/dataset/u-s-passenger-carrier-delay-costs/
- Holding fuel weight ($0.85/kg, approximate): jet fuel between IATA's 2025 average (about $90/bbl) and its
  June 2026 outlook (about $152/bbl), at roughly 127 kg per barrel. IATA jet fuel price monitor,
  https://www.iata.org/en/publications/economics/fuel-monitor/
- Overtime weight ($1.5/min, approximate): a four-person ramp crew at the US median wage for hand laborers and
  material movers (about $18/h), between straight time and 1.5x. BLS Occupational Employment and Wage
  Statistics, occupation 53-7062, https://www.bls.gov/oes/current/oes537062.htm
- Missed-connection weight ($250 per passenger, approximate): Switchfly's US per-passenger rebooking estimate
  (2017 data), a cancellation figure used here as a misconnect proxy,
  https://switchfly.com/blog/disrupting-travel-disruptions-and-helping-stranded-passengers

## Limitations

- Results are measured inside the simulation. They are not proven reductions of the real 2015 delays.
- One airport and one disrupted flight per scenario. No multi-flight cascades.
- Every airport gets the same generic layout (one arrival runway, 6 taxiways, 2 or 3 gates). Results say nothing
  about a specific airport's real capacity.
- Aircraft type is inferred from distance, so wake category and fuel burn can be wrong for a given flight. A
  registry lookup by tail number would fix this.
- The time-zone offset is inferred from the schedule and rounded to whole hours.
- Agents are not expected to beat a central solver that knows every constraint. We measure how well they
  coordinate within bounds and how traceable the agreement is.

## Repo layout

```
data/            flights.csv, airports.csv, airlines.csv
config.yaml      cost weights, timeouts, simulation bounds
app.py           Streamlit UI (Dafeng)
ui/              pixel replay page and its Python helper (Dafeng)
docs/LOG_FORMAT.md   audit log contract between the pipeline and the UI
fixtures/        cached demo runs + benchmark (cached/), sample logs for UI work
models.py, scenario.py, options.py        (Ashvin)
checker.py, costs.py, fallback.py, benchmark.py   (Yizhuo)
agents.py, coordinator.py                (Damien)
logs/            JSON audit logs and duty manager decisions
tests/           schema and check tests (run: python -m pytest tests)
```
