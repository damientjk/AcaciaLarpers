"""Generate up to 8 coupled candidates (slot, extra holding, gate, concession). (Ashvin)

A candidate = arrival slot + gate. Everything downstream is coupled to the slot:
    landing = slot time
    extra_holding_min = landing - base ETA
    gate_arrival = landing + that gate's taxi-in
    ready = gate_arrival + turnaround minimum
    gate_release = max(ready, next scheduled departure of this tail)

`Candidate.concession` names the concessions the candidate DEPENDS ON
(e.g. "ATC_EARLIER_SLOT + GROUND_REASSIGN_CREW"):
    ATC_EARLIER_SLOT      slot is held by a flexible neighbour that ATC can move later
    PILOT_EXTRA_HOLDING   extra holding exceeds the pilot's comfortable limit
    GROUND_REASSIGN_CREW  no crew on shift at the gate; a reassignable crew exists
The checker evaluates a candidate as if its own concessions were applied; the coordinator
only treats it as available once the owning agent has offered those concessions.

Candidate IDs and the set are deterministic for a scenario and do NOT change after
concessions, so C3 means the same thing in round 1, round 2 and the audit log.
Hard rules (wake, fuel, gate conflicts, taxiway closures, aircraft fit) are left to
checker.py: infeasible candidates are generated on purpose so the checks have work to do.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from models import Candidate, Scenario
from scenario import config, from_iso, hhmm, iso

MAX_SLOTS = 4


def generate(scenario: Scenario, concessions: list | None = None) -> list[Candidate]:
    """Up to max_candidates candidates. `concessions` is accepted for interface compatibility
    and does not change the set (IDs must stay stable across rounds)."""
    return [c for c, _ in generate_detailed(scenario)]


def timeline(candidate: Candidate | str, scenario: Scenario) -> dict:
    """Full-datetime detail for one candidate (slot_id, ISO times, taxi route, concession list).
    Use this in checker/costs rather than parsing the HH:MM strings (overnight safe)."""
    cid = candidate if isinstance(candidate, str) else candidate.id
    for c, d in generate_detailed(scenario):
        if c.id == cid:
            return d
    raise KeyError(cid)


def generate_detailed(scenario: Scenario) -> list[tuple[Candidate, dict]]:
    atc, pilot, ground = (scenario.simulated[a] for a in ("atc", "pilot", "ground"))
    base_eta = from_iso(atc["base_eta"])
    slots = _pick_slots(atc, pilot, base_eta)
    gates = sorted(ground["gates"], key=lambda g: (g["gate_id"] != ground["planned_gate"], g["gate_id"]))

    combos = []
    for si, slot in enumerate(slots):
        for gi, gate in enumerate(gates):
            combos.append((si + gi, si, gi, slot, gate))
    combos.sort(key=lambda x: (x[0], x[1], x[2]))
    combos = combos[: config()["protocol"]["max_candidates"]]
    combos.sort(key=lambda x: (x[1], x[2]))          # IDs in slot order, planned gate first

    out = []
    for n, (_, _, _, slot, gate) in enumerate(combos, start=1):
        d = _detail(f"C{n}", slot, gate, base_eta, pilot, ground)
        cand = Candidate(
            id=d["id"],
            landing=hhmm(from_iso(d["landing"])),
            extra_holding_min=d["extra_holding_min"],
            gate=gate["gate_id"],
            concession=" + ".join(c["id"] for c in d["concessions"]) or None,
            gate_arrival=hhmm(from_iso(d["gate_arrival"])),
            gate_release=hhmm(from_iso(d["gate_release"])),
        )
        out.append((cand, d))
    return out


def _pick_slots(atc: dict, pilot: dict, base_eta: datetime) -> list[dict]:
    """Up to 4 distinct slots: an ATC-earlier slot, the first two free slots, and the first
    free slot beyond the pilot's comfortable holding. Limited to fuel-safe holding + 10 min
    so some fuel-infeasible options exist for F-1 to reject."""
    limit = base_eta + timedelta(minutes=pilot["fuel_safe_holding_min"] + 10)
    ahead = [s for s in atc["slots"] if base_eta <= from_iso(s["time"]) <= limit]
    free = [s for s in ahead if s["occupant"] is None]
    picks = []
    first_free_t = from_iso(free[0]["time"]) if free else limit
    earlier = [s for s in ahead if s["occupant_flexible"] and from_iso(s["time"]) < first_free_t]
    if earlier:
        picks.append(earlier[0])
    picks += free[:2]
    comfort = base_eta + timedelta(minutes=pilot["comfortable_holding_min"])
    beyond = [s for s in free if from_iso(s["time"]) > comfort and s not in picks]
    if beyond:
        picks.append(beyond[0])
    picks = sorted({s["slot_id"]: s for s in picks}.values(), key=lambda s: s["time"])
    return picks[:MAX_SLOTS]


def _detail(cid: str, slot: dict, gate: dict, base_eta: datetime, pilot: dict, ground: dict) -> dict:
    landing = from_iso(slot["time"])
    holding = int((landing - base_eta).total_seconds() // 60)
    gate_arrival = landing + timedelta(minutes=gate["taxi_in_min"])
    ready = gate_arrival + timedelta(minutes=ground["turnaround_min"])
    release = max(ready, from_iso(ground["next_departure"]))

    concessions = []
    if slot["occupant"] is not None and slot["occupant_flexible"]:
        concessions.append({"id": "ATC_EARLIER_SLOT", "target": slot["slot_id"],
                            "detail": f"move {slot['occupant']} to a later slot"})
    if holding > pilot["comfortable_holding_min"]:
        concessions.append({"id": "PILOT_EXTRA_HOLDING", "target": f"{holding} min",
                            "detail": f"comfortable limit {pilot['comfortable_holding_min']} min"})
    crew = _crew_at(ground, gate["gate_id"], gate_arrival)
    if crew is None:
        donor = next((c for c in ground["crews"] if c["reassignable"]
                      and from_iso(c["shift_start"]) <= gate_arrival <= from_iso(c["shift_end"])), None)
        if donor:
            concessions.append({"id": "GROUND_REASSIGN_CREW", "target": gate["gate_id"],
                                "detail": f"move {donor['crew_id']} from {donor['assigned_gate']}"})

    return {
        "id": cid, "slot_id": slot["slot_id"], "landing": iso(landing), "extra_holding_min": holding,
        "gate": gate["gate_id"], "taxi_route": gate["taxi_route"], "taxi_in_min": gate["taxi_in_min"],
        "gate_arrival": iso(gate_arrival), "ready": iso(ready), "gate_release": iso(release),
        "crew": crew["crew_id"] if crew else None, "concessions": concessions,
    }


def _crew_at(ground: dict, gate_id: str, t: datetime) -> dict | None:
    for c in ground["crews"]:
        if c["assigned_gate"] == gate_id and from_iso(c["shift_start"]) <= t <= from_iso(c["shift_end"]):
            return c
    return None
