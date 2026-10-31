"""One passing boundary and one failing boundary per rule, plus missing-input and concession behaviour."""
import pytest

import checker
from models import CheckResult
from tests.conftest import cand, rule, with_state


def run(c, s, cfg, rid):
    return rule(checker.check(c, s, cfg), rid)


# ---------------------------------------------------------------- F-1 fuel reserve

def test_f1_equality_passes(demo, cfg):
    # 2600 - 12*40 = 2120; reserve raised to exactly 2120 must pass
    s = with_state(demo["scenario"], lambda sim: sim["pilot"].__setitem__("reserve_kg", 2120))
    r = run(cand(demo, "C3"), s, cfg, "F-1")
    assert r.passed and r.inputs["fuel_at_landing_kg"] == 2120


def test_f1_one_minute_more_fails(demo, cfg):
    s = with_state(demo["scenario"], lambda sim: sim["pilot"].__setitem__("reserve_kg", 2120))
    r = run(cand(demo, "C3", extra_holding_min=13), s, cfg, "F-1")
    assert not r.passed and "below" in r.explanation


def test_f1_missing_reserve_fails_not_raises(demo, cfg):
    s = with_state(demo["scenario"], lambda sim: sim["pilot"].pop("reserve_kg"))
    r = run(cand(demo, "C1"), s, cfg, "F-1")
    assert not r.passed and "Cannot evaluate" in r.explanation and "reserve_kg" in r.inputs["error"]


def test_f1_non_finite_fuel_fails(demo, cfg):
    s = with_state(demo["scenario"], lambda sim: sim["pilot"].__setitem__("fuel_at_baseline_eta_kg", float("nan")))
    assert not run(cand(demo, "C1"), s, cfg, "F-1").passed


# ---------------------------------------------------------------- W-1 wake spacing

def _move(callsign, to):
    def m(sim):
        for o in sim["atc"]["other_arrivals"]:
            if o["callsign"] == callsign:
                o["time"] = to
    return m


def test_w1_equality_passes(demo, cfg):
    # C1 lands 20:40 behind UAL455 (H); H-M needs 180 s. Leader at 20:37 gives exactly 180 s.
    s = with_state(demo["scenario"], _move("UAL455", "20:37"))
    r = run(cand(demo, "C1"), s, cfg, "W-1")
    assert r.passed and r.inputs["gap_s"] == 180 and r.inputs["pair"] == "H-M"


def test_w1_one_second_short_fails(demo, cfg):
    s = with_state(demo["scenario"], _move("UAL455", "20:38"))
    r = run(cand(demo, "C1"), s, cfg, "W-1")
    assert not r.passed and r.inputs["gap_s"] == 120


def test_w1_unsupported_pair_fails(demo, cfg):
    s = with_state(demo["scenario"], lambda sim: sim["atc"]["wake_separation_s"].pop("H-M"))
    r = run(cand(demo, "C1"), s, cfg, "W-1")
    assert not r.passed and "No simulated separation profile" in r.explanation


def test_w1_no_preceding_aircraft_passes_explicitly(demo, cfg):
    s = with_state(demo["scenario"], lambda sim: sim["atc"].__setitem__("other_arrivals", []))
    r = run(cand(demo, "C1"), s, cfg, "W-1")
    assert r.passed and r.inputs["preceding"] is None


# ---------------------------------------------------------------- R-1 runway capacity

def _add(*arrivals):
    def m(sim):
        sim["atc"]["other_arrivals"] += [{"callsign": f"X{i}", "time": t, "wake_category": "L"} for i, t in enumerate(arrivals)]
    return m


def test_r1_at_capacity_passes(demo, cfg):
    # bin 20:40-20:50 capacity 3: two others + focal = 3
    s = with_state(demo["scenario"], _add("20:46", "20:49"))
    r = run(cand(demo, "C1"), s, cfg, "R-1")
    assert r.passed and r.inputs["arrivals_in_interval"] == 3


def test_r1_over_capacity_fails(demo, cfg):
    s = with_state(demo["scenario"], _add("20:46", "20:48", "20:49"))
    r = run(cand(demo, "C1"), s, cfg, "R-1")
    assert not r.passed and r.inputs["arrivals_in_interval"] == 4


def test_r1_unoffered_slot_fails(demo, cfg):
    r = run(cand(demo, "C5"), demo["scenario"], cfg, "R-1")  # 20:32 only opens via ATC_EARLIER_SLOT
    assert not r.passed and "not an offered" in r.explanation


# ---------------------------------------------------------------- T-1 taxiways

def test_t1_open_route_passes(demo, cfg):
    assert run(cand(demo, "C1"), demo["scenario"], cfg, "T-1").passed


