"""Hard checks: F-1, W-1, R-1, T-1, G-1, G-2, G-3, C-1. Simplified, not full FAA compliance. (Yizhuo)"""
from models import Candidate, CheckResult, Scenario


def check(candidate: Candidate, scenario: Scenario) -> list[CheckResult]:
    raise NotImplementedError


def feasible(results: list[CheckResult]) -> bool:
    return all(r.passed for r in results)
