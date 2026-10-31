"""Load the CSVs, sample seeded scenarios and build each agent's simulated private state. (Ashvin)

Time handling
-------------
DOT reports departure times in ORIGIN local time and arrival times in DESTINATION
local time. Everything here is converted to destination local time (naive datetimes):
  * the time-zone offset is inferred from SCHEDULED_DEPARTURE + SCHEDULED_TIME vs
    SCHEDULED_ARRIVAL, rounded to whole hours;
  * actual arrival = scheduled arrival + ARRIVAL_DELAY (no HHMM parsing, so no
    overnight or "2400" ambiguity, and the recorded delay is counted exactly once);
  * "2400" is midnight at the end of the day.

Real vs simulated
-----------------
`historical` holds real fields only. `simulated` holds seeded state per agent; base_eta
(the unconstrained landing time) is the real wheels-on time, and the negotiation only
adds extra holding on top of it. Every simulated dict carries "simulated": True.
"""
from __future__ import annotations

import hashlib
import random as _random
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

from models import Historical, Scenario

ROOT = Path(__file__).resolve().parent
HHMM_COLS = ["SCHEDULED_DEPARTURE", "DEPARTURE_TIME", "WHEELS_OFF", "WHEELS_ON",
             "SCHEDULED_ARRIVAL", "ARRIVAL_TIME"]
DELAY_COLS = ["AIR_SYSTEM_DELAY", "SECURITY_DELAY", "AIRLINE_DELAY",
              "LATE_AIRCRAFT_DELAY", "WEATHER_DELAY"]


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text())


def sim_cfg() -> dict:
    return config()["simulation"]


# ------------------------------------------------------------------ loading

@lru_cache(maxsize=1)
def load_flights(data_dir: str = "data") -> pd.DataFrame:
    """Read data/flights.csv. HHMM fields stay strings; use parse_hhmm / row_times."""
    d = ROOT / data_dir
    df = pd.read_csv(d / "flights.csv", dtype={c: str for c in HHMM_COLS + ["TAIL_NUMBER"]})
    df[DELAY_COLS] = df[DELAY_COLS].fillna(0)
    df["disruption_type"] = [
        disruption_type(w, l) for w, l in zip(df.WEATHER_DELAY, df.LATE_AIRCRAFT_DELAY)
    ]
    return df


@lru_cache(maxsize=1)
def load_lookups(data_dir: str = "data") -> tuple[dict, dict]:
    d = ROOT / data_dir
    airlines = pd.read_csv(d / "airlines.csv").set_index("IATA_CODE")["AIRLINE"].to_dict()
    airports = pd.read_csv(d / "airports.csv").set_index("IATA_CODE")["AIRPORT"].to_dict()
    return airlines, airports


def disruption_type(weather_delay: float, late_aircraft_delay: float) -> str | None:
    w, l = weather_delay > 15, late_aircraft_delay > 20
    if w and l:
        return "both"
    return "weather" if w else "late_aircraft" if l else None


# ------------------------------------------------------------------ time parsing

def parse_hhmm(value) -> int:
    """'0648' -> 408 minutes after midnight. '2400' -> 1440 (midnight, end of day)."""
    s = str(value).strip().split(".")[0].zfill(4)
    h, m = int(s[:2]), int(s[2:])
    if not (0 <= h <= 24 and 0 <= m < 60) or (h == 24 and m != 0):
        raise ValueError(f"bad HHMM value: {value!r}")
    return h * 60 + m


def tz_offset_hours(sched_dep_min: int, sched_arr_min: int, scheduled_time: int) -> int:
    """Destination local minus origin local, inferred from the schedule."""
    diff = (sched_arr_min - sched_dep_min - scheduled_time) % 1440
    if diff >= 720:
        diff -= 1440
    return round(diff / 60)


