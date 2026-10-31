"""Load the CSVs, sample seeded scenarios and build each agent's simulated private state. (Ashvin)"""
from models import Scenario


def load_flights(data_dir: str = "data"):
    """Read data/flights.csv. Parse HHMM fields as times and handle overnight arrivals."""
    raise NotImplementedError


def build_scenario(row, scenario_id: str, seed: int) -> Scenario:
    """Real anchor from one row plus seeded simulated state for atc, pilot and ground."""
    raise NotImplementedError


def apply_concessions(scenario: Scenario, concessions: list[dict]) -> Scenario:
    """Return a new Scenario with round 1 concessions applied to the simulated state.

    Each concession is {"agent", "id", "target"}, e.g. GROUND_REASSIGN_CREW with target "B7" makes a crew
    available at B7. Candidate IDs must not change: coordinator.py rechecks the same candidates on the result.
    """
    raise NotImplementedError


def private_view(scenario: Scenario, agent: str) -> dict:
    """Shared scenario plus only this agent's own simulated state."""
    raise NotImplementedError