def test_t1_closed_segment_fails(demo, cfg):
    r = run(cand(demo, "C8"), demo["scenario"], cfg, "T-1")  # C5 gate route uses closed taxiway L
    assert not r.passed and r.inputs["blocked_segments"] == ["L"]


def test_t1_unknown_gate_route_fails(demo, cfg):
    assert not run(cand(demo, "C1", gate="Z9"), demo["scenario"], cfg, "T-1").passed


# ---------------------------------------------------------------- G-1 gate compatibility

def test_g1_compatible_passes(demo, cfg):
    assert run(cand(demo, "C1"), demo["scenario"], cfg, "G-1").passed


def test_g1_incompatible_fails(demo, cfg):
    r = run(cand(demo, "C8"), demo["scenario"], cfg, "G-1")
    assert not r.passed and r.inputs["gate_classes"] == ["regional"]


# ---------------------------------------------------------------- G-2 gate occupancy

def _end(gate, booking, end):
    def m(sim):
        for b in sim["ground"]["gates"][gate]["bookings"]:
            if b["id"] == booking:
                b["end"] = end
    return m


def test_g2_exact_adjacency_passes(demo, cfg):
    # C4 arrives 21:13; booking end 21:03 + 10 buffer = 21:13 -> half-open, passes
    s = with_state(demo["scenario"], _end("B4", "BK-B4-1", "21:03"))
    r = run(cand(demo, "C4"), s, cfg, "G-2")
    assert r.passed and r.inputs["conflicts"] == []


def test_g2_one_minute_overlap_fails(demo, cfg):
    s = with_state(demo["scenario"], _end("B4", "BK-B4-1", "21:04"))
    r = run(cand(demo, "C4"), s, cfg, "G-2")
    assert not r.passed and r.inputs["conflicts"][0]["id"] == "BK-B4-1"


def test_g2_own_booking_excluded_only_by_id(demo, cfg):
    # Remove the other booking: only the flight's own replaced booking remains and is excluded by id.
    s = with_state(demo["scenario"], lambda sim: sim["ground"]["gates"]["B4"].__setitem__(
        "bookings", [b for b in sim["ground"]["gates"]["B4"]["bookings"] if b["id"] == "BK-B4-OWN"]))
    assert run(cand(demo, "C1"), s, cfg, "G-2").passed
    s2 = with_state(s, lambda sim: sim["ground"].pop("own_booking_id"))
    assert not run(cand(demo, "C1"), s2, cfg, "G-2").passed


# ---------------------------------------------------------------- G-3 turnaround and coupling

def test_g3_equality_passes(demo, cfg):
    r = run(cand(demo, "C1"), demo["scenario"], cfg, "G-3")  # 45 min service, 45 min minimum
    assert r.passed and r.inputs["service_min"] == 45


def test_g3_one_minute_short_fails(demo, cfg):
    r = run(cand(demo, "C1", gate_release="21:32"), demo["scenario"], cfg, "G-3")
    assert not r.passed and "turnaround" in r.explanation


def test_g3_inconsistent_taxi_fails(demo, cfg):
    assert not run(cand(demo, "C1", gate_arrival="20:50", gate_release="21:35"), demo["scenario"], cfg, "G-3").passed


def test_g3_release_before_arrival_fails(demo, cfg):
    assert not run(cand(demo, "C1", gate_release="20:30"), demo["scenario"], cfg, "G-3").passed


def test_g3_landing_before_issue_fails(demo, cfg):
    s = with_state(demo["scenario"], lambda sim: sim["atc"]["slots"].append("19:50"))
    r = run(cand(demo, "C1", landing="19:50", gate_arrival="19:58", gate_release="20:43"), s, cfg, "G-3")
    assert not r.passed and "before the issue time" in r.explanation


# ---------------------------------------------------------------- C-1 crew

def _crew(cid, **changes):
    def m(sim):
        for c in sim["ground"]["crews"]:
            if c["id"] == cid:
                c.update(changes)
    return m


def test_c1_shift_ends_at_release_passes(demo, cfg):
    s = with_state(demo["scenario"], _crew("CR1", shift_end="21:45"))
    r = run(cand(demo, "C3"), s, cfg, "C-1")  # service 21:00-21:45
    assert r.passed and r.inputs["eligible_crews"] == ["CR1"]


def test_c1_shift_one_minute_short_fails(demo, cfg):
    s = with_state(demo["scenario"], _crew("CR1", shift_end="21:44"))
    assert not run(cand(demo, "C3"), s, cfg, "C-1").passed


