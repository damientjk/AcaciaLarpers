"""Reproducible evaluation. Deterministic runs over JSON fixtures, optional agent runs through
coordinator.run, the four labelled failure tests, and logs/benchmark.json. (Yizhuo)

Only completed runs are reported. Anything that could not run is written as ``not_run`` with the
reason, never as a number.

Usage (repo root, project venv):
    python benchmark.py                                   # deterministic over tests/fixtures/*.json
    python benchmark.py --fixtures 'fixtures/scenarios/*.json' --agents 10
    python benchmark.py --agents 5 --fake-agents          # coordinator with fake agents, no API calls
    python benchmark.py --print demo-001                  # per-candidate table for one fixture

Fixture JSON shape (write_fixture() produces it):
    {"seed": int, "category": "weather_only|late_aircraft_only|both", "scenario": Scenario,
     "candidates": [Candidate, ...], "concessions": [{"id", "target", "agent"?}, ...]}
"""
from __future__ import annotations

import argparse
import glob
import inspect
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import checker
import costs as costs_mod
import fallback
from models import Candidate, Scenario

ROOT = Path(__file__).parent
DEFAULT_FIXTURES = str(ROOT / "tests" / "fixtures" / "*.json")
FAILURE_TESTS = ["Injected invalid proposal", "Impossible scenario", "Malformed agent response", "API timeout"]


# --------------------------------------------------------------------------- fixtures

def category_of(scenario: Scenario) -> str:
    h = scenario.historical
    if h.weather_delay_min > 0 and h.late_aircraft_delay_min > 0:
        return "both"
    if h.weather_delay_min > 0:
        return "weather_only"
    if h.late_aircraft_delay_min > 0:
        return "late_aircraft_only"
    return "other"


