"""Reproducible evaluation. Deterministic runs over the seeded scenarios (or JSON fixtures), optional agent runs
through coordinator.run, the four labelled failure tests, and logs/benchmark.json. (Yizhuo)

Only completed runs are reported. Anything that could not run is written as ``not_run`` with the reason,
never as a number.

Usage (repo root, project venv):
    python benchmark.py                                   # deterministic: demo-001 + the 50 seeded scenarios
    python benchmark.py --agents 10                       # plus 10 coordinator runs with FAKE agents (no API)
    python benchmark.py --agents 10 --live                # real Claude calls: costs API credit
    python benchmark.py --ids demo-001,S1234 --print demo-001
    python benchmark.py --fixtures 'tests/fixtures/*.json'  # replay JSON fixtures instead

Fixture JSON shape (write_fixture() produces it):
    {"seed": int, "category": str, "scenario": Scenario, "candidates": [Candidate...],
     "concessions": [{"agent", "id", "target"}, ...]}
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import checker
import costs as costs_mod
import fallback
from models import Candidate, Scenario

ROOT = Path(__file__).parent
FAILURE_TESTS = ["Injected invalid proposal", "Impossible scenario", "Malformed agent response", "API timeout"]
CATEGORY = {"weather": "weather_only", "late_aircraft": "late_aircraft_only", "both": "both"}


# --------------------------------------------------------------------------- scenario sources

def category_of(scenario: Scenario) -> str:
    d = scenario.simulated.get("atc", {}).get("disruption_type")
    if d in CATEGORY:
        return CATEGORY[d]
    h = scenario.historical
    if h.weather_delay_min > 0 and h.late_aircraft_delay_min > 0:
        return "both"
    return "weather_only" if h.weather_delay_min > 0 else "late_aircraft_only" if h.late_aircraft_delay_min > 0 else "other"


def write_fixture(path: str | Path, scenario: Scenario, candidates: list[Candidate], seed: int | None,
                  concessions: list | None = None, category: str | None = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"seed": seed, "category": category or category_of(scenario),
                             "scenario": scenario.model_dump(), "candidates": [c.model_dump() for c in candidates],
                             "concessions": concessions or []}, indent=1))
    return p


def write_demo_fixture(path: str | Path = ROOT / "tests" / "fixtures" / "demo_scenario.json") -> Path:
    """Regenerate tests/fixtures/demo_scenario.json from scenario.py's demo-001."""
    import options
    import scenario as S
    s = S.get_scenario(S.DEMO_ID)
    return write_fixture(path, s, options.generate(s), S.seed_for(S.DEMO_ID),
                         [{"agent": "atc", "id": "ATC_EARLIER_SLOT", "target": "C1"},
                          {"agent": "pilot", "id": "PILOT_EXTRA_HOLDING", "target": "14 min"},
                          {"agent": "ground", "id": "GROUND_REASSIGN_CREW", "target": "B7"}])


def load_fixture(path: str | Path) -> dict:
    raw = json.loads(Path(path).read_text())
    sc = Scenario(**raw["scenario"])
    cands = [Candidate(**c) for c in raw["candidates"]]
    if len(cands) > 8:
        raise ValueError(f"{path}: {len(cands)} candidates, maximum is 8")
    return {"source": str(path), "seed": raw.get("seed"), "category": raw.get("category") or category_of(sc),
            "scenario": sc, "candidates": cands, "concessions": raw.get("concessions", [])}


def load_fixtures(pattern: str) -> list[dict]:
    return [load_fixture(p) for p in sorted(glob.glob(pattern))]


def seeded_fixtures(ids: list[str] | None = None) -> list[dict]:
    """scenario.py's seeded evaluation set (plus demo-001) with options.py's candidates."""
    import options
    import scenario as S
    ids = ids or [S.DEMO_ID] + S.fixture_ids()
    out = []
    for sid in ids:
        s = S.get_scenario(sid)
        out.append({"source": f"scenario.get_scenario({sid!r})", "seed": S.seed_for(sid), "category": category_of(s),
                    "scenario": s, "candidates": options.generate(s), "concessions": None})
    return out


