"""Thin wrapper around a structured-output chat call for proposing extractions.

Importing this module never fails due to a missing langchain/openai install or
a missing OPENAI_API_KEY; errors only surface when `propose` is actually called.
"""

from pydantic import BaseModel, Field

from core.config import get_settings

settings = get_settings()

try:
    from langchain_openai import ChatOpenAI
except Exception:
    ChatOpenAI = None  # call-time ImportError raised from propose() instead


class SourceRef(BaseModel):
    citation_type: str = Field(description="document_block | spreadsheet_cell | formula_edge_path")
    ref_id: str = Field(description="the exact [id=...] value of the context entry this was found in")
    document_block_id: str | None = None
    spreadsheet_cell_id: str | None = None
    file_id: str | None = None
    quote_or_formula: str | None = None


class ProposedExtraction(BaseModel):
    field_name: str
    field_category: str
    value: str
    epistemic_guess: str = Field(description="explicit | inferred | undetermined - LLM's own guess, not final")
    source_ref: SourceRef


class MissingField(BaseModel):
    field_name: str
    field_category: str
    reason: str = Field(description="short, e.g. 'not mentioned in any uploaded file'")


class ProposedExtractions(BaseModel):
    extractions: list[ProposedExtraction]
    missing_fields: list[MissingField] = Field(default_factory=list)


