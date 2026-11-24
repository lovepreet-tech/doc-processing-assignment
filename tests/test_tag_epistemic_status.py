"""Unit tests for extraction/nodes/tag_epistemic_status.py - the deterministic rule
set that turns (citation verified?, LLM's own guess) into the final explicit /
inferred / undetermined label shown to the user.

This is the "distinguish explicit from inferred, flag uncertainty rather than fill
gaps with unsupported assumptions" half of the spec's success criteria - a value
must never come out "explicit" unless its citation was actually verified.
"""

from extraction.nodes.tag_epistemic_status import tag_epistemic_status


def _proposal(verified: bool, epistemic_guess: str) -> dict:
    return {
        "field_name": "client_name",
        "value": "Acme Corp",
        "epistemic_guess": epistemic_guess,
        "_citation_verification": {"verified": verified},
    }


def test_verified_and_llm_confident_is_explicit():
    [tagged] = tag_epistemic_status([_proposal(verified=True, epistemic_guess="explicit")])
    assert tagged["epistemic_status"] == "explicit"
    assert tagged["verification_reason"] is None


def test_verified_but_llm_says_inferred_stays_inferred():
    [tagged] = tag_epistemic_status([_proposal(verified=True, epistemic_guess="inferred")])
    assert tagged["epistemic_status"] == "inferred"
    assert tagged["verification_reason"]


def test_citation_failed_verification_is_undetermined_even_if_llm_was_confident():
    # the whole point of server-side verification: the LLM's own confidence never
    # overrides a failed deterministic check
    [tagged] = tag_epistemic_status([_proposal(verified=False, epistemic_guess="explicit")])
    assert tagged["epistemic_status"] == "undetermined"
    assert "unconfirmed" in tagged["verification_reason"].lower()


def test_verified_but_llm_unsure_is_undetermined_with_low_confidence_note():
    [tagged] = tag_epistemic_status([_proposal(verified=True, epistemic_guess="undetermined")])
    assert tagged["epistemic_status"] == "undetermined"
    assert "confident" in tagged["verification_reason"].lower()


def test_missing_verification_defaults_to_undetermined():
    proposal = {"field_name": "x", "value": "y", "epistemic_guess": "explicit"}
    [tagged] = tag_epistemic_status([proposal])
    assert tagged["epistemic_status"] == "undetermined"


def test_never_drops_a_proposal_even_when_undetermined():
    proposals = [_proposal(verified=False, epistemic_guess="explicit") for _ in range(3)]
    assert len(tag_epistemic_status(proposals)) == 3


def test_does_not_mutate_input_proposals():
    original = _proposal(verified=True, epistemic_guess="explicit")
    tag_epistemic_status([original])
    assert "epistemic_status" not in original