# --------------------------------------------------------------------------- deterministic

def needs(c: Candidate) -> list[str]:
    return sorted(x.strip() for x in (c.concession or "").split("+") if x.strip())


def concession_variants(fx: dict) -> list[list[dict]]:
    """Concession sets for the all-information reference solver: one concession per agent per round, so
    every ATC slot target and every ground gate target that some candidate needs is tried, with the pilot
    always accepting holding up to the fuel-safe limit. Bounded by the candidate count."""
    if fx.get("concessions") is not None:
        return [fx["concessions"]]
    s, cands = fx["scenario"], fx["candidates"]
    pilot = s.simulated.get("pilot", {})
    pilot_c = [{"agent": "pilot", "id": "PILOT_EXTRA_HOLDING", "target": f"{pilot.get('fuel_safe_holding_min', '')}"}]
    atc_targets = [None] + sorted({c.id for c in cands if "ATC_EARLIER_SLOT" in needs(c)})
    gate_targets = [None] + sorted({c.gate for c in cands if "GROUND_REASSIGN_CREW" in needs(c)})
    out = []
    for a in atc_targets:
        for g in gate_targets:
            cs = list(pilot_c)
            if a:
                cs.append({"agent": "atc", "id": "ATC_EARLIER_SLOT", "target": a})
            if g:
                cs.append({"agent": "ground", "id": "GROUND_REASSIGN_CREW", "target": g})
            out.append(cs)
    return out


def apply(scenario: Scenario, concessions: list[dict]) -> tuple[Scenario, list[dict], list[dict]]:
    """scenario.apply_concessions (Ashvin) plus the applied/rejected records it leaves in the state."""
    import scenario as S
    new = S.apply_concessions(scenario, concessions) if concessions else scenario
    applied = [c for st in new.simulated.values() for c in st.get("applied_concessions", [])]
    rejected = [c for st in new.simulated.values() for c in st.get("rejected_concessions", [])]
    return new, applied, rejected


def _rule_table(checks: dict) -> dict:
    return {cid: {r.rule_id: r.passed for r in rs} for cid, rs in checks.items()}


def run_deterministic(fx: dict, config: dict | None = None) -> dict:
    """One scenario: checks, costs, solver and heuristic on the base state (state v1) and the reference
    optimum over the concession-adjusted states (the problem the agents actually solve)."""
    cfg = config if config is not None else checker.load_config()
    t0 = time.perf_counter()
    sc, cands = fx["scenario"], fx["candidates"]
    base = fallback.run_pipeline(cands, sc, cfg)
    best = None
    for cs in concession_variants(fx):
        new, applied, rejected = apply(sc, cs)
        res = fallback.run_pipeline(cands, new, cfg)
        dec = res["decision"]
        key = (dec["candidate"] is None, res["costs"][dec["candidate"]].total_usd if dec["candidate"] else 0,
               fallback.id_key(dec["candidate"] or ""))
        if best is None or key < best[0]:
            best = (key, res, applied, rejected, cs)
    _, after, applied, rejected, used = best
    heur = fallback.heuristic(sc, cfg)
    dec = after["decision"]
    return {
        "scenario_id": sc.scenario_id, "seed": fx.get("seed"), "category": fx["category"], "source": fx["source"],
        "state_version": 2 if applied else 1, "concessions_tried": used, "concessions_applied": applied,
        "concessions_rejected": rejected, "candidates": len(cands),
        "feasible_before": base["decision"]["feasible"], "feasible_after": dec["feasible"],
        "feasible_count": len(dec["feasible"]),
        "outcome": dec["outcome"], "selected": dec["candidate"], "reason": dec["reason"],
        "solver_base": {"candidate": base["decision"]["candidate"],
                        "total_usd": base["costs"][base["decision"]["candidate"]].total_usd
                        if base["decision"]["candidate"] else None},
        "solver": {"candidate": dec["candidate"],
                   "total_usd": after["costs"][dec["candidate"]].total_usd if dec["candidate"] else None},
        "rules_before": _rule_table(base["checks"]), "rules_after": _rule_table(after["checks"]),
        "checks_after": {cid: [r.model_dump() for r in rs] for cid, rs in after["checks"].items()},
        "costs": {cid: (c.model_dump() if c is not None else None) for cid, c in after["costs"].items()},
        "cost_errors": after.get("cost_errors", []), "weights": after["weights"],
        "heuristic": {k: heur.get(k) for k in ("plan", "feasible", "failed", "cost", "assumption", "error")},
        "execution_ms": round((time.perf_counter() - t0) * 1000, 2),
    }