def row_times(row) -> dict:
    """All key times of one flights.csv row as datetimes in destination local time."""
    date = datetime(int(row.YEAR), int(row.MONTH), int(row.DAY))
    dep_min = parse_hhmm(row.SCHEDULED_DEPARTURE)
    arr_min = parse_hhmm(row.SCHEDULED_ARRIVAL)
    sched_time = int(row.SCHEDULED_TIME)
    offset = tz_offset_hours(dep_min, arr_min, sched_time)

    sched_dep = date + timedelta(minutes=dep_min + offset * 60)
    approx_arr = sched_dep + timedelta(minutes=sched_time)
    # anchor the HHMM arrival to the day nearest the schedule-based estimate
    sched_arr = min(
        (approx_arr.replace(hour=0, minute=0) + timedelta(days=k, minutes=arr_min) for k in (-1, 0, 1)),
        key=lambda t: abs((t - approx_arr).total_seconds()),
    )
    actual_arr = sched_arr + timedelta(minutes=int(row.ARRIVAL_DELAY))
    return {
        "tz_offset_hours": offset,
        "scheduled_departure": sched_dep,
        "actual_departure": sched_dep + timedelta(minutes=int(row.DEPARTURE_DELAY)),
        "scheduled_arrival": sched_arr,
        "actual_arrival": actual_arr,
        "wheels_on": actual_arr - timedelta(minutes=int(row.TAXI_IN)),
    }


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M")


def hhmm(t: datetime) -> str:
    return t.strftime("%H:%M")


def from_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


# ------------------------------------------------------------------ scenario IDs

def seed_for(scenario_id: str) -> int:
    return int(hashlib.sha256(scenario_id.encode()).hexdigest()[:8], 16)


def scenario_id_for(row_index: int) -> str:
    return f"S{row_index}"


def row_for(scenario_id: str):
    df = load_flights()
    if scenario_id == DEMO_ID:
        return df.loc[demo_row_index()]
    return df.loc[int(scenario_id.lstrip("S"))]


def get_scenario(scenario_id: str) -> Scenario:
    """Rebuild any scenario from its ID alone (fixtures, logs and reruns use this)."""
    return build_scenario(row_for(scenario_id), scenario_id, seed_for(scenario_id))


def random_scenario(rng: _random.Random | None = None) -> Scenario:
    rng = rng or _random.Random()
    return get_scenario(scenario_id_for(rng.randrange(len(load_flights()))))


def find_rows(flight: str, date: str) -> pd.DataFrame:
    """flight like 'AA1344' (or '1344'), date 'YYYY-MM-DD'."""
    df = load_flights()
    f = flight.strip().upper()
    carrier, number = (f[:2], f[2:]) if f[:2].isalpha() else (None, f)
    y, m, d = (int(x) for x in date.split("-"))
    hit = df[(df.YEAR == y) & (df.MONTH == m) & (df.DAY == d) & (df.FLIGHT_NUMBER == int(number))]
    if carrier:
        hit = hit[hit.AIRLINE == carrier]
    return hit


def find_scenario(flight: str, date: str) -> Scenario | None:
    hit = find_rows(flight, date)
    return None if hit.empty else get_scenario(scenario_id_for(int(hit.index[0])))


# ------------------------------------------------------------------ build

def build_scenario(row, scenario_id: str, seed: int) -> Scenario:
    """Real anchor from one row plus seeded simulated state for atc, pilot and ground."""
    airlines, airports = load_lookups()
    t = row_times(row)
    dtype = disruption_type(row.WEATHER_DELAY, row.LATE_AIRCRAFT_DELAY)
    if dtype is None:
        raise ValueError(f"row {row.name} does not qualify (weather>15 or late aircraft>20)")

    historical = Historical(
        carrier=row.AIRLINE,
        carrier_name=airlines.get(row.AIRLINE, row.AIRLINE),
        flight=str(int(row.FLIGHT_NUMBER)),
        tail=row.TAIL_NUMBER,
        origin=row.ORIGIN_AIRPORT,
        destination=row.DESTINATION_AIRPORT,
        date=f"{int(row.YEAR):04d}-{int(row.MONTH):02d}-{int(row.DAY):02d}",
        scheduled_arrival=hhmm(t["scheduled_arrival"]),
        actual_arrival=hhmm(t["actual_arrival"]),
        arrival_delay_min=int(row.ARRIVAL_DELAY),
        weather_delay_min=int(row.WEATHER_DELAY),
        late_aircraft_delay_min=int(row.LATE_AIRCRAFT_DELAY),
        distance_mi=int(row.DISTANCE),
    )

    rng = _random.Random(seed)
    sim = _simulate(row, t, dtype, rng)
    if scenario_id == DEMO_ID:
        _force_demo(sim)
    return Scenario(scenario_id=scenario_id, issue_time=sim.pop("issue_time"),
                    historical=historical, simulated=sim)


