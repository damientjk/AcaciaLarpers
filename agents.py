"""Three agent prompts, LLM wrapper, schema validation, one retry, timeouts, parallel calls. (Damien)"""
from models import Offer, Proposal, Vote


def offer(agent: str, view: dict, candidates: list, run_id: str, state_version: int) -> Offer:
    raise NotImplementedError


def vote(agent: str, view: dict, proposal: Proposal, round1: list[Offer], run_id: str) -> Vote:
    raise NotImplementedError


def fake_offer(agent: str, view: dict, candidates: list, run_id: str, state_version: int) -> Offer:
    """Picks randomly from acceptable options so nobody waits on the real agents."""
    raise NotImplementedError
