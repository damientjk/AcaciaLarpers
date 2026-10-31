"""One passing boundary and one failing boundary per rule, plus missing-input and concession behaviour.
All numbers come from scenario.py's demo-001 (see conftest.demo)."""
import pytest

import checker
import scenario as S
from models import CheckResult
from tests.conftest import cand, crew, gate, rule, slot, with_config, with_state


def run(c, s, cfg, rid):
    return rule(checker.check(c, s, cfg), rid)


# ---------------------------------------------------------------- F-1 fuel reserve

def test_f1_equality_passes(demo, cfg):
    # 3395 - 45*23 = 2360 kg at base ETA; 14 min * 40 = 560 -> exactly the 1800 kg reserve
    r = run(cand(demo, "C4", extra_holding_min=14), demo["scenario"], cfg, "F-1")
    assert r.passed and r.inputs["fuel_at_landing_kg"] == 1800 and r.inputs["fuel_at_base_eta_kg"] == 2360


def test_f1_one_minute_more_fails(demo, cfg):
    r = run(cand(demo, "C4", extra_holding_min=15), demo["scenario"], cfg, "F-1")
    assert not r.passed and "below" in r.explanation


def test_f1_missing_reserve_fails_not_raises(demo, cfg):
    s = with_state(demo["scenario"], lambda sim: sim["pilot"].pop("reserve_kg"))
    r = run(cand(demo, "C4"), s, cfg, "F-1")
    assert not r.passed and "Cannot evaluate" in r.explanation and "reserve_kg" in r.inputs["error"]


def test_f1_non_finite_fuel_fails(demo, cfg):
    s = with_state(demo["scenario"], lambda sim: sim["pilot"].__setitem__("fuel_on_board_kg", float("nan")))
    assert not run(cand(demo, "C4"), s, cfg, "F-1").passed


# ---------------------------------------------------------------- W-1 wake spacing

def test_w1_passes_with_margin(demo, cfg):
    # C4 lands 20:33; the last occupied slot before it is UA402 at 20:30 (large): 180 s, profile large-large 120 s
    r = run(cand(demo, "C4"), demo["scenario"], cfg, "W-1")
    assert r.passed and r.inputs == {**r.inputs, "preceding": "UA402", "gap_s": 180, "pair": "large-large"}


def test_w1_equality_passes_and_one_second_short_fails(demo, cfg):
    eq = with_config(cfg, lambda c: c["simulation"]["wake_separation_s"].__setitem__("large-large", 180))
    assert run(cand(demo, "C4"), demo["scenario"], eq, "W-1").passed
    short = with_config(cfg, lambda c: c["simulation"]["wake_separation_s"].__setitem__("large-large", 181))
    assert not run(cand(demo, "C4"), demo["scenario"], short, "W-1").passed


def test_w1_unsupported_pair_fails(demo, cfg):
    c = with_config(cfg, lambda c: c["simulation"]["wake_separation_s"].pop("large-large"))
    r = run(cand(demo, "C4"), demo["scenario"], c, "W-1")
    assert not r.passed and "No simulated separation profile" in r.explanation


def test_w1_heavy_pair_in_adjacent_slot_fails(demo, cfg):
    def heavy(sim):
        slot(sim, "SL-2030")["occupant_wake"] = "heavy"
        sim["atc"]["own_wake"] = "heavy"
    r = run(cand(demo, "C4"), with_state(demo["scenario"], heavy), cfg, "W-1")   # heavy-heavy needs 240 s, gap 180 s
    assert not r.passed and r.inputs["pair"] == "heavy-heavy" and r.inputs["required_s"] == 240


def test_w1_no_preceding_aircraft_passes_explicitly(demo, cfg):
    def clear(sim):
        for sl in sim["atc"]["slots"]:
            sl.update(occupant=None, occupant_wake=None)
    r = run(cand(demo, "C4"), with_state(demo["scenario"], clear), cfg, "W-1")
    assert r.passed and r.inputs["preceding"] is None


# ---------------------------------------------------------------- R-1 runway capacity

def test_r1_free_slot_at_capacity_passes(demo, cfg):
    # 12 occupied slots in 20:00-21:00 plus this flight = 13
    s = with_state(demo["scenario"], lambda sim: sim["atc"].__setitem__("runway_capacity_per_hour", 13))
    r = run(cand(demo, "C4"), s, cfg, "R-1")
    assert r.passed and r.inputs["arrivals_in_interval"] == 13


