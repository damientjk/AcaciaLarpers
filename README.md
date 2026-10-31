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
python -m pytest -q                                 # 141 tests, no API calls
python benchmark.py --agents 10 --live             # writes logs/benchmark.json
python -c "import coordinator; print(coordinator.run(flight='AA1344', date='2015-01-01')['outcome'])"
```

## Results

Measured inside the simulation on 51 seeded scenarios (20 weather only, 20 late aircraft only, 11 both).
Costs are USD-equivalent scores from `config.yaml` weights, not measured savings.

| | Result |
|---|---|
| Scenarios with a safe plan before any concession | 21 of 51 |
| Scenarios with a safe plan after agent concessions | **29 of 51** (concessions rescued 8) |
| Scenarios with no safe plan in the modelled options | 22 of 51, escalated to the duty manager |
| Unsafe plans accepted | **0** |
| Simple heuristic (delay by the recorded delay, keep the planned gate) | infeasible in 100% of scenarios |
| Live agent runs (10, `claude-haiku-5-5`) | 7 consensus, 0 fallback, 3 escalation; 0 unsafe plans accepted; est. API cost $0.053 |
| Agent result vs all-knowing solver on the same options | 6 of 7 consensus runs matched the solver's cost; one chose a plan $1,213 dearer (mean gap 42.9%) |
| Failure tests (invalid proposal, impossible scenario, malformed reply, API timeout) | 4 of 4 handled |

**Why 22 escalations is the right answer.** When none of the up to 8 modelled plans passes every hard check,
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
| F-1 | Fuel at landing meets the reserve | Simplified; 45 min inspired by 14 CFR 121.639 |
| W-1 | Wake spacing behind the preceding aircraft | Simplified, based on FAA JO 7110.65 categories |
| R-1 | Slot within runway capacity | Simulated |
| T-1 | Taxi route avoids closed taxiways | Simulated |
| G-1 | Aircraft fits the gate | Simulated |
| G-2 | Gate free for the full window plus buffer | Simulated |
| G-3 | Turnaround minimum respected | Assumption |
| C-1 | Ground crew available | Simulated |

These checks are simplified. They are not full FAA compliance.

## Data

- `data/flights.csv`: 358,774 delayed 2015 US flights (US DOT). Every row qualifies.
- `data/airports.csv`, `data/airlines.csv`: labels.
- Anything not in these files (slots, fuel, gates, crew) is simulated, seeded by scenario ID and labelled
  "simulated" in the UI.

## Sources

- Cost of aircraft time: $100.76 per block minute in 2024, Airlines for America,
  https://www.airlines.org/dataset/u-s-passenger-carrier-delay-costs/

## Limitations

- Results are measured inside the simulation. They are not proven reductions of the real 2015 delays.
- One airport and one disrupted flight per scenario. No multi-flight cascades.
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
