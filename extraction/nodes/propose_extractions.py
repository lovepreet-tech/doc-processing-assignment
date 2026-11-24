"""propose_extractions node - asks the LLM to turn retrieved context into candidate
extractions.

Calls the LLM once per file rather than once across the whole batch's combined
context, so each call only ever sees one source and reports what that source
says; the deterministic merge/conflict decision stays in persist.py.

Several deterministic cleanup passes run on every file's results, as a safety
net the LLM's own prompt instructions can't be relied on alone to enforce:

1. Disambiguate field_name (field_canon.py) so a LOGIC proposal never ends up
   with the exact same field_name as the DATA field it explains. Cross-file
   consistency for DATA field_name itself is the LLM's job (forced to use the
   query's own literal term), not a hardcoded synonym list here.
2. Reclassify a DATA proposal whose value is just a "not stated" placeholder as
   a missing_fields entry instead of a competing value.
3. Reclassify a DATA proposal whose value doesn't match the shape implied by its
   own field_name (a non-date value in a "...Date" field, a bare number/percent
   in "Methodology") as missing instead of a competing value - catches the model
   mislabeling an unrelated nearby cell as the requested field.
4. Reclassify a LOGIC proposal whose value is just a pointer to another location
   ("see attached", "refer to the model") as missing instead of real logic - such
   a sentence has no derivation content to extract.
5. Drop an "undetermined logic" placeholder for a field_name that some other
   proposal in this same run already answered with a real value - the
   placeholder only means that one file had no evidence, not that it disagrees.
6. Reclassify a LOGIC proposal tagged epistemic_guess="inferred" whose cited
   source text doesn't actually mention the concept its own field_name names -
   an inferred (layout-guessed, never explicitly stated) derivation that can't
   even be tied back to its own cited evidence is more likely a mislabeled
   nearby value than a real derivation.
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from extraction import llm_client
from extraction.field_canon import UNDETERMINED_LOGIC_VALUE, disambiguate_logic_field_names
from extraction.nodes.detect_conflicts import _try_parse_date, normalize_field_name

# bounds a single file's own prompt size
MAX_CONTEXT_ITEMS_PER_FILE = 40

# each file's propose call is an independent OpenAI request, so they run
# concurrently; capped so a large batch doesn't blow past rate limits
MAX_PARALLEL_FILES = 5

_WORD_RE = re.compile(r"[a-z0-9]+")

_MISSING_SENTINEL_RE = re.compile(
    r"not\s+(explicitly\s+|clearly\s+|directly\s+)?(stated|mentioned|available|found|provided|disclosed|present|specified)"
    r"|no\s+(evidence|information|data)"
    r"|not\s+in\s+the\s+(provided|uploaded)",
    re.IGNORECASE,
)
_DATA_CATEGORIES = {"client_info", "property_detail", "valuation_info"}

# a sentence that only points elsewhere for the real detail has no derivation
# content of its own and must never be accepted as a LOGIC field's value, even
# when the model (wrongly) tagged it epistemic_guess="explicit"
_POINTER_SENTINEL_RE = re.compile(
    r"see\s+(the\s+)?attached"
    r"|refer\s+to\s+(the\s+)?attached"
    r"|as\s+per\s+(the\s+)?attached"
    r"|refer\s+to\s+the\s+(valuation\s+)?(model|workbook|worksheet|spreadsheet)"
    r"|see\s+the\s+(valuation\s+)?(model|workbook|worksheet|calculation)"
    r"|per\s+the\s+calculation\s+(sheet|workbook)"
    r"|(is|are)\s+filed\s+(with|in|under)"
    r"|(is|are)\s+issued\s+separately"
    r"|available\s+(on|upon)\s+request",
    re.IGNORECASE,
)

# fields named like this must hold a date, never a bare number or other quantity
_DATE_FIELD_NAME_RE = re.compile(r"\bdate\b", re.IGNORECASE)
_BARE_NUMBER_RE = re.compile(r"^[-+]?\$?\s*[0-9][0-9,]*\.?[0-9]*\s*%?$")


def propose_extractions(
    query: str,
    retrieved_context: list[dict],
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[list[dict], list[dict]]:
    if not retrieved_context:
        return [], []

    by_file: dict[str | None, list[dict]] = {}
    for item in retrieved_context:
        by_file.setdefault(item.get("file_id"), []).append(item)

    all_proposals: list[dict] = []
    all_missing: list[dict] = []
    total_files = len(by_file)

    def _propose_for_file(items: list[dict]) -> tuple[list[dict], list[dict]]:
        capped = sorted(items, key=lambda c: c.get("score", 0), reverse=True)[:MAX_CONTEXT_ITEMS_PER_FILE]
        proposals, missing = llm_client.propose(query, capped)
        # retries once on an unresolved citation, since a resample of the same
        # context sometimes copies the ref_id correctly where the first call didn't
        if any(_is_unresolved(p) for p in proposals):
            proposals, missing = llm_client.propose(query, capped)
        return proposals, missing

    completed = 0
    with ThreadPoolExecutor(max_workers=min(total_files, MAX_PARALLEL_FILES)) as pool:
        futures = [pool.submit(_propose_for_file, items) for items in by_file.values()]
        for future in as_completed(futures):
            completed += 1
            if on_progress:
                on_progress(completed, total_files)
            proposals, missing = future.result()
            all_proposals.extend(proposals)
            all_missing.extend(missing)

    disambiguate_logic_field_names(all_proposals)
    _attach_units(all_proposals, retrieved_context)

    resolved, unresolved = _drop_unresolved_citations(all_proposals)
    proposals, demoted_sentinel = _demote_sentinel_data_proposals(resolved)
    proposals, demoted_shape = _demote_shape_mismatched_data_proposals(proposals)
    # dropped LOGIC candidates are not reported as missing: a logic field name is
    # the model's own invention, not something the query asked for by name, and
    # the real logic is usually carried by another candidate under another name
    proposals, _ = _demote_pointer_logic_proposals(proposals)
    proposals, _ = _demote_unsupported_inferred_logic(proposals, retrieved_context)
    _sanitize_undetermined_logic(proposals)
    proposals = _drop_shadowed_undetermined_logic(proposals)
    demoted = demoted_sentinel + demoted_shape
    return proposals, _dedupe_missing(proposals, all_missing + demoted + unresolved)


_LOGIC_CATEGORIES = {"logic", "methodology"}


def _sanitize_undetermined_logic(proposals: list[dict]) -> None:
    """Replaces the value of any LOGIC proposal tagged epistemic_guess="undetermined"
    with a fixed, neutral statement, since "undetermined" means no real evidence was
    found and the model-written value isn't trustworthy. The citation/source_ref is
    left untouched."""
    for proposal in proposals:
        category = (proposal.get("field_category") or "").lower()
        if category in _LOGIC_CATEGORIES and proposal.get("epistemic_guess") == "undetermined":
            proposal["value"] = UNDETERMINED_LOGIC_VALUE


def _drop_unresolved_citations(proposals: list[dict]) -> tuple[list[dict], list[dict]]:
    """Moves any proposal with an unresolved source_ref into missing_fields instead
    of persisting an Extraction row with no real citation behind it."""
    resolved: list[dict] = []
    demoted: list[dict] = []
    for proposal in proposals:
        if not _is_unresolved(proposal):
            resolved.append(proposal)
            continue
        demoted.append(
            {
                "field_name": proposal.get("field_name", ""),
                "field_category": proposal.get("field_category", ""),
                "reason": "model cited a source that could not be resolved to real evidence",
            }
        )
    return resolved, demoted


def _is_unresolved(proposal: dict) -> bool:
    ref = proposal.get("source_ref") or {}
    return not (ref.get("document_block_id") or ref.get("spreadsheet_cell_id"))


def _demote_sentinel_data_proposals(proposals: list[dict]) -> tuple[list[dict], list[dict]]:
    """Moves DATA-category proposals whose value is just a "no evidence found"
    placeholder into missing_fields instead of leaving them as competing values."""
    kept: list[dict] = []
    demoted: list[dict] = []
    for proposal in proposals:
        value = proposal.get("value") or ""
        category = (proposal.get("field_category") or "").lower()
        if category in _DATA_CATEGORIES and _MISSING_SENTINEL_RE.search(value):
            demoted.append(
                {
                    "field_name": proposal.get("field_name", ""),
                    "field_category": proposal.get("field_category", ""),
                    "reason": value,
                }
            )
            continue
        kept.append(proposal)
    return kept, demoted


def _demote_shape_mismatched_data_proposals(proposals: list[dict]) -> tuple[list[dict], list[dict]]:
    """Moves a DATA proposal into missing_fields when its value's shape contradicts
    its own field_name - a "...Date" field whose value doesn't parse as a date, or
    a "Methodology" field whose value is just a bare number/percent. Both are a
    nearby, unrelated cell getting mislabeled as the requested field rather than a
    real (if disputed) answer, so they must not be left standing as a competing
    value for that field."""
    kept: list[dict] = []
    demoted: list[dict] = []
    for proposal in proposals:
        category = (proposal.get("field_category") or "").lower()
        field_name = proposal.get("field_name", "")
        value = (proposal.get("value") or "").strip()
        reason = None
        if category in _DATA_CATEGORIES and value:
            if _DATE_FIELD_NAME_RE.search(field_name) and _try_parse_date(value) is None:
                reason = f"value {value!r} does not look like a date"
            elif normalize_field_name(field_name) == "methodology" and _BARE_NUMBER_RE.match(value):
                reason = f"value {value!r} is a bare number, not a methodology/approach name"
        if reason:
            demoted.append(
                {"field_name": field_name, "field_category": proposal.get("field_category", ""), "reason": reason}
            )
            continue
        kept.append(proposal)
    return kept, demoted


def _demote_pointer_logic_proposals(proposals: list[dict]) -> tuple[list[dict], list[dict]]:
    """Moves a LOGIC proposal into missing_fields when its value only points
    elsewhere for the real detail ("see attached", "refer to the model") instead
    of stating any actual formula, rule, or assumption."""
    kept: list[dict] = []
    demoted: list[dict] = []
    for proposal in proposals:
        category = (proposal.get("field_category") or "").lower()
        value = proposal.get("value") or ""
        if category in _LOGIC_CATEGORIES and _POINTER_SENTINEL_RE.search(value):
            demoted.append(
                {
                    "field_name": proposal.get("field_name", ""),
                    "field_category": proposal.get("field_category", ""),
                    "reason": "cited text only points to another location and has no derivation content",
                }
            )
            continue
        kept.append(proposal)
    return kept, demoted


# generic filler words stripped before checking a LOGIC field_name against its own
# cited evidence - too common to be the specific concept the field actually names
_LOGIC_NAME_STOPWORDS = {"logic", "rate", "value", "amount", "figure", "the", "of", "and", "for", "a", "an"}


def _demote_unsupported_inferred_logic(
    proposals: list[dict], retrieved_context: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Moves a LOGIC proposal into missing_fields when it's tagged
    epistemic_guess="inferred" (a layout-guessed derivation, never something the
    file actually states) and its own cited source text doesn't mention any of
    the specific words in its field_name at all - e.g. a "Growth Rate Logic"
    proposal that cites a cell whose text is just the cap rate, with no mention
    of growth anywhere. "inferred" already means "nothing explicit backs this";
    if it also can't be tied back to its own cited evidence by name, it's more
    likely the model derived a plausible-looking relationship between two
    unrelated numbers than a real one. Explicit/undetermined proposals are left
    alone - this only targets the one epistemic bucket built from guesswork."""
    text_by_ref_id = _index_retrieved_text(retrieved_context)

    kept: list[dict] = []
    demoted: list[dict] = []
    for proposal in proposals:
        category = (proposal.get("field_category") or "").lower()
        if category not in _LOGIC_CATEGORIES or proposal.get("epistemic_guess") != "inferred":
            kept.append(proposal)
            continue

        words = _WORD_RE.findall(proposal.get("field_name", "").lower())
        significant_words = [w for w in words if w not in _LOGIC_NAME_STOPWORDS]
        if not significant_words:
            kept.append(proposal)  # nothing specific enough in the name to check against
            continue

        ref = proposal.get("source_ref") or {}
        source_text = text_by_ref_id.get(ref.get("document_block_id")) or text_by_ref_id.get(
            ref.get("spreadsheet_cell_id")
        )
        if source_text is None or any(word in source_text for word in significant_words):
            kept.append(proposal)
            continue

        demoted.append(
            {
                "field_name": proposal.get("field_name", ""),
                "field_category": proposal.get("field_category", ""),
                "reason": "inferred derivation's own cited evidence doesn't mention this field's own term",
            }
        )
    return kept, demoted


