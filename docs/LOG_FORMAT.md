# Audit log format (UI contract)

The UI (`app.py` and the pixel replay) reads one JSON file per run from `logs/`.
`coordinator.py` should write exactly this shape. A full example: `fixtures/sample_logs/demo_consensus.json`.
Field names can change at the 12:15 freeze, but then update this file and `fixtures/make_sample_logs.py` together.

```jsonc
{
  "run_id": "r-0142",                 // unique per run; a rerun gets a new one
  "label": "Demo: concession unlocks gate B7",   // optional, shown in the run picker
  "created_at": "2026-10-31T13:05:00+08:00",
  "sample": false,                    // true only for fake UI fixtures

  "scenario": {
    "scenario_id": "demo-001",
    "issue_time": "2015-01-01T19:55",
    "historical": {                   // REAL fields from flights.csv only
      "carrier": "AA", "carrier_name": "American Airlines Inc.", "flight": "1344", "tail": "N200AA",
      "origin": "DEN", "destination": "DFW", "date": "2015-01-01",
      "scheduled_arrival": "20:30", "actual_arrival": "22:29", "arrival_delay_min": 119,
      "weather_delay_min": 35, "late_aircraft_delay_min": 40, "distance_mi": 641
    },
    "simulated": { "atc": {}, "pilot": {}, "ground": {} }   // each agent's private state, labelled simulated
  },

  "weights": { "delay_usd_per_min": 100.76 },               // from config.yaml
  "candidates": [ { "id": "C5", "landing": "20:32", "extra_holding_min": 0, "gate": "B7",
                    "concession": "ATC_EARLIER_SLOT + GROUND_REASSIGN_CREW",
                    "gate_arrival": "20:40", "gate_release": "21:25" } ],      // max 8
  "costs": { "C5": { "delay_min": 2, "holding_fuel_kg": 0, "overtime_min": 20,
                     "missed_connections": 0, "total_usd": 232 } },
  "checks": {
    "before_concessions": { "C5": [ { "rule_id": "R-1", "basis": "...", "inputs": {}, "passed": false, "explanation": "..." } ] },
    "after_concessions":  { "C5": [ /* same rules, after round 1 concessions */ ] }
  },

  "rounds": [
    { "round": 1, "offers": [ { "agent": "ground", "preferred": "C3", "acceptable": ["C3","C5"],
        "constraints_cited": ["G-2","C-1"], "concessions": [ { "id": "GROUND_REASSIGN_CREW", "target": "B7" } ],
        "rationale": "...", "latency_s": 3.4, "valid": true } ] },
    { "round": 2, "votes": [ { "agent": "ground", "proposal_version": 2,
        "vote": "accept",            // accept | reject | abstain (timeout, invalid)
        "rationale": "...", "latency_s": 2.5 } ] }
  ],

  "compromise": {                      // null if no rounds ran
    "concessions_applied": [ { "agent": "ground", "id": "GROUND_REASSIGN_CREW", "target": "B7" } ],
    "feasible_before": ["C3"], "feasible_after": ["C2","C3","C5","C7"], "in_all_acceptable": ["C2","C3","C5","C7"],
    "rule": "Lowest cost among feasible candidates in all three acceptable sets",
    "proposal": { "version": 2, "candidate": "C5" }
  },

  "outcome": {
    "type": "consensus",               // consensus | fallback | escalation
    "final_candidate": "C5",           // null on escalation
    "reason": "All three accepted proposal v2 and the final recheck passed.",
    "concessions_that_unlocked": ["ATC_EARLIER_SLOT","GROUND_REASSIGN_CREW"],
    "final_recheck": { "state_version": 2, "passed": true }
  },
  "fallback": null,                    // or { "candidate": "C3", "rule": "...", "feasible": ["C3"] }
  "baselines": { "solver": { "candidate": "C5", "total_usd": 232 },
                 "heuristic": { "plan": "Delay ETA by recorded delay, keep planned gate", "feasible": false, "failed": ["G-2"] } },
  "human_decision": null,              // the UI writes logs/decisions/<run_id>.json
  "stats": { "api_calls": 6, "retries": 0, "total_latency_s": 9.6 }
}
```

## Hooks the UI calls (optional)

`app.py` tries `import coordinator` and calls:

- `coordinator.run(random=True)` for "Run a random qualifying row"
- `coordinator.run(flight="AA1344", date="2015-01-01")` for search

Both should write the log to `logs/` and return the same dict. If the import fails, the UI shows saved runs only.

## Benchmark

`benchmark.py` writes `logs/benchmark.json` in the shape of `fixtures/sample_benchmark.json`.
