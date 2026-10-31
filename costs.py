"""Soft costs. Raw components in physical units, weights from config.yaml, weighted total. (Yizhuo)

All four components are SIMULATED quantities measured inside the scenario:

- delay_min          landing minus the simulated baseline ETA (atc.baseline_eta). Signed: a slot
                     earlier than the baseline is negative. The recorded historical delay is never
                     added, so nothing is double-counted.
- holding_fuel_kg    extra_holding_min x pilot.holding_burn_kg_per_min.
- overtime_min       service minutes after the serving crew's regular_end (first eligible crew by id).
                     0 when no crew is eligible (C-1 fails and the candidate is infeasible anyway).
- missed_connections passengers on ground.connections whose departure is earlier than
                     gate_arrival + min_connect_min.

total_usd = sum(component x weight). The weights are the team's agreed scoring weights; the total is
a score in USD-equivalent units, not a measured monetary saving.
"""
from __future__ import annotations

from datetime import timedelta

from checker import (MissingInput, _get, _num, _state, candidate_times, eligible_crews, hhmm,
                     load_config, minutes, parse_time)
from models import Candidate, CandidateCost, Scenario

WEIGHT_KEYS = {
    "delay_min": "delay_usd_per_min",
    "holding_fuel_kg": "holding_fuel_usd_per_kg",
    "overtime_min": "overtime_usd_per_min",
    "missed_connections": "missed_connection_usd",
}
UNITS = {"delay_min": "min", "holding_fuel_kg": "kg", "overtime_min": "min", "missed_connections": "pax"}


def weights_from_config(config: dict | None = None) -> dict:
    cfg = config if config is not None else load_config()
    w = cfg.get("costs")
    if not isinstance(w, dict):
        raise MissingInput("config.costs is required")
    out = {}
    for key in WEIGHT_KEYS.values():
        if key not in w:
            raise MissingInput(f"config.costs.{key} is required")
        out[key] = float(_num(w[key], f"config.costs.{key}", minimum=0))
    return out


def components(candidate: Candidate, scenario: Scenario) -> dict:
    """Raw cost components plus the inputs behind them. Raises MissingInput if state is incomplete."""
    t = candidate_times(candidate, scenario)
    atc, pilot, ground = _state(scenario, "atc"), _state(scenario, "pilot"), _state(scenario, "ground")

    baseline = parse_time(_get(atc, "baseline_eta", "atc"), t.issue, "atc.baseline_eta")
    delay = minutes(baseline, t.landing)

    burn = _num(_get(pilot, "holding_burn_kg_per_min", "pilot"), "pilot.holding_burn_kg_per_min", minimum=0)
    fuel = candidate.extra_holding_min * burn

    crews, _ = eligible_crews(candidate, scenario)
    overtime, crew_id, regular_end = 0.0, None, None
    if crews:
        crew = crews[0]
        crew_id = crew["id"]
        regular_end = parse_time(_get(crew, "regular_end", f"crew {crew_id}"), t.issue, "regular_end")
        overtime = max(0.0, minutes(max(t.gate_arrival, regular_end), t.gate_release))

    missed, missed_list = 0, []
    for conn in _get(ground, "connections", "ground", (list,)):
        dep = parse_time(_get(conn, "departure", "connection"), t.issue, "connection.departure")
        mct = _num(_get(conn, "min_connect_min", "connection"), "connection.min_connect_min", minimum=0)
        pax = int(_num(conn.get("pax", 1), "connection.pax", minimum=0, integer=True))
        if t.gate_arrival + timedelta(minutes=mct) > dep:
            missed += pax
            missed_list.append({"flight": conn.get("flight"), "departure": hhmm(dep), "pax": pax})

    return {
        "delay_min": delay,
        "holding_fuel_kg": fuel,
        "overtime_min": overtime,
        "missed_connections": missed,
        "inputs": {
            "baseline_eta": hhmm(baseline), "landing": hhmm(t.landing),
            "scheduled_arrival": scenario.historical.scheduled_arrival,
            "delay_vs_schedule_min": minutes(parse_time(scenario.historical.scheduled_arrival, t.issue), t.landing),
            "holding_burn_kg_per_min": burn, "extra_holding_min": candidate.extra_holding_min,
            "crew": crew_id, "regular_end": hhmm(regular_end) if regular_end else None,
            "gate_release": hhmm(t.gate_release), "missed": missed_list,
        },
    }


def total(raw: dict, weights: dict) -> float:
    return float(sum(raw[k] * weights[w] for k, w in WEIGHT_KEYS.items()))


def cost(candidate: Candidate, scenario: Scenario, weights: dict | None = None) -> CandidateCost:
    """Agreed CandidateCost. ``weights`` is config['costs'] (or any dict with the four keys)."""
    w = weights_from_config({"costs": weights}) if weights is not None else weights_from_config()
    raw = components(candidate, scenario)
    return CandidateCost(delay_min=float(raw["delay_min"]), holding_fuel_kg=float(raw["holding_fuel_kg"]),
                         overtime_min=float(raw["overtime_min"]), missed_connections=int(raw["missed_connections"]),
                         total_usd=round(total(raw, w), 2))


def cost_all(candidates: list[Candidate], scenario: Scenario, weights: dict | None = None,
             strict: bool = True) -> dict[str, CandidateCost | None]:
    """Costs per candidate id. With strict=False a candidate whose inputs are invalid gets None instead of
    raising; such a candidate already fails its checks, and the solver refuses to select a feasible
    candidate without a cost."""
    out = {}
    for c in candidates:
        try:
            out[c.id] = cost(c, scenario, weights)
        except MissingInput:
            if strict:
                raise
            out[c.id] = None
    return out


def breakdown(candidate: Candidate, scenario: Scenario, weights: dict | None = None) -> dict:
    """Transparent view for the UI and agents: raw value, unit, weight and weighted value per component."""
    w = weights_from_config({"costs": weights}) if weights is not None else weights_from_config()
    raw = components(candidate, scenario)
    rows = []
    for k, wk in WEIGHT_KEYS.items():
        rows.append({"component": k, "raw": raw[k], "unit": UNITS[k], "weight": w[wk], "weight_key": wk,
                     "weighted_usd": round(raw[k] * w[wk], 2)})
    return {"candidate": candidate.id, "components": rows, "total_usd": round(total(raw, w), 2),
            "inputs": raw["inputs"], "note": "Simulated score; weights from config.yaml; not a measured saving."}
