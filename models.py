"""Shared Pydantic schemas. DRAFT: agree and freeze at the 12:15 kickoff.

Field names follow docs/LOG_FORMAT.md. If a name changes here, update that file
and fixtures/make_sample_logs.py in the same commit.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgentName = Literal["atc", "pilot", "ground"]
ConcessionId = Literal["PILOT_EXTRA_HOLDING", "GROUND_REASSIGN_CREW", "ATC_EARLIER_SLOT"]
OutcomeType = Literal["consensus", "fallback", "escalation"]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Scenario (Ashvin) ---

class Historical(Frozen):
    """Real fields from one flights.csv row. Nothing simulated goes here."""
    carrier: str
    carrier_name: str
    flight: str
    tail: str
    origin: str
    destination: str
    date: str                      # YYYY-MM-DD
    scheduled_arrival: str         # HH:MM
    actual_arrival: str            # HH:MM
    arrival_delay_min: int
    weather_delay_min: int
    late_aircraft_delay_min: int
    distance_mi: int


class Scenario(Frozen):
    scenario_id: str
    issue_time: str                # ISO datetime
    historical: Historical
    simulated: dict[AgentName, dict]   # each agent's private state, labelled simulated in the UI


class Candidate(Frozen):
    id: str                        # C1..C8
    landing: str
    extra_holding_min: int
    gate: str
    concession: str | None = None
    gate_arrival: str
    gate_release: str


# --- Checks and costs (Yizhuo) ---

class CheckResult(Frozen):
    rule_id: str                   # F-1, W-1, R-1, T-1, G-1, G-2, G-3, C-1
    basis: str
    inputs: dict
    passed: bool
    explanation: str


class CandidateCost(Frozen):
    delay_min: float
    holding_fuel_kg: float
    overtime_min: float
    missed_connections: int
    total_usd: float


# --- Protocol (Damien) ---

class Concession(Frozen):
    id: ConcessionId
    target: str | None = None      # e.g. the gate opened by a crew move


class Offer(Frozen):
    """Round 1 message from one agent."""
    agent: AgentName
    run_id: str
    round: Literal[1] = 1
    state_version: int
    preferred: str
    acceptable: list[str]
    constraints_cited: list[str] = Field(default_factory=list)
    concessions: list[Concession] = Field(default_factory=list)
    rationale: str


class Proposal(Frozen):
    """Immutable compromise frozen by the coordinator between rounds."""
    version: int
    candidate: str


class Vote(Frozen):
    """Round 2 message: accept or reject one exact proposal version."""
    agent: AgentName
    run_id: str
    round: Literal[2] = 2
    proposal_version: int
    vote: Literal["accept", "reject", "abstain"]   # abstain = timeout or invalid, never an accept
    rationale: str


class Outcome(Frozen):
    type: OutcomeType
    final_candidate: str | None    # None on escalation
    reason: str
    concessions_that_unlocked: list[ConcessionId] = Field(default_factory=list)
