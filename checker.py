"""Hard checks F-1, W-1, R-1, T-1, G-1, G-2, G-3, C-1 and concession application. (Yizhuo)

Every check is a simplified SIMULATION rule. None of them establishes FAA compliance.

Inputs come from the agreed ``models.Scenario`` / ``models.Candidate``. The keys the
checker reads inside ``scenario.simulated[agent]`` are documented in
docs/CHECKER_INPUTS.md. A missing or malformed required input FAILS the rule that
needs it; nothing passes silently.

Time handling: every clock value is either "HH:MM" on the scenario's issue date (rolled
to the next day when it is more than 12 h before the issue time) or a full ISO
datetime. One time zone is assumed throughout (the scenario's local zone).

Public API
----------
check(candidate, scenario, config=None) -> list[CheckResult]      one candidate, all 8 rules
check_all(candidates, scenario, config=None) -> dict[id, list]    every candidate
feasible(results) -> bool                                         all rules passed
apply_concessions(scenario, concessions, state_version=1) -> AdjustedState
load_config(path=None) -> dict                                    config.yaml as a dict
"""
from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import yaml

from models import Candidate, CheckResult, Scenario

RULES = ["F-1", "W-1", "R-1", "T-1", "G-1", "G-2", "G-3", "C-1"]

BASIS = {
    "F-1": "Simplified simulation: fuel at baseline ETA minus holding burn must meet the scenario "
           "reserve (kg). The reserve figure is a scenario parameter inspired by 14 CFR 121.639; "
           "this is not a dispatch-fuel or FAA compliance check.",
    "W-1": "Simulated wake-separation profile (seconds) informed by FAA JO 7110.65 category "
           "concepts. No universal real-airport value is claimed.",
    "R-1": "Simulated runway resource model: landing must be an offered slot and the arrivals in "
           "its capacity interval (focal flight counted once) must not exceed the declared capacity.",
    "T-1": "Simulated taxiway topology: the gate's taxi route must avoid every closed taxiway.",
    "G-1": "Simulated gate compatibility: the gate's declared classes must include the aircraft class.",
    "G-2": "Simulated gate schedule: occupancy [gate arrival, gate release + buffer) must not overlap "
           "another booking's [start, end + buffer). Half-open intervals; exact adjacency passes.",
    "G-3": "Explicit simulation assumption: service time at the gate must be at least the turnaround "
           "minimum and the candidate's coupled times must be consistent.",
    "C-1": "Simulated crew roster: one crew must cover the gate for the whole service interval with no "
           "overlapping assignment. A reassignment never removes crew from another active job.",
}

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
    """'HH:MM' on the issue date (next day if >12 h before the issue time) or an ISO datetime."""
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


def hhmm(t: datetime) -> str:
    return t.strftime("%H:%M")


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
    if key not in state:
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


def _sim_params(scenario: Scenario, config: dict) -> tuple[int, int]:
    """(gate_buffer_min, turnaround_min): ground-state override, else config.simulation."""
    ground = _state(scenario, "ground")
    sim = config.get("simulation") or {}
    buf = ground.get("gate_buffer_min", sim.get("gate_buffer_min"))
    turn = ground.get("turnaround_min", sim.get("turnaround_min"))
    if buf is None or turn is None:
        raise MissingInput("gate_buffer_min and turnaround_min must be set in config.simulation or ground state")
    return int(_num(buf, "gate_buffer_min", minimum=0)), int(_num(turn, "turnaround_min", minimum=0))


# --------------------------------------------------------------------------- the eight rules