# --------------------------------------------------------------------------- agents (Person C)

def _violations(log: dict) -> int:
    """1 if the final candidate fails any rule in the final check set, else 0. Escalation has none."""
    out = log.get("outcome") or {}
    cid = out.get("final_candidate")
    if not cid:
        return 0
    checks = log.get("checks") or {}
    key = "before_concessions" if out.get("type") == "fallback" else "after_concessions"
    rs = (checks.get(key) or checks.get("after_concessions") or {}).get(cid)
    if not rs:
        return 1
    return 0 if all(r.get("passed") if isinstance(r, dict) else r.passed for r in rs) else 1


def summarise_run(log: dict, sid: str, reference: dict | None, wall_s: float) -> dict:
    stats, out = log.get("stats") or {}, log.get("outcome") or {}
    costs = log.get("costs") or {}
    solver = (log.get("baselines") or {}).get("solver") or {}
    final = out.get("final_candidate")
    final_cost = (costs.get(final) or {}).get("total_usd") if final else None
    ref_cost = (reference or {}).get("solver", {}).get("total_usd")
    votes = [v for r in log.get("rounds", []) for v in r.get("votes", [])]
    return {
        "run_id": log.get("run_id"), "scenario_id": sid, "outcome": out.get("type"), "final_candidate": final,
        "final_cost_usd": final_cost,
        "coordinator_solver": solver, "reference_optimum": (reference or {}).get("solver"),
        "cost_gap_vs_coordinator_usd": (final_cost - solver["total_usd"])
        if final_cost is not None and solver.get("total_usd") is not None else None,
        "cost_gap_vs_reference_usd": (final_cost - ref_cost) if final_cost is not None and ref_cost is not None else None,
        "votes": {v.get("agent"): v.get("vote") for v in votes},
        "offers_valid": [o.get("valid") for r in log.get("rounds", []) for o in r.get("offers", [])],
        "rounds_completed": len(log.get("rounds", [])),
        "concessions_that_unlocked": out.get("concessions_that_unlocked", []),
        "api_calls": stats.get("api_calls"), "retries": stats.get("retries"),
        "latency_s": stats.get("total_latency_s", round(wall_s, 2)),
        "input_tokens": stats.get("input_tokens"), "output_tokens": stats.get("output_tokens"),
        "est_cost_usd": stats.get("est_cost_usd"), "model": stats.get("model"),
        "accepted_violations": _violations(log),
    }


def run_agents(scenario_ids: list[str], live: bool, limit: int, reference: dict[str, dict]) -> dict:
    try:
        import coordinator
    except Exception as e:
        return {"completed": 0, "runs": [], "not_run": f"coordinator import failed: {e}"}
    runs, failures = [], []
    for sid in scenario_ids[:limit]:
        t0 = time.perf_counter()
        try:
            log = coordinator.run(scenario_id=sid, fake_agents=not live)
        except NotImplementedError:
            return {"completed": 0, "runs": [], "not_run": "coordinator.run is not implemented yet"}
        except Exception as e:
            failures.append({"scenario_id": sid, "error": f"{type(e).__name__}: {e}"})
            continue
        runs.append(summarise_run(log, sid, reference.get(sid), time.perf_counter() - t0))
    return {"completed": len(runs), "runs": runs, "failures": failures, "fake_agents": not live,
            "not_run": None if runs else "no run completed"}


