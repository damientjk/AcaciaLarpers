"""Escalation assist: help the duty manager when no candidate plan passes every hard check.

Deterministic, plain code, no LLM and no API calls. It never picks or approves anything: it ranks the closest
plans with their exact shortfalls, names the main blocker, lists actions a human could take outside the
modelled options, and searches a small ladder of costly fixes (remote stand, call-out crew) for the cheapest
plan that checker.py passes once the fix is applied to a scenario copy.

Rules (escalation_assist_plan.md, section 3):
- A plan is only called safe if checker.check passes it. No new definition of "safe".
- F-1 (fuel reserve) and W-1 (wake spacing) are never offered for relaxation.
- Nothing is applied automatically; every suggestion is labelled as the human's decision.
"""
from __future__ import annotations

import copy
from collections import Counter
from datetime import datetime, timedelta

import checker
import costs as costs_mod
from models import Candidate, Scenario

NEVER_RELAX = {"F-1", "W-1"}
OUTSIDE = "Outside the modelled options: your decision."

# Phase 2: fixed, rule-based suggestions per blocking rule (not AI).
ACTIONS = {
    "G-2": {"title": "Gate still occupied", "relaxable": True,
            "actions": ["Use another compatible gate or a remote stand", "Ask the ramp to move the occupant",
                        "Check the gate-change notice time"]},
    "C-1": {"title": "No crew on shift at the gate", "relaxable": True,
            "actions": ["Call in an extra ground crew", "Authorise overtime for the nearest crew"]},
    "G-3": {"title": "Turnaround too short", "relaxable": True,
            "actions": ["Delay the aircraft's next departure", "Swap the aircraft for the next departure"]},
    "G-1": {"title": "Gate too small for the aircraft", "relaxable": True,
            "actions": ["Use a larger gate", "Use a remote stand with buses"]},
    "R-1": {"title": "Arrival slot taken or over capacity", "relaxable": True,
            "actions": ["Ask ATC for a slot swap", "Ask for flow control on other arrivals"]},
    "T-1": {"title": "Taxi route uses a closed taxiway", "relaxable": True,
            "actions": ["Use another taxi route", "Wait for the taxiway's reopening time"]},
    "F-1": {"title": "Fuel reserve would be broken", "relaxable": False,
            "actions": ["Never relax the reserve", "Ask for priority to land earlier", "Divert to an alternate"]},
    "W-1": {"title": "Wake spacing would be broken", "relaxable": False,
            "actions": ["Never relax spacing", "Resequence the arrivals", "Take a later slot"]},
}

DEFAULTS = {"top_n": 3, "costly_fixes": ["remote_stand", "extra_crew"], "remote_stand_taxi_in_min": 20,
            "remote_stand_usd": 900, "crew_callout_usd": 450}


def settings(config: dict | None = None) -> dict:
    cfg = config if config is not None else checker.load_config()
    return {**DEFAULTS, **(cfg.get("escalation") or {})}


# --------------------------------------------------------------------------- Phase 1: shortfalls and ranking

def _hm(s):
    try:
        return datetime.strptime(str(s)[-5:], "%H:%M")
    except (TypeError, ValueError):
        return None


def _minutes_after(start, end):
    a, b = _hm(start), _hm(end)
    if a is None or b is None:
        return None
    m = (b - a).total_seconds() / 60
    return m + 1440 if m < -720 else m  # crosses midnight


def shortfall(r) -> dict:
    """How far one failing check is from passing, read from checker.py's own inputs. Never invents a number."""
    rid, inp, expl = r["rule_id"], r.get("inputs") or {}, r.get("explanation", "")
    out = {"rule_id": rid, "amount": None, "unit": None, "explanation": expl}
    if "error" in inp:
        return {**out, "explanation": f"Not computable: {inp['error']}"}
    if rid == "F-1" and inp.get("reserve_kg") is not None and inp.get("fuel_at_landing_kg") is not None:
        return {**out, "amount": round(inp["reserve_kg"] - inp["fuel_at_landing_kg"], 1), "unit": "kg"}
    if rid == "W-1" and inp.get("required_s") is not None and inp.get("gap_s") is not None:
        return {**out, "amount": round(inp["required_s"] - inp["gap_s"], 1), "unit": "s"}
    if rid == "G-2" and inp.get("conflicts") and inp.get("occupancy"):
        until = max(inp["conflicts"], key=lambda x: _hm(x["busy_until_incl_buffer"]) or datetime.min)
        m = _minutes_after(inp["occupancy"][0], until["busy_until_incl_buffer"])
        return {**out, "amount": round(m) if m is not None else None, "unit": "min" if m is not None else None,
                "explanation": f"Gate {inp.get('gate')} busy until {until['busy_until_incl_buffer']} "
                               f"({until.get('occupant')}, incl. buffer)"}
    if rid == "G-3" and inp.get("turnaround_min") is not None and inp.get("service_min") is not None \
            and inp["service_min"] < inp["turnaround_min"]:
        return {**out, "amount": round(inp["turnaround_min"] - inp["service_min"]), "unit": "min"}
    return out  # R-1, T-1, G-1, C-1 and G-3 timing mismatches are yes/no blockers