# the unit a spreadsheet label ends with ("Net operating income INR/year"),
# usually from a units column next to the label
_LABEL_UNIT_RE = re.compile(
    r"(?P<currency>INR|USD|EUR|GBP|AED|Rs\.?|₹|\$)(?P<per>(?:\s*/\s*[A-Za-z ]+?)*)\s*$"
    r"|(?P<area>sq\.?\s*ft|sq\.?\s*m|square\s+(?:feet|metres|meters)|acres?|hectares?)\s*$"
    r"|(?P<rate>rate|%|percent)\s*$"
    r"|(?P<period>months?|years?)\s*$",
    re.IGNORECASE,
)


def _attach_units(proposals: list[dict], retrieved_context: list[dict]) -> None:
    """A DATA value read from a numeric spreadsheet cell is rebuilt from the cell
    itself - its stored number plus the unit from the label beside it ("INR
    12,000,000 per year", "5%", "20,000 sq ft") - rather than kept as the model
    retyped it. The model's own rendering of a cell varies by model and run
    ("120,000,000 INR (adopted market value)", "1,680,000 INR/year"); the cell's
    number and unit are the evidence, so every cell-backed value is reported the
    same way and compares cleanly against the same figure stated elsewhere."""
    cells = {item["spreadsheet_cell_id"]: item for item in retrieved_context if item.get("spreadsheet_cell_id")}
    for proposal in proposals:
        if (proposal.get("field_category") or "").lower() not in _DATA_CATEGORIES:
            continue
        cell = cells.get((proposal.get("source_ref") or {}).get("spreadsheet_cell_id"))
        cached = str((cell or {}).get("cached_value") or "").strip()
        if not _PLAIN_NUMBER_RE.match(cached):
            continue
        unit = _LABEL_UNIT_RE.search(_cell_label(cell.get("text") or ""))
        number = float(cached.replace(",", ""))
        proposal["value"] = _with_unit(number, unit) if unit else _plain(number)