# --------------------------------------------------------------------------- failure tests

class _BrokenClient:
    """Mocked API: every structured call returns no parsed output (malformed / refused). No network."""
    @property
    def messages(self):
        return self

    def parse(self, **kw):
        return SimpleNamespace(stop_reason="end_turn", parsed_output=None, usage=None)


class _TimeoutClient:
    """Mocked API: every call raises the SDK's timeout error immediately. No network."""
    @property
    def messages(self):
        return self

    def parse(self, **kw):
        import anthropic
        import httpx
        raise anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


def _negotiate_with_mock(scenario: Scenario, client_factory, weights: dict) -> dict:
    """Run the real two-round coordinator on the real pipeline with the LLM client replaced by a mock."""
    import agents
    import coordinator
    original = agents._client
    agents._client = client_factory
    try:
        return coordinator.negotiate(coordinator.ModuleWorld(weights), scenario, weights, fake_agents=False,
                                     label=f"failure test ({client_factory.__name__})")
    finally:
        agents._client = original


def failure_tests(fixtures: list[dict], config: dict) -> list[dict]:
    cfg = config
    weights = costs_mod.weights_from_config(cfg)
    out = []
    demo = next((f for f in fixtures if f["scenario"].scenario_id == "demo-001"), fixtures[0] if fixtures else None)

    # 1. Injected invalid proposal: unknown gate, negative holding, gate released before arrival.
    if demo:
        bad = Candidate(id="X9", landing="20:33", extra_holding_min=-5, gate="ZZ", concession=None,
                        gate_arrival="20:43", gate_release="20:30")
        res = fallback.run_pipeline(demo["candidates"] + [bad], demo["scenario"], cfg)
        blocked = not checker.feasible(res["checks"]["X9"]) and res["decision"]["candidate"] != "X9"
        out.append({"test": FAILURE_TESTS[0], "expected": "blocked", "result": "blocked" if blocked else "ACCEPTED",
                    "passed": blocked, "detail": {"failed_rules": checker.failed_rules(res["checks"]["X9"]),
                                                  "selected": res["decision"]["candidate"]}})
    else:
        out.append({"test": FAILURE_TESTS[0], "expected": "blocked", "result": "not_run", "passed": None, "detail": "no fixture"})

    # 2. Impossible scenario: nothing feasible, must escalate.
    imp = next((f for f in fixtures if f["scenario"].scenario_id == "esc-001"), None)
    if imp is None:
        try:
            imp = load_fixture(ROOT / "tests" / "fixtures" / "impossible_scenario.json")
        except Exception as e:
            imp = None
            out.append({"test": FAILURE_TESTS[1], "expected": "escalate", "result": "not_run", "passed": None, "detail": str(e)})
    if imp is not None:
        res = fallback.run_pipeline(imp["candidates"], imp["scenario"], cfg)
        ok = res["decision"]["outcome"] == "escalation" and res["decision"]["candidate"] is None
        out.append({"test": FAILURE_TESTS[1], "expected": "escalate", "result": res["decision"]["outcome"],
                    "passed": ok, "detail": {"reason": res["decision"]["reason"]}})

    # 3 and 4: real coordinator + real pipeline, mocked LLM client. Expected fallback (or escalation when the
    # base state has nothing feasible, which is itself the explicit non-consensus outcome). Never consensus.
    # Prefer a scenario whose base state has a feasible candidate so the rulebook fallback is visible.
    target = demo
    for f in fixtures:
        if f["scenario"].scenario_id == "esc-001":
            continue
        if fallback.run_pipeline(f["candidates"], f["scenario"], cfg)["decision"]["candidate"]:
            target = f
            break
    for name, client in ((FAILURE_TESTS[2], _BrokenClient), (FAILURE_TESTS[3], _TimeoutClient)):
        rec = {"test": name, "expected": "fallback", "result": "not_run", "passed": None}
        if target is None:
            rec["detail"] = "no fixture"
        else:
            try:
                log = _negotiate_with_mock(target["scenario"], client, weights)
                typ = (log.get("outcome") or {}).get("type")
                offers_valid = [o.get("valid") for r in log.get("rounds", []) for o in r.get("offers", [])]
                rec.update(result=typ or "no outcome", passed=(typ in ("fallback", "escalation") and not any(offers_valid)),
                           detail={"run_id": log.get("run_id"), "scenario_id": target["scenario"].scenario_id,
                                   "offers_valid": offers_valid,
                                   "api_calls_mocked": (log.get("stats") or {}).get("api_calls"),
                                   "retries": (log.get("stats") or {}).get("retries"),
                                   "reason": (log.get("outcome") or {}).get("reason"), "violations": _violations(log)})
            except Exception as e:
                rec.update(result=f"error: {type(e).__name__}", passed=False, detail=str(e))
        out.append(rec)
    return out