def _as_dict(r):
    return r if isinstance(r, dict) else r.model_dump()


def _total(costs, cid):
    c = costs.get(cid)
    if c is None:
        return None
    return c["total_usd"] if isinstance(c, dict) else c.total_usd


def rank(checks: dict, costs: dict) -> list[dict]:
    """Every candidate, closest to passing first: (failing rules, any F-1/W-1, total cost, ID)."""
    rows = []
    for cid, rs in checks.items():
        rs = [_as_dict(r) for r in rs]
        failed = [r for r in rs if not r["passed"]]
        tot = _total(costs, cid)
        rows.append({"candidate": cid, "failed_rules": [r["rule_id"] for r in failed],
                     "shortfalls": [shortfall(r) for r in failed], "total_usd": tot,
                     "_key": (len(failed), any(r["rule_id"] in NEVER_RELAX for r in failed),
                              tot if tot is not None else float("inf"), cid)})
    rows.sort(key=lambda x: x["_key"])
    for r in rows:
        r.pop("_key")
    return rows


# --------------------------------------------------------------------------- Phase 3: the costly-fix ladder

def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M")


def _like(template: str, t: datetime) -> str:
    """Write a time in the same format as the candidate field it replaces (HH:MM or ISO)."""
    return t.strftime("%H:%M") if len(str(template)) <= 5 else _iso(t)


def _remote_stand(c: Candidate, s: Scenario, st: dict) -> tuple[Candidate, Scenario]:
    t = checker.candidate_times(c, s)
    taxi = int(st["remote_stand_taxi_in_min"])
    service = t.gate_release - t.gate_arrival
    arrive = t.landing + timedelta(minutes=taxi)
    sim = copy.deepcopy(s.simulated)
    # Reached over the original gate's taxiways plus an apron segment, so a closed taxiway still blocks it (T-1).
    route = list(checker.gate_of(s, c.gate).get("taxi_route") or []) + ["REMOTE-APRON"]
    sim["ground"]["gates"].append({"gate_id": "REMOTE", "max_class": "widebody", "taxi_route": route,
                                   "taxi_in_min": taxi, "occupancy": [], "simulated": True,
                                   "note": "remote stand with buses (escalation assist, rough assumption)"})
    c2 = c.model_copy(update={"gate": "REMOTE", "gate_arrival": _like(c.gate_arrival, arrive),
                              "gate_release": _like(c.gate_release, arrive + service)})
    return c2, s.model_copy(update={"simulated": sim})


def _extra_crew(c: Candidate, s: Scenario, st: dict) -> tuple[Candidate, Scenario]:
    t = checker.candidate_times(c, s)
    sim = copy.deepcopy(s.simulated)
    sim["ground"]["crews"].append({"crew_id": "CRW-CALLOUT", "assigned_gate": c.gate,
                                   "shift_start": _iso(t.gate_arrival - timedelta(minutes=30)),
                                   "shift_end": _iso(t.gate_release + timedelta(minutes=30)),
                                   "reassignable": False, "simulated": True,
                                   "note": "called-out crew (escalation assist, rough assumption)"})
    return c, s.model_copy(update={"simulated": sim})


LADDER = {  # step order matters for tie-breaks; fees are rough assumptions from config.yaml
    "remote_stand": {"step": 1, "fixes": ["G-1", "G-2"], "apply": _remote_stand, "fee": "remote_stand_usd",
                     "label": "Remote stand with buses"},
    "extra_crew": {"step": 2, "fixes": ["C-1"], "apply": _extra_crew, "fee": "crew_callout_usd",
                   "label": "Call in an extra ground crew"},
}


def _ladder_combos(enabled: list[str]) -> list[tuple[str, ...]]:
    steps = [k for k in sorted(LADDER, key=lambda k: LADDER[k]["step"]) if k in enabled]
    return [(a,) for a in steps] + [(a, b) for i, a in enumerate(steps) for b in steps[i + 1:]]