def _simulate(row, t: dict, dtype: str, rng: _random.Random) -> dict:
    c = sim_cfg()
    weather = dtype in ("weather", "both")
    late = dtype in ("late_aircraft", "both")
    ac_class = "widebody" if row.DISTANCE >= c["widebody_min_distance_mi"] else "narrowbody"
    own_wake = "heavy" if ac_class == "widebody" else "large"

    base_eta = t["wheels_on"]
    issue = base_eta - timedelta(minutes=rng.randint(*c["issue_lead_min"]))
    shared = {"simulated": True, "base_eta": iso(base_eta), "aircraft_class": ac_class,
              "disruption_type": dtype}

    # ---- ATC: arrival slots around the base ETA, neighbour traffic, taxiway closures
    cap = c["runway_capacity_per_hour"]["weather" if weather else "normal"]
    slot_min = 60 // cap
    occ_p = c["slot_occupancy_prob"]["weather" if weather else "normal"]
    wakes, wake_p = zip(*c["neighbour_wake_probs"].items())
    first = base_eta - timedelta(minutes=(base_eta.minute % slot_min) + 3 * slot_min,
                                 seconds=base_eta.second)
    slots = []
    tt = first
    while tt <= base_eta + timedelta(minutes=c["slot_horizon_min"]):
        occupied = rng.random() < occ_p
        slots.append({
            "slot_id": "SL-" + tt.strftime("%H%M"),
            "time": iso(tt),
            "occupant": f"{rng.choice(['DL', 'AA', 'UA', 'WN', 'B6'])}{rng.randint(100, 2999)}" if occupied else None,
            "occupant_wake": rng.choices(wakes, wake_p)[0] if occupied else None,
            "occupant_flexible": occupied and rng.random() < c["occupant_flexible_prob"],
        })
        tt += timedelta(minutes=slot_min)
    taxiways = list(c["taxiways"])
    closure_p = max(c["taxiway_closure_prob"]["weather"] if weather else 0,
                    c["taxiway_closure_prob"]["late_aircraft"] if late else 0)
    closed = [rng.choice(taxiways)] if rng.random() < closure_p else []
    atc = {**shared, "runway": "ARR-1", "runway_capacity_per_hour": cap, "slot_minutes": slot_min,
           "own_wake": own_wake, "slots": slots, "closed_taxiways": closed}

    # ---- Pilot: fuel, holding limits, passenger connections
    hold_burn = c["holding_burn_kg_per_min"][ac_class]
    cruise_burn = c["cruise_burn_kg_per_min"][ac_class]
    reserve_kg = c["fuel_reserve_min"] * hold_burn
    safe_hold = rng.randint(*c["extra_holding_fuel_min"])
    to_eta = (base_eta - issue).total_seconds() / 60
    fob = reserve_kg + cruise_burn * to_eta + hold_burn * safe_hold
    conns = []
    for _ in range(rng.randint(*c["connections_count"])):
        conns.append({
            "flight": f"{row.AIRLINE}{rng.randint(100, 2999)}",
            "departure_time": iso(base_eta + timedelta(minutes=rng.randint(*c["connection_depart_after_eta_min"]))),
            "passengers": rng.randint(*c["connection_passengers"]),
            "min_connect_min": rng.randint(*c["connection_min_connect_min"]),
        })
    pilot = {**shared, "fuel_on_board_kg": round(fob), "cruise_burn_kg_per_min": cruise_burn,
             "holding_burn_kg_per_min": hold_burn, "reserve_min": c["fuel_reserve_min"],
             "reserve_kg": reserve_kg, "fuel_safe_holding_min": safe_hold,
             "comfortable_holding_min": int(safe_hold * c["comfortable_fraction"]),
             "connections": conns}

    # ---- Ground: gates, occupancy, crews, turnaround
    turn = c["turnaround_min_widebody"] if ac_class == "widebody" else c["turnaround_min"]
    n_gates = rng.randint(*c["gates_per_scenario"])
    gate_ids = c["gate_ids"][:n_gates]
    planned = gate_ids[0]
    taxi_base = int(row.TAXI_IN)
    gates, crews = [], []
    for i, g in enumerate(gate_ids):
        max_class = ac_class if i == 0 else ("widebody" if ac_class == "widebody" and rng.random() < 0.5
                                             else rng.choice(["narrowbody", "widebody"]))
        taxi = max(3, taxi_base + rng.randint(*c["taxi_in_jitter_min"]))
        arrive = base_eta + timedelta(minutes=taxi)
        occupancy = []
        if i == 0 and (late or rng.random() < 0.5):
            # planned gate still held by the previous occupant when this flight arrives
            occupancy.append({"start": iso(arrive - timedelta(minutes=90)),
                              "end": iso(arrive + timedelta(minutes=rng.randint(10, 35))),
                              "occupant": f"{row.AIRLINE}{rng.randint(100, 2999)}"})
        elif rng.random() < 0.3:
            s = arrive + timedelta(minutes=rng.randint(-60, 30))
            occupancy.append({"start": iso(s), "end": iso(s + timedelta(minutes=rng.randint(40, 80))),
                              "occupant": f"{rng.choice(['DL', 'AA', 'UA'])}{rng.randint(100, 2999)}"})
        gates.append({"gate_id": g, "max_class": max_class, "taxi_route": rng.sample(taxiways, 2),
                      "taxi_in_min": taxi, "occupancy": occupancy})
        if i == 0 or rng.random() < c["gate_crewed_prob"]:
            crews.append({"crew_id": f"CRW-{g}", "assigned_gate": g,
                          "shift_start": iso(issue - timedelta(hours=6)),
                          "shift_end": iso(base_eta + timedelta(minutes=rng.randint(*c["crew_shift_end_after_eta_min"]))),
                          "reassignable": i != 0 and rng.random() < c["crew_reassignable_prob"]})
    next_dep = t["scheduled_arrival"] + timedelta(minutes=turn + rng.randint(*c["next_departure_slack_min"]))
    ground = {**shared, "planned_gate": planned, "gates": gates, "crews": crews,
              "turnaround_min": turn, "gate_buffer_min": c["gate_buffer_min"],
              "next_departure": iso(next_dep)}

    return {"issue_time": iso(issue), "atc": atc, "pilot": pilot, "ground": ground}