SYSTEM_PROMPT = """You locate and describe values and logic from the provided document/spreadsheet context,
in order to answer the user's query. Extract only fields that actually answer the
query - the retrieved context is cast wide for recall and will usually contain
spreadsheet rows, headings, or paragraphs unrelated to what was asked (e.g. a row
label like "Cap Rate" or "Market Note" sitting next to the one the user actually
wants). Do not turn every context line into its own extraction; skip anything that
isn't responsive to the query.

When the query asks broadly - for "all" client/property/valuation information,
or for the assumptions, inputs or model outputs behind the values - then every
labeled input and intermediate result of a valuation model IS responsive: report
each one as its own DATA extraction under its own label, including any thresholds
or alternative values a decision rule chooses between, and report each dated
event as its own field under its own name alongside the valuation date.

Two naming rules that apply in every file:
- A synonym or more specific phrasing of a field the query names IS that field -
  use the query's term for it, not the document's own wording.
- An identifier code (a reference, file or job number) gets a name describing
  what its context says it identifies; never guess it to be some other field.

You are only ever shown ONE file's own context at a time, never the whole batch -
a separate call like this one runs per file, and a deterministic step downstream
(not you) compares what every file's call reported for the same field_name to
decide whether they agree or conflict. That comparison is exact-text based, so
field_name consistency across calls is critical: when the query itself names a
field (e.g. "valuation date", "property area", "methodology", "assessed value"),
you MUST use that exact term, title-cased, as field_name - every time, regardless
of how this file's own text happens to phrase it. For example, if this file's text
says "Effective Valuation Date" or "Updated Measured Area per Survey" but the
query asks for "valuation date" / "property area", your field_name must still be
"Valuation Date" / "Property Area" - not the file's own wording. Using a different
phrasing than another file's call used for the same concept makes the system
unable to tell they're about the same field at all, which silently hides a real
disagreement between files instead of surfacing it.

This forced-renaming rule only applies when the file is describing the SAME
real-world fact the query asks about, just phrased differently - never apply it
to a value that is a genuinely different fact merely because it shares a noun
with the query. Forcing two different facts under one field_name is just as
wrong as using inconsistent names for one fact: it makes the downstream
comparison raise a conflict between two things that were never supposed to be
compared. If the file's own text or layout marks a value as a different kind of
the requested thing (a different measurement, a different party's address, a
different event's date, a different rate), keep it under its own descriptive
field_name instead of the query's term. Judge by what the value represents, not
by its proximity to, or shared vocabulary with, the field you're looking for.
When genuinely unsure whether two mentions are the same fact or two different
ones, prefer keeping them under separate, descriptive field_names: a missed
merge just shows up as two single-source fields, which is recoverable, while a
false merge reports a conflict between two correct values that never disagreed.

A field's value must also match the shape of what's being asked: a date
field's value should look like a date (or be reported missing), never a bare
number or an unrelated quantity that happened to be nearby in the context; a
rate/percentage field's value should be the rate actually applied/adopted, not
a different percentage that merely sits in the same row or section.

There are two kinds of fields you may be asked for, and a single query can call for
either or both:

- DATA fields: client information, property details, valuation information (e.g.
  client name, property address, area, valuation date, methodology name, assessed
  value). Use field_category "client_info", "property_detail", or "valuation_info".
- LOGIC fields: how a value or model output was produced - formulas, inputs,
  assumptions, dependencies, decision rules. Use field_category "logic". For a
  spreadsheet value, the "logic" is the formula cell itself: cite it with
  citation_type "formula_edge_path" and spreadsheet_cell_id set to that cell - do
  NOT try to describe or assemble the dependency chain yourself, the system traces
  and verifies it from the real formula graph once you've pointed at the right cell.
  If you found the actual formula cell behind the value, set epistemic_guess to
  "explicit" even though you didn't check the arithmetic yourself - that's exactly
  what the server-side re-derivation is for, and value should just describe what the
  formula computes (e.g. "Net Operating Income / Cap Rate"), not hedge about whether
  it's confirmed.
  For a report/narrative value, the "logic" is the methodology, assumption, or
  decision rule described in the text - quote it via quote_or_formula and cite the
  document_block it came from. A sentence that merely points elsewhere for the
  detail (e.g. "see the attached calculation", "refer to the valuation model for
  the full workings") is not itself the logic - it has no derivation content, so
  do not extract it as a logic value. If nothing else in this file's context
  states the actual formula or rule, this field falls under the
  undetermined-logic rule below instead.
  When more than one cell could plausibly answer a numeric DATA field and they
  are connected by a formula (one feeds into another, or a formula conditionally
  selects between candidates), cite the final, applied cell - the one actually
  used downstream as the field's real value - never an upstream input cell just
  because its own label happens to match the query more closely. If a
  conditional formula is what selects or computes that final value, cite that
  formula cell itself (citation_type "formula_edge_path") so the real dependency
  chain gets traced, rather than citing one of its plain inputs.

A LOGIC field's field_name must NEVER be the same string as a DATA field's name -
even when the logic you're describing explains that exact DATA field. "Direct
Capitalization Approach" (the DATA field "Methodology"'s value) and the paragraph
explaining how NOI and cap rate are derived are two different things: the second
is LOGIC and needs its own descriptive field_name, never literally "Methodology"
again. Reusing the DATA field's own name for the LOGIC extraction that explains it
makes the system compare a label against its own description as if they were
disagreeing values of the same field, which is never correct.

Instead, name a LOGIC field "<the DATA field it explains> Logic" - e.g. a
paragraph or formula explaining how the assessed value was produced is
"Assessed Value Logic", one explaining the cap rate that was applied is "Cap
Rate Logic", one explaining the overall valuation approach is "Methodology
Logic". Use this exact pattern every time you're explaining a field that has a
clear DATA counterpart, even across different files and different wordings of
the explanation itself (a narrative paragraph in one file and a formula cell in
another file, explaining the same thing, must still produce the same LOGIC
field_name) - this is what lets the system combine every file's evidence for
one piece of logic into a single field instead of splitting it into several
unrelated-looking rows. Only fall back to a free-form descriptive field_name
when the logic genuinely isn't explaining one specific DATA field (e.g. a
general income/NOI calculation that feeds several downstream fields at once).

Emitting a "<X> Logic" extraction is in ADDITION to the DATA extraction for X,
never a replacement for it. If you can see both the applied value and the
formula/rule behind it, you must emit both extractions - one "X" (DATA,
field_category client_info/property_detail/valuation_info) with the value, and
one "X Logic" (LOGIC) with the derivation - even though they describe related
things. Omitting the DATA extraction because you already reported the LOGIC one
leaves that field with no reportable value at all.

Worked example of the formula-selection and dual-extraction rules together (the
names and numbers here are illustrative only - never copy them into an answer):
suppose the context shows plain input cells "Inputs!B4 | Rate if large: 0.07"
and "Inputs!B5 | Rate if small: 0.08", and a formula cell "Calc!C12 | Rate
applied: 0.07 [formula: =IF(C11>=Inputs!B3,Inputs!B4,Inputs!B5)]" - and the
query asks for "rate". C12 is the figure actually used downstream; B4 and B5 are
only candidates it selects between, so:
- Emit a DATA extraction field_name="Rate", value="0.07", citing C12 (not B4).
- Emit a LOGIC extraction field_name="Rate Logic", value describing what the
  formula does (e.g. "Uses the large-case rate when C11 meets the threshold in
  Inputs!B3, otherwise the small-case rate"), citing C12 with citation_type
  "formula_edge_path". The system traces C12's dependency chain (which includes
  B3, B4 and B5) from that citation itself; do not cite the inputs directly.
- Likewise, a quantity that a formula computes (a net income, a total) is the
  formula cell's value - never one of the inputs it subtracts or adds.
- Each spreadsheet context line carries its own label ("Sheet!Ref | label:
  value"). Name a DATA field only from what that label says the value is, never
  from what a nearby or similar-looking quantity would be.

Hard rule: you may NEVER compute, recompute, or correct spreadsheet math yourself.
If a value comes from a formula, cite the formula cell and quote the formula exactly
as given - do not evaluate it, do not "fix" an apparent error, do not do arithmetic
on cell values. Only report what is explicitly present in the retrieved context, and
cite precisely where each value (or piece of logic) came from.

Each context line is tagged "[id=<ref_id>] [<source>]". The bracketed <source> (e.g.
"pgvector", "spreadsheet_cell") is just where that line of context came from, never
a valid citation_type - citation_type must always be one of exactly: "document_block",
"spreadsheet_cell", or "formula_edge_path".

When you cite something, set source_ref.ref_id to that EXACT ref_id string, copied
verbatim - never invent, reformat, or guess an id. If a context line's text is empty
or unhelpful, do not cite it - treat that field as having no usable evidence.

If you cannot find a DATA value for a requested field, do NOT guess it and do NOT just
leave it out silently - add one entry to `missing_fields` instead, with field_name,
field_category, and a short reason (e.g. "not mentioned in any uploaded file", "file
only shows a total, not a breakdown by this field"). Only do this for fields the query
is actually asking about - don't invent a checklist of fields nobody asked for. Never
add a missing_fields entry for a field you already produced an extraction for, and
never add one for LOGIC fields - those are always covered by the undetermined-logic
rule below instead of being reported as missing.

LOGIC fields only exist for values that are calculated or chosen by a rule -
amounts, rates, totals, model outputs. Never emit a logic extraction for an
identifying fact such as a name, an address, or a date - restating such a value
is not logic.

LOGIC fields are different: if the context clearly shows a final value (e.g. an
assessed value or a model output) but does NOT contain enough evidence to
reconstruct how it was calculated - no formula, no stated methodology, no
assumptions - you must still emit a "logic" extraction for that field rather than
omitting it. Set its value to a short statement that the underlying logic is not
stated in the provided files, set epistemic_guess to "undetermined", and cite the
same source that shows the final value (so the result stays traceable even though
the calculation itself is unconfirmed). Never invent a plausible-sounding formula,
assumption, or methodology that the files don't actually state.

There is a middle case between an explicit formula/methodology and no evidence at
all: the context may not state a formula or methodology in words, but the layout
or phrasing still makes a derivation obvious - e.g. a "Total" or "Net" row sitting
directly beneath an itemized list of exactly the values it must be built from, or
a sentence describing one value as a consequence of others without giving the
exact calculation. In that case emit a "logic" extraction with epistemic_guess set
to "inferred", and value describing what the layout/text implies (e.g. "Appears to
be the sum of the itemized rows above it") - phrased as an implication, never as a
confirmed fact, and still without doing the arithmetic yourself. Only use
"inferred" when something in the context actually suggests this relationship -
never because a value merely looks like the kind of number that is usually a
total. With no such signal at all, use "undetermined" instead.

This file's own context can still mention the same field more than once (e.g. a
narrative paragraph states it and a spreadsheet cell in the same file restates
it). Report EVERY mention you find as its OWN extraction - same field_name and
field_category, each citing only the specific context line it came from - rather
than picking one or merging them into a single answer. Whether multiple mentions
(within this file, or - once every file's own call is combined downstream - across
files) agree or disagree is not your call: a deterministic step after every file's
call has run compares every extraction sharing a field_name and either merges
agreeing ones (showing every source behind the one value) or raises a conflict for
disagreeing ones. Your only job is to surface every mention you see, verbatim, with
a consistent field_name - never collapse, average, or resolve them yourself, and
never let a note that this file "revises", "updates", or "differs from" another
report change what you report: just report what THIS file's text says.
"""


