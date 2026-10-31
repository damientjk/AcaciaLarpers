"""Hard checks F-1, W-1, R-1, T-1, G-1, G-2, G-3, C-1. (Yizhuo)

Every check is a simplified SIMULATION rule. None of them establishes FAA compliance.

Inputs are the agreed ``models.Scenario`` / ``models.Candidate``; the simulated-state keys read here
are the ones ``scenario.py`` (Ashvin) emits, listed in docs/CHECKER_INPUTS.md. A missing or malformed
required input FAILS the rule that needs it; nothing passes silently. The checker never raises for
bad simulated input, it returns a failed CheckResult whose explanation starts with "Cannot evaluate".

Time handling: every clock value is an ISO datetime ("2015-01-06T20:22") or "HH:MM" on the scenario's
issue date (rolled to the next day when more than 12 h before the issue time). Naive datetimes in the
destination's local time, as scenario.py produces them.

Public API
----------
check(candidate, scenario, config=None) -> list[CheckResult]      one candidate, all 8 rules
check_all(candidates, scenario, config=None) -> dict[id, list]    every candidate
feasible(results) -> bool / failed_rules(results) -> list[str]
eligible_crews(candidate, scenario) -> (crews, reasons)           shared with costs.py (overtime)
load_config(path=None) -> dict                                    config.yaml as a dict
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import yaml

from models import Candidate, CheckResult, Scenario

RULES = ["F-1", "W-1", "R-1", "T-1", "G-1", "G-2", "G-3", "C-1"]

BASIS = {
    "F-1": "Simplified simulation: fuel on board at issue time minus cruise burn to the base ETA minus holding "
           "burn must meet the scenario reserve (kg). The reserve is a scenario parameter inspired by "
           "14 CFR 121.639; this is not a dispatch-fuel or FAA compliance check.",
    "W-1": "Simulated wake-separation profile (seconds, config.simulation.wake_separation_s) informed by "
           "FAA JO 7110.65 category concepts. No universal real-airport value is claimed.",
    "R-1": "Simulated runway resource model: landing must be an offered, unoccupied arrival slot and the "
           "arrivals in that clock hour (this flight counted once) must not exceed the declared capacity.",
    "T-1": "Simulated taxiway topology: the gate's taxi route must avoid every closed taxiway.",
    "G-1": "Simulated gate compatibility: the gate's maximum aircraft class must be at least the aircraft's class.",
    "G-2": "Simulated gate schedule: occupancy [gate arrival, gate release + buffer) must not overlap another "
           "occupant's [start, end + buffer). Half-open intervals; exact adjacency passes.",
    "G-3": "Explicit simulation assumption: service time at the gate must be at least the turnaround minimum "
           "and the candidate's coupled times (holding, landing, taxi-in, gate arrival, release) must agree.",
    "C-1": "Simulated crew roster: a crew assigned to the gate must be on shift when the aircraft reaches it. "
           "Work past the shift end is costed as overtime, not forbidden.",
}

CLASS_ORDER = ["regional", "narrowbody", "widebody"]   # gate max_class must be >= aircraft class
_HHMM = re.compile(r"^(\d{2}):(\d{2})$")


class MissingInput(ValueError):
    """A required simulated input is absent or malformed. The rule that needs it fails."""


# --------------------------------------------------------------------------- config

def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else Path(__file__).with_name("config.yaml")
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise MissingInput(f"{p} did not parse to a mapping")
    return cfg


# --------------------------------------------------------------------------- time helpers

def issue_time(scenario: Scenario) -> datetime:
    try:
        return datetime.fromisoformat(scenario.issue_time)
    except (TypeError, ValueError) as e:
        raise MissingInput(f"scenario.issue_time {scenario.issue_time!r} is not an ISO datetime") from e


def parse_time(value: Any, issue: datetime, label: str = "time") -> datetime:
    """ISO datetime, or 'HH:MM' on the issue date (next day if more than 12 h before the issue time)."""
    if not isinstance(value, str):
        raise MissingInput(f"{label} must be a string, got {type(value).__name__}")
    if "T" in value:
        try:
            t = datetime.fromisoformat(value)
        except ValueError as e:
            raise MissingInput(f"{label} {value!r} is not an ISO datetime") from e
        if (t.tzinfo is None) != (issue.tzinfo is None):
            raise MissingInput(f"{label} {value!r} mixes naive and aware datetimes with issue_time")
        return t
    m = _HHMM.match(value)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise MissingInput(f"{label} {value!r} is not HH:MM")
    t = issue.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    if t < issue - timedelta(hours=12):
        t += timedelta(days=1)
    return t


def minutes(a: datetime, b: datetime) -> float:
    """b - a in minutes."""
    return (b - a).total_seconds() / 60.0


def hhmm(t: datetime | None) -> str | None:
    return None if t is None else t.strftime("%H:%M")


def _num(value: Any, label: str, *, minimum: float | None = None, integer: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MissingInput(f"{label} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise MissingInput(f"{label} must be finite, got {value!r}")
    if integer and int(value) != value:
        raise MissingInput(f"{label} must be an integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise MissingInput(f"{label} must be >= {minimum}, got {value!r}")
    return value


def _get(state: dict, key: str, label: str, types: tuple = ()) -> Any:
    if not isinstance(state, dict) or key not in state:
        raise MissingInput(f"{label}.{key} is required")
    v = state[key]
    if types and not isinstance(v, types):
        raise MissingInput(f"{label}.{key} has the wrong type ({type(v).__name__})")
    return v


def _state(scenario: Scenario, agent: str) -> dict:
    s = scenario.simulated.get(agent)
    if not isinstance(s, dict):
        raise MissingInput(f"scenario.simulated.{agent} is required")
    return s


def base_eta(scenario: Scenario, issue: datetime | None = None) -> datetime:
    issue = issue or issue_time(scenario)
    return parse_time(_get(_state(scenario, "atc"), "base_eta", "atc"), issue, "atc.base_eta")


def gate_of(scenario: Scenario, gate_id: str) -> dict:
    gates = _get(_state(scenario, "ground"), "gates", "ground", (list,))
    for g in gates:
        if isinstance(g, dict) and g.get("gate_id") == gate_id:
            return g
    raise MissingInput(f"ground.gates has no gate {gate_id!r}")


def _sim_params(scenario: Scenario, config: dict) -> tuple[int, int]:
    """(gate_buffer_min, turnaround_min): ground-state value, else config.simulation."""
    ground = _state(scenario, "ground")
    sim = config.get("simulation") or {}
    buf = ground.get("gate_buffer_min", sim.get("gate_buffer_min"))
    turn = ground.get("turnaround_min", sim.get("turnaround_min"))
    if buf is None or turn is None:
        raise MissingInput("gate_buffer_min and turnaround_min must be set in ground state or config.simulation")
    return int(_num(buf, "gate_buffer_min", minimum=0)), int(_num(turn, "turnaround_min", minimum=0))


# --------------------------------------------------------------------------- candidate times

@dataclass(frozen=True)
class _Times:
    issue: datetime
    landing: datetime
    gate_arrival: datetime
    gate_release: datetime


def candidate_times(candidate: Candidate, scenario: Scenario) -> _Times:
    issue = issue_time(scenario)
    _num(candidate.extra_holding_min, "candidate.extra_holding_min", minimum=0, integer=True)
    return _Times(
        issue=issue,
        landing=parse_time(candidate.landing, issue, "candidate.landing"),
        gate_arrival=parse_time(candidate.gate_arrival, issue, "candidate.gate_arrival"),
        gate_release=parse_time(candidate.gate_release, issue, "candidate.gate_release"),
    )


# --------------------------------------------------------------------------- the eight rules

def fuel_at_base_eta_kg(scenario: Scenario) -> tuple[float, dict]:
    """Fuel on board at issue time minus cruise burn until the base ETA (simulated)."""
    issue = issue_time(scenario)
    pilot = _state(scenario, "pilot")
    fob = _num(_get(pilot, "fuel_on_board_kg", "pilot"), "pilot.fuel_on_board_kg", minimum=0)
    cruise = _num(_get(pilot, "cruise_burn_kg_per_min", "pilot"), "pilot.cruise_burn_kg_per_min", minimum=0)
    to_eta = minutes(issue, base_eta(scenario, issue))
    if to_eta < 0:
        raise MissingInput("atc.base_eta is before the issue time")
    return fob - cruise * to_eta, {"fuel_on_board_kg": fob, "cruise_burn_kg_per_min": cruise,
                                   "minutes_issue_to_base_eta": round(to_eta, 1)}


def _f1(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    pilot = _state(s, "pilot")
    at_eta, inputs = fuel_at_base_eta_kg(s)
    burn = _num(_get(pilot, "holding_burn_kg_per_min", "pilot"), "pilot.holding_burn_kg_per_min", minimum=0)
    reserve = _num(_get(pilot, "reserve_kg", "pilot"), "pilot.reserve_kg", minimum=0)
    hold = _num(c.extra_holding_min, "candidate.extra_holding_min", minimum=0, integer=True)
    at_landing = at_eta - hold * burn
    inputs.update({"fuel_at_base_eta_kg": round(at_eta, 1), "holding_burn_kg_per_min": burn,
                   "extra_holding_min": hold, "fuel_at_landing_kg": round(at_landing, 1), "reserve_kg": reserve})
    ok = at_landing >= reserve
    return ok, inputs, (f"{hold:.0f} min extra holding burns {hold * burn:.0f} kg; {at_landing:.0f} kg at landing "
                        f"{'meets' if ok else 'is below'} the {reserve:.0f} kg scenario reserve.")


def _slots(atc: dict, issue: datetime) -> list[tuple[dict, datetime]]:
    out = []
    for sl in _get(atc, "slots", "atc", (list,)):
        if not isinstance(sl, dict):
            raise MissingInput("atc.slots entries must be objects")
        out.append((sl, parse_time(_get(sl, "time", "atc.slots[]"), issue, "atc.slots[].time")))
    return out


def _w1(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    t = candidate_times(c, s)
    atc = _state(s, "atc")
    focal = _get(atc, "own_wake", "atc", (str,))
    table = (cfg.get("simulation") or {}).get("wake_separation_s")
    if not isinstance(table, dict):
        raise MissingInput("config.simulation.wake_separation_s is required")
    leader = None
    for sl, st in _slots(atc, t.issue):
        if sl.get("occupant") is not None and st < t.landing and (leader is None or st > leader[1]):
            leader = (sl, st)
    if leader is None:
        return True, {"landing": hhmm(t.landing), "preceding": None, "follower_wake": focal}, \
            "No occupied simulated arrival slot before this landing; no spacing requirement applies."
    sl, st = leader
    lead = _get(sl, "occupant_wake", "atc.slots[]", (str,))
    pair = f"{lead}-{focal}"
    gap_s = (t.landing - st).total_seconds()
    inputs = {"landing": hhmm(t.landing), "preceding": sl.get("occupant"), "preceding_slot": sl.get("slot_id"),
              "preceding_time": hhmm(st), "pair": pair, "gap_s": gap_s, "required_s": table.get(pair)}
    if pair not in table:
        return False, inputs, f"No simulated separation profile for wake pair {pair}; cannot pass."
    req = _num(table[pair], f"wake_separation_s[{pair}]", minimum=0)
    ok = gap_s >= req
    return ok, inputs, (f"{gap_s:.0f} s behind {sl.get('occupant')} ({lead}); profile {pair} requires "
                        f"{req:.0f} s: {'met' if ok else 'not met'}.")


def _r1(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    t = candidate_times(c, s)
    atc = _state(s, "atc")
    cap = int(_num(_get(atc, "runway_capacity_per_hour", "atc"), "atc.runway_capacity_per_hour", minimum=0, integer=True))
    slots = _slots(atc, t.issue)
    hour0 = t.landing.replace(minute=0, second=0, microsecond=0)
    hour1 = hour0 + timedelta(hours=1)
    in_hour = [sl.get("occupant") for sl, st in slots if sl.get("occupant") is not None and hour0 <= st < hour1]
    mine = [sl for sl, st in slots if st == t.landing]
    inputs = {"landing": hhmm(t.landing), "slot_id": mine[0].get("slot_id") if mine else None,
              "occupant": mine[0].get("occupant") if mine else None,
              "occupant_flexible": mine[0].get("occupant_flexible") if mine else None,
              "interval": f"{hhmm(hour0)}-{hhmm(hour1)}", "other_arrivals_in_interval": len(in_hour),
              "focal_counted_once": 1, "arrivals_in_interval": len(in_hour) + 1, "capacity_per_hour": cap,
              "runway": atc.get("runway")}
    if not mine:
        return False, inputs, f"{hhmm(t.landing)} is not an offered arrival slot."
    if mine[0].get("occupant") is not None:
        flex = " (flexible: ATC_EARLIER_SLOT can resequence it)" if mine[0].get("occupant_flexible") else ""
        return False, inputs, f"Slot {mine[0].get('slot_id')} is occupied by {mine[0]['occupant']}{flex}."
    ok = len(in_hour) + 1 <= cap
    return ok, inputs, (f"Slot {mine[0].get('slot_id')} is free; {len(in_hour) + 1} arrivals in {inputs['interval']} "
                        f"against capacity {cap}: {'within' if ok else 'exceeds'} the simulated runway capacity.")


def _t1(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    closed = _get(_state(s, "atc"), "closed_taxiways", "atc", (list,))
    route = _get(gate_of(s, c.gate), "taxi_route", f"ground.gates[{c.gate}]", (list,))
    blocked = [seg for seg in route if seg in set(closed)]
    inputs = {"gate": c.gate, "route": route, "closed_taxiways": closed, "blocked_segments": blocked}
    return (not blocked), inputs, ("Route avoids every closed taxiway." if not blocked
                                   else f"Route uses closed taxiway(s) {blocked}.")


def _g1(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    cls = _get(_state(s, "ground"), "aircraft_class", "ground", (str,))
    max_cls = _get(gate_of(s, c.gate), "max_class", f"ground.gates[{c.gate}]", (str,))
    inputs = {"gate": c.gate, "aircraft_class": cls, "gate_max_class": max_cls, "class_order": CLASS_ORDER}
    if cls not in CLASS_ORDER or max_cls not in CLASS_ORDER:
        raise MissingInput(f"unknown aircraft class {cls!r} or gate max_class {max_cls!r}; known: {CLASS_ORDER}")
    ok = CLASS_ORDER.index(cls) <= CLASS_ORDER.index(max_cls)
    return ok, inputs, (f"Gate {c.gate} (max {max_cls}) accepts a {cls}." if ok
                        else f"Gate {c.gate} (max {max_cls}) cannot take a {cls}.")


def _g2(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    t = candidate_times(c, s)
    buffer_min, _ = _sim_params(s, cfg)
    occupancy = _get(gate_of(s, c.gate), "occupancy", f"ground.gates[{c.gate}]", (list,))
    if t.gate_release < t.gate_arrival:
        raise MissingInput("candidate.gate_release is before gate_arrival")
    a0, a1 = t.gate_arrival, t.gate_release + timedelta(minutes=buffer_min)
    conflicts = []
    for b in occupancy:
        b0 = parse_time(_get(b, "start", "occupancy"), t.issue, "occupancy.start")
        b1 = parse_time(_get(b, "end", "occupancy"), t.issue, "occupancy.end") + timedelta(minutes=buffer_min)
        if b1 < b0:
            raise MissingInput(f"occupancy by {b.get('occupant')} ends before it starts")
        if a0 < b1 and b0 < a1:
            conflicts.append({"occupant": b.get("occupant"), "busy_until_incl_buffer": hhmm(b1)})
    inputs = {"gate": c.gate, "occupancy": [hhmm(a0), hhmm(a1)], "buffer_min": buffer_min, "conflicts": conflicts}
    ok = not conflicts
    return ok, inputs, (f"Gate {c.gate} free for [{hhmm(a0)}, {hhmm(a1)}) including {buffer_min} min buffer."
                        if ok else f"Gate {c.gate} overlaps {len(conflicts)} other occupant(s): "
                                   + ", ".join(f"{x['occupant']} until {x['busy_until_incl_buffer']}" for x in conflicts))


def _g3(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    t = candidate_times(c, s)
    _, turnaround = _sim_params(s, cfg)
    taxi = _num(_get(gate_of(s, c.gate), "taxi_in_min", f"ground.gates[{c.gate}]"), "taxi_in_min", minimum=0)
    eta = base_eta(s, t.issue)
    problems = []
    if t.landing < t.issue:
        problems.append(f"landing {hhmm(t.landing)} is before the issue time {hhmm(t.issue)}")
    if t.landing < eta:
        problems.append(f"landing {hhmm(t.landing)} is before the base ETA {hhmm(eta)}")
    elif abs(minutes(eta, t.landing) - c.extra_holding_min) > 1e-9:
        problems.append(f"extra_holding_min {c.extra_holding_min} does not equal landing - base ETA "
                        f"({minutes(eta, t.landing):.0f} min)")
    if t.gate_arrival < t.landing:
        problems.append("gate_arrival is before landing")
    elif abs(minutes(t.landing, t.gate_arrival) - taxi) > 1e-9:
        problems.append(f"gate_arrival - landing = {minutes(t.landing, t.gate_arrival):.0f} min, "
                        f"but gate {c.gate} taxi-in is {taxi:.0f} min")
    service = minutes(t.gate_arrival, t.gate_release)
    if service < 0:
        problems.append("gate_release is before gate_arrival")
    elif service < turnaround:
        problems.append(f"service {service:.0f} min is below the {turnaround} min turnaround minimum")
    inputs = {"base_eta": hhmm(eta), "landing": hhmm(t.landing), "extra_holding_min": c.extra_holding_min,
              "gate_arrival": hhmm(t.gate_arrival), "gate_release": hhmm(t.gate_release),
              "taxi_in_min": taxi, "service_min": service, "turnaround_min": turnaround}
    ok = not problems
    return ok, inputs, (f"Service {service:.0f} min meets the {turnaround} min turnaround; coupled times consistent."
                        if ok else "; ".join(problems) + ".")


def eligible_crews(c: Candidate, s: Scenario) -> tuple[list[dict], list[str]]:
    """Crews assigned to the candidate's gate and on shift at gate arrival, plus reasons for the others."""
    t = candidate_times(c, s)
    crews = _get(_state(s, "ground"), "crews", "ground", (list,))
    ok, why = [], []
    for crew in sorted(crews, key=lambda x: str(x.get("crew_id"))):
        if not isinstance(crew, dict) or "crew_id" not in crew:
            raise MissingInput("ground.crews entries need a crew_id")
        cid = crew["crew_id"]
        if _get(crew, "assigned_gate", f"crew {cid}") != c.gate:
            why.append(f"{cid}: assigned to {crew['assigned_gate']}, not {c.gate}")
            continue
        s0 = parse_time(_get(crew, "shift_start", f"crew {cid}"), t.issue, "shift_start")
        s1 = parse_time(_get(crew, "shift_end", f"crew {cid}"), t.issue, "shift_end")
        if not (s0 <= t.gate_arrival <= s1):
            why.append(f"{cid}: shift {hhmm(s0)}-{hhmm(s1)} does not cover gate arrival {hhmm(t.gate_arrival)}")
            continue
        ok.append(crew)
    return ok, why