# ------------------------------------------------------------------ demo scenario

DEMO_ID = "demo-001"


@lru_cache(maxsize=1)
def demo_row_index() -> int:
    """A real evening ATL weather row on a narrowbody. Chosen by rule, not by hand."""
    df = load_flights()
    sa = df.SCHEDULED_ARRIVAL.astype(int)
    hit = df[(df.DESTINATION_AIRPORT == "ATL") & (df.disruption_type == "both")
             & (df.DISTANCE < sim_cfg()["widebody_min_distance_mi"]) & sa.between(1830, 2030)]
    return int(hit.index[0])


def _force_demo(sim: dict) -> None:
    """Shape the simulated state so preferences conflict at the start (plan section 8):
    limited holding fuel, planned gate occupied, a second gate usable only via a crew move,
    and an earlier slot available only via ATC resequencing. The answer is NOT fixed here;
    options/checker/agents still have to find it."""
    atc, pilot, ground = sim["atc"], sim["pilot"], sim["ground"]
    base_eta = from_iso(atc["base_eta"])
    after = [s for s in atc["slots"] if from_iso(s["time"]) >= base_eta]
    for i, s in enumerate(after):
        if i == 0:
            s.update(occupant="DL1187", occupant_wake="large", occupant_flexible=True)
        elif i in (1, 2):
            s.update(occupant=f"UA{400 + i}", occupant_wake="large", occupant_flexible=False)
        elif i in (3, 6):
            s.update(occupant=None, occupant_wake=None, occupant_flexible=False)
    before = [s for s in atc["slots"] if from_iso(s["time"]) < base_eta]
    if before:
        before[-1].update(occupant="AA2210", occupant_wake="large", occupant_flexible=False)
    atc["closed_taxiways"] = ["D"]

    pilot["fuel_safe_holding_min"] = 14
    pilot["comfortable_holding_min"] = 7
    pilot["fuel_on_board_kg"] = round(
        pilot["reserve_kg"]
        + pilot["cruise_burn_kg_per_min"] * (base_eta - from_iso(sim["issue_time"])).total_seconds() / 60
        + pilot["holding_burn_kg_per_min"] * 14)
    pilot["connections"] = [{"flight": "DL2045", "departure_time": iso(base_eta + timedelta(minutes=55)),
                             "passengers": 18, "min_connect_min": 40}]

    cls = ground["aircraft_class"]
    taxi = ground["gates"][0]["taxi_in_min"]
    arrive = base_eta + timedelta(minutes=taxi)
    shift_end = iso(base_eta + timedelta(minutes=90))
    shift_start = iso(from_iso(sim["issue_time"]) - timedelta(hours=6))
    ground["planned_gate"] = "B4"
    ground["gates"] = [
        {"gate_id": "B4", "max_class": cls, "taxi_route": ["A", "B"], "taxi_in_min": taxi,
         "occupancy": [{"start": iso(arrive - timedelta(minutes=80)),
                        "end": iso(arrive + timedelta(minutes=25)), "occupant": "DL1622"}]},
        {"gate_id": "B7", "max_class": cls, "taxi_route": ["A", "C"], "taxi_in_min": taxi + 1,
         "occupancy": []},
        {"gate_id": "B9", "max_class": cls, "taxi_route": ["D", "E"], "taxi_in_min": taxi + 2,
         "occupancy": []},
    ]
    ground["crews"] = [
        {"crew_id": "CRW-B4", "assigned_gate": "B4", "shift_start": shift_start,
         "shift_end": shift_end, "reassignable": False},
        {"crew_id": "CRW-B9", "assigned_gate": "B9", "shift_start": shift_start,
         "shift_end": shift_end, "reassignable": True},
    ]


