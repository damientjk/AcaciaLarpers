"""Two-round protocol, compromise, outcome, final recheck and audit log. (Damien)

app.py calls run(random=True) and run(flight=..., date=...). Both write one log to logs/
in the shape of docs/LOG_FORMAT.md and return the same dict.

Protocol:
  round 1   three parallel offers on state v1 (preferred, acceptable, cited checks, concessions)
  between   apply the offered concessions -> state v2, recheck every candidate, freeze one proposal
  round 2   three parallel accept/reject votes on that exact proposal version
  outcome   consensus  = three accepts and the final recheck passes
            fallback   = anything else; the solver decides on the base state, without unconfirmed concessions
            escalation = nothing feasible in the state the decision is made on

Candidates and costs come from the base scenario once; only the checks change with concessions.
"""
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Protocol

import agents
from agents import AGENTS, AgentResult
from models import Candidate, CandidateCost, CheckResult, Concession, Proposal, Scenario, Vote


class World(Protocol):
    """Everything the coordinator needs from the rest of the pipeline."""
    def candidates(self, s: Scenario) -> list[Candidate]: ...
    def check(self, c: Candidate, s: Scenario) -> list[CheckResult]: ...
    def cost(self, c: Candidate, s: Scenario) -> CandidateCost: ...
    def apply(self, s: Scenario, concessions: list[dict]) -> Scenario: ...
    def view(self, s: Scenario, agent: str) -> dict: ...
    def solve(self, candidates: list[Candidate], checks: dict, costs: dict) -> str | None: ...
    def heuristic(self, s: Scenario) -> dict: ...


class ModuleWorld:
    """The real pipeline: scenario.py, options.py, checker.py, costs.py, fallback.py."""
    def __init__(self, weights: dict):
        import checker, costs, fallback, options, scenario
        self.m = dict(scenario=scenario, options=options, checker=checker, costs=costs, fallback=fallback)
        self.weights = weights

    def candidates(self, s):
        return self.m["options"].generate(s)

    def check(self, c, s):
        return self.m["checker"].check(c, s)

    def cost(self, c, s):
        return self.m["costs"].cost(c, s, self.weights)

    def apply(self, s, concessions):
        return self.m["scenario"].apply_concessions(s, concessions)

    def view(self, s, agent):
        return self.m["scenario"].private_view(s, agent)

    def solve(self, candidates, checks, costs):
        return self.m["fallback"].solve(candidates, checks, costs)

    def heuristic(self, s):
        return self.m["fallback"].heuristic(s)


def _feasible(checks: dict) -> list[str]:
    return sorted(cid for cid, rs in checks.items() if all(r.passed for r in rs))


def compromise(offers: dict, feasible: list[str], costs: dict) -> tuple[str, str, list[str]]:
    """Pick the proposal. Returns (candidate, rule, in_all_acceptable)."""
    accepted = [set(o.acceptable) for o in offers.values() if o is not None]
    votes = {c: sum(c in s for s in accepted) for c in feasible}
    in_all = [c for c in feasible if len(accepted) == len(AGENTS) and votes[c] == len(AGENTS)]
    if in_all:
        best = min(in_all, key=lambda c: (costs[c].total_usd, c))
        return best, "Lowest cost among feasible candidates in all three acceptable sets", in_all
    best = min(feasible, key=lambda c: (-votes[c], costs[c].total_usd, c))
    return best, "No feasible candidate in all three acceptable sets: most acceptances, then lowest cost", in_all