def write_fixture(path: str | Path, scenario: Scenario, candidates: list[Candidate], seed: int,
                  concessions: list | None = None, category: str | None = None) -> Path:
    """Person A can dump (scenario, candidates) pairs with this so the benchmark replays them."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"seed": seed, "category": category or category_of(scenario),
                             "scenario": scenario.model_dump(), "candidates": [c.model_dump() for c in candidates],
                             "concessions": concessions or []}, indent=2))
    return p


def load_fixture(path: str | Path) -> dict:
    raw = json.loads(Path(path).read_text())
    sc = Scenario(**raw["scenario"])
    cands = [Candidate(**c) for c in raw["candidates"]]
    if len(cands) > 8:
        raise ValueError(f"{path}: {len(cands)} candidates, maximum is 8")
    return {"path": str(path), "seed": raw.get("seed"), "category": raw.get("category") or category_of(sc),
            "scenario": sc, "candidates": cands, "concessions": raw.get("concessions", [])}


def load_fixtures(pattern: str = DEFAULT_FIXTURES) -> list[dict]:
    return [load_fixture(p) for p in sorted(glob.glob(pattern))]


# --------------------------------------------------------------------------- deterministic

def _rule_table(checks: dict) -> dict:
    return {cid: {r.rule_id: r.passed for r in rs} for cid, rs in checks.items()}


def run_deterministic(fx: dict, config: dict | None = None) -> dict:
    """One scenario through checks, costs, solver and heuristic on the base state and, when the fixture
    carries concessions, on the concession-adjusted state (the problem the agents actually solve)."""
    cfg = config if config is not None else checker.load_config()
    t0 = time.perf_counter()
    sc, cands = fx["scenario"], fx["candidates"]
    base = fallback.run_pipeline(cands, sc, cfg)
    adj = checker.apply_concessions(sc, fx.get("concessions", []), state_version=1)
    after = fallback.run_pipeline(cands, adj.scenario, cfg) if adj.applied else base
    heur = fallback.heuristic(sc, cfg)
    elapsed = time.perf_counter() - t0
    dec = after["decision"]
    return {
        "scenario_id": sc.scenario_id, "seed": fx.get("seed"), "category": fx["category"],
        "state_version": adj.state_version, "concessions_applied": adj.applied, "concessions_rejected": adj.rejected,
        "candidates": len(cands),
        "feasible_before": base["decision"]["feasible"], "feasible_after": dec["feasible"],
        "feasible_count": len(dec["feasible"]),
        "outcome": dec["outcome"], "selected": dec["candidate"], "reason": dec["reason"],
        "solver_before": {"candidate": base["decision"]["candidate"],
                          "total_usd": base["costs"][base["decision"]["candidate"]].total_usd
                          if base["decision"]["candidate"] else None},
        "solver": {"candidate": dec["candidate"],
                   "total_usd": after["costs"][dec["candidate"]].total_usd if dec["candidate"] else None},
        "rules_before": _rule_table(base["checks"]), "rules_after": _rule_table(after["checks"]),
        "checks_after": {cid: [r.model_dump() for r in rs] for cid, rs in after["checks"].items()},
        "costs": {cid: (c.model_dump() if c is not None else None) for cid, c in after["costs"].items()},
        "cost_errors": after.get("cost_errors", []),
        "weights": after["weights"],
        "heuristic": {k: heur.get(k) for k in ("plan", "feasible", "failed", "cost", "assumption", "error")},
        "execution_ms": round(elapsed * 1000, 2),
    }


# --------------------------------------------------------------------------- agents (Person C)

def _coordinator():
    try:
        import coordinator  # noqa: WPS433
    except Exception as e:  # import error means not available yet
        return None, f"coordinator import failed: {e}"
    return coordinator, None


def _violations(log: dict) -> int:
    """1 if the final candidate fails any rule in the final check set, else 0. Escalation has none."""
    out = log.get("outcome") or {}
    cid = out.get("final_candidate")
    if not cid:
        return 0
    checks = (log.get("checks") or {})
    final = checks.get("after_concessions") or checks.get("before_concessions") or checks
    rs = final.get(cid) if isinstance(final, dict) else None
    if not rs:
        return 1  # accepted without evidence of a passing check set
    return 0 if all(r.get("passed") if isinstance(r, dict) else r.passed for r in rs) else 1


def run_agents(scenario_ids: list[str], fake: bool, limit: int) -> dict:
    coord, err = _coordinator()
    if coord is None:
        return {"completed": 0, "runs": [], "not_run": err}
    runs, failures = [], []
    for sid in scenario_ids[:limit]:
        t0 = time.perf_counter()
        try:
            log = coord.run(scenario_id=sid, fake_agents=fake)
        except NotImplementedError:
            return {"completed": 0, "runs": [], "not_run": "coordinator.run is not implemented yet"}
        except Exception as e:  # a crashed run is reported, not hidden
            failures.append({"scenario_id": sid, "error": f"{type(e).__name__}: {e}"})
            continue
        stats, out = log.get("stats") or {}, log.get("outcome") or {}
        costs = log.get("costs") or {}
        solver = (log.get("baselines") or {}).get("solver") or {}
        final = out.get("final_candidate")
        final_cost = (costs.get(final) or {}).get("total_usd") if final else None
        votes = [v for r in log.get("rounds", []) for v in r.get("votes", [])]
        runs.append({
            "run_id": log.get("run_id"), "scenario_id": sid, "outcome": out.get("type"), "final_candidate": final,
            "final_cost_usd": final_cost, "solver_candidate": solver.get("candidate"),
            "solver_cost_usd": solver.get("total_usd"),
            "cost_gap_usd": (final_cost - solver["total_usd"]) if final_cost is not None and solver.get("total_usd") is not None else None,
            "votes": {v.get("agent"): v.get("vote") for v in votes},
            "rounds_completed": len(log.get("rounds", [])),
            "concessions_that_unlocked": out.get("concessions_that_unlocked", []),
            "api_calls": stats.get("api_calls"), "retries": stats.get("retries"),
            "latency_s": stats.get("total_latency_s", round(time.perf_counter() - t0, 2)),
            "tokens": stats.get("tokens"), "accepted_violations": _violations(log),
        })
    return {"completed": len(runs), "runs": runs, "failures": failures, "fake_agents": fake}


# --------------------------------------------------------------------------- failure tests

def failure_tests(fixtures: list[dict], config: dict, fake_agents: bool = True) -> list[dict]:
    cfg = config
    out = []
    demo = next((f for f in fixtures if f["scenario"].scenario_id == "demo-001"), fixtures[0] if fixtures else None)

    # 1. Injected invalid proposal: unknown gate, negative holding, gate released before arrival.
    if demo:
        bad = Candidate(id="X9", landing="20:40", extra_holding_min=-5, gate="ZZ", concession=None,
                        gate_arrival="20:48", gate_release="20:30")
        cands = demo["candidates"] + [bad]
        res = fallback.run_pipeline(cands, demo["scenario"], cfg)
        blocked = not checker.feasible(res["checks"]["X9"]) and res["decision"]["candidate"] != "X9"
        out.append({"test": FAILURE_TESTS[0], "expected": "blocked", "result": "blocked" if blocked else "ACCEPTED",
                    "passed": blocked, "detail": {"failed_rules": checker.failed_rules(res["checks"]["X9"]),
                                                  "selected": res["decision"]["candidate"]}})
    else:
        out.append({"test": FAILURE_TESTS[0], "expected": "blocked", "result": "not_run", "passed": None,
                    "detail": "no fixture"})

    # 2. Impossible scenario: nothing feasible, must escalate.
    imp = next((f for f in fixtures if f["scenario"].scenario_id == "esc-001"), None)
    if imp:
        res = fallback.run_pipeline(imp["candidates"], imp["scenario"], cfg)
        ok = res["decision"]["outcome"] == "escalation" and res["decision"]["candidate"] is None
        out.append({"test": FAILURE_TESTS[1], "expected": "escalate", "result": res["decision"]["outcome"],
                    "passed": ok, "detail": {"reason": res["decision"]["reason"]}})
    else:
        out.append({"test": FAILURE_TESTS[1], "expected": "escalate", "result": "not_run", "passed": None,
                    "detail": "fixture esc-001 missing"})

    # 3 and 4 need the coordinator's injection hook: coordinator.run(..., inject={"mode": "malformed"|"timeout", ...}).
    coord, err = _coordinator()
    for name, mode in ((FAILURE_TESTS[2], "malformed"), (FAILURE_TESTS[3], "timeout")):
        rec = {"test": name, "expected": "fallback", "result": "not_run", "passed": None}
        if coord is None:
            rec["detail"] = err
        elif "inject" not in inspect.signature(coord.run).parameters:
            rec["detail"] = "coordinator.run has no 'inject' parameter yet (Person C hook)"
        else:
            try:
                log = coord.run(scenario_id=demo["scenario"].scenario_id if demo else None, fake_agents=fake_agents,
                                inject={"mode": mode, "agent": "ground", "round": 2})
                typ = (log.get("outcome") or {}).get("type")
                rec.update(result=typ or "no outcome", passed=(typ == "fallback"),
                           detail={"run_id": log.get("run_id"), "violations": _violations(log)})
            except NotImplementedError:
                rec["detail"] = "coordinator.run is not implemented yet"
            except Exception as e:
                rec.update(result=f"error: {type(e).__name__}", passed=False, detail=str(e))
        out.append(rec)
    return out


# --------------------------------------------------------------------------- aggregate

def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.fmean(xs), 2) if xs else None


def aggregate(det: list[dict], agents: dict, failures: list[dict], fixtures_pattern: str) -> dict:
    cats = {k: sum(1 for d in det if d["category"] == k) for k in ("weather_only", "late_aircraft_only", "both")}
    heur_feasible = [d for d in det if d["heuristic"].get("feasible")]
    heur_costs = [d["heuristic"]["cost"]["total_usd"] for d in heur_feasible if d["heuristic"].get("cost")]
    runs = agents.get("runs", [])
    gaps = [r["cost_gap_usd"] / r["solver_cost_usd"] * 100 for r in runs
            if r.get("cost_gap_usd") is not None and r.get("solver_cost_usd")]
    return {
        "sample": False,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Measured inside the simulation. Costs are USD-equivalent scores with config.yaml weights, "
                "not measured savings. Checks are simplified, not FAA compliance.",
        "fixtures": fixtures_pattern,
        "scenarios": {"total": len(det), **cats, "other": len(det) - sum(cats.values())},
        "deterministic": {
            "runs": len(det),
            "fallback_feasible": sum(1 for d in det if d["outcome"] == "fallback"),
            "escalations": sum(1 for d in det if d["outcome"] == "escalation"),
            "mean_feasible_count": _mean([d["feasible_count"] for d in det]),
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
        "per_scenario": [{k: v for k, v in d.items() if k not in ("checks_after",)} for d in det],
        "agent_runs": runs,
    }


def print_table(rec: dict) -> None:
    print(f"\n{rec['scenario_id']}  category={rec['category']}  state_version={rec['state_version']}  "
          f"outcome={rec['outcome']}  selected={rec['selected']}  ({rec['execution_ms']} ms)")
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
    ap.add_argument("--fixtures", default=DEFAULT_FIXTURES, help="glob of fixture JSON files")
    ap.add_argument("--agents", type=int, default=0, help="number of agent runs through coordinator.run (0 = none)")
    ap.add_argument("--fake-agents", action="store_true", help="pass fake_agents=True (no API calls)")
    ap.add_argument("--out", default=str(ROOT / "logs" / "benchmark.json"))
    ap.add_argument("--print", dest="print_id", default=None, help="print the candidate table for one scenario id")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    cfg = checker.load_config()
    fixtures = load_fixtures(args.fixtures)
    det = [run_deterministic(fx, cfg) for fx in fixtures]
    agents = run_agents([d["scenario_id"] for d in det], args.fake_agents, args.agents) if args.agents > 0 \
        else {"completed": 0, "runs": [], "not_run": "agent runs not requested (--agents 0)"}
    failures = failure_tests(fixtures, cfg, fake_agents=args.fake_agents or True)
    result = aggregate(det, agents, failures, args.fixtures)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str))

    if not args.quiet:
        for rec in det:
            if args.print_id is None or rec["scenario_id"] == args.print_id:
                print_table(rec)
        print(f"\nDeterministic: {result['deterministic']}")
        print(f"Agents: completed={result['agents']['completed']} not_run={result['agents']['not_run']}")
        for ft in failures:
            print(f"  [{'PASS' if ft['passed'] else 'NOT RUN' if ft['passed'] is None else 'FAIL'}] {ft['test']}: "
                  f"expected {ft['expected']}, got {ft['result']}")
        print(f"Wrote {out}")
    return result


if __name__ == "__main__":
    main()
