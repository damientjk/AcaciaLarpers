"""Write sample audit logs so the UI can be built before the real pipeline exists.

Run:  python fixtures/make_sample_logs.py
Output: fixtures/sample_logs/*.json and fixtures/sample_benchmark.json

Everything under "simulated" and every cost is made up for UI development.
The "historical" block comes from real rows of flights.csv.
Replace these files with coordinator.py / benchmark.py output once they exist.
"""
import json
from pathlib import Path

OUT = Path(__file__).parent / "sample_logs"
OUT.mkdir(exist_ok=True)

WEIGHTS = {"delay_usd_per_min": 100.76, "holding_fuel_usd_per_kg": 0.85,
           "overtime_usd_per_min": 1.5, "missed_connection_usd": 250}
BASIS = {
    "F-1": "Simplified; 45 min reserve inspired by 14 CFR 121.639",
    "W-1": "Simplified wake profile based on FAA JO 7110.65 categories",
    "R-1": "Simulated runway capacity",
    "T-1": "Simulated taxiway closures",
    "G-1": "Simulated gate size limits",
    "G-2": "Simulated gate occupancy plus 10 min buffer",
    "G-3": "Assumption: 45 min turnaround minimum",
    "C-1": "Simulated ground crew roster",
}
RULES = list(BASIS)


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def cost(delay, hold, ot, missed):
    fuel = hold * 40  # kg, simulated A321 holding burn
    total = (delay * WEIGHTS["delay_usd_per_min"] + fuel * WEIGHTS["holding_fuel_usd_per_kg"]
             + ot * WEIGHTS["overtime_usd_per_min"] + missed * WEIGHTS["missed_connection_usd"])
    return {"delay_min": delay, "holding_fuel_kg": fuel, "overtime_min": ot,
            "missed_connections": missed, "total_usd": round(total)}


def check(rule, passed, explanation, inputs):
    return {"rule_id": rule, "basis": BASIS[rule], "inputs": inputs, "passed": passed, "explanation": explanation}


def demo_candidates():
    sched = 20 * 60 + 30
    rows = [
        # id, landing, hold, gate, concession needed
        ("C1", 20 * 60 + 40, 0, "B4", None),
        ("C2", 20 * 60 + 40, 0, "B7", "GROUND_REASSIGN_CREW"),
        ("C3", 20 * 60 + 52, 12, "C3", "PILOT_EXTRA_HOLDING"),
        ("C4", 21 * 60 + 5, 25, "B4", None),
        ("C5", 20 * 60 + 32, 0, "B7", "ATC_EARLIER_SLOT + GROUND_REASSIGN_CREW"),
        ("C6", 20 * 60 + 32, 0, "B4", "ATC_EARLIER_SLOT"),
        ("C7", 20 * 60 + 52, 12, "B7", "GROUND_REASSIGN_CREW"),
        ("C8", 20 * 60 + 40, 0, "C5", None),
    ]
    cands, costs = [], {}
    for cid, land, hold, gate, conc in rows:
        taxi = 8
        cands.append({"id": cid, "landing": hhmm(land), "extra_holding_min": hold, "gate": gate,
                      "concession": conc, "gate_arrival": hhmm(land + taxi),
                      "gate_release": hhmm(land + taxi + 45)})
        missed = 0 if land - sched <= 10 else 6 if gate != "C3" else 9
        ot = 20 if gate == "B7" else 0
        costs[cid] = cost(land - sched, hold, ot, missed)
    return cands, costs


