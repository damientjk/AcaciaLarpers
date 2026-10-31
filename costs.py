"""Soft costs. Raw components in physical units, weights from config.yaml, weighted total. (Yizhuo)

All four components are SIMULATED quantities measured inside the scenario:

- delay_min          landing minus the simulated base ETA (atc.base_eta, the unconstrained landing time).
                     The recorded historical delay is never added, so nothing is double-counted.
- holding_fuel_kg    extra_holding_min x pilot.holding_burn_kg_per_min.
- overtime_min       minutes of the turnaround service window (gate arrival + turnaround) past the serving
                     crew's shift_end. 0 when no crew is on shift (C-1 fails; candidate infeasible anyway).
- missed_connections passengers on pilot.connections whose departure_time is earlier than
                     gate_arrival + min_connect_min.

total_usd = sum(component x weight). Weights are the team's scoring weights from config.costs; the total is
a USD-equivalent score inside the simulation, not a measured monetary saving.
"""
from __future__ import annotations

from datetime import timedelta

from checker import (MissingInput, _get, _num, _sim_params, _state, base_eta, candidate_times, eligible_crews,
                     hhmm, load_config, minutes, parse_time)
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


def components(candidate: Candidate, scenario: Scenario, config: dict | None = None) -> dict:
    """Raw cost components plus the inputs behind them. Raises MissingInput if state is incomplete."""
    cfg = config if config is not None else load_config()
    t = candidate_times(candidate, scenario)
    pilot = _state(scenario, "pilot")

    eta = base_eta(scenario, t.issue)
    delay = minutes(eta, t.landing)

    burn = _num(_get(pilot, "holding_burn_kg_per_min", "pilot"), "pilot.holding_burn_kg_per_min", minimum=0)
    fuel = candidate.extra_holding_min * burn

    _, turnaround = _sim_params(scenario, cfg)
    service_end = t.gate_arrival + timedelta(minutes=turnaround)
    crews, _ = eligible_crews(candidate, scenario)
    overtime, crew_id, shift_end = 0.0, None, None
    if crews:
        crew_id = crews[0]["crew_id"]
        shift_end = parse_time(crews[0]["shift_end"], t.issue, "shift_end")
        overtime = max(0.0, minutes(shift_end, service_end))

    missed, missed_list = 0, []
    for conn in _get(pilot, "connections", "pilot", (list,)):
        dep = parse_time(_get(conn, "departure_time", "connection"), t.issue, "connection.departure_time")
        mct = _num(_get(conn, "min_connect_min", "connection"), "connection.min_connect_min", minimum=0)
        pax = int(_num(_get(conn, "passengers", "connection"), "connection.passengers", minimum=0, integer=True))
        if t.gate_arrival + timedelta(minutes=mct) > dep:
            missed += pax
            missed_list.append({"flight": conn.get("flight"), "departure": hhmm(dep), "passengers": pax})

    sched = parse_time(scenario.historical.scheduled_arrival, t.issue, "historical.scheduled_arrival")
    return {
        "delay_min": delay,
        "holding_fuel_kg": fuel,
        "overtime_min": overtime,
        "missed_connections": missed,
        "inputs": {
            "base_eta": hhmm(eta), "landing": hhmm(t.landing),
            "scheduled_arrival": scenario.historical.scheduled_arrival,
            "delay_vs_schedule_min": minutes(sched, t.landing),
            "holding_burn_kg_per_min": burn, "extra_holding_min": candidate.extra_holding_min,
            "crew": crew_id, "shift_end": hhmm(shift_end), "service_end": hhmm(service_end),
            "missed": missed_list,
        },
    }


def total(raw: dict, weights: dict) -> float:
    return float(sum(raw[k] * weights[w] for k, w in WEIGHT_KEYS.items()))


def cost(candidate: Candidate, scenario: Scenario, weights: dict | None = None,
         config: dict | None = None) -> CandidateCost:
    """Agreed CandidateCost. ``weights`` is config['costs'] (or any dict with the four keys)."""
    w = weights_from_config({"costs": weights}) if weights is not None else weights_from_config(config)
    raw = components(candidate, scenario, config)
    return CandidateCost(delay_min=float(raw["delay_min"]), holding_fuel_kg=float(raw["holding_fuel_kg"]),
                         overtime_min=float(raw["overtime_min"]), missed_connections=int(raw["missed_connections"]),
                         total_usd=round(total(raw, w), 2))


def cost_all(candidates: list[Candidate], scenario: Scenario, weights: dict | None = None,
             strict: bool = True, config: dict | None = None) -> dict[str, CandidateCost | None]:
    """Costs per candidate id. With strict=False a candidate whose inputs are invalid gets None instead of
    raising; such a candidate already fails its checks, and the solver refuses to select a feasible
    candidate without a cost."""
    out = {}
    for c in candidates:
        try:
            out[c.id] = cost(c, scenario, weights, config)
        except MissingInput:
            if strict:
                raise
            out[c.id] = None
    return out


def breakdown(candidate: Candidate, scenario: Scenario, weights: dict | None = None,
              config: dict | None = None) -> dict:
    """Transparent view for the UI and agents: raw value, unit, weight and weighted value per component."""
    w = weights_from_config({"costs": weights}) if weights is not None else weights_from_config(config)
    raw = components(candidate, scenario, config)
    rows = [{"component": k, "raw": raw[k], "unit": UNITS[k], "weight": w[wk], "weight_key": wk,
             "weighted_usd": round(raw[k] * w[wk], 2)} for k, wk in WEIGHT_KEYS.items()]
    return {"candidate": candidate.id, "components": rows, "total_usd": round(total(raw, w), 2),
            "inputs": raw["inputs"], "note": "Simulated score; weights from config.yaml; not a measured saving."}
