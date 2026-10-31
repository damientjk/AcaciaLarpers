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