# --------------------------------------------------------------------------- aggregate and CLI

def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.fmean(xs), 2) if xs else None


def aggregate(det: list[dict], agents: dict, failures: list[dict], source: str) -> dict:
    cats = {k: sum(1 for d in det if d["category"] == k) for k in ("weather_only", "late_aircraft_only", "both")}
    heur_feasible = [d for d in det if d["heuristic"].get("feasible")]
    heur_costs = [d["heuristic"]["cost"]["total_usd"] for d in heur_feasible if d["heuristic"].get("cost")]
    runs = agents.get("runs", [])
    gaps = [r["cost_gap_vs_reference_usd"] / r["reference_optimum"]["total_usd"] * 100 for r in runs
            if r.get("cost_gap_vs_reference_usd") is not None and (r.get("reference_optimum") or {}).get("total_usd")]
    rule_fail = {}
    for d in det:
        for cid, rules in d["rules_after"].items():
            for rid, ok in rules.items():
                rule_fail[rid] = rule_fail.get(rid, 0) + (0 if ok else 1)
    return {
        "sample": False,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Measured inside the simulation. Costs are USD-equivalent scores with config.yaml weights, not "
                "measured savings. Checks are simplified, not FAA compliance.",
        "source": source,
        "scenarios": {"total": len(det), **cats, "other": len(det) - sum(cats.values())},
        "deterministic": {
            "runs": len(det),
            "fallback_feasible": sum(1 for d in det if d["outcome"] == "fallback"),
            "escalations": sum(1 for d in det if d["outcome"] == "escalation"),
            "feasible_on_base_state": sum(1 for d in det if d["solver_base"]["candidate"]),
            "mean_feasible_count": _mean([d["feasible_count"] for d in det]),
            "rule_failures_after_concessions": rule_fail,
            "mean_execution_ms": _mean([d["execution_ms"] for d in det]),
        },
        "agents": {
            "completed": agents.get("completed", 0),
            "consensus": sum(1 for r in runs if r["outcome"] == "consensus"),
            "fallback": sum(1 for r in runs if r["outcome"] == "fallback"),
            "escalation": sum(1 for r in runs if r["outcome"] == "escalation"),
            "accepted_violations": sum(r.get("accepted_violations", 0) for r in runs),
            "mean_latency_s": _mean([r.get("latency_s") for r in runs]),
            "mean_api_calls": _mean([r.get("api_calls") for r in runs]),
            "retries": sum(r.get("retries") or 0 for r in runs),
            "total_input_tokens": sum(r.get("input_tokens") or 0 for r in runs),
            "total_output_tokens": sum(r.get("output_tokens") or 0 for r in runs),
            "est_api_cost_usd": round(sum(r.get("est_cost_usd") or 0 for r in runs), 4),
            "fake_agents": agents.get("fake_agents"),
            "not_run": agents.get("not_run"),
            "failures": agents.get("failures", []),
        },
        "cost_vs_solver_gap_pct": round(statistics.fmean(gaps), 2) if gaps else None,
        "heuristic": {
            "infeasible_rate_pct": round(100 * (1 - len(heur_feasible) / len(det)), 1) if det else None,
            "mean_cost_usd_when_feasible": _mean(heur_costs),
        },
        "failure_tests": failures,
        "per_scenario": [{k: v for k, v in d.items() if k != "checks_after"} for d in det],
        "agent_runs": runs,
    }


