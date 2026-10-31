import json
import time
from types import SimpleNamespace

import agents
import coordinator
from agents import AgentResult, OfferReply, VoteReply
from models import Vote
from tests.toy_world import ToyWorld, scenario

W = {"delay_usd_per_min": 100.76}


def run(**kw):
    return coordinator.negotiate(ToyWorld(), kw.pop("s", scenario()), W, **kw)


def test_demo_reaches_consensus_through_concessions():
    log = run(fake_agents=True)
    out = log["outcome"]
    assert out["type"] == "consensus" and out["final_candidate"] == "C5"
    assert sorted(out["concessions_that_unlocked"]) == ["ATC_EARLIER_SLOT", "GROUND_REASSIGN_CREW"]
    assert log["compromise"]["feasible_before"] == ["C3"]
    assert log["compromise"]["proposal"] == {"version": 2, "candidate": "C5"}
    assert [len(r.get("offers", r.get("votes"))) for r in log["rounds"]] == [3, 3]
    assert log["stats"]["api_calls"] == 0


def test_reject_falls_back_on_base_state(monkeypatch):
    real = agents.fake_vote

    def pilot_rejects(agent, brief, proposal, run_id):
        res = real(agent, brief, proposal, run_id)
        if agent == "pilot":
            res.message = res.message.model_copy(update={"vote": "reject"})
        return res

    monkeypatch.setattr(agents, "fake_vote", pilot_rejects)
    log = run(fake_agents=True)
    assert log["outcome"]["type"] == "fallback"
    assert log["outcome"]["final_candidate"] == "C3"      # C5 needs unconfirmed concessions
    assert "pilot rejected" in log["outcome"]["reason"]


def test_impossible_scenario_escalates():
    log = run(s=scenario(impossible=True), fake_agents=True)
    assert log["outcome"]["type"] == "escalation"
    assert log["outcome"]["final_candidate"] is None
    assert log["compromise"] is None


def test_injected_invalid_proposal_is_blocked(monkeypatch):
    monkeypatch.setattr(coordinator, "compromise", lambda offers, feasible, costs: ("C1", "injected", []))
    monkeypatch.setattr(agents, "fake_vote", lambda agent, brief, proposal, run_id: AgentResult(
        agent, Vote(agent=agent, run_id=run_id, proposal_version=proposal.version, vote="accept", rationale="")))
    log = run(fake_agents=True)
    assert log["outcome"]["type"] == "fallback"
    assert log["outcome"]["final_candidate"] == "C3"
    assert "final recheck failed" in log["outcome"]["reason"]


class BrokenClient:
    """Every call returns no parsed output, like a malformed or refused response."""
    calls = 0

    @property
    def messages(self):
        return self

    def parse(self, **kw):
        BrokenClient.calls += 1
        return SimpleNamespace(stop_reason="end_turn", parsed_output=None)


def test_malformed_responses_fall_back(monkeypatch):
    monkeypatch.setattr(agents, "_client", lambda: BrokenClient())
    log = run(fake_agents=False)
    offers = log["rounds"][0]["offers"]
    assert not any(o["valid"] for o in offers)
    assert log["outcome"]["type"] == "fallback" and log["outcome"]["final_candidate"] == "C3"
    assert log["stats"] == {**log["stats"], "api_calls": 12, "retries": 6}   # 6 calls, each retried once


def test_slow_agent_counts_as_timeout():
    def call(agent):
        if agent == "ground":
            time.sleep(1)
        return AgentResult(agent)

    out = agents.in_parallel(call, budget_s=0.2)
    assert "timeout" in out["ground"].error and out["atc"].error is None


def test_offer_validation_rejects_foreign_concession_and_unknown_ids():
    r = OfferReply(preferred="C9", acceptable=["C1"], constraints_cited=["X-1"],
                   concessions=[{"id": "ATC_EARLIER_SLOT", "target": None}], rationale="")
    errs = agents._offer_errors("ground", r, {"C1", "C3"})
    assert len(errs) == 4


def test_log_saves_as_json(tmp_path):
    path = coordinator.save(run(fake_agents=True), str(tmp_path))
    assert path.exists() and path.stat().st_size > 1000


class GoodClient:
    """Well-formed replies with usage, to exercise the real agent path without the API."""
    messages = property(lambda self: self)

    def parse(self, **kw):
        brief = json.loads(kw["messages"][0]["content"])
        if kw["output_format"] is OfferReply:
            parsed = OfferReply(preferred="C5", acceptable=["C3", "C5"], constraints_cited=[],
                                concessions=[{"id": brief["your_concession"], "target": None}], rationale="ok")
        else:
            parsed = VoteReply(vote="accept", rationale="ok")
        return SimpleNamespace(stop_reason="end_turn", parsed_output=parsed,
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=200))


def test_real_agent_path_and_usage(monkeypatch):
    monkeypatch.setattr(agents, "_client", lambda: GoodClient())
    log = run(fake_agents=False)
    assert log["outcome"]["type"] == "consensus" and log["outcome"]["final_candidate"] == "C5"
    st = log["stats"]
    assert (st["api_calls"], st["retries"], st["input_tokens"], st["output_tokens"]) == (6, 0, 6000, 1200)
    assert st["est_cost_usd"] == agents.cost_usd(6000, 1200) > 0
    assert "C5" in coordinator.summary(log)


def test_rejected_concession_is_logged_and_unlocks_nothing(monkeypatch):
    world = ToyWorld()
    plain = world.apply

    def atc_rejected(s, offered):
        ok = [c for c in offered if c["id"] != "ATC_EARLIER_SLOT"]
        bad = [{**c, "applied": False, "reason": "no free slot"} for c in offered if c["id"] == "ATC_EARLIER_SLOT"]
        return plain(s, ok), [{**c, "applied": True} for c in ok] + bad

    world.apply = atc_rejected
    log = coordinator.negotiate(world, scenario(), W, fake_agents=True)
    applied = {c["id"]: c["applied"] for c in log["compromise"]["concessions_applied"]}
    assert applied == {"ATC_EARLIER_SLOT": False, "GROUND_REASSIGN_CREW": True}
    assert log["outcome"]["final_candidate"] == "C3"      # C5 still needs the rejected slot
    assert log["outcome"]["concessions_that_unlocked"] == []
