import pytest

import costs
from checker import MissingInput
from models import CandidateCost
from tests.conftest import cand, crew, with_state

W = {"delay_usd_per_min": 100.76, "holding_fuel_usd_per_kg": 0.85, "overtime_usd_per_min": 1.5, "missed_connection_usd": 250}


def test_components_and_weighted_total(demo):
    c = costs.cost(cand(demo, "C5"), demo["scenario"], W)
    assert isinstance(c, CandidateCost)
    # 11 min holding, 440 kg, no crew at B7 (0 overtime), DL2045 at 21:17 missed by 20:44 + 40 min: 18 pax
    assert (c.delay_min, c.holding_fuel_kg, c.overtime_min, c.missed_connections) == (11, 440, 0, 18)
    assert c.total_usd == pytest.approx(11 * 100.76 + 440 * 0.85 + 18 * 250, abs=0.01)


def test_delay_relative_to_base_eta_and_no_double_count(demo):
    c2 = costs.cost(cand(demo, "C2"), demo["scenario"], W)
    assert c2.delay_min == 2 and c2.missed_connections == 0
    bd = costs.breakdown(cand(demo, "C2"), demo["scenario"], W)
    assert bd["inputs"]["base_eta"] == "20:22" and bd["inputs"]["delay_vs_schedule_min"] == 102
    assert demo["scenario"].historical.arrival_delay_min == 106      # recorded delay is never added


def test_zero_weights_isolate_components(demo):
    only_missed = {**{k: 0.0 for k in W}, "missed_connection_usd": 1.0}
    assert costs.cost(cand(demo, "C5"), demo["scenario"], only_missed).total_usd == 18


def test_overtime_is_service_window_past_shift_end(demo):
    s = with_state(demo["scenario"], lambda sim: crew(sim, "CRW-B4").__setitem__("shift_end", "2015-01-06T20:50"))
    c = costs.cost(cand(demo, "C4"), s, W)      # gate 20:43 + 35 min turnaround = 21:18; 28 min past 20:50
    assert c.overtime_min == 28


def test_missing_weight_raises(demo):
    with pytest.raises(MissingInput):
        costs.cost(cand(demo, "C4"), demo["scenario"], {k: v for k, v in W.items() if k != "overtime_usd_per_min"})


def test_missing_base_eta_raises(demo):
    s = with_state(demo["scenario"], lambda sim: sim["atc"].pop("base_eta"))
    with pytest.raises(MissingInput):
        costs.cost(cand(demo, "C4"), s, W)


def test_config_weights_are_used_by_default(demo, cfg):
    assert costs.weights_from_config(cfg) == {k: float(v) for k, v in cfg["costs"].items()}
    bd = costs.breakdown(cand(demo, "C5"), demo["scenario"])
    assert {r["component"] for r in bd["components"]} == set(costs.WEIGHT_KEYS)
    assert all("unit" in r and "weight" in r for r in bd["components"])