def demo_checks(after):
    """after=True means round 1 concessions are applied."""
    out = {}
    fuel_at_landing = {0: 50, 12: 47 if after else 47, 25: 38}
    for cid, land, hold, gate in [("C1", "20:40", 0, "B4"), ("C2", "20:40", 0, "B7"), ("C3", "20:52", 12, "C3"),
                                  ("C4", "21:05", 25, "B4"), ("C5", "20:32", 0, "B7"), ("C6", "20:32", 0, "B4"),
                                  ("C7", "20:52", 12, "B7"), ("C8", "20:40", 0, "C5")]:
        f = fuel_at_landing[hold]
        hold_ok = True
        rs = [
            check("F-1", f >= 45 and hold_ok,
                  f"{f} min fuel at landing, reserve 45" + ("" if hold_ok else "; holding beyond what Pip agreed"),
                  {"fuel_at_landing_min": f, "reserve_min": 45, "extra_holding_min": hold}),
            check("W-1", True, "3 min behind the preceding B757 (Medium after Heavy-equivalent spacing kept)",
                  {"leader": "AAL2213 B757", "gap_min": 3, "required_min": 3}),
        ]
        slot_full = land == "20:32" and not after
        rs.append(check("R-1", not slot_full,
                        "20:32 slot is full at 30 arrivals/hour" if slot_full else "Slot within declared capacity",
                        {"slot": land, "declared_rate_per_hr": 30}))
        rs.append(check("T-1", True, "Route via taxiway K avoids closed taxiway L", {"closed": ["L"]}))
        rs.append(check("G-1", gate != "C5", "A321 does not fit regional gate C5" if gate == "C5" else f"A321 fits {gate}",
                        {"aircraft": "A321", "gate": gate}))
        busy = gate == "B4" and land < "21:05"
        rs.append(check("G-2", not busy, "B4 occupied until 20:55 plus 10 min buffer" if busy else f"{gate} free for the full window",
                        {"gate": gate, "occupied_until": "20:55" if gate == "B4" else None, "buffer_min": 10}))
        rs.append(check("G-3", True, "45 min turnaround fits before next departure 22:05", {"turnaround_min": 45}))
        crew_ok = gate != "B7" or after
        rs.append(check("C-1", crew_ok,
                        "Crew reassigned from B9 to B7 from 20:25" if gate == "B7" and after else
                        "No crew at B7 until 21:20" if gate == "B7" else "Crew available",
                        {"gate": gate, "crew_move": gate == "B7" and after}))
        out[cid] = rs
    return out


HIST_DEMO = {"carrier": "AA", "carrier_name": "American Airlines Inc.", "flight": "1344", "tail": "N200AA",
             "origin": "DEN", "destination": "DFW", "date": "2015-01-01", "scheduled_arrival": "20:30",
             "actual_arrival": "22:29", "arrival_delay_min": 119, "weather_delay_min": 35,
             "late_aircraft_delay_min": 40, "air_system_delay_min": 44, "distance_mi": 641,
             "air_time_min": 95, "taxi_in_min": 12}
SIM_DEMO = {
    "atc": {"runway": "17C", "declared_rate_per_hr": 30, "slots": ["20:32", "20:40", "20:52", "21:05"],
            "preceding": "AAL2213 B757", "closed_taxiways": ["L"]},
    "pilot": {"aircraft": "A321", "fuel_on_board_min": 50, "reserve_min": 45, "max_extra_holding_min": 12,
              "connecting_pax": 9},
    "ground": {"gates": {"B4": "occupied until 20:55", "B7": "free, no crew until 21:20", "C3": "free",
                         "C5": "regional only"}, "turnaround_min": 45, "next_departure": "22:05",
               "crew_shift_end": "23:00"},
}