def test_r1_over_capacity_fails(demo, cfg):
    s = with_state(demo["scenario"], lambda sim: sim["atc"].__setitem__("runway_capacity_per_hour", 12))
    assert not run(cand(demo, "C4"), s, cfg, "R-1").passed


def test_r1_occupied_slot_fails_and_names_the_concession(demo, cfg):
    r = run(cand(demo, "C1"), demo["scenario"], cfg, "R-1")
    assert not r.passed and "DL1187" in r.explanation and "ATC_EARLIER_SLOT" in r.explanation


def test_r1_unoffered_time_fails(demo, cfg):
    r = run(cand(demo, "C4", landing="20:34", extra_holding_min=12, gate_arrival="20:44", gate_release="21:19"),
            demo["scenario"], cfg, "R-1")
    assert not r.passed and "not an offered" in r.explanation


# ---------------------------------------------------------------- T-1 taxiways

def test_t1_open_route_passes(demo, cfg):
    assert run(cand(demo, "C4"), demo["scenario"], cfg, "T-1").passed


def test_t1_closed_segment_fails(demo, cfg):
    r = run(cand(demo, "C6"), demo["scenario"], cfg, "T-1")   # B9 route D,E; D is closed
    assert not r.passed and r.inputs["blocked_segments"] == ["D"]


def test_t1_unknown_gate_fails(demo, cfg):
    assert not run(cand(demo, "C4", gate="Z9"), demo["scenario"], cfg, "T-1").passed


# ---------------------------------------------------------------- G-1 gate compatibility

def test_g1_compatible_passes_including_larger_gate(demo, cfg):
    assert run(cand(demo, "C4"), demo["scenario"], cfg, "G-1").passed
    s = with_state(demo["scenario"], lambda sim: gate(sim, "B4").__setitem__("max_class", "widebody"))
    assert run(cand(demo, "C4"), s, cfg, "G-1").passed


def test_g1_too_small_gate_fails(demo, cfg):
    s = with_state(demo["scenario"], lambda sim: gate(sim, "B4").__setitem__("max_class", "regional"))
    r = run(cand(demo, "C4"), s, cfg, "G-1")
    assert not r.passed and r.inputs["gate_max_class"] == "regional"


def test_g1_unknown_class_fails(demo, cfg):
    s = with_state(demo["scenario"], lambda sim: sim["ground"].__setitem__("aircraft_class", "A380"))
    assert not run(cand(demo, "C4"), s, cfg, "G-1").passed


# ---------------------------------------------------------------- G-2 gate occupancy

def test_g2_exact_adjacency_passes(demo, cfg):
    # C4 reaches B4 at 20:43; DL1622 leaving 20:33 + 10 min buffer = 20:43 -> half-open, passes
    s = with_state(demo["scenario"], lambda sim: gate(sim, "B4")["occupancy"][0].__setitem__("end", "2015-01-06T20:33"))
    r = run(cand(demo, "C4"), s, cfg, "G-2")
    assert r.passed and r.inputs["conflicts"] == []


def test_g2_one_minute_overlap_fails(demo, cfg):
    s = with_state(demo["scenario"], lambda sim: gate(sim, "B4")["occupancy"][0].__setitem__("end", "2015-01-06T20:34"))
    r = run(cand(demo, "C4"), s, cfg, "G-2")
    assert not r.passed and r.inputs["conflicts"][0]["occupant"] == "DL1622"


def test_g2_empty_gate_passes_and_planned_gate_fails(demo, cfg):
    assert run(cand(demo, "C5"), demo["scenario"], cfg, "G-2").passed
    assert not run(cand(demo, "C4"), demo["scenario"], cfg, "G-2").passed


# ---------------------------------------------------------------- G-3 turnaround and coupling

def test_g3_equality_passes(demo, cfg):
    r = run(cand(demo, "C4"), demo["scenario"], cfg, "G-3")   # 35 min service, 35 min minimum
    assert r.passed and r.inputs["service_min"] == 35


def test_g3_one_minute_short_fails(demo, cfg):
    r = run(cand(demo, "C4", gate_release="21:17"), demo["scenario"], cfg, "G-3")
    assert not r.passed and "turnaround" in r.explanation


def test_g3_inconsistent_taxi_fails(demo, cfg):
    assert not run(cand(demo, "C4", gate_arrival="20:44", gate_release="21:19"), demo["scenario"], cfg, "G-3").passed


def test_g3_holding_not_matching_landing_fails(demo, cfg):
    r = run(cand(demo, "C4", extra_holding_min=10), demo["scenario"], cfg, "G-3")
    assert not r.passed and "extra_holding_min" in r.explanation


