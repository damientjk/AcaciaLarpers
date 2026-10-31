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
    """scenario.py's demo-001 (ATL, US2031, 2015-01-06): issue 19:59, base ETA 20:22, 3-min slots, cap 20/h,
    fuel at base ETA 2360 kg, reserve 1800 kg, burn 40 kg/min (fuel-safe 14 min), gates B4/B7/B9."""
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


def with_config(cfg: dict, mutate) -> dict:
    c = copy.deepcopy(cfg)
    mutate(c)
    return c


def cand(demo, cid: str, **changes) -> Candidate:
    base = next(c for c in demo["candidates"] if c.id == cid)
    return base.model_copy(update=changes)


def rule(results, rule_id):
    return next(r for r in results if r.rule_id == rule_id)


def slot(sim, slot_id):
    return next(s for s in sim["atc"]["slots"] if s["slot_id"] == slot_id)


def gate(sim, gate_id):
    return next(g for g in sim["ground"]["gates"] if g["gate_id"] == gate_id)


def crew(sim, crew_id):
    return next(c for c in sim["ground"]["crews"] if c["crew_id"] == crew_id)
