"""When no candidate is acceptable, an agent may say so instead of inventing a preference."""
import agents as A

IDS = {"C1", "C2", "C3"}


def reply(preferred, acceptable):
    return A.OfferReply(preferred=preferred, acceptable=acceptable, constraints_cited=["G-2"], concessions=[],
                        rationale="Every plan fails G-2.")


def test_blank_or_none_preference_is_valid_when_nothing_is_acceptable():
    for p in ["", "none", "NONE", " None "]:
        assert A._offer_errors("ground", reply(p, []), IDS) == []


def test_blank_preference_with_acceptable_plans_is_still_invalid():
    assert "preferred must be one of acceptable" in A._offer_errors("ground", reply("", ["C1"]), IDS)


def test_real_unknown_ids_are_still_rejected():
    errs = A._offer_errors("ground", reply("C9", []), IDS)
    assert any("unknown candidate IDs" in e for e in errs)