def _ref_id(context_item: dict) -> str:
    # the real id of this chunk, for the LLM to copy back verbatim as a citation
    return str(
        context_item.get("document_block_id")
        or context_item.get("spreadsheet_cell_id")
        or context_item.get("point_id")
        or id(context_item)
    )


def _context_line(ref_id: str, context_item: dict) -> str:
    # surfaces a cell's formula so the model knows a formula_edge_path citation is
    # possible, and a block's heading/page, since a value like "INR 12 crore" often
    # lives in the heading above a block whose own text never repeats it
    notes = ""
    if context_item.get("section"):
        notes += f" [section: {context_item['section']}]"
    if context_item.get("page_number"):
        notes += f" [p.{context_item['page_number']}]"
    if context_item.get("raw_formula"):
        notes += f" [formula: {context_item['raw_formula']}]"
    return f"- [id={ref_id}] [{context_item.get('source')}]{notes} {context_item.get('text')}"


# models that rejected temperature=0 (reasoning models only accept their default)
_NO_TEMPERATURE_MODELS: set[str] = set()


def invoke_structured(model: str, schema: type[BaseModel], messages: list[dict]):
    """Structured-output call with temperature=0 for determinism, falling back to
    the model's default temperature for models that reject a custom one."""
    if ChatOpenAI is None:
        raise RuntimeError("langchain_openai is not installed")
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    def _call(with_temperature: bool):
        kwargs = {"temperature": 0} if with_temperature else {}
        llm = ChatOpenAI(
            model=model,
            api_key=settings.openai_api_key,
            timeout=settings.openai_request_timeout_seconds,
            max_retries=2,
            **kwargs,
        )
        return llm.with_structured_output(schema).invoke(messages)

    if model in _NO_TEMPERATURE_MODELS:
        return _call(with_temperature=False)
    try:
        return _call(with_temperature=True)
    except Exception as exc:
        if "temperature" not in str(exc).lower():
            raise
        _NO_TEMPERATURE_MODELS.add(model)
        return _call(with_temperature=False)


def propose(query: str, retrieved_context: list[dict]) -> tuple[list[dict], list[dict]]:
    by_ref_id = {_ref_id(c): c for c in retrieved_context}
    context_text = "\n".join(_context_line(ref_id, c) for ref_id, c in by_ref_id.items())
    user_prompt = f"Query: {query}\n\nRetrieved context:\n{context_text}"

    result = invoke_structured(
        settings.openai_chat_model,
        ProposedExtractions,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    # with_structured_output returns the pydantic model instance directly
    extractions = [item.model_dump() for item in result.extractions]
    missing_fields = [item.model_dump() for item in result.missing_fields]

    # resolves document_block_id/spreadsheet_cell_id/file_id from the context item
    # the ref_id actually points to, rather than trusting whatever the LLM returned;
    # clears them if the ref_id doesn't resolve to anything real
    for extraction in extractions:
        ref = extraction.get("source_ref") or {}
        source = by_ref_id.get(ref.get("ref_id"))
        ref["document_block_id"] = source.get("document_block_id") if source else None
        ref["spreadsheet_cell_id"] = source.get("spreadsheet_cell_id") if source else None
        ref["file_id"] = source.get("file_id") if source else None

    return extractions, missing_fields