_PLAIN_NUMBER_RE = re.compile(r"^-?[0-9][0-9,]*(\.[0-9]+)?$")


def _cell_label(text: str) -> str:
    # retrieve.py renders a cell as "Sheet!Ref | label: value"
    label = text.split("|", 1)[-1]
    return label.rsplit(":", 1)[0].strip()


def _plain(number: float) -> str:
    return f"{number:,.0f}" if float(number).is_integer() else f"{number:,.4f}".rstrip("0").rstrip(".")


def _with_unit(number: float, unit: re.Match) -> str:
    if unit.group("rate"):
        return f"{number * 100:g}%" if abs(number) <= 1 else f"{number:g}%"
    if unit.group("currency"):
        per = " per ".join(p.strip() for p in unit.group("per").split("/") if p.strip())
        return f"{unit.group('currency')} {_plain(number)}" + (f" per {per}" if per else "")
    return f"{_plain(number)} {(unit.group('area') or unit.group('period')).strip()}"


def _index_retrieved_text(retrieved_context: list[dict]) -> dict[str, str]:
    index: dict[str, str] = {}
    for item in retrieved_context:
        text = (item.get("text") or "").lower()
        for key in ("document_block_id", "spreadsheet_cell_id"):
            ref_id = item.get(key)
            if ref_id:
                index[ref_id] = text
    return index


def _drop_shadowed_undetermined_logic(proposals: list[dict]) -> list[dict]:
    """Drops an "undetermined logic" placeholder for any field_name that some
    other proposal in this same run already answered with a real value. The
    placeholder only ever means "this file's own call found no evidence" - it is
    not a competing answer, so it must not survive to be compared against a real
    one and reported as a conflict."""
    fields_with_real_value = {
        normalize_field_name(p.get("field_name", ""))
        for p in proposals
        if p.get("value") != UNDETERMINED_LOGIC_VALUE
    }
    return [
        p
        for p in proposals
        if p.get("value") != UNDETERMINED_LOGIC_VALUE
        or normalize_field_name(p.get("field_name", "")) not in fields_with_real_value
    ]


def _dedupe_missing(proposals: list[dict], missing: list[dict]) -> list[dict]:
    """Drops a missing-field report if some other file's call found the field, and
    collapses duplicate reports of the same missing field to one."""
    found_fields = {normalize_field_name(p.get("field_name", "")) for p in proposals}

    deduped: list[dict] = []
    seen: set[str] = set()
    for item in missing:
        key = normalize_field_name(item.get("field_name", ""))
        if key in found_fields or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
