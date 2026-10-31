"""Benchmark reproducibility and the four labelled failure tests. The malformed-response and timeout tests
run the real coordinator on the real pipeline with a mocked LLM client: no API call is ever made."""
import json

import pytest

import benchmark
from tests.conftest import FIXTURES

GLOB = str(FIXTURES / "*.json")


def test_deterministic_run_is_reproducible(cfg):
    fx = benchmark.load_fixture(FIXTURES / "demo_scenario.json")
    a, b = benchmark.run_deterministic(fx, cfg), benchmark.run_deterministic(fx, cfg)
    for k in ("selected", "outcome", "feasible_before", "feasible_after", "rules_after", "costs", "state_version"):
        assert a[k] == b[k]
    assert a["selected"] == "C2" and a["feasible_before"] == [] and a["feasible_after"] == ["C2", "C5"]
    assert a["state_version"] == 2 and a["solver_base"]["candidate"] is None and a["heuristic"]["feasible"] is False


def test_reference_optimum_enumerates_concession_variants(cfg):
    fx = benchmark.load_fixture(FIXTURES / "demo_scenario.json")
    fx["concessions"] = None                     # seeded mode: benchmark tries the variants itself
    variants = benchmark.concession_variants(fx)
    assert all(any(c["id"] == "PILOT_EXTRA_HOLDING" for c in v) for v in variants) and len(variants) > 1
    rec = benchmark.run_deterministic(fx, cfg)
    assert rec["selected"] == "C2" and rec["solver"]["total_usd"] == pytest.approx(269.52)
    assert {c["id"] for c in rec["concessions_applied"]} == {"ATC_EARLIER_SLOT", "PILOT_EXTRA_HOLDING", "GROUND_REASSIGN_CREW"}


def test_main_writes_real_numbers_not_sample(tmp_path):
    out = tmp_path / "benchmark.json"
    res = benchmark.main(["--fixtures", GLOB, "--out", str(out), "--quiet"])
    data = json.loads(out.read_text())
    assert data["sample"] is False and data == json.loads(json.dumps(res, default=str))
    assert data["deterministic"]["runs"] == 2 and data["deterministic"]["escalations"] == 1
    assert data["agents"]["completed"] == 0 and data["agents"]["not_run"]
    assert [t["test"] for t in data["failure_tests"]] == benchmark.FAILURE_TESTS


def test_fake_agent_runs_go_through_the_real_pipeline(tmp_path):
    res = benchmark.main(["--ids", "demo-001", "--agents", "1", "--out", str(tmp_path / "b.json"), "--quiet"])
    a = res["agents"]
    assert a["completed"] == 1 and a["fake_agents"] is True and a["accepted_violations"] == 0
    run = res["agent_runs"][0]
    assert run["outcome"] in ("consensus", "fallback", "escalation") and run["api_calls"] == 0
    if run["outcome"] == "consensus":
        assert run["cost_gap_vs_reference_usd"] >= 0     # agents cannot beat the reference optimum


def test_more_than_eight_candidates_rejected(tmp_path):
    raw = json.loads((FIXTURES / "demo_scenario.json").read_text())
    raw["candidates"] += [dict(raw["candidates"][0], id="C9")]
    p = tmp_path / "nine.json"
    p.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        benchmark.load_fixture(p)


# ---------------------------------------------------------------- the four labelled failure tests

@pytest.fixture(scope="module")
def failure_results():
    import checker
    return {t["test"]: t for t in benchmark.failure_tests(benchmark.load_fixtures(GLOB), checker.load_config())}


def test_failure_1_injected_invalid_proposal_is_blocked(failure_results):
    rec = failure_results["Injected invalid proposal"]
    assert rec["passed"] is True and rec["result"] == "blocked"
    assert {"F-1", "T-1", "G-1", "G-2", "G-3", "C-1"} <= set(rec["detail"]["failed_rules"])


def test_failure_2_impossible_scenario_escalates(failure_results):
    rec = failure_results["Impossible scenario"]
    assert rec["passed"] is True and rec["result"] == "escalation"


def test_failure_3_malformed_response_never_reaches_consensus(failure_results):
    rec = failure_results["Malformed agent response"]
    assert rec["passed"] is True, rec
    assert not any(rec["detail"]["offers_valid"]) and rec["detail"]["violations"] == 0
    assert rec["detail"]["api_calls_mocked"] == 6 and rec["detail"]["retries"] == 3   # 3 offers, each retried once


def test_failure_4_api_timeout_never_reaches_consensus(failure_results):
    rec = failure_results["API timeout"]
    assert rec["passed"] is True, rec
    assert rec["result"] in ("fallback", "escalation") and rec["detail"]["violations"] == 0
