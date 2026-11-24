"""detect_conflicts node - flags disagreements before persist writes anything.

Compares tagged proposal dicts (not yet in the DB) against already-persisted,
active extractions for this batch. Only marks which normalized field_names are
in conflict; persist.py creates the actual Conflict rows.
"""

import difflib
import re
from datetime import date, datetime

from sqlalchemy.orm import Session as DBSession

from core.models import Extraction
from extraction.field_canon import UNDETERMINED_LOGIC_VALUE

NUMERIC_TOLERANCE = 0.01  # relative tolerance for numeric field comparisons
FUZZY_TEXT_THRESHOLD = 0.9  # ratio above which two text values count as "the same, typo aside"


def normalize_field_name(name: str) -> str:
    return re.sub(r"[\s_-]+", "_", name.strip().lower())


def detect_conflicts(db: DBSession, tenant_id: str, batch_id: str, tagged_proposals: list[dict]) -> tuple[list[dict], set[str]]:
    existing = (
        db.query(Extraction)
        .filter(Extraction.tenant_id == tenant_id, Extraction.batch_id == batch_id, Extraction.superseded == False)  # noqa: E712
        .all()
    )
    existing_by_field: dict[str, list[str | None]] = {}
    for row in existing:
        existing_by_field.setdefault(normalize_field_name(row.field_name), []).append(row.value)

    proposals_by_field: dict[str, list[dict]] = {}
    for proposal in tagged_proposals:
        key = normalize_field_name(proposal.get("field_name", ""))
        proposals_by_field.setdefault(key, []).append(proposal)

    conflicted_fields: set[str] = set()
    kept_proposals: list[dict] = []
    for field_name, proposals in proposals_by_field.items():
        existing_values = existing_by_field.get(field_name, [])
        proposals = _drop_proposals_shadowed_by_existing(proposals, existing_values)
        kept_proposals.extend(proposals)

        # a formula description and a narrative description of the same logic
        # are complementary evidence, never competing values - persist merges them
        if all(is_logic_category(p.get("field_category")) for p in proposals):
            continue

        values = _effective_values_for_conflict(
            [p.get("value") for p in proposals] + existing_values
        )
        if len(values) < 2:
            continue
        if not _all_agree(values):
            conflicted_fields.add(field_name)

    return kept_proposals, conflicted_fields


LOGIC_FIELD_CATEGORIES = {"logic", "methodology"}


def is_logic_category(field_category: str | None) -> bool:
    return (field_category or "").lower() in LOGIC_FIELD_CATEGORIES


def _drop_proposals_shadowed_by_existing(proposals: list[dict], existing_values: list[str | None]) -> list[dict]:
    """Drops an "undetermined logic" proposal when a real (non-placeholder) value
    already exists for this field from an earlier run. This run simply finding no
    evidence this time must not supersede, or be compared against, a real answer
    already on record."""
    if not any(v is not None and v != UNDETERMINED_LOGIC_VALUE for v in existing_values):
        return proposals
    return [p for p in proposals if p.get("value") != UNDETERMINED_LOGIC_VALUE]


def _effective_values_for_conflict(values: list[str | None]) -> list[str | None]:
    """An "undetermined logic" placeholder just means one source had no evidence -
    it is never a real disagreement with another source's real answer, so it must
    not count as a competing value whenever at least one real value is present."""
    real = [v for v in values if v != UNDETERMINED_LOGIC_VALUE]
    return real if real else values


def _all_agree(values: list[str | None]) -> bool:
    first = values[0]
    return all(_values_equal(first, value) for value in values[1:])


_LEADING_NUMBER_RE = re.compile(r"[-+]?(?:inr|rs\.?|₹)?\s*\$?\s*([0-9][0-9,]*\.?[0-9]*)", re.IGNORECASE)
# allows only letters/%/whitespace/periods after the number; anything else
# trailing means the value is a date or other compound string, not
# number-with-unit. Periods are allowed so an abbreviation like "sq. ft." or
# "Rs." doesn't fail this check just because it's written with full stops -
# without this, "31,400 sq. ft." and "31,400 sq ft" (same number, same unit,
# different punctuation) fell through to a textual compare and could register
# as a false conflict.
_UNIT_SUFFIX_RE = re.compile(r"^[a-zA-Z%\s./-]*$")
# "(adopted market value)" style notes a model appends to a figure
_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")

