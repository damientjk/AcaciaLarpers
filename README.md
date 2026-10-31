# Sky Huddle

Three AI agents (ATC, Pilot, Ground Ops) negotiate a fix for a disrupted flight in two rounds.
Plain code checks every proposal, a rulebook decides if they don't agree, and a human duty manager approves.

Autonomous SG 2026, Airbus track, Challenge 2.

## Run it

```bash
pip install -r requirements.txt
python fixtures/make_sample_logs.py   # sample runs, until the pipeline writes real ones
streamlit run app.py
```

The run picker lists `fixtures/cached/` first (commit real runs there for the offline demo), then `logs/`, then
`fixtures/sample_logs/` (labelled sample). "New run" buttons call `coordinator.run(...)`; without `ANTHROPIC_API_KEY`
they pass `fake_agents=True`. Logs are read through `normalize_log` in `app.py` (see `docs/LOG_FORMAT.md`).
Status: backend modules are stubs on `main`, so only sample logs render until they are filled in.

Pages: **Story** (problem, user, architecture, results), **Negotiation** (one run in full), **Pixel replay**
(the same run played back as pixel-art agents talking), **Benchmark**.

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
fixtures/        sample logs and benchmark for UI work; later the 50 seeded scenario IDs
models.py, scenario.py, options.py        (Ashvin)
checker.py, costs.py, fallback.py, benchmark.py   (Yizhuo)
agents.py, coordinator.py                (Damien)
logs/            JSON audit logs and duty manager decisions
tests/           schema and check tests (run: python -m pytest tests)
```
