import pytest

import costs
from checker import MissingInput
from models import CandidateCost
from tests.conftest import cand, with_state

W = {"delay_usd_per_min": 100.76, "holding_fuel_usd_per_kg": 0.85, "overtime_usd_per_min": 1.5, "missed_connection_usd": 250}


def test_components_and_weighted_total(demo):
    c = costs.cost(cand(demo, "C3"), demo["scenario"], W)
    assert isinstance(c, CandidateCost)
    assert (c.delay_min, c.holding_fuel_kg, c.overtime_min, c.missed_connections) == (12, 480, 45, 6)
    assert c.total_usd == pytest.approx(12 * 100.76 + 480 * 0.85 + 45 * 1.5 + 6 * 250, abs=0.01)


def test_delay_relative_to_baseline_not_schedule_and_no_double_count(demo):
    c1 = costs.cost(cand(demo, "C1"), demo["scenario"], W)
    assert c1.delay_min == 0                       # lands at the baseline ETA 20:40
    assert demo["scenario"].historical.arrival_delay_min == 119  # recorded delay is never added
    bd = costs.breakdown(cand(demo, "C1"), demo["scenario"], W)
    assert bd["inputs"]["delay_vs_schedule_min"] == 10 and bd["inputs"]["baseline_eta"] == "20:40"


def test_earlier_than_baseline_is_negative_delay(demo):
    assert costs.cost(cand(demo, "C5"), demo["scenario"], W).delay_min == -8


def test_zero_weights_isolate_components(demo):
    only_missed = {**{k: 0.0 for k in W}, "missed_connection_usd": 1.0}
    assert costs.cost(cand(demo, "C4"), demo["scenario"], only_missed).total_usd == 9


def test_overtime_uses_serving_crew_regular_end(demo):
    s = with_state(demo["scenario"], lambda sim: sim["ground"]["crews"][0].__setitem__("regular_end", "21:20"))
    assert costs.cost(cand(demo, "C1"), s, W).overtime_min == 13   # release 21:33 - 21:20


def test_missing_weight_raises(demo):
    with pytest.raises(MissingInput):
        costs.cost(cand(demo, "C1"), demo["scenario"], {k: v for k, v in W.items() if k != "overtime_usd_per_min"})


def test_missing_baseline_eta_raises(demo):
    s = with_state(demo["scenario"], lambda sim: sim["atc"].pop("baseline_eta"))
    with pytest.raises(MissingInput):
        costs.cost(cand(demo, "C1"), s, W)


def test_config_weights_are_used_by_default(demo, cfg):
    assert costs.weights_from_config(cfg) == {k: float(v) for k, v in cfg["costs"].items()}
    bd = costs.breakdown(cand(demo, "C3"), demo["scenario"])
    assert {r["component"] for r in bd["components"]} == set(costs.WEIGHT_KEYS)
    assert all("unit" in r and "weight" in r for r in bd["components"])
