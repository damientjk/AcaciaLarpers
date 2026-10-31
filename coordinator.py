"""Two-round protocol, compromise, outcome, final recheck and audit log. (Damien)

app.py calls run(random=True) and run(flight=..., date=...). Both write one log to logs/
in the shape of docs/LOG_FORMAT.md and return the same dict.
"""


def run(random: bool = False, flight: str | None = None, date: str | None = None,
        scenario_id: str | None = None, fake_agents: bool = False) -> dict:
    raise NotImplementedError