def demo_log(kind):
    cands, costs = demo_candidates()
    before, after = demo_checks(False), demo_checks(True)
    feas_before = [c for c in before if all(r["passed"] for r in before[c])]
    feas_after = [c for c in after if all(r["passed"] for r in after[c])]
    offers = [
        {"agent": "atc", "preferred": "C5", "acceptable": ["C2", "C3", "C5", "C7"], "constraints_cited": ["R-1", "W-1"],
         "concessions": [{"id": "ATC_EARLIER_SLOT", "target": "20:32"}],
         "rationale": "20:40 and 20:52 fit current capacity. I can resequence AAL2213 to open 20:32 and keep wake spacing.",
         "latency_s": 3.1, "valid": True},
        {"agent": "pilot", "preferred": "C5", "acceptable": ["C2", "C3", "C5", "C7"], "constraints_cited": ["F-1"],
         "concessions": [{"id": "PILOT_EXTRA_HOLDING", "target": "12 min"}],
         "rationale": "50 min fuel now. Holding 25 min leaves 38 min, under the 45 min reserve. I can accept up to 12 min. 9 passengers connect.",
         "latency_s": 2.8, "valid": True},
        {"agent": "ground", "preferred": "C3", "acceptable": ["C2", "C3", "C5", "C7"], "constraints_cited": ["G-2", "C-1"],
         "concessions": [{"id": "GROUND_REASSIGN_CREW", "target": "B7"}],
         "rationale": "B4 occupied until 20:55. B7 usable if the crew moves from B9 at 20:25. C3 works without changes.",
         "latency_s": 3.4, "valid": True},
    ]
    in_all = [c for c in feas_after if all(c in o["acceptable"] for o in offers)]
    best = min(in_all, key=lambda c: (costs[c]["total_usd"], c))
    fb_base = min(feas_before, key=lambda c: (costs[c]["total_usd"], c))
    votes = [{"agent": a, "proposal_version": 2, "vote": "accept", "rationale": r, "latency_s": l} for a, r, l in [
        ("atc", "C5 keeps wake spacing behind the resequenced B757.", 2.2),
        ("pilot", "No holding, 50 min fuel at landing, connections protected.", 2.0),
        ("ground", "Crew move to B7 confirmed, turnaround fits.", 2.5)]]
    outcome = {"type": "consensus", "final_candidate": best,
               "reason": "All three accepted proposal v2 and the final recheck passed.",
               "concessions_that_unlocked": ["ATC_EARLIER_SLOT", "GROUND_REASSIGN_CREW"],
               "final_recheck": {"state_version": 2, "passed": True}}
    fallback = None
    label = "Demo: concession unlocks gate B7"
    if kind == "fallback":
        votes[2] = {"agent": "ground", "proposal_version": 2, "vote": "abstain",
                    "rationale": "Timed out after 20 s (no valid response).", "latency_s": 20.0}
        outcome = {"type": "fallback", "final_candidate": fb_base,
                   "reason": "Ground did not vote in round 2 (timeout). An abstention is not an accept, so the rulebook decides on the base state without unconfirmed concessions.",
                   "concessions_that_unlocked": [], "final_recheck": {"state_version": 1, "passed": True}}
        fallback = {"candidate": fb_base, "rule": "Lowest-cost candidate that passes every check; ties by candidate ID",
                    "feasible": feas_before}
        label = "Failure case: Ground times out, rulebook decides"
    return {
        "run_id": "r-demo-0001" if kind == "consensus" else "r-demo-0002-timeout",
        "label": label, "created_at": "2026-10-31T12:00:00+08:00", "sample": True,
        "scenario": {"scenario_id": "demo-001", "issue_time": "2015-01-01T19:55", "historical": HIST_DEMO,
                     "simulated": SIM_DEMO},
        "weights": WEIGHTS, "candidates": cands, "costs": costs,
        "checks": {"before_concessions": before, "after_concessions": after},
        "rounds": [{"round": 1, "offers": offers}, {"round": 2, "votes": votes}],
        "compromise": {"concessions_applied": [{"agent": o["agent"], **c} for o in offers for c in o["concessions"]],
                       "feasible_before": feas_before, "feasible_after": feas_after, "in_all_acceptable": in_all,
                       "rule": "Lowest cost among feasible candidates in all three acceptable sets",
                       "proposal": {"version": 2, "candidate": best}},
        "outcome": outcome, "fallback": fallback,
        "baselines": {"solver": {"candidate": best, "total_usd": costs[best]["total_usd"]},
                      "heuristic": {"plan": "Delay ETA by recorded delay, keep planned gate B4",
                                    "feasible": False, "failed": ["G-2"]}},
        "human_decision": None,
        "stats": {"api_calls": 6 if kind == "consensus" else 7, "retries": 0 if kind == "consensus" else 1,
                  "total_latency_s": 9.6 if kind == "consensus" else 26.5},
    }


