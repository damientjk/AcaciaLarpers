"""A tiny hand-built world matching the plan's demo, so the protocol can be tested before the real
scenario, options, checker and costs modules exist."""
from models import Candidate, CandidateCost, CheckResult, Historical, Scenario

RULES = ["F-1", "W-1", "R-1", "T-1", "G-1", "G-2", "G-3", "C-1"]

HISTORICAL = Historical(carrier="AA", carrier_name="American Airlines Inc.", flight="1344", tail="N200AA",
                        origin="DEN", destination="DFW", date="2015-01-01", scheduled_arrival="20:30",
                        actual_arrival="22:29", arrival_delay_min=119, weather_delay_min=35,
                        late_aircraft_delay_min=40, distance_mi=641)

CANDIDATES = [
    Candidate(id="C1", landing="20:30", extra_holding_min=0, gate="B4", gate_arrival="20:38", gate_release="21:23"),
    Candidate(id="C2", landing="20:40", extra_holding_min=25, gate="C3", gate_arrival="20:48", gate_release="21:33"),
    Candidate(id="C3", landing="20:52", extra_holding_min=12, gate="C3", gate_arrival="21:00", gate_release="21:45"),
    Candidate(id="C5", landing="20:32", extra_holding_min=0, gate="B7", concession="ATC_EARLIER_SLOT + GROUND_REASSIGN_CREW",
              gate_arrival="20:40", gate_release="21:25"),
]
COSTS = {"C1": 150, "C2": 6100, "C3": 4900, "C5": 232}


def scenario(impossible: bool = False) -> Scenario:
    return Scenario(scenario_id="toy-demo", issue_time="2015-01-01T19:55", historical=HISTORICAL, simulated={
        "atc": {"earlier_slot_open": False,
                "slot_20_32": "occupied by AAL2213, a flexible neighbour that can be resequenced to 20:44"},
        "pilot": {"max_extra_holding_min": 0 if impossible else 12},
        "ground": {"crew_at_B7": False, "b7_compatible": not impossible},
    })


class ToyWorld:
    def candidates(self, s):
        return list(CANDIDATES)

    def check(self, c, s):
        sim = s.simulated
        failing = set()
        if c.extra_holding_min > sim["pilot"]["max_extra_holding_min"]:
            failing.add("F-1")
        if c.gate == "B4":
            failing.add("G-2")
        if c.id == "C5":
            if not sim["atc"]["earlier_slot_open"]:
                failing.add("R-1")
            if not sim["ground"]["crew_at_B7"]:
                failing.add("C-1")
            if not sim["ground"]["b7_compatible"]:
                failing.add("G-1")
        return [CheckResult(rule_id=r, basis="toy", inputs={}, passed=r not in failing,
                            explanation=f"{r} {'fails' if r in failing else 'passes'} on {c.id}") for r in RULES]

    def cost(self, c, s):
        return CandidateCost(delay_min=0, holding_fuel_kg=0, overtime_min=0, missed_connections=0,
                             total_usd=COSTS[c.id])

    def apply(self, s, concessions):
        sim = {k: dict(v) for k, v in s.simulated.items()}
        for c in concessions:
            if c["id"] == "ATC_EARLIER_SLOT":
                sim["atc"]["earlier_slot_open"] = True
            if c["id"] == "GROUND_REASSIGN_CREW":
                sim["ground"]["crew_at_B7"] = True
        return s.model_copy(update={"simulated": sim})

    def view(self, s, agent):
        hidden = {"earlier_slot_open", "crew_at_B7", "b7_compatible"}   # checker internals, not agent knowledge
        return {"historical": s.historical.model_dump(),
                "private": {k: v for k, v in s.simulated[agent].items() if k not in hidden}}

    def solve(self, candidates, checks, costs):
        ok = [c.id for c in candidates if all(r.passed for r in checks[c.id])]
        return min(ok, key=lambda i: (costs[i].total_usd, i)) if ok else None

    def heuristic(self, s):
        return {"plan": "Delay ETA by recorded delay, keep planned gate", "feasible": False, "failed": ["G-2"]}
