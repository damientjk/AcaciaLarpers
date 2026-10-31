"""Load the CSVs, sample seeded scenarios and build each agent's simulated private state. (Ashvin)"""
from models import Scenario


def load_flights(data_dir: str = "data"):
    """Read data/flights.csv. Parse HHMM fields as times and handle overnight arrivals."""
    raise NotImplementedError


def build_scenario(row, scenario_id: str, seed: int) -> Scenario:
    """Real anchor from one row plus seeded simulated state for atc, pilot and ground."""
    raise NotImplementedError


def private_view(scenario: Scenario, agent: str) -> dict:
    """Shared scenario plus only this agent's own simulated state."""
    raise NotImplementedError
