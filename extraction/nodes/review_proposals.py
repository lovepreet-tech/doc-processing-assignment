"""review_proposals node - one LLM pass over every candidate from every file, each
shown next to the exact evidence it cites, that decides what real-world fact each
candidate actually states and gives every candidate stating the same fact the
same field_name.

Per-file proposal calls each see only one file, so they can't tell that the
value one file reports under a generic requested name and the value another
file reports under that same name are two different facts, they name
one fact differently in different files, and they sometimes label a nearby value
with the wrong field. Deterministic string rules can't make those calls; this
pass can, because it sees every candidate side by side with its own evidence and
the query. It first lists the distinct facts present, then assigns each
candidate to one fact (or drops it). It never edits a value and never picks a
winner between candidates that state the same fact differently - those keep the
same name and detect_conflicts surfaces them.

Fails open: if the review call errors, every proposal passes through unchanged.
"""

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from core.config import get_settings
from extraction.field_canon import UNDETERMINED_LOGIC_VALUE
from extraction.llm_client import invoke_structured
from extraction.nodes.detect_conflicts import is_logic_category

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_EVIDENCE_CHARS = 1500


class Fact(BaseModel):
    name: str = Field(description="final Title Case field name for this fact")
    kind: Literal["data", "logic"]
    description: str = Field(description="what this fact is, in a few words")


class CandidateReview(BaseModel):
    candidate_id: str
    decision: Literal["keep", "drop"]
    fact_name: str | None = Field(default=None, description="one of facts[].name; required when decision is keep")
    reason: str = Field(description="one short sentence")


class CandidateReviews(BaseModel):
    facts: list[Fact]
    reviews: list[CandidateReview]


SYSTEM_PROMPT = """You review candidate extractions taken from a set of valuation documents,
made by separate per-file passes that could not see each other. Each candidate has
a field_name, a category, a value, and the id of the evidence it was cited from;
every evidence item is shown in full. You are also given the user's query.

Step 1 - list the facts. Read every candidate against its own evidence and list
each distinct real-world fact they state, once, in `facts`, each with a final
field name:
- If a fact is exactly a field the query names, its name MUST be the query's own
  term in Title Case, even when a document words it differently (a synonym or a
  more specific phrasing of the requested field is still that field).
- If a field the query names generically covers more than one distinct fact in
  these documents (two different measurements, two different addresses, two
  different dates, ...), name each of those facts specifically from its own
  evidence instead of using the generic term for any of them.
- One fact gets one name even when files word it differently or state it in a
  different format, unit or scale.
- Logic facts describe how a value is produced. A narrative rule and the
  spreadsheet formula that implements the same rule are ONE logic fact, and so
  is a narrative rule describing just one step of what a cited formula does (a
  rounding, a conditional choice, a deduction): that formula is evidence for it.
  Name logic facts "<what it produces> Logic". Only merge logic that describes
  the same calculation or a step of it.
- Other facts (not named in the query) get a short name from their evidence's
  own label.
- An identifier code (a reference, file or job number) gets a name describing
  what its evidence says it identifies - never guess it to be some other field.

Step 2 - review each candidate:
- "keep" with fact_name = the fact its evidence actually shows this value to be.
  Wording, format, unit or scale differences don't matter.
- "drop" when the evidence does not actually state a value for any fact: the
  value is a placeholder, a sentence that talks about a value without containing
  the figure, a logic candidate whose evidence only points elsewhere for the
  working, or a logic candidate that only restates a value without any
  calculation or rule. A value whose evidence labels it as a different quantity
  is not dropped - it is kept under the fact its evidence says it is.

Never decide which of two candidates is right: if two candidates state the same
fact and disagree, give both the same fact_name - a human reviews genuine
conflicts. When unsure whether to drop, keep. Return exactly one review per
candidate_id, and every kept candidate's fact_name must appear in facts."""


def review_proposals(
    proposals: list[dict], retrieved_context: list[dict], query: str = ""
) -> tuple[list[dict], list[dict]]:
    """Returns (reviewed proposals, missing_fields entries for any DATA field whose
    every candidate was dropped)."""
    reviewable = [p for p in proposals if p.get("value") != UNDETERMINED_LOGIC_VALUE]
    placeholders = [p for p in proposals if p.get("value") == UNDETERMINED_LOGIC_VALUE]
    if not reviewable:
        return proposals, []

    evidence_by_ref = _index_evidence(retrieved_context)
    try:
        reviews = _call_reviewer(reviewable, evidence_by_ref, query)
    except Exception:
        logger.exception("review_proposals failed; passing proposals through unreviewed")
        return unify_identical_codes(proposals), []

    reviewed, missing = apply_reviews(reviewable, reviews)
    return unify_identical_codes(reviewed) + placeholders, missing


# a reference/file/job code: letters and digits together, no spaces ("VAL-2617",
# "REF/24/017") - unlike a name or an amount, an identical code is one fact
_CODE_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9][A-Za-z0-9\-/._]{2,39}$")


