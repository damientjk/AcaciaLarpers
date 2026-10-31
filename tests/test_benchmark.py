"""Benchmark reproducibility and the four labelled failure tests.

Malformed-response and timeout tests mock the agent layer (no API calls). They are skipped until
Person C's coordinator.run is implemented; they then run automatically.
"""
import inspect
import json

import pytest

import benchmark
import checker
import fallback
from tests.conftest import FIXTURES


def test_deterministic_run_is_reproducible(cfg):
    fx = benchmark.load_fixture(FIXTURES / "demo_scenario.json")
    a, b = benchmark.run_deterministic(fx, cfg), benchmark.run_deterministic(fx, cfg)
    for k in ("selected", "outcome", "feasible_before", "feasible_after", "rules_after", "costs", "state_version"):
        assert a[k] == b[k]
    assert a["selected"] == "C5" and a["feasible_before"] == ["C3"] and a["state_version"] == 2
    assert a["solver_before"]["candidate"] == "C3" and a["heuristic"]["feasible"] is False


def test_main_writes_real_numbers_not_sample(tmp_path):
    out = tmp_path / "benchmark.json"
    res = benchmark.main(["--out", str(out), "--quiet"])
    data = json.loads(out.read_text())
    assert data["sample"] is False and data == json.loads(json.dumps(res, default=str))
    assert data["deterministic"]["runs"] == 2 and data["deterministic"]["escalations"] == 1
    assert data["agents"]["completed"] == 0 and data["agents"]["not_run"]
    assert [t["test"] for t in data["failure_tests"]] == benchmark.FAILURE_TESTS


def test_more_than_eight_candidates_rejected(tmp_path):
    raw = json.loads((FIXTURES / "demo_scenario.json").read_text())
    raw["candidates"] += [dict(raw["candidates"][0], id="C9")]
    p = tmp_path / "nine.json"
    p.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        benchmark.load_fixture(p)


# ---------------------------------------------------------------- the four labelled failure tests

def test_failure_1_injected_invalid_proposal_is_blocked(cfg):
    fx = benchmark.load_fixtures(str(FIXTURES / "*.json"))
    rec = next(t for t in benchmark.failure_tests(fx, cfg) if t["test"] == "Injected invalid proposal")
    assert rec["passed"] is True and rec["result"] == "blocked"
    assert {"F-1", "T-1", "G-1", "G-2", "G-3", "C-1"} <= set(rec["detail"]["failed_rules"])


def test_failure_2_impossible_scenario_escalates(cfg):
    fx = benchmark.load_fixtures(str(FIXTURES / "*.json"))
    rec = next(t for t in benchmark.failure_tests(fx, cfg) if t["test"] == "Impossible scenario")
    assert rec["passed"] is True and rec["result"] == "escalation"


def _coordinator_or_skip():
    try:
        import coordinator
    except Exception as e:  # pragma: no cover
        pytest.skip(f"coordinator unavailable: {e}")
    if "inject" not in inspect.signature(coordinator.run).parameters:
        pytest.skip("coordinator.run has no 'inject' hook yet (Person C)")
    return coordinator


def _mock_agents(monkeypatch, mode):
    """Mocked API layer: never calls Anthropic. Ground's round-2 vote is malformed or times out."""
    import agents

    def bad_vote(agent, *a, **k):
        if agent == "ground":
            if mode == "timeout":
                raise TimeoutError("mocked 20 s timeout")
            return {"vote": "yes please", "agent": "ground"}   # fails Vote schema
        return agents.fake_vote(agent, *a, **k) if hasattr(agents, "fake_vote") else None

    monkeypatch.setattr(agents, "vote", bad_vote, raising=False)
    monkeypatch.setattr(agents, "offer", getattr(agents, "fake_offer", agents.offer), raising=False)


@pytest.mark.parametrize("mode", ["malformed", "timeout"])
def test_failure_3_and_4_malformed_or_timeout_falls_back(monkeypatch, mode, cfg):
    coordinator = _coordinator_or_skip()
    _mock_agents(monkeypatch, mode)
    try:
        log = coordinator.run(scenario_id="demo-001", fake_agents=False,
                              inject={"mode": mode, "agent": "ground", "round": 2})
    except NotImplementedError:
        pytest.skip("coordinator.run not implemented yet")
    assert log["outcome"]["type"] == "fallback"
    assert benchmark._violations(log) == 0
    votes = {v["agent"]: v["vote"] for r in log["rounds"] for v in r.get("votes", [])}
    assert votes.get("ground") == "abstain"