# Indian numbering scale words, e.g. "12 crore" == 120,000,000 and "50 lakh" ==
# 5,000,000 - without this, "INR 12 crore" (text) and "120000000" (an already
# computed Excel total) never register as the same value and get flagged as a
# false conflict even though they're the same number.
_SCALE_WORDS: dict[str, float] = {
    "crore": 1_00_00_000,
    "crores": 1_00_00_000,
    "cr": 1_00_00_000,
    "lakh": 1_00_000,
    "lakhs": 1_00_000,
    "lac": 1_00_000,
    "lacs": 1_00_000,
    "thousand": 1_000,
    "million": 1_000_000,
    "millions": 1_000_000,
    "mn": 1_000_000,
    "billion": 1_000_000_000,
    "billions": 1_000_000_000,
    "bn": 1_000_000_000,
}
_SCALE_VALUE_RE = re.compile(
    r"[-+]?(?:inr|rs\.?|₹|usd|\$)?\s*([0-9][0-9,]*\.?[0-9]*)\s*"
    r"(crores?|cr|lakhs?|lacs?|thousand|millions?|mn|billions?|bn)\b",
    re.IGNORECASE,
)


def _extract_number(value: str) -> float | None:
    """Pulls the leading numeric token out of a value that may carry a unit,
    currency symbol, or Indian numbering scale word, e.g. "45,000 sq ft",
    "$45,000.00", and "INR 12 crore" extract to 45000.0, 45000.0, and 120000000.0
    respectively."""
    value = _PARENTHETICAL_RE.sub("", value).strip()

    scale_match = _SCALE_VALUE_RE.match(value)
    if scale_match and _UNIT_SUFFIX_RE.match(value[scale_match.end():]):
        try:
            number = float(scale_match.group(1).replace(",", ""))
        except ValueError:
            return None
        return number * _SCALE_WORDS[scale_match.group(2).lower()]

    match = _LEADING_NUMBER_RE.match(value)
    if not match or not _UNIT_SUFFIX_RE.match(value[match.end():]):
        return None
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    # "10%" and a spreadsheet's 0.1 are the same rate
    return number / 100 if "%" in value[match.end():] else number


def _values_equal(a: str | None, b: str | None) -> bool:
    if a == b:
        return True
    if a is None or b is None:
        return False

    fa, fb = _extract_number(str(a)), _extract_number(str(b))
    if fa is not None and fb is not None:
        if fa == 0 and fb == 0:
            return True
        return abs(fa - fb) <= NUMERIC_TOLERANCE * max(abs(fa), abs(fb))

    parsed_a, parsed_b = _try_parse_date(str(a)), _try_parse_date(str(b))
    if parsed_a and parsed_b:
        return parsed_a == parsed_b

    norm_a, norm_b = str(a).strip().lower(), str(b).strip().lower()
    if norm_a == norm_b:
        return True
    # "Direct capitalization" and "Apply direct capitalization." state the same
    # thing - one value's words appearing as a run inside the other's
    words_a, words_b = _WORDS_RE.findall(norm_a), _WORDS_RE.findall(norm_b)
    shorter, longer = sorted((words_a, words_b), key=len)
    if len(shorter) >= 2 and _contains_run(longer, shorter):
        return True
    # fuzzy match catches OCR noise ("Hoidings" vs "Holdings") on longer strings only
    if len(norm_a) >= 6 and len(norm_b) >= 6:
        return difflib.SequenceMatcher(None, norm_a, norm_b).ratio() >= FUZZY_TEXT_THRESHOLD
    return False


_WORDS_RE = re.compile(r"[a-z0-9]+")


def _contains_run(longer: list[str], shorter: list[str]) -> bool:
    n = len(shorter)
    return any(longer[i : i + n] == shorter for i in range(len(longer) - n + 1))


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%Y/%m/%d",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
)
_ORDINAL_RE = re.compile(r"(\d)(st|nd|rd|th)\b", re.IGNORECASE)
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
# a date embedded in a longer value, e.g. "effective 30 September 2026"
_EMBEDDED_DATE_RE = re.compile(
    rf"\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH},?\s+\d{{4}}"
    rf"|{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}[/.-]\d{1,2}[/.-]\d{4}",
    re.IGNORECASE,
)


def _try_parse_date(value: str) -> date | None:
    """Parses a value that is a date, or that contains exactly one recognizable
    date inside surrounding words ("effective 30 September 2026")."""
    parsed = _parse_date_exact(value)
    if parsed:
        return parsed
    match = _EMBEDDED_DATE_RE.search(value)
    return _parse_date_exact(match.group(0)) if match else None


def _parse_date_exact(value: str) -> date | None:
    cleaned = _ORDINAL_RE.sub(r"\1", value.strip().rstrip(".")).replace(",", "")
    cleaned = re.sub(r"\s+", " ", cleaned).replace("Sept ", "Sep ").replace("sept ", "sep ")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None