# ------------------------------------------------------------------ agent views

def apply_concessions(scenario: Scenario, concessions: list[dict]) -> Scenario:
    """Return a new Scenario with round 1 concessions applied to the simulated state.

    Each concession is {"agent", "id", "target"}, e.g. GROUND_REASSIGN_CREW with target "B7" makes a crew
    available at B7. Candidate IDs must not change: coordinator.py rechecks the same candidates on the result.
    """
    raise NotImplementedError


def private_view(scenario: Scenario, agent: str) -> dict:
    """Shared scenario plus only this agent's own simulated state."""
    if agent not in ("atc", "pilot", "ground"):
        raise ValueError(agent)
    return {
        "scenario_id": scenario.scenario_id,
        "issue_time": scenario.issue_time,
        "historical": scenario.historical.model_dump(),
        "own_state": scenario.simulated[agent],
    }


# ------------------------------------------------------------------ fixtures

def fixture_ids(seed: int | None = None) -> list[str]:
    """The seeded evaluation set: 20 weather only, 20 late aircraft only, 10 both."""
    ev = config()["evaluation"]
    seed = ev["seed"] if seed is None else seed
    df = load_flights()
    out = []
    for key, dtype in (("weather_only", "weather"), ("late_aircraft_only", "late_aircraft"), ("both", "both")):
        idx = df.index[df.disruption_type == dtype]
        rng = _random.Random(f"{seed}-{dtype}")
        out += [scenario_id_for(int(i)) for i in sorted(rng.sample(list(idx), ev["scenarios"][key]))]
    return out
