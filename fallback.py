"""Deterministic solver and heuristic baseline. (Yizhuo)

solve():     lowest weighted cost among fully feasible candidates, ties broken by candidate ID.
decide():    the same choice as a log-ready dict with an explicit escalation when nothing is feasible.
heuristic(): "delay the ETA by the recorded delay and keep the planned gate", checked and costed with the
             same rules so its infeasibility and cost can be reported separately.
"""
from __future__ import annotations

from datetime import timedelta

import re

import checker
import costs as costs_mod
from checker import MissingInput, _get, _state, failed_rules, feasible, hhmm, issue_time, parse_time
from models import Candidate, CandidateCost, CheckResult, Scenario

ESCALATION_TEXT = "No feasible plan within the modelled options"
RULE_TEXT = "Lowest-cost candidate that passes every check; ties by candidate ID"


def _cost_value(c) -> float | None:
    if c is None:
        return None
    if isinstance(c, CandidateCost):
        return c.total_usd
    if isinstance(c, dict):
        return float(c["total_usd"])
    return float(c)


def id_key(cid: str) -> tuple:
    """Natural order so C2 < C10: ('C', 2) < ('C', 10). Non-matching ids compare as strings."""
    m = re.match(r"^([A-Za-z_-]*)(\d+)$", str(cid))
    return (0, m.group(1), int(m.group(2))) if m else (1, str(cid), 0)


def _passed(results) -> bool:
    if not results:
        return False
    return all((r.passed if isinstance(r, CheckResult) else bool(r["passed"])) for r in results)


def rank(candidates: list[Candidate], checks: dict, costs: dict) -> list[dict]:
    """Every candidate with feasibility, cost and the failed rules, sorted the way solve() chooses."""
    rows = []
    for c in candidates:
        if c.id not in checks:
            raise MissingInput(f"no check results for candidate {c.id}")
        if c.id not in costs:
            raise MissingInput(f"no cost for candidate {c.id}")
        res = checks[c.id]
        ok, value = _passed(res), _cost_value(costs[c.id])
        if ok and value is None:
            raise MissingInput(f"feasible candidate {c.id} has no cost; cannot rank it")
        rows.append({"id": c.id, "feasible": ok, "total_usd": value,
                     "failed": [r.rule_id if isinstance(r, CheckResult) else r["rule_id"]
                                for r in res if not (r.passed if isinstance(r, CheckResult) else r["passed"])]})
    return sorted(rows, key=lambda r: (not r["feasible"], r["total_usd"] if r["total_usd"] is not None else float("inf"),
                                       id_key(r["id"])))


def solve(candidates: list[Candidate], checks: dict, costs: dict) -> str | None:
    """Lowest-cost feasible candidate, ties broken by candidate ID. None means escalate."""
    rows = [r for r in rank(candidates, checks, costs) if r["feasible"]]
    return rows[0]["id"] if rows else None


def decide(candidates: list[Candidate], checks: dict, costs: dict) -> dict:
    """Log-ready fallback block (docs/LOG_FORMAT.md) plus an outcome type."""
    rows = rank(candidates, checks, costs)
    feasible_ids = [r["id"] for r in rows if r["feasible"]]
    chosen = feasible_ids[0] if feasible_ids else None
    if chosen is None:
        return {"outcome": "escalation", "candidate": None, "rule": RULE_TEXT, "feasible": [],
                "reason": f"{ESCALATION_TEXT}. {len(candidates)} candidate(s) evaluated, none passed every check. "
                          f"Escalate to the duty manager.", "ranking": rows}
    tied = [r["id"] for r in rows if r["feasible"] and r["total_usd"] == rows[0]["total_usd"]]
    reason = f"{chosen} is the lowest-cost feasible candidate ({rows[0]['total_usd']:.2f} USD-equivalent)."
    if len(tied) > 1:
        reason += f" Tie between {tied} broken by candidate ID."
    return {"outcome": "fallback", "candidate": chosen, "rule": RULE_TEXT, "feasible": feasible_ids,
            "reason": reason, "ranking": rows}


def run_pipeline(candidates: list[Candidate], scenario: Scenario, config: dict | None = None) -> dict:
    """Checks, costs and deterministic decision for one scenario. No LLM involved."""
    cfg = config if config is not None else checker.load_config()
    checks = checker.check_all(candidates, scenario, cfg)
    weights = costs_mod.weights_from_config(cfg)
    cost_map = costs_mod.cost_all(candidates, scenario, weights, strict=False)
    return {"checks": checks, "costs": cost_map, "weights": weights,
            "cost_errors": [cid for cid, v in cost_map.items() if v is None],
            "decision": decide(candidates, checks, cost_map)}


def heuristic_candidate(scenario: Scenario, config: dict | None = None) -> Candidate:
    """Historical outcome: scheduled arrival + recorded arrival delay (= actual arrival), planned gate.

    The baseline ETA is NOT used here, so the recorded delay is counted exactly once. Any part of the
    actual arrival later than the simulated baseline ETA is treated as airborne holding (simulated
    assumption) so F-1 can be evaluated.
    """
    cfg = config if config is not None else checker.load_config()
    issue = issue_time(scenario)
    atc, ground = _state(scenario, "atc"), _state(scenario, "ground")
    h = scenario.historical
    sched = parse_time(h.scheduled_arrival, issue, "historical.scheduled_arrival")
    landing = sched + timedelta(minutes=int(h.arrival_delay_min))
    baseline = parse_time(_get(atc, "baseline_eta", "atc"), issue, "atc.baseline_eta")
    hold = max(0, int(round((landing - baseline).total_seconds() / 60)))
    taxi = int(_get(atc, "taxi_in_min", "atc"))
    _, turnaround = checker._sim_params(scenario, cfg)
    gate_arrival = landing + timedelta(minutes=taxi)
    return Candidate(id="H", landing=hhmm(landing), extra_holding_min=hold,
                     gate=str(_get(ground, "planned_gate", "ground")), concession=None,
                     gate_arrival=hhmm(gate_arrival), gate_release=hhmm(gate_arrival + timedelta(minutes=turnaround)))


def heuristic(scenario: Scenario, config: dict | None = None) -> dict:
    """Delay ETA by the recorded delay and keep the planned gate. Checked and costed like any candidate."""
    cfg = config if config is not None else checker.load_config()
    try:
        cand = heuristic_candidate(scenario, cfg)
    except MissingInput as e:
        return {"plan": "Delay ETA by recorded delay, keep planned gate", "feasible": False,
                "failed": ["INPUT"], "error": str(e), "candidate": None, "cost": None}
    results = checker.check(cand, scenario, cfg)
    out = {"plan": f"Delay ETA by recorded delay ({scenario.historical.arrival_delay_min} min), "
                   f"keep planned gate {cand.gate}",
           "candidate": cand.model_dump(), "feasible": feasible(results), "failed": failed_rules(results),
           "checks": [r.model_dump() for r in results],
           "assumption": "Simulated: arrival later than the baseline ETA is treated as airborne holding."}
    try:
        out["cost"] = costs_mod.cost(cand, scenario, costs_mod.weights_from_config(cfg)).model_dump()
    except MissingInput as e:
        out["cost"] = None
        out["cost_error"] = str(e)
    return out