def costly_option(scenario: Scenario, candidates: list[Candidate], ranked: list[dict], cfg: dict) -> dict | None:
    """Cheapest plan that passes every check once costly fixes are applied to a scenario copy. Ties: fewer fixes,
    earlier ladder step, candidate ID. Plans that fail F-1 or W-1 are never fixed (those rules are never relaxed)."""
    st = settings(cfg)
    by_id = {c.id: c for c in candidates}
    best = None
    for row in ranked:
        if set(row["failed_rules"]) & NEVER_RELAX or row["candidate"] not in by_id:
            continue
        for combo in _ladder_combos(st["costly_fixes"]):
            c2, s2 = by_id[row["candidate"]], scenario
            try:
                for name in combo:
                    c2, s2 = LADDER[name]["apply"](c2, s2, st)
                results = checker.check(c2, s2, cfg)
                if not checker.feasible(results):
                    continue
                base = costs_mod.cost(c2, s2).total_usd
            except Exception:  # a fix that can't be checked or costed is not offered
                continue
            fees = {n: float(st[LADDER[n]["fee"]]) for n in combo}
            total = round(base + sum(fees.values()), 2)
            key = (total, len(combo), [LADDER[n]["step"] for n in combo], row["candidate"])
            if best is None or key < best[0]:
                best = (key, {"candidate": row["candidate"], "fixes": list(combo),
                              "fix_labels": [LADDER[n]["label"] for n in combo],
                              "plan": {k: getattr(c2, k) for k in ("gate", "landing", "extra_holding_min",
                                                                   "gate_arrival", "gate_release")},
                              "plan_cost_usd": round(base, 2), "fees_usd": fees, "total_usd": total,
                              "checks": [{"rule_id": r.rule_id, "passed": r.passed, "explanation": r.explanation}
                                         for r in results]})
    if best is None:
        return None
    opt = best[1]
    normal = [r["total_usd"] for r in ranked if r["total_usd"] is not None]
    opt["extra_vs_cheapest_normal_usd"] = round(opt["total_usd"] - min(normal), 2) if normal else None
    opt["label"] = "Safe but costly. " + OUTSIDE
    return opt


# --------------------------------------------------------------------------- entry points

def assist(scenario: Scenario, candidates: list[Candidate], checks: dict, costs: dict,
           config: dict | None = None) -> dict:
    """The escalation_assist block for one escalated run. `checks` and `costs` are keyed by candidate ID."""
    cfg = config if config is not None else checker.load_config()
    st = settings(cfg)
    ranked = rank(checks, costs)
    blockers = Counter(rid for r in ranked for rid in r["failed_rules"])
    top_blockers = dict(sorted(blockers.items(), key=lambda kv: (-kv[1], kv[0])))
    closest = ranked[: int(st["top_n"])]
    near = Counter(rid for r in closest for rid in r["failed_rules"])
    suggestions = [{"rule_id": rid, **ACTIONS.get(rid, {"title": rid, "relaxable": rid not in NEVER_RELAX,
                                                         "actions": []}), "label": OUTSIDE}
                   for rid, _ in sorted(near.items(), key=lambda kv: (-kv[1], kv[0]))]
    main = next(iter(top_blockers), None)
    return {
        "closest": closest,
        "top_blockers": top_blockers,
        "main_blocker": {"rule_id": main, "plans": top_blockers[main], "of": len(ranked),
                         "title": ACTIONS.get(main, {}).get("title", main)} if main else None,
        "one_rule_away": sum(1 for r in ranked if len(r["failed_rules"]) == 1),
        "suggestions": suggestions,
        "costly_option": costly_option(scenario, candidates, ranked, cfg) if st["costly_fixes"] else None,
        "note": "Deterministic plain code, no AI. Nothing is applied automatically.",
    }


def assist_from_log(log: dict, config: dict | None = None) -> dict | None:
    """For saved escalated runs without the block: rebuild it from the log's own scenario, candidates and checks."""
    if (log.get("outcome") or {}).get("type") != "escalation":
        return None
    scenario = Scenario.model_validate(log["scenario"])
    candidates = [Candidate.model_validate(c) for c in log.get("candidates", [])]
    checks = (log.get("checks") or {}).get("after_concessions") or (log.get("checks") or {}).get("before_concessions")
    return assist(scenario, candidates, checks or {}, log.get("costs") or {}, config)