def test_g3_landing_before_base_eta_fails(demo, cfg):
    r = run(cand(demo, "C4", landing="20:21", extra_holding_min=0, gate_arrival="20:31", gate_release="21:06"),
            demo["scenario"], cfg, "G-3")
    assert not r.passed and "before the base ETA" in r.explanation


def test_g3_release_before_arrival_fails(demo, cfg):
    assert not run(cand(demo, "C4", gate_release="20:30"), demo["scenario"], cfg, "G-3").passed


# ---------------------------------------------------------------- C-1 crew

def test_c1_on_shift_passes_and_shift_end_equality_passes(demo, cfg):
    assert run(cand(demo, "C4"), demo["scenario"], cfg, "C-1").inputs["eligible_crews"] == ["CRW-B4"]
    s = with_state(demo["scenario"], lambda sim: crew(sim, "CRW-B4").__setitem__("shift_end", "2015-01-06T20:43"))
    assert run(cand(demo, "C4"), s, cfg, "C-1").passed


def test_c1_shift_one_minute_short_fails(demo, cfg):
    s = with_state(demo["scenario"], lambda sim: crew(sim, "CRW-B4").__setitem__("shift_end", "2015-01-06T20:42"))
    assert not run(cand(demo, "C4"), s, cfg, "C-1").passed


def test_c1_no_crew_for_gate_fails_then_passes_after_reassignment(demo, cfg):
    r = run(cand(demo, "C5"), demo["scenario"], cfg, "C-1")
    assert not r.passed and r.inputs["eligible_crews"] == [] and "GROUND_REASSIGN_CREW" in r.explanation
    s2 = S.apply_concessions(demo["scenario"], [{"agent": "ground", "id": "GROUND_REASSIGN_CREW", "target": "B7"}])
    r2 = run(cand(demo, "C5"), s2, cfg, "C-1")
    assert r2.passed and "reassigned from B9" in r2.explanation


# ---------------------------------------------------------------- shape, invalid candidates, concessions

def test_check_returns_eight_agreed_results(demo, cfg):
    rs = checker.check(cand(demo, "C4"), demo["scenario"], cfg)
    assert [r.rule_id for r in rs] == checker.RULES
    assert all(isinstance(r, CheckResult) and r.basis and isinstance(r.inputs, dict) for r in rs)


def test_negative_holding_fails_every_time_rule(demo, cfg):
    rs = checker.check(cand(demo, "C4", extra_holding_min=-1), demo["scenario"], cfg)
    assert not checker.feasible(rs)
    assert {"F-1", "W-1", "R-1", "G-2", "G-3", "C-1"} <= set(checker.failed_rules(rs))


def test_unparsable_time_fails_not_raises(demo, cfg):
    rs = checker.check(cand(demo, "C4", landing="8pm"), demo["scenario"], cfg)
    assert not checker.feasible(rs) and "not HH:MM" in rule(rs, "R-1").inputs["error"]


def test_missing_agent_state_fails_everything(demo, cfg):
    s = demo["scenario"].model_copy(update={"simulated": {"atc": demo["scenario"].simulated["atc"]}})
    rs = checker.check(cand(demo, "C4"), s, cfg)
    assert not checker.feasible(rs) and not rule(rs, "F-1").passed and not rule(rs, "G-1").passed


def test_duplicate_candidate_ids_rejected(demo, cfg):
    with pytest.raises(ValueError):
        checker.check_all([cand(demo, "C4"), cand(demo, "C5", id="C4")], demo["scenario"], cfg)


def test_hhmm_overnight_rollover_and_iso(demo):
    issue = checker.issue_time(demo["scenario"])
    assert checker.parse_time("00:30", issue).day == issue.day + 1
    assert checker.parse_time("2015-01-07T00:30", issue).day == issue.day + 1


def test_recheck_on_concession_adjusted_state_source_unchanged(demo, cfg):
    before = checker.check_all(demo["candidates"], demo["scenario"], cfg)
    assert not any(checker.feasible(rs) for rs in before.values())
    after_s = S.apply_concessions(demo["scenario"], demo["concessions"])
    after = checker.check_all(demo["candidates"], after_s, cfg)
    assert {cid for cid, rs in after.items() if checker.feasible(rs)} == {"C2", "C5"}
    assert slot(demo["scenario"].simulated, "SL-2024")["occupant"] == "DL1187"      # source untouched
    assert crew(demo["scenario"].simulated, "CRW-B9")["assigned_gate"] == "B9"