def negotiate(world: World, scenario: Scenario, weights: dict, fake_agents: bool = False,
              label: str | None = None, run_id: str | None = None) -> dict:
    cfg = agents.config()["protocol"]
    t0 = time.monotonic()
    run_id = run_id or f"r-{uuid.uuid4().hex[:6]}"
    per_round = cfg["call_timeout_s"] * (1 + cfg["retries_per_call"])

    def left() -> float:
        return cfg["run_timeout_s"] - (time.monotonic() - t0)

    # State v1: candidates, costs and checks on the base scenario.
    cands = world.candidates(scenario)[: cfg["max_candidates"]]
    by_id = {c.id: c for c in cands}
    costs = {c.id: world.cost(c, scenario) for c in cands}
    before = {c.id: world.check(c, scenario) for c in cands}
    feasible_before = _feasible(before)

    # Round 1: offers.
    def brief(agent, s, checks):
        return agents.briefing(agent, world.view(s, agent), cands, checks, costs)

    r1 = agents.in_parallel(
        lambda a: agents.offer(a, brief(a, scenario, before), run_id, 1, fake_agents), min(per_round, left()))
    offers = {a: r.message for a, r in r1.items()}

    # Between rounds: apply concessions from valid offers, recheck, freeze one proposal.
    applied = [{"agent": a, **c.model_dump()} for a in AGENTS if offers[a] for c in offers[a].concessions]
    state_version = 2 if applied else 1
    after_scenario = world.apply(scenario, applied) if applied else scenario
    after = {c.id: world.check(c, after_scenario) for c in cands} if applied else before
    feasible_after = _feasible(after)

    rounds = [{"round": 1, "offers": [_offer_entry(r1[a]) for a in AGENTS]}]
    cp, r2 = None, None
    if feasible_after:
        pick, rule, in_all = compromise(offers, feasible_after, costs)
        proposal = Proposal(version=state_version, candidate=pick)
        cp = {"concessions_applied": applied, "feasible_before": feasible_before, "feasible_after": feasible_after,
              "in_all_acceptable": in_all, "rule": rule, "proposal": proposal.model_dump()}

        # Round 2: votes on exactly that proposal.
        round1 = [o for o in offers.values() if o is not None]
        r2 = agents.in_parallel(
            lambda a: agents.vote(a, brief(a, after_scenario, after), proposal, round1, run_id, fake_agents),
            min(per_round, left()))
        votes = {a: r2[a].message or Vote(agent=a, run_id=run_id, proposal_version=proposal.version,
                                          vote="abstain", rationale=f"No valid vote: {r2[a].error}")
                 for a in AGENTS}
        rounds.append({"round": 2, "votes": [{**votes[a].model_dump(), "latency_s": r2[a].latency_s,
                                              **({"error": r2[a].error} if r2[a].error else {})} for a in AGENTS]})

    # Outcome.
    final_recheck, fb = None, None
    if cp and all(v.vote == "accept" for v in votes.values()):
        recheck = world.check(by_id[pick], after_scenario)
        final_recheck = {"state_version": state_version, "passed": all(r.passed for r in recheck)}
    if final_recheck and final_recheck["passed"]:
        unlocked = []
        if pick not in feasible_before:
            unlocked = [c["id"] for c in applied if c["id"] in (by_id[pick].concession or "")]
        outcome = {"type": "consensus", "final_candidate": pick, "concessions_that_unlocked": unlocked,
                   "reason": f"All three accepted proposal v{state_version} and the final recheck passed.",
                   "final_recheck": final_recheck}
    else:
        solved = world.solve(cands, before, costs)
        fb = {"candidate": solved, "feasible": feasible_before,
              "rule": "Lowest-cost candidate that passes every check on the base state; ties by candidate ID"}
        why = _why_not_consensus(cp, r2, final_recheck)
        if solved:
            recheck = world.check(by_id[solved], scenario)
            outcome = {"type": "fallback", "final_candidate": solved, "concessions_that_unlocked": [],
                       "reason": f"{why} The rulebook decides on the base state without unconfirmed concessions.",
                       "final_recheck": {"state_version": 1, "passed": all(r.passed for r in recheck)}}
        else:
            outcome = {"type": "escalation", "final_candidate": None, "concessions_that_unlocked": [],
                       "reason": f"{why} No feasible plan within the modelled options. Escalated to the duty manager.",
                       "final_recheck": None}

    solver_pick = world.solve(cands, after, costs)
    results = list(r1.values()) + (list(r2.values()) if r2 else [])
    calls = sum(r.attempts for r in results)
    log = {
        "run_id": run_id,
        "label": label,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sample": False,
        "fake_agents": fake_agents,
        "scenario": scenario.model_dump(),
        "weights": weights,
        "candidates": [c.model_dump() for c in cands],
        "costs": {k: v.model_dump() for k, v in costs.items()},
        "checks": {"before_concessions": {k: [r.model_dump() for r in v] for k, v in before.items()},
                   "after_concessions": {k: [r.model_dump() for r in v] for k, v in after.items()}},
        "rounds": rounds,
        "compromise": cp,
        "outcome": outcome,
        "fallback": fb,
        "baselines": {"solver": {"candidate": solver_pick,
                                 "total_usd": costs[solver_pick].total_usd if solver_pick else None},
                      "heuristic": world.heuristic(scenario)},
        "human_decision": None,
        "stats": {"api_calls": calls, "retries": sum(max(r.attempts - 1, 0) for r in results),
                  "total_latency_s": round(time.monotonic() - t0, 2)},
    }
    return log


def _offer_entry(r: AgentResult) -> dict:
    if r.message is None:
        return {"agent": r.agent, "preferred": None, "acceptable": [], "constraints_cited": [], "concessions": [],
                "rationale": f"No valid offer: {r.error}", "latency_s": r.latency_s, "valid": False,
                "error": r.error}
    return {**r.message.model_dump(), "latency_s": r.latency_s, "valid": True}


def _why_not_consensus(cp, r2, final_recheck) -> str:
    if cp is None:
        return "No candidate was feasible even with the offered concessions."
    if final_recheck and not final_recheck["passed"]:
        return "All three accepted, but the final recheck failed."
    parts = []
    for a in AGENTS:
        res = r2[a]
        if res.message is None:
            parts.append(f"{a} gave no valid vote ({res.error})")
        elif res.message.vote != "accept":
            parts.append(f"{a} rejected")
    return "No consensus: " + ", ".join(parts) + ". An abstention is not an accept."


def save(log: dict, logs_dir: str | None = None) -> Path:
    d = Path(logs_dir or agents.config()["logs_dir"])
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{log['run_id']}.json"
    path.write_text(json.dumps(log, indent=2, default=str))
    return path


def run(random: bool = False, flight: str | None = None, date: str | None = None,
        scenario_id: str | None = None, fake_agents: bool = False) -> dict:
    import scenario as sc
    cfg = agents.config()
    seed = cfg["evaluation"]["seed"]
    df = sc.load_flights(cfg["data_dir"])
    if flight:
        rows = df[(df["AIRLINE"] == flight[:2].upper()) & (df["FLIGHT_NUMBER"].astype(str) == flight[2:])]
        if date:
            y, m, d = (int(x) for x in date.split("-"))
            rows = rows[(rows["YEAR"] == y) & (rows["MONTH"] == m) & (rows["DAY"] == d)]
        if rows.empty:
            raise ValueError(f"No qualifying row for {flight} on {date}")
        row = rows.iloc[0]
    else:
        row = df.sample(1, random_state=None if random else seed).iloc[0]
    sid = scenario_id or f"{row['AIRLINE']}{row['FLIGHT_NUMBER']}-{row['YEAR']}{row['MONTH']:02d}{row['DAY']:02d}"
    s = sc.build_scenario(row, sid, seed)
    log = negotiate(ModuleWorld(cfg["costs"]), s, cfg["costs"], fake_agents=fake_agents)
    save(log, cfg["logs_dir"])
    return log
