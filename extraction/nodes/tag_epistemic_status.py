"""tag_epistemic_status node - deterministic rules on top of verify_citations' output.

explicit:      citation verified AND the LLM didn't flag this as an inference step
inferred:      citation verified but the LLM says it required narrative interpretation,
               or it bottoms out at an unverifiable (but not outright failed) formula
undetermined:  citation failed verification, or there was no evidence at all - the
               value is still kept (never dropped), just marked not to be trusted blind
"""

INFERRED_GUESSES = {"inferred"}

# maps status to a user-facing caveat, since verify_citations' own `reason` is
# an internal debug string not meant for display
FRIENDLY_NOTES = {
    "undetermined_unverified": "Couldn't verify this value against the cited source - treat it as unconfirmed.",
    "undetermined_low_confidence": "The model wasn't confident in this value.",
    "inferred": "Inferred from surrounding context rather than stated explicitly.",
}


def tag_epistemic_status(proposals: list[dict]) -> list[dict]:
    tagged = []
    for proposal in proposals:
        verification = proposal.get("_citation_verification") or {}
        verified = verification.get("verified", False)
        llm_guess = proposal.get("epistemic_guess", "undetermined")

        formula_rederived = (proposal.get("source_ref") or {}).get("citation_type") == "formula_edge_path" and any(
            hop.get("derivation_matched") for hop in verification.get("chain") or []
        )

        if not verified:
            status = "undetermined"
            note = FRIENDLY_NOTES["undetermined_unverified"]
        elif formula_rederived:
            # the system re-derived the formula chain itself and it matched -
            # that is explicit evidence whatever the model guessed
            status = "explicit"
            note = None
        elif llm_guess in INFERRED_GUESSES:
            status = "inferred"
            note = FRIENDLY_NOTES["inferred"]
        elif llm_guess == "undetermined":
            status = "undetermined"
            note = FRIENDLY_NOTES["undetermined_low_confidence"]
        else:
            status = "explicit"
            note = None

        proposal = dict(proposal)
        proposal["epistemic_status"] = status
        proposal["verification_reason"] = note
        tagged.append(proposal)
    return tagged
