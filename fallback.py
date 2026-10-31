"""Deterministic solver and heuristic baseline. (Yizhuo)"""
from models import Candidate


def solve(candidates: list[Candidate], checks: dict, costs: dict) -> str | None:
    """Lowest-cost feasible candidate, ties broken by candidate ID. None means escalate."""
    raise NotImplementedError


def heuristic(scenario) -> dict:
    """Delay ETA by the recorded delay and keep the planned gate."""
    raise NotImplementedError
