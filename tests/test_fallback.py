import pytest

import checker
import costs
import fallback
from checker import MissingInput
from models import CandidateCost
from tests.conftest import cand


def _cost(total):
    return CandidateCost(delay_min=0, holding_fuel_kg=0, overtime_min=0, missed_connections=0, total_usd=total)


def _checks(cands, feasible_ids):
    return {c.id: [r.model_copy(update={"passed": c.id in feasible_ids}) for r in checker.check(c, SC, CFG)]
            for c in cands}


@pytest.fixture(autouse=True)
def _globals(demo, cfg):
    global SC, CFG
    SC, CFG = demo["scenario"], cfg


def test_lowest_cost_feasible(demo):
    cands = demo["candidates"]
    checks = _checks(cands, {"C1", "C3", "C7"})
    cost_map = {c.id: _cost(i * 10.0) for i, c in enumerate(cands, 1)}  # C1 cheapest but C3 < C7
    assert fallback.solve(cands, checks, cost_map) == "C1"
    cost_map["C1"] = _cost(999)
    assert fallback.solve(cands, checks, cost_map) == "C3"


def test_tie_broken_by_candidate_id_natural_order(demo):
    cands = [cand(demo, "C1", id="C10"), cand(demo, "C2", id="C2"), cand(demo, "C3", id="C9")]
    checks = _checks(cands, {"C10", "C2", "C9"})
    cost_map = {c.id: _cost(5.0) for c in cands}
    assert fallback.solve(cands, checks, cost_map) == "C2"
    assert fallback.decide(cands, checks, cost_map)["reason"].endswith("broken by candidate ID.")


def test_infeasible_cheapest_is_never_chosen(demo):
    cands = demo["candidates"]
    checks = _checks(cands, {"C4"})
    cost_map = {c.id: _cost(0.0 if c.id == "C1" else 50.0) for c in cands}
    assert fallback.solve(cands, checks, cost_map) == "C4"


def test_escalation_when_nothing_feasible(demo):
    cands = demo["candidates"]
    d = fallback.decide(cands, _checks(cands, set()), {c.id: _cost(1.0) for c in cands})
    assert d["outcome"] == "escalation" and d["candidate"] is None and d["feasible"] == []
    assert d["reason"].startswith(fallback.ESCALATION_TEXT)
    assert fallback.solve(cands, _checks(cands, set()), {c.id: _cost(1.0) for c in cands}) is None


def test_missing_checks_or_costs_raise(demo):
    cands = demo["candidates"]
    checks = _checks(cands, {"C1"})
    cost_map = {c.id: _cost(1.0) for c in cands}
    with pytest.raises(MissingInput):
        fallback.solve(cands, {k: v for k, v in checks.items() if k != "C1"}, cost_map)
    with pytest.raises(MissingInput):
        fallback.solve(cands, checks, {k: v for k, v in cost_map.items() if k != "C1"})


def test_run_pipeline_on_demo_fixture(demo, cfg):
    r = fallback.run_pipeline(demo["candidates"], demo["scenario"], cfg)
    assert r["decision"]["outcome"] == "fallback" and r["decision"]["candidate"] == "C3"
    assert r["decision"]["feasible"] == ["C3"]
    adj = checker.apply_concessions(demo["scenario"], demo["concessions"])
    r2 = fallback.run_pipeline(demo["candidates"], adj.scenario, cfg)
    assert r2["decision"]["candidate"] == "C5" and set(r2["decision"]["feasible"]) == {"C2", "C3", "C5", "C7"}


def test_run_pipeline_escalates_on_impossible_fixture(impossible, cfg):
    r = fallback.run_pipeline(impossible["candidates"], impossible["scenario"], cfg)
    assert r["decision"]["outcome"] == "escalation"
    assert {cid: checker.failed_rules(rs) for cid, rs in r["checks"].items()} == \
        {"C1": ["G-2"], "C2": ["F-1", "G-1"], "C3": ["F-1", "G-2"]}


def test_heuristic_uses_recorded_delay_once(demo, cfg):
    h = fallback.heuristic(demo["scenario"], cfg)
    assert h["candidate"]["landing"] == "22:29" == demo["scenario"].historical.actual_arrival
    assert h["candidate"]["extra_holding_min"] == 109          # 22:29 - baseline 20:40, not 119 + anything
    assert h["feasible"] is False and "F-1" in h["failed"]
    assert h["cost"]["delay_min"] == 109 and "Simulated" in h["assumption"]


def test_heuristic_reports_missing_input(demo, cfg):
    s = demo["scenario"].model_copy(update={"simulated": {**demo["scenario"].simulated,
                                                          "ground": {k: v for k, v in demo["scenario"].simulated["ground"].items() if k != "planned_gate"}}})
    h = fallback.heuristic(s, cfg)
    assert h["feasible"] is False and h["failed"] == ["INPUT"] and "planned_gate" in h["error"]


def test_feasible_candidate_without_cost_cannot_be_ranked(demo):
    cands = demo["candidates"][:2]
    checks = _checks(cands, {"C1"})
    with pytest.raises(MissingInput):
        fallback.solve(cands, checks, {"C1": None, "C2": _cost(1.0)})
    assert fallback.solve(cands, checks, {"C1": _cost(1.0), "C2": None}) == "C1"  # infeasible C2 may lack a cost