def escalation_log():
    hist = {"carrier": "AA", "carrier_name": "American Airlines Inc.", "flight": "8", "tail": "N368AA",
            "origin": "HNL", "destination": "DFW", "date": "2015-01-01", "scheduled_arrival": "05:10",
            "actual_arrival": "06:59", "arrival_delay_min": 109, "weather_delay_min": 0,
            "late_aircraft_delay_min": 108, "air_system_delay_min": 1, "distance_mi": 3784,
            "air_time_min": 390, "taxi_in_min": 9}
    cands, checks, costs = [], {}, {}
    for i, (land, gate, why) in enumerate([("05:20", "D2", "G-2"), ("05:30", "D4", "G-1"), ("05:45", "D2", "F-1")], 1):
        cid = f"C{i}"
        cands.append({"id": cid, "landing": land, "extra_holding_min": 0 if why != "F-1" else 25, "gate": gate,
                      "concession": None, "gate_arrival": land, "gate_release": land})
        rs = [check(r, r != why, "Blocked in this scenario" if r == why else "Passes", {}) for r in RULES]
        checks[cid] = rs
        costs[cid] = cost(10 * i, 0, 0, 0)
    return {"run_id": "r-esc-0003", "label": "Impossible scenario: nothing passes, escalate", "sample": True,
            "created_at": "2026-10-31T12:00:00+08:00",
            "scenario": {"scenario_id": "esc-001", "issue_time": "2015-01-01T04:30", "historical": hist,
                         "simulated": {"atc": {"runway": "17C"}, "pilot": {"fuel_on_board_min": 47, "reserve_min": 45},
                                       "ground": {"gates": {"D2": "occupied until 06:30", "D4": "too small"}}}},
            "weights": WEIGHTS, "candidates": cands, "costs": costs,
            "checks": {"before_concessions": checks, "after_concessions": checks},
            "rounds": [], "compromise": None,
            "outcome": {"type": "escalation", "final_candidate": None,
                        "reason": "No feasible plan within the modelled options. Escalated to the duty manager.",
                        "concessions_that_unlocked": [], "final_recheck": None},
            "fallback": {"candidate": None, "rule": "Nothing passes the checker", "feasible": []},
            "baselines": {}, "human_decision": None, "stats": {"api_calls": 0, "retries": 0, "total_latency_s": 0.4}}


for name, log in [("demo_consensus", demo_log("consensus")), ("demo_timeout_fallback", demo_log("fallback")),
                  ("impossible_escalation", escalation_log())]:
    (OUT / f"{name}.json").write_text(json.dumps(log, indent=2))

bench = {"sample": True, "note": "SAMPLE NUMBERS for UI layout only. Replace with benchmark.py output.",
         "scenarios": {"total": 50, "weather_only": 20, "late_aircraft_only": 20, "both": 10},
         "deterministic": {"runs": 50, "fallback_feasible": 47, "escalations": 3},
         "agents": {"completed": 10, "consensus": 8, "fallback": 2, "escalation": 0, "accepted_violations": 0,
                    "mean_latency_s": 11.8, "mean_api_calls": 6.2, "retries": 2},
         "cost_vs_solver_gap_pct": 3.4,
         "heuristic": {"infeasible_rate_pct": 62, "mean_cost_usd_when_feasible": 3900},
         "failure_tests": [
             {"test": "Injected invalid proposal", "expected": "blocked", "result": "blocked", "passed": True},
             {"test": "Impossible scenario", "expected": "escalate", "result": "escalate", "passed": True},
             {"test": "Malformed agent response", "expected": "fallback", "result": "fallback", "passed": True},
             {"test": "API timeout", "expected": "fallback", "result": "fallback", "passed": True}]}
(Path(__file__).parent / "sample_benchmark.json").write_text(json.dumps(bench, indent=2))
print("wrote", sorted(p.name for p in OUT.iterdir()))