def test_c1_overlapping_assignment_fails_and_adjacent_passes(demo, cfg):
    busy = with_state(demo["scenario"], _crew("CR1", assignments=[{"id": "J1", "gate": "B4", "start": "21:30", "end": "22:00"}]))
    assert not run(cand(demo, "C3"), busy, cfg, "C-1").passed
    adjacent = with_state(demo["scenario"], _crew("CR1", assignments=[{"id": "J1", "gate": "B4", "start": "21:45", "end": "22:00"}]))
    assert run(cand(demo, "C3"), adjacent, cfg, "C-1").passed


def test_c1_no_crew_for_gate_fails(demo, cfg):
    r = run(cand(demo, "C2"), demo["scenario"], cfg, "C-1")
    assert not r.passed and r.inputs["eligible_crews"] == []


# ---------------------------------------------------------------- shape, invalid candidates, concessions

def test_check_returns_eight_agreed_results(demo, cfg):
    rs = checker.check(cand(demo, "C1"), demo["scenario"], cfg)
    assert [r.rule_id for r in rs] == checker.RULES
    assert all(isinstance(r, CheckResult) and r.basis and isinstance(r.inputs, dict) for r in rs)


def test_negative_holding_fails_every_time_rule(demo, cfg):
    rs = checker.check(cand(demo, "C1", extra_holding_min=-1), demo["scenario"], cfg)
    assert not checker.feasible(rs)
    assert {"F-1", "W-1", "R-1", "G-2", "G-3", "C-1"} <= set(checker.failed_rules(rs))


def test_unparsable_time_fails_not_raises(demo, cfg):
    rs = checker.check(cand(demo, "C1", landing="8pm"), demo["scenario"], cfg)
    assert not checker.feasible(rs) and "not HH:MM" in rule(rs, "R-1").inputs["error"]


def test_missing_agent_state_fails_everything(demo, cfg):
    s = demo["scenario"].model_copy(update={"simulated": {"atc": demo["scenario"].simulated["atc"]}})
    rs = checker.check(cand(demo, "C3"), s, cfg)
    assert not checker.feasible(rs) and not rule(rs, "F-1").passed and not rule(rs, "G-1").passed


def test_duplicate_candidate_ids_rejected(demo, cfg):
    with pytest.raises(ValueError):
        checker.check_all([cand(demo, "C1"), cand(demo, "C2", id="C1")], demo["scenario"], cfg)


def test_overnight_rollover(demo, cfg):
    issue = checker.issue_time(demo["scenario"])
    t = checker.parse_time("00:30", issue)
    assert t.day == 2 and t.hour == 0


def test_apply_concessions_new_version_source_unchanged(demo, cfg):
    before = checker.check_all(demo["candidates"], demo["scenario"], cfg)
    adj = checker.apply_concessions(demo["scenario"], demo["concessions"], state_version=1)
    after = checker.check_all(demo["candidates"], adj.scenario, cfg)
    assert adj.state_version == 2 and [a["id"] for a in adj.applied] == [c["id"] for c in demo["concessions"]]
    assert demo["scenario"].simulated["atc"]["slots"] == ["20:40", "20:52", "21:05"]
    assert demo["scenario"].simulated["ground"]["crews"][1]["gates"] == ["B9"]
    assert not checker.feasible(before["C5"]) and checker.feasible(after["C5"])
    assert not checker.feasible(before["C2"]) and checker.feasible(after["C2"])
    assert adj.scenario.simulated["pilot"]["max_extra_holding_min"] == 12  # min(12, fuel-safe 12)


def test_crew_reassignment_keeps_existing_jobs(demo, cfg):
    # Give CR2 a B9 job overlapping C2's service; after reassignment C-1 must still fail for C2.
    s = with_state(demo["scenario"], _crew("CR2", assignments=[{"id": "J-B9-2", "gate": "B9", "start": "20:40", "end": "21:10"}]))
    adj = checker.apply_concessions(s, [{"id": "GROUND_REASSIGN_CREW", "target": "B7"}])
    r = run(cand(demo, "C2"), adj.scenario, cfg, "C-1")
    assert not r.passed and "J-B9-2" in r.explanation


def test_undeclared_concession_target_rejected(demo, cfg):
    adj = checker.apply_concessions(demo["scenario"], [{"id": "ATC_EARLIER_SLOT", "target": "20:20"},
                                                       {"id": "GROUND_REASSIGN_CREW", "target": "C9"},
                                                       {"id": "PILOT_EXTRA_HOLDING", "target": "lots"}])
    assert adj.applied == [] and len(adj.rejected) == 3 and adj.state_version == 1
    assert adj.scenario is demo["scenario"]


def test_pilot_concession_capped_at_fuel_safe_limit(demo, cfg):
    adj = checker.apply_concessions(demo["scenario"], [{"id": "PILOT_EXTRA_HOLDING", "target": "30 min"}])
    assert adj.scenario.simulated["pilot"]["max_extra_holding_min"] == 12
