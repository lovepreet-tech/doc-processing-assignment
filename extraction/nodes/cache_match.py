"""cache_match node - decides whether a query can be answered from what's already
persisted for this batch instead of re-running retrieve/propose/verify/persist.

Matches a query's words against existing active extractions' field_names using a
loose word-overlap heuristic. Only returns matches when the matched fields
collectively cover (almost) every content word in the query; a partial match
returns nothing, sending the query through the full pipeline instead.
"""

import re

from sqlalchemy.orm import Session as DBSession

from core.models import Extraction

_WORD_RE = re.compile(r"[a-z0-9]+")
MATCH_THRESHOLD = 0.5

# words that carry no field-identifying meaning - stripped before checking whether
# the matched fields cover "everything the query is actually asking about"
_STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of", "for", "and", "or", "please",
    "extract", "tell", "me", "show", "give", "across", "all", "uploaded", "files",
    "file", "from", "in", "on", "to", "this", "that", "these", "those", "with",
    "can", "you", "find", "get", "primary",
}


def _field_match_score(field_name: str, query_words: set[str]) -> float:
    """Fraction of field_name's own words that show up in the query."""
    field_words = _WORD_RE.findall(field_name.replace("_", " ").lower())
    if not field_words:
        return 0.0
    return sum(1 for w in field_words if w in query_words) / len(field_words)


def _is_fully_covered(query_words: set[str], matched_field_names: list[str]) -> bool:
    content_words = query_words - _STOPWORDS
    if not content_words:
        return False  # nothing identifiable to match against - don't guess
    covered: set[str] = set()
    for field_name in matched_field_names:
        covered.update(_WORD_RE.findall(field_name.replace("_", " ").lower()))
    return not (content_words - covered)


def find_cached_matches(db: DBSession, tenant_id: str, batch_id: str, query: str) -> list[str]:
    """Returns the ids (as strings) of already-active extractions that fully answer
    this query, or an empty list if nothing cached covers it, or only part does."""
    if not query.strip():
        return []

    active = (
        db.query(Extraction)
        .filter(Extraction.tenant_id == tenant_id, Extraction.batch_id == batch_id, Extraction.superseded == False)  # noqa: E712
        .all()
    )
    if not active:
        return []

    query_words = set(_WORD_RE.findall(query.lower()))
    if not query_words:
        return []

    matched = [row for row in active if _field_match_score(row.field_name, query_words) >= MATCH_THRESHOLD]
    if not matched or not _is_fully_covered(query_words, [row.field_name for row in matched]):
        return []

    return [str(row.id) for row in matched]