def print_table(rec: dict) -> None:
    print(f"\n{rec['scenario_id']}  category={rec['category']}  state_version={rec['state_version']}  "
          f"outcome={rec['outcome']}  selected={rec['selected']}  ({rec['execution_ms']} ms)")
    print(f"  concessions tried: {[(c['id'], c['target']) for c in rec['concessions_tried']]}")
    print(f"  {'id':<4}{'before':<9}{'after':<9}{'total_usd':>11}  failed rules (after)")
    for cid, cost in rec["costs"].items():
        fb = "ok" if all(rec["rules_before"][cid].values()) else "x"
        fa = "ok" if all(rec["rules_after"][cid].values()) else "x"
        failed = [r for r, p in rec["rules_after"][cid].items() if not p]
        total = f"{cost['total_usd']:>11.2f}" if cost else f"{'n/a':>11}"
        print(f"  {cid:<4}{fb:<9}{fa:<9}{total}  {','.join(failed)}")
    h = rec["heuristic"]
    print(f"  heuristic: {h.get('plan')} -> feasible={h.get('feasible')} failed={h.get('failed')} "
          f"cost={(h.get('cost') or {}).get('total_usd')}")
    print(f"  {rec['reason']}")


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixtures", default=None, help="glob of fixture JSON files (replaces the seeded set)")
    ap.add_argument("--ids", default=None, help="comma-separated scenario IDs (replaces the seeded set)")
    ap.add_argument("--agents", type=int, default=0, help="number of coordinator runs (0 = none)")
    ap.add_argument("--live", action="store_true", help="real Claude calls (default: fake agents, no API)")
    ap.add_argument("--out", default=str(ROOT / "logs" / "benchmark.json"))
    ap.add_argument("--print", dest="print_id", default=None, help="print the candidate table for one scenario id")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    cfg = checker.load_config()
    if args.fixtures:
        fixtures, source = load_fixtures(args.fixtures), args.fixtures
    else:
        ids = args.ids.split(",") if args.ids else None
        fixtures, source = seeded_fixtures(ids), ("scenario.fixture_ids()" if not ids else f"ids={ids}")
    det = [run_deterministic(fx, cfg) for fx in fixtures]
    reference = {d["scenario_id"]: d for d in det}
    agents = run_agents([d["scenario_id"] for d in det], args.live, args.agents, reference) if args.agents > 0 \
        else {"completed": 0, "runs": [], "not_run": "agent runs not requested (--agents 0)"}
    failures = failure_tests(fixtures, cfg)
    result = aggregate(det, agents, failures, source)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str))

    if not args.quiet:
        for rec in det:
            if args.print_id == rec["scenario_id"] or (args.print_id is None and len(det) <= 3):
                print_table(rec)
        print(f"\nDeterministic: {json.dumps(result['deterministic'])}")
        print(f"Heuristic: {result['heuristic']}")
        a = result["agents"]
        print(f"Agents: completed={a['completed']} consensus={a['consensus']} fallback={a['fallback']} "
              f"escalation={a['escalation']} violations={a['accepted_violations']} fake={a['fake_agents']} "
              f"not_run={a['not_run']}")
        for ft in failures:
            print(f"  [{'PASS' if ft['passed'] else 'NOT RUN' if ft['passed'] is None else 'FAIL'}] {ft['test']}: "
                  f"expected {ft['expected']}, got {ft['result']}")
        print(f"Wrote {out}")
    return result


if __name__ == "__main__":
    main()
