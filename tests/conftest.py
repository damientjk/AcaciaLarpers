import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import checker  # noqa: E402
from models import Candidate, Scenario  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def load(name: str) -> dict:
    raw = json.loads((FIXTURES / name).read_text())
    return {"scenario": Scenario(**raw["scenario"]), "candidates": [Candidate(**c) for c in raw["candidates"]],
            "concessions": raw.get("concessions", []), "raw": raw}


@pytest.fixture
def demo():
    return load("demo_scenario.json")


@pytest.fixture
def impossible():
    return load("impossible_scenario.json")


@pytest.fixture
def cfg():
    return checker.load_config()


def with_state(scenario: Scenario, mutate) -> Scenario:
    """Deep-copy the simulated state, apply mutate(sim) and return a new frozen Scenario."""
    sim = copy.deepcopy(dict(scenario.simulated))
    mutate(sim)
    return scenario.model_copy(update={"simulated": sim})


def cand(demo, cid: str, **changes) -> Candidate:
    base = next(c for c in demo["candidates"] if c.id == cid)
    return base.model_copy(update=changes)


def rule(results, rule_id):
    return next(r for r in results if r.rule_id == rule_id)