def _c1(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    t = candidate_times(c, s)
    ok, why = eligible_crews(c, s)
    inputs = {"gate": c.gate, "gate_arrival": hhmm(t.gate_arrival), "eligible_crews": [x["crew_id"] for x in ok],
              "ineligible": why}
    if ok:
        moved = f" (reassigned from {ok[0]['reassigned_from']})" if ok[0].get("reassigned_from") else ""
        return True, inputs, f"Crew {ok[0]['crew_id']}{moved} is on shift at gate {c.gate} when the aircraft arrives."
    return False, inputs, ("No crew on shift at gate " + c.gate + ": " + ("; ".join(why) if why else "no crews declared")
                           + ". GROUND_REASSIGN_CREW can move a reassignable crew here.")


_RULE_FNS: dict[str, Callable[[Candidate, Scenario, dict], tuple[bool, dict, str]]] = {
    "F-1": _f1, "W-1": _w1, "R-1": _r1, "T-1": _t1, "G-1": _g1, "G-2": _g2, "G-3": _g3, "C-1": _c1,
}


def _run(rule_id: str, c: Candidate, s: Scenario, cfg: dict) -> CheckResult:
    try:
        passed, inputs, explanation = _RULE_FNS[rule_id](c, s, cfg)
    except MissingInput as e:
        passed, inputs, explanation = False, {"error": str(e)}, f"Cannot evaluate: {e}. Missing or invalid input fails."
    return CheckResult(rule_id=rule_id, basis=BASIS[rule_id], inputs=inputs, passed=bool(passed),
                       explanation=explanation)


def check(candidate: Candidate, scenario: Scenario, config: dict | None = None) -> list[CheckResult]:
    """All eight rules for one candidate. Never raises for bad simulated input: it fails the rule."""
    cfg = config if config is not None else load_config()
    return [_run(r, candidate, scenario, cfg) for r in RULES]


def check_all(candidates: list[Candidate], scenario: Scenario, config: dict | None = None) -> dict[str, list[CheckResult]]:
    cfg = config if config is not None else load_config()
    ids = [c.id for c in candidates]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate candidate ids: {ids}")
    return {c.id: check(c, scenario, cfg) for c in candidates}


def feasible(results: list[CheckResult]) -> bool:
    return bool(results) and all(r.passed for r in results)


def failed_rules(results: list[CheckResult]) -> list[str]:
    return [r.rule_id for r in results if not r.passed]
