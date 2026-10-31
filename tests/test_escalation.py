"""Escalation assist (escalation_assist_plan.md, section 6). Deterministic, plain code, no API calls."""
from functools import lru_cache

import pytest

import checker
import coordinator
import costs as C
import escalation as E
import options
import scenario as S
from models import CheckResult


@lru_cache(maxsize=None)
def built(sid):
    s = S.get_scenario(sid)
    cands = options.generate(s)
    cfg = checker.load_config()
    return s, cands, {c.id: checker.check(c, s, cfg) for c in cands}, {c.id: C.cost(c, s) for c in cands}


@lru_cache(maxsize=1)
def escalated_ids():
    """The benchmark's own escalations: no candidate passes even after every allowed concession."""
    import benchmark
    cfg = checker.load_config()
    return [d["scenario_id"] for d in (benchmark.run_deterministic(fx, cfg) for fx in benchmark.seeded_fixtures())
            if not d["feasible_after"]]


def test_the_benchmark_has_eleven_escalations():
    assert len(escalated_ids()) == 11


def test_wn407_blocker_is_the_gate_and_first_suggestion_is_a_gate_change():
    s, cands, checks, costs = built("S220337")  # WN407 SFO to SAN
    a = E.assist(s, cands, checks, costs)
    assert a["main_blocker"]["rule_id"] == "G-2"
    assert all(r["failed_rules"] == ["G-2"] for r in a["closest"])
    first = a["suggestions"][0]
    assert first["rule_id"] == "G-2" and "gate" in first["actions"][0].lower()
    assert a["closest"][0]["shortfalls"][0]["unit"] == "min" and a["closest"][0]["shortfalls"][0]["amount"] > 0


def test_fuel_and_wake_are_never_relaxable_in_any_benchmark_scenario():
    for sid in escalated_ids():
        a = E.assist(*built(sid))
        for sug in a["suggestions"]:
            if sug["rule_id"] in E.NEVER_RELAX:
                assert sug["relaxable"] is False
        opt = a["costly_option"]
        if opt:
            row = next(r for r in a["closest"] + E.rank(built(sid)[2], built(sid)[3]) if r["candidate"] == opt["candidate"])
            assert not set(row["failed_rules"]) & E.NEVER_RELAX
            assert all(c["passed"] for c in opt["checks"] if c["rule_id"] in E.NEVER_RELAX)


def test_assist_is_deterministic():
    for sid in escalated_ids():
        assert E.assist(*built(sid)) == E.assist(*built(sid))


def test_missing_inputs_give_null_amounts_not_crashes():
    err = CheckResult(rule_id="F-1", basis="x", inputs={"error": "pilot.reserve_kg is required"}, passed=False,
                      explanation="Cannot evaluate")
    sf = E.shortfall(err.model_dump())
    assert sf["amount"] is None and "reserve_kg" in sf["explanation"]
    bare = E.shortfall({"rule_id": "G-2", "inputs": {"gate": "B4"}, "passed": False, "explanation": "overlap"})
    assert bare["amount"] is None and bare["unit"] is None


def test_costly_option_passes_the_real_checker_and_never_breaks_fuel_or_wake():
    cfg = checker.load_config()
    st = E.settings(cfg)
    for sid in escalated_ids():
        s, cands, checks, costs = built(sid)
        opt = E.assist(s, cands, checks, costs)["costly_option"]
        if not opt:
            continue
        c2, s2 = next(c for c in cands if c.id == opt["candidate"]), s
        for name in opt["fixes"]:
            c2, s2 = E.LADDER[name]["apply"](c2, s2, st)
        results = checker.check(c2, s2, cfg)
        assert checker.feasible(results)
        assert all(r.passed for r in results if r.rule_id in E.NEVER_RELAX)


def test_costly_option_is_the_cheapest_and_normal_costs_do_not_change():
    s, cands, checks, costs = built("S220337")
    before = {k: v.total_usd for k, v in costs.items()}
    opt = E.assist(s, cands, checks, costs)["costly_option"]
    assert opt and opt["candidate"] == "C1" and opt["fixes"] == ["remote_stand", "extra_crew"]
    assert {c.id: C.cost(c, s).total_usd for c in cands} == before  # fees never touch normal plans
    st = E.settings(checker.load_config())
    assert opt["total_usd"] == round(opt["plan_cost_usd"] + st["remote_stand_usd"] + st["crew_callout_usd"], 2)


def test_plans_that_fail_fuel_or_wake_are_never_offered():
    s, cands, checks, costs = built("S220337")
    ranked = E.rank(checks, costs)
    for r in ranked:
        r["failed_rules"] = r["failed_rules"] + ["F-1"]  # pretend every plan also breaks the fuel reserve
    assert E.costly_option(s, cands, ranked, checker.load_config()) is None


def _negotiate(sid):
    s = S.get_scenario(sid)
    cfg = coordinator.agents.config()
    return coordinator.negotiate(coordinator.ModuleWorld(cfg["costs"]), s, cfg["costs"], fake_agents=True)


def test_only_escalated_runs_carry_the_block():
    esc = _negotiate("S220337")
    assert esc["outcome"]["type"] == "escalation"
    assert esc["escalation_assist"]["main_blocker"]["rule_id"] == "G-2"
    ok = _negotiate(S.DEMO_ID)
    assert ok["outcome"]["type"] != "escalation" and ok["escalation_assist"] is None


def test_assist_from_log_rebuilds_the_block_for_saved_runs():
    log = _negotiate("S220337")
    rebuilt = E.assist_from_log({k: v for k, v in log.items() if k != "escalation_assist"})
    assert rebuilt["main_blocker"] == log["escalation_assist"]["main_blocker"]
    assert E.assist_from_log({"outcome": {"type": "consensus"}}) is None


def test_official_benchmark_numbers_unchanged(tmp_path):
    import benchmark
    res = benchmark.main(["--out", str(tmp_path / "b.json"), "--quiet"])
    d = res["deterministic"]
    assert (d["runs"], d["feasible_on_base_state"], d["fallback_feasible"], d["escalations"]) == (51, 26, 40, 11)
    assert all(ft["passed"] is not False for ft in res["failure_tests"])
