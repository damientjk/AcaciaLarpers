import random
from datetime import datetime

import pytest

import options as O
import scenario as S


def test_parse_hhmm():
    assert S.parse_hhmm("0648") == 408
    assert S.parse_hhmm("5") == 5
    assert S.parse_hhmm("2400") == 1440
    with pytest.raises(ValueError):
        S.parse_hhmm("2460")


def test_tz_offset():
    # DFW 13:05 -> HNL 17:40, 515 min block: HNL is 4 h behind DFW in January
    assert S.tz_offset_hours(S.parse_hhmm("1305"), S.parse_hhmm("1740"), 515) == -4
    assert S.tz_offset_hours(S.parse_hhmm("2350"), S.parse_hhmm("0130"), 100) == 0


def test_actual_arrival_matches_csv_on_sample():
    df = S.load_flights()
    for i in random.Random(0).sample(list(df.index), 2000):
        r = df.loc[i]
        t = S.row_times(r)["actual_arrival"]
        assert t.hour * 60 + t.minute == S.parse_hhmm(r.ARRIVAL_TIME) % 1440


def test_overnight_arrival_moves_to_next_day():
    df = S.load_flights()
    r = df[(df.SCHEDULED_ARRIVAL.astype(int) < 300) & (df.SCHEDULED_DEPARTURE.astype(int) > 2000)
           & (df.ORIGIN_AIRPORT == "LAX")].iloc[0]
    t = S.row_times(r)
    assert t["scheduled_arrival"].date() > datetime(int(r.YEAR), int(r.MONTH), int(r.DAY)).date()


def test_scenario_is_deterministic():
    a, b = S.get_scenario("S1234"), S.get_scenario("S1234")
    assert a == b
    assert [c.id for c in O.generate(a)] == [c.id for c in O.generate(b)]


def test_private_view_hides_other_agents():
    v = S.private_view(S.get_scenario("S1234"), "pilot")
    assert "fuel_on_board_kg" in v["own_state"]
    assert "slots" not in v["own_state"] and "gates" not in v["own_state"]


def test_fixture_mix():
    ids = S.fixture_ids()
    types = [S.get_scenario(i).simulated["atc"]["disruption_type"] for i in ids]
    assert (types.count("weather"), types.count("late_aircraft"), types.count("both")) == (20, 20, 10)
    assert len(set(ids)) == 50


@pytest.mark.parametrize("sid", [S.DEMO_ID] + S.fixture_ids())
def test_candidates_are_coupled_and_bounded(sid):
    sc = S.get_scenario(sid)
    det = O.generate_detailed(sc)
    assert len(det) <= 8
    eta = S.from_iso(sc.simulated["atc"]["base_eta"])
    for c, d in det:
        landing = S.from_iso(d["landing"])
        assert c.extra_holding_min == (landing - eta).total_seconds() // 60 >= 0
        assert (S.from_iso(d["gate_arrival"]) - landing).total_seconds() / 60 == d["taxi_in_min"]
        assert S.from_iso(d["gate_release"]) >= S.from_iso(d["ready"])


def test_demo_has_conflicting_preferences():
    sc = S.get_scenario(S.DEMO_ID)
    det = dict((c.id, d) for c, d in O.generate_detailed(sc))
    used = {x["id"] for d in det.values() for x in d["concessions"]}
    assert used == {"ATC_EARLIER_SLOT", "PILOT_EXTRA_HOLDING", "GROUND_REASSIGN_CREW"}
    assert sc.simulated["ground"]["gates"][0]["occupancy"]          # planned gate occupied


def test_one_global_seed_still_gives_distinct_scenarios():
    df = S.load_flights()
    safe = {S.build_scenario(df.loc[i], f"X{i}", 2026).simulated["pilot"]["fuel_safe_holding_min"]
            for i in range(0, 4000, 200)}
    assert len(safe) > 5


def _demo_applied():
    sc = S.get_scenario(S.DEMO_ID)
    det = dict((c.id, d) for c, d in O.generate_detailed(sc))
    atc_slot = next(d for d in det.values() if any(x["id"] == "ATC_EARLIER_SLOT" for x in d["concessions"]))
    applied = S.apply_concessions(sc, [
        {"agent": "atc", "id": "ATC_EARLIER_SLOT", "target": atc_slot["landing"][11:16]},
        {"agent": "ground", "id": "GROUND_REASSIGN_CREW", "target": "B7"},
        {"agent": "pilot", "id": "PILOT_EXTRA_HOLDING", "target": "12"},
    ])
    return sc, applied, atc_slot


def test_apply_concessions_changes_state_not_base():
    sc, after, atc_slot = _demo_applied()
    slot = next(s for s in after.simulated["atc"]["slots"] if s["slot_id"] == atc_slot["slot_id"])
    assert slot["occupant"] is None
    moved = [s for s in after.simulated["atc"]["slots"] if s.get("resequenced_from") == atc_slot["slot_id"]]
    assert len(moved) == 1 and moved[0]["slot_id"] not in {d["slot_id"] for _, d in O.generate_detailed(sc)}
    assert any(c["assigned_gate"] == "B7" for c in after.simulated["ground"]["crews"])
    assert after.simulated["pilot"]["comfortable_holding_min"] == 12
    assert all(len(after.simulated[a]["applied_concessions"]) == 1 for a in ("atc", "pilot", "ground"))
    # base scenario untouched
    assert next(s for s in sc.simulated["atc"]["slots"] if s["slot_id"] == atc_slot["slot_id"])["occupant"]
    assert "applied_concessions" not in sc.simulated["atc"]


def test_apply_concessions_rejects_out_of_bounds():
    sc = S.get_scenario(S.DEMO_ID)
    fixed = next(s for s in sc.simulated["atc"]["slots"] if s["occupant"] and not s["occupant_flexible"])
    after = S.apply_concessions(sc, [
        {"agent": "pilot", "id": "ATC_EARLIER_SLOT", "target": fixed["time"][11:16]},     # wrong agent
        {"agent": "atc", "id": "ATC_EARLIER_SLOT", "target": fixed["time"][11:16]},       # not flexible
        {"agent": "pilot", "id": "PILOT_EXTRA_HOLDING", "target": "999"},                 # capped at fuel-safe
        {"agent": "ground", "id": "GROUND_REASSIGN_CREW", "target": "Z99"},               # unknown gate
    ])
    assert len(after.simulated["atc"]["rejected_concessions"]) == 2
    assert after.simulated["pilot"]["comfortable_holding_min"] == after.simulated["pilot"]["fuel_safe_holding_min"]
    assert len(after.simulated["ground"]["rejected_concessions"]) == 1
    assert next(s for s in after.simulated["atc"]["slots"] if s["slot_id"] == fixed["slot_id"])["occupant"]


def test_apply_concessions_accepts_candidate_id_targets():
    sc = S.get_scenario(S.DEMO_ID)
    after = S.apply_concessions(sc, [{"agent": "ground", "id": "GROUND_REASSIGN_CREW", "target": "C2"},
                                     {"agent": "atc", "id": "ATC_EARLIER_SLOT", "target": "C2"}])
    assert not after.simulated["atc"]["rejected_concessions"]
    assert not after.simulated["ground"]["rejected_concessions"]
