"""Keeps a LOGIC extraction's field_name from colliding with the DATA field it
explains, without guessing at which field_name wordings mean "the same field".

This used to also hold a static dictionary mapping known wording variants (e.g.
"Net Rentable Area", "Effective Date") to one canonical display name, so that
different per-file LLM calls phrasing the same field differently would still
group together downstream. That dictionary was a recurring source of false
conflicts: it encoded guesses about which concepts are "the same" that didn't
always hold (a site/parcel area and a net rentable area are two different
measurements, not two phrasings of one fact), and fixing one bad guess tended to
surface another. Cross-file field_name consistency is handled a different way
now: llm_client.py's system prompt forces every per-file call to use the query's
own literal term for a DATA field, so "the same field" is decided by what the
query actually asked for, not by a hardcoded synonym list. All this module does
is the one thing that can't be decided by the LLM alone: once every file's
proposals are in hand, make sure a LOGIC field explaining a DATA field never
ends up with that DATA field's own exact name.
"""

import re

_WORD_RE = re.compile(r"[a-z0-9]+")

LOGIC_CATEGORIES = {"logic"}

# shared with propose_extractions.py and detect_conflicts.py - kept here (rather
# than in either of those) so neither has to import the other to use it
UNDETERMINED_LOGIC_VALUE = "Underlying logic/methodology is not stated in the provided files."


def _normalize_key(name: str) -> str:
    return "_".join(_WORD_RE.findall(name.lower()))


def disambiguate_logic_field_names(proposals: list[dict]) -> None:
    """Mutates field_name in place: any LOGIC-category proposal whose normalized
    field_name exactly matches a DATA-category proposal's field_name in this same
    batch gets " Logic" appended. Decided dynamically from what this run's own
    proposals actually contain, never from a precompiled list of known field
    names - a LOGIC field only needs disambiguating if it is actually colliding
    with a real DATA field this run produced."""
    data_keys = {
        _normalize_key(p.get("field_name", ""))
        for p in proposals
        if (p.get("field_category") or "").lower() not in LOGIC_CATEGORIES
    }

    for proposal in proposals:
        field_name = proposal.get("field_name", "")
        if not field_name:
            continue
        if (proposal.get("field_category") or "").lower() not in LOGIC_CATEGORIES:
            continue
        if _normalize_key(field_name) in data_keys:
            proposal["field_name"] = f"{field_name} Logic"
