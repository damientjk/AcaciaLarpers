"""Soft costs; weights and units come from config.yaml. (Yizhuo)"""
from models import Candidate, CandidateCost, Scenario


def cost(candidate: Candidate, scenario: Scenario, weights: dict) -> CandidateCost:
    raise NotImplementedError