def _f1(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    pilot = _state(s, "pilot")
    fuel = _num(_get(pilot, "fuel_at_baseline_eta_kg", "pilot"), "pilot.fuel_at_baseline_eta_kg", minimum=0)
    burn = _num(_get(pilot, "holding_burn_kg_per_min", "pilot"), "pilot.holding_burn_kg_per_min", minimum=0)
    reserve = _num(_get(pilot, "reserve_kg", "pilot"), "pilot.reserve_kg", minimum=0)
    hold = _num(c.extra_holding_min, "candidate.extra_holding_min", minimum=0, integer=True)
    at_landing = fuel - hold * burn
    inputs = {"fuel_at_baseline_eta_kg": fuel, "holding_burn_kg_per_min": burn,
              "extra_holding_min": hold, "fuel_at_landing_kg": round(at_landing, 1), "reserve_kg": reserve}
    ok = at_landing >= reserve
    return ok, inputs, (f"{hold} min extra holding burns {hold * burn:.0f} kg; {at_landing:.0f} kg at landing "
                        f"{'meets' if ok else 'is below'} the {reserve:.0f} kg scenario reserve.")


def _w1(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    t = candidate_times(c, s)
    atc = _state(s, "atc")
    focal = _get(atc, "wake_category", "atc", (str,))
    table = _get(atc, "wake_separation_s", "atc", (dict,))
    others = _get(atc, "other_arrivals", "atc", (list,))
    leader = None
    for o in others:
        if not isinstance(o, dict):
            raise MissingInput("atc.other_arrivals entries must be objects")
        ot = parse_time(_get(o, "time", "atc.other_arrivals[]"), t.issue, "atc.other_arrivals[].time")
        if ot <= t.landing and (leader is None or ot > leader[1]):
            leader = (o, ot)
    if leader is None:
        return True, {"landing": hhmm(t.landing), "preceding": None, "follower_category": focal}, \
            "No preceding simulated arrival at or before this landing; no spacing requirement applies."
    o, ot = leader
    lead_cat = _get(o, "wake_category", "atc.other_arrivals[]", (str,))
    pair = f"{lead_cat}-{focal}"
    gap_s = (t.landing - ot).total_seconds()
    inputs = {"landing": hhmm(t.landing), "preceding": o.get("callsign"), "preceding_time": hhmm(ot),
              "pair": pair, "gap_s": gap_s, "required_s": table.get(pair)}
    if pair not in table:
        return False, inputs, f"No simulated separation profile for category pair {pair}; cannot pass."
    req = _num(table[pair], f"atc.wake_separation_s[{pair}]", minimum=0)
    ok = gap_s >= req
    return ok, inputs, (f"{gap_s:.0f} s behind {o.get('callsign')} ({lead_cat}); profile {pair} requires "
                        f"{req:.0f} s: {'met' if ok else 'not met'}.")


def _r1(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    t = candidate_times(c, s)
    atc = _state(s, "atc")
    slots = [parse_time(x, t.issue, "atc.slots[]") for x in _get(atc, "slots", "atc", (list,))]
    rw = _get(atc, "runway", "atc", (dict,))
    cap = int(_num(_get(rw, "capacity_per_interval", "atc.runway"), "atc.runway.capacity_per_interval", minimum=0, integer=True))
    interval = int(_num(_get(rw, "interval_min", "atc.runway"), "atc.runway.interval_min", minimum=1, integer=True))
    others = _get(atc, "other_arrivals", "atc", (list,))

    def bin_of(x: datetime) -> int:
        return int((x - t.issue.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() // 60) // interval

    b = bin_of(t.landing)
    in_bin = [o.get("callsign") for o in others
              if bin_of(parse_time(_get(o, "time", "atc.other_arrivals[]"), t.issue)) == b]
    start = t.issue.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=b * interval)
    inputs = {"landing": hhmm(t.landing), "offered_slots": [hhmm(x) for x in slots],
              "interval": f"{hhmm(start)}-{hhmm(start + timedelta(minutes=interval))}",
              "other_arrivals_in_interval": in_bin, "focal_counted_once": 1,
              "arrivals_in_interval": len(in_bin) + 1, "capacity_per_interval": cap, "runway": rw.get("id")}
    if t.landing not in slots:
        return False, inputs, f"{hhmm(t.landing)} is not an offered arrival slot."
    ok = len(in_bin) + 1 <= cap
    return ok, inputs, (f"{len(in_bin) + 1} arrivals in {inputs['interval']} against capacity {cap}: "
                        f"{'within' if ok else 'exceeds'} the simulated runway capacity.")


def _t1(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    atc = _state(s, "atc")
    closed = _get(atc, "closed_taxiways", "atc", (list,))
    routes = _get(atc, "taxi_routes", "atc", (dict,))
    if c.gate not in routes:
        raise MissingInput(f"atc.taxi_routes has no route for gate {c.gate!r}")
    route = routes[c.gate]
    if not isinstance(route, list):
        raise MissingInput(f"atc.taxi_routes[{c.gate!r}] must be a list of segments")
    blocked = [seg for seg in route if seg in set(closed)]
    inputs = {"gate": c.gate, "route": route, "closed_taxiways": closed, "blocked_segments": blocked}
    return (not blocked), inputs, ("Route avoids every closed taxiway." if not blocked
                                   else f"Route uses closed taxiway(s) {blocked}.")


def _g1(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    ground = _state(s, "ground")
    cls = _get(ground, "aircraft_class", "ground", (str,))
    gates = _get(ground, "gates", "ground", (dict,))
    if c.gate not in gates:
        raise MissingInput(f"ground.gates has no gate {c.gate!r}")
    classes = _get(gates[c.gate], "classes", f"ground.gates[{c.gate}]", (list,))
    ok = cls in classes
    return ok, {"gate": c.gate, "aircraft_class": cls, "gate_classes": classes}, \
        (f"Gate {c.gate} accepts class {cls}." if ok else f"Gate {c.gate} does not accept class {cls}.")


def _g2(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    t = candidate_times(c, s)
    ground = _state(s, "ground")
    gates = _get(ground, "gates", "ground", (dict,))
    if c.gate not in gates:
        raise MissingInput(f"ground.gates has no gate {c.gate!r}")
    buffer_min, _ = _sim_params(s, cfg)
    own = ground.get("own_booking_id")
    bookings = _get(gates[c.gate], "bookings", f"ground.gates[{c.gate}]", (list,))
    if t.gate_release < t.gate_arrival:
        raise MissingInput("candidate.gate_release is before gate_arrival")
    a0, a1 = t.gate_arrival, t.gate_release + timedelta(minutes=buffer_min)
    conflicts, excluded = [], []
    for b in bookings:
        if not isinstance(b, dict) or "id" not in b:
            raise MissingInput(f"ground.gates[{c.gate}].bookings entries need an id, start and end")
        if own is not None and b["id"] == own:
            excluded.append(b["id"])
            continue
        b0 = parse_time(_get(b, "start", "booking"), t.issue, "booking.start")
        b1 = parse_time(_get(b, "end", "booking"), t.issue, "booking.end") + timedelta(minutes=buffer_min)
        if b1 < b0:
            raise MissingInput(f"booking {b['id']} ends before it starts")
        if a0 < b1 and b0 < a1:
            conflicts.append({"id": b["id"], "flight": b.get("flight"), "busy_until_incl_buffer": hhmm(b1)})
    inputs = {"gate": c.gate, "occupancy": [hhmm(a0), hhmm(a1)], "buffer_min": buffer_min,
              "conflicts": conflicts, "excluded_own_booking": excluded}
    ok = not conflicts
    return ok, inputs, (f"Gate {c.gate} free for [{hhmm(a0)}, {hhmm(a1)}) including {buffer_min} min buffer."
                        if ok else f"Gate {c.gate} overlaps {len(conflicts)} other booking(s): "
                                   + ", ".join(f"{x['id']} until {x['busy_until_incl_buffer']}" for x in conflicts))


def _g3(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    t = candidate_times(c, s)
    _, turnaround = _sim_params(s, cfg)
    atc = _state(s, "atc")
    taxi = atc.get("taxi_in_min")
    problems = []
    if t.landing < t.issue:
        problems.append(f"landing {hhmm(t.landing)} is before the issue time {hhmm(t.issue)}")
    if t.gate_arrival < t.landing:
        problems.append("gate_arrival is before landing")
    elif taxi is not None:
        taxi = _num(taxi, "atc.taxi_in_min", minimum=0)
        if abs(minutes(t.landing, t.gate_arrival) - taxi) > 1e-9:
            problems.append(f"gate_arrival - landing = {minutes(t.landing, t.gate_arrival):.0f} min, "
                            f"but the simulated taxi-in time is {taxi:.0f} min")
    service = minutes(t.gate_arrival, t.gate_release)
    if service < 0:
        problems.append("gate_release is before gate_arrival")
    elif service < turnaround:
        problems.append(f"service {service:.0f} min is below the {turnaround} min turnaround minimum")
    inputs = {"landing": hhmm(t.landing), "gate_arrival": hhmm(t.gate_arrival), "gate_release": hhmm(t.gate_release),
              "taxi_in_min": taxi, "service_min": service, "turnaround_min": turnaround}
    ok = not problems
    return ok, inputs, (f"Service {service:.0f} min meets the {turnaround} min turnaround; coupled times consistent."
                        if ok else "; ".join(problems) + ".")


def eligible_crews(c: Candidate, s: Scenario) -> tuple[list[dict], list[str]]:
    """Crews that can serve this candidate, plus per-crew reasons for the ones that cannot."""
    t = candidate_times(c, s)
    ground = _state(s, "ground")
    crews = _get(ground, "crews", "ground", (list,))
    if t.gate_release < t.gate_arrival:
        raise MissingInput("candidate.gate_release is before gate_arrival")
    ok, why = [], []
    for crew in sorted(crews, key=lambda x: str(x.get("id"))):
        if not isinstance(crew, dict) or "id" not in crew:
            raise MissingInput("ground.crews entries need an id")
        cid = crew["id"]
        gates = _get(crew, "gates", f"crew {cid}", (list,))
        if c.gate not in gates:
            why.append(f"{cid}: does not cover gate {c.gate}")
            continue
        s0 = parse_time(_get(crew, "shift_start", f"crew {cid}"), t.issue, "shift_start")
        s1 = parse_time(_get(crew, "shift_end", f"crew {cid}"), t.issue, "shift_end")
        if not (s0 <= t.gate_arrival and t.gate_release <= s1):
            why.append(f"{cid}: shift {hhmm(s0)}-{hhmm(s1)} does not cover {hhmm(t.gate_arrival)}-{hhmm(t.gate_release)}")
            continue
        clash = None
        for job in _get(crew, "assignments", f"crew {cid}", (list,)):
            j0 = parse_time(_get(job, "start", "assignment"), t.issue, "assignment.start")
            j1 = parse_time(_get(job, "end", "assignment"), t.issue, "assignment.end")
            if t.gate_arrival < j1 and j0 < t.gate_release:
                clash = job
                break
        if clash:
            why.append(f"{cid}: already assigned to {clash.get('id')} at {clash.get('gate')} "
                       f"{clash.get('start')}-{clash.get('end')}")
            continue
        ok.append(crew)
    return ok, why


def _c1(c: Candidate, s: Scenario, cfg: dict) -> tuple[bool, dict, str]:
    t = candidate_times(c, s)
    ok, why = eligible_crews(c, s)
    inputs = {"gate": c.gate, "service": [hhmm(t.gate_arrival), hhmm(t.gate_release)],
              "eligible_crews": [x["id"] for x in ok], "ineligible": why}
    if ok:
        return True, inputs, f"Crew {ok[0]['id']} covers gate {c.gate} for the whole service interval."
    return False, inputs, "No crew covers the service interval: " + ("; ".join(why) if why else "no crews declared") + "."


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


# --------------------------------------------------------------------------- concessions

@dataclass(frozen=True)
class AdjustedState:
    """A new, immutable scenario version produced by applying concessions. Recheck it."""
    scenario: Scenario
    state_version: int
    applied: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)


def _concession_fields(x: Any) -> tuple[str, str | None]:
    if isinstance(x, dict):
        return str(x.get("id")), x.get("target")
    return str(getattr(x, "id")), getattr(x, "target", None)


def fuel_safe_holding_min(scenario: Scenario) -> int:
    """Largest whole-minute holding that keeps F-1 passing (simulated)."""
    pilot = _state(scenario, "pilot")
    fuel = _num(_get(pilot, "fuel_at_baseline_eta_kg", "pilot"), "pilot.fuel_at_baseline_eta_kg", minimum=0)
    burn = _num(_get(pilot, "holding_burn_kg_per_min", "pilot"), "pilot.holding_burn_kg_per_min", minimum=0)
    reserve = _num(_get(pilot, "reserve_kg", "pilot"), "pilot.reserve_kg", minimum=0)
    if burn == 0:
        return 10 ** 6
    return max(0, int(math.floor((fuel - reserve) / burn)))


def apply_concessions(scenario: Scenario, concessions: list, state_version: int = 1) -> AdjustedState:
    """Apply allow-listed concessions to a deep copy of the simulated state.

    The source scenario is never mutated. The result carries state_version + 1 when at least
    one concession changed the state, otherwise the same version. Effects (all simulated):

    - ATC_EARLIER_SLOT target "HH:MM": the slot must be declared in atc.resequence_options;
      it is added to atc.slots and the declared neighbour moves are applied to atc.other_arrivals.
      R-1 and W-1 are rechecked afterwards, so capacity and spacing are still enforced.
    - GROUND_REASSIGN_CREW target gate: every crew whose can_reassign_to lists that gate gains it in
      crew.gates. Existing assignments stay, so C-1 still rejects an overlapping job.
    - PILOT_EXTRA_HOLDING target "N" or "N min": pilot.max_extra_holding_min becomes min(N, fuel-safe
      limit). This is a preference bound for the agents; F-1 is the hard rule either way.
    """
    sim = copy.deepcopy(dict(scenario.simulated))
    applied, rejected = [], []
    for raw in concessions:
        cid, target = _concession_fields(raw)
        rec = {"id": cid, "target": target}
        try:
            if cid == "ATC_EARLIER_SLOT":
                atc = sim["atc"]
                opts = _get(atc, "resequence_options", "atc", (list,))
                match = next((o for o in opts if o.get("slot") == target), None)
                if match is None:
                    raise MissingInput(f"slot {target!r} is not in atc.resequence_options")
                issue = issue_time(scenario)
                parse_time(target, issue, "concession.target")
                if target not in atc.setdefault("slots", []):
                    atc["slots"].append(target)
                moved = []
                for mv in match.get("moves", []):
                    for o in atc.get("other_arrivals", []):
                        if o.get("callsign") == mv.get("callsign"):
                            parse_time(mv["to"], issue, "resequence move")
                            moved.append({"callsign": o["callsign"], "from": o["time"], "to": mv["to"]})
                            o["time"] = mv["to"]
                rec["effect"] = {"slot_added": target, "moves": moved}
            elif cid == "GROUND_REASSIGN_CREW":
                crews = _get(sim["ground"], "crews", "ground", (list,))
                moved = []
                for crew in crews:
                    if target in crew.get("can_reassign_to", []) and target not in crew.get("gates", []):
                        crew.setdefault("gates", []).append(target)
                        moved.append(crew["id"])
                if not moved:
                    raise MissingInput(f"no crew declares can_reassign_to {target!r}")
                rec["effect"] = {"gate": target, "crews_now_covering": moved, "assignments_kept": True}
            elif cid == "PILOT_EXTRA_HOLDING":
                m = re.match(r"^\s*(\d+)", str(target or ""))
                if not m:
                    raise MissingInput(f"target {target!r} is not a number of minutes")
                safe = fuel_safe_holding_min(scenario)
                new = min(int(m.group(1)), safe)
                sim["pilot"]["max_extra_holding_min"] = new
                rec["effect"] = {"max_extra_holding_min": new, "fuel_safe_limit_min": safe}
            else:
                raise MissingInput(f"unknown concession id {cid!r}")
        except (MissingInput, KeyError, TypeError) as e:
            rec["reason"] = str(e)
            rejected.append(rec)
            continue
        applied.append(rec)
    new_scenario = scenario.model_copy(update={"simulated": sim}) if applied else scenario
    return AdjustedState(scenario=new_scenario, state_version=state_version + (1 if applied else 0),
                         applied=applied, rejected=rejected)
