import pytest
from pydantic import ValidationError

from models import Offer, Vote


def test_offer_matches_plan_example():
    o = Offer(agent="ground", run_id="r-0142", state_version=1, preferred="C3",
              acceptable=["C3", "C5"], constraints_cited=["G-2", "C-1"],
              concessions=[{"id": "GROUND_REASSIGN_CREW", "target": "B7"}],
              rationale="B4 occupied until 19:40; B7 usable if crew moves from B9.")
    assert o.concessions[0].target == "B7"


def test_unknown_concession_rejected():
    with pytest.raises(ValidationError):
        Offer(agent="atc", run_id="r", state_version=1, preferred="C1", acceptable=["C1"],
              concessions=[{"id": "ATC_IGNORE_WAKE"}], rationale="")


def test_vote_values_are_closed():
    with pytest.raises(ValidationError):
        Vote(agent="pilot", run_id="r", proposal_version=2, vote="maybe", rationale="")