def unify_identical_codes(proposals: list[dict]) -> list[dict]:
    """Gives every DATA candidate carrying the same identifier code one shared
    field_name (the one most candidates already use), so a code stated in
    several files merges into one field with all its sources instead of
    appearing once per file under slightly different names."""
    names_by_code: dict[str, list[str]] = {}
    for p in proposals:
        value = (p.get("value") or "").strip()
        if not is_logic_category(p.get("field_category")) and _CODE_RE.match(value):
            names_by_code.setdefault(value.upper(), []).append(p.get("field_name", ""))

    chosen = {
        code: max(sorted(set(names)), key=names.count) for code, names in names_by_code.items() if len(set(names)) > 1
    }
    if not chosen:
        return proposals
    unified = []
    for p in proposals:
        code = (p.get("value") or "").strip().upper()
        if code in chosen and not is_logic_category(p.get("field_category")):
            p = {**p, "field_name": chosen[code]}
        unified.append(p)
    return unified


def apply_reviews(proposals: list[dict], reviews: dict[str, CandidateReview]) -> tuple[list[dict], list[dict]]:
    kept: list[dict] = []
    dropped: list[dict] = []
    for index, proposal in enumerate(proposals):
        review = reviews.get(_candidate_id(index))
        if review is None:
            kept.append(proposal)
        elif review.decision == "drop" and _droppable(proposal):
            dropped.append({**proposal, "_review_reason": review.reason})
        elif review.decision == "drop":
            kept.append(proposal)
        else:
            if review.fact_name and review.fact_name.strip():
                proposal = {**proposal, "field_name": review.fact_name.strip()}
            kept.append(proposal)

    remaining_fields = {p.get("field_name", "").strip().lower() for p in kept}
    missing: list[dict] = []
    reported: set[str] = set()
    for proposal in dropped:
        key = proposal.get("field_name", "").strip().lower()
        if key in remaining_fields or key in reported or is_logic_category(proposal.get("field_category")):
            continue
        reported.add(key)
        missing.append(
            {
                "field_name": proposal.get("field_name", ""),
                "field_category": proposal.get("field_category", ""),
                "reason": f"no supporting evidence after review: {proposal['_review_reason']}",
            }
        )
    return kept, missing


_DIGIT_RE = re.compile(r"\d")


def _droppable(proposal: dict) -> bool:
    """The reviewer may relabel anything, but may only remove candidates whose
    evidence is soft: narrative logic, or a narrative DATA value with no figure
    in it at all (a placeholder, or a sentence about a value). A value read from
    a spreadsheet cell or formula is labeled and re-verified hard evidence, and
    a narrative value containing an actual figure is a real statement - neither
    is ever removed on the model's say-so."""
    citation_type = (proposal.get("source_ref") or {}).get("citation_type")
    if citation_type in ("spreadsheet_cell", "formula_edge_path"):
        return False
    if is_logic_category(proposal.get("field_category")):
        return True
    return not _DIGIT_RE.search(proposal.get("value") or "")


def _candidate_id(index: int) -> str:
    return f"C{index + 1}"


def _index_evidence(retrieved_context: list[dict]) -> dict[str, str]:
    index: dict[str, str] = {}
    for item in retrieved_context:
        parts = []
        if item.get("section"):
            parts.append(f"[section: {item['section']}]")
        if item.get("raw_formula"):
            parts.append(f"[formula: {item['raw_formula']}]")
        parts.append((item.get("text") or "")[:MAX_EVIDENCE_CHARS])
        rendered = " ".join(parts)
        for key in ("document_block_id", "spreadsheet_cell_id"):
            if item.get(key):
                index[item[key]] = rendered
    return index


def _call_reviewer(
    proposals: list[dict], evidence_by_ref: dict[str, str], query: str
) -> dict[str, CandidateReview]:
    evidence_ids: dict[str, str] = {}
    evidence_lines: list[str] = []
    candidate_lines: list[str] = []
    for index, proposal in enumerate(proposals):
        ref = proposal.get("source_ref") or {}
        ref_key = ref.get("document_block_id") or ref.get("spreadsheet_cell_id")
        evidence_id = "none"
        if ref_key and ref_key in evidence_by_ref:
            if ref_key not in evidence_ids:
                evidence_ids[ref_key] = f"E{len(evidence_ids) + 1}"
                evidence_lines.append(f"{evidence_ids[ref_key]}: {evidence_by_ref[ref_key]}")
            evidence_id = evidence_ids[ref_key]
        quote = ref.get("quote_or_formula")
        candidate_lines.append(
            f"{_candidate_id(index)}: field_name={proposal.get('field_name')!r} "
            f"category={proposal.get('field_category')!r} value={proposal.get('value')!r} "
            f"evidence={evidence_id}" + (f" quote={quote!r}" if quote else "")
        )

    user_prompt = (
        f"Query: {query}\n\nEvidence:\n" + "\n".join(evidence_lines) + "\n\nCandidates:\n" + "\n".join(candidate_lines)
    )

    result = invoke_structured(
        settings.openai_review_model or settings.openai_chat_model,
        CandidateReviews,
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}],
    )

    # a kept candidate pointing at a fact name the model never listed is a model
    # slip, not a decision - fall back to leaving that candidate's name alone
    fact_names = {fact.name for fact in result.facts}
    reviews = {}
    for review in result.reviews:
        if review.decision == "keep" and review.fact_name not in fact_names:
            review = review.model_copy(update={"fact_name": None})
        reviews[review.candidate_id] = review
    return reviews
