"""persist node - writes everything from this run inside one transaction:
supersedes old rows for touched fields, inserts new Extraction + Citation rows,
bumps the batch's reconciliation_version, and turns detect_conflicts' flagged
field names into real Conflict rows.

Proposals that agree on a field are collapsed into one Extraction row with a
Citation per source; proposals that disagree stay as separate rows, feeding a
Conflict.
"""

from core.db import session_scope
from core.models import Batch, Citation, Conflict, Extraction
from extraction.nodes.detect_conflicts import _all_agree, _values_equal, is_logic_category, normalize_field_name

EPISTEMIC_PRIORITY = {"explicit": 0, "inferred": 1, "undetermined": 2}


def _cluster_by_value(proposals: list[dict]) -> list[list[dict]]:
    """Groups proposals whose values agree with each other (via _values_equal)."""
    clusters: list[list[dict]] = []
    for proposal in proposals:
        value = proposal.get("value")
        for cluster in clusters:
            if _values_equal(cluster[0].get("value"), value):
                cluster.append(proposal)
                break
        else:
            clusters.append([proposal])
    return clusters


def persist(tenant_id: str, batch_id: str, tagged_proposals: list[dict], conflicted_fields: set[str]) -> list[str]:
    with session_scope() as db:
        batch = db.query(Batch).filter(Batch.id == batch_id, Batch.tenant_id == tenant_id).one()
        batch.reconciliation_version += 1
        new_version = batch.reconciliation_version

        touched_fields = {normalize_field_name(p.get("field_name", "")) for p in tagged_proposals}

        active = (
            db.query(Extraction)
            .filter(Extraction.tenant_id == tenant_id, Extraction.batch_id == batch_id, Extraction.superseded == False)  # noqa: E712
            .all()
        )
        for row in active:
            row_field = normalize_field_name(row.field_name)
            # rows for a field already flagged as conflicting stay active, since
            # the Conflict created below needs to point at both old and new values
            if row_field in touched_fields and row_field not in conflicted_fields:
                row.superseded = True

        # auto-resolves any open conflict for a touched field, since its
        # conflicting_extraction_ids are about to point at rows superseded above
        stale_conflicts = (
            db.query(Conflict)
            .filter(Conflict.tenant_id == tenant_id, Conflict.batch_id == batch_id, Conflict.status != "RESOLVED")
            .all()
        )
        for conflict in stale_conflicts:
            if normalize_field_name(conflict.field_name) in touched_fields:
                conflict.status = "RESOLVED"
                conflict.resolved_value = {"auto_resolved": "superseded by a newer extraction run"}

        proposals_by_field: dict[str, list[dict]] = {}
        for proposal in tagged_proposals:
            key = normalize_field_name(proposal.get("field_name", ""))
            proposals_by_field.setdefault(key, []).append(proposal)

        created: list[Extraction] = []
        for proposals in proposals_by_field.values():
            # every source describing one piece of logic (a formula trace, a
            # narrative rule) becomes one row with all of them as citations
            if len(proposals) > 1 and all(is_logic_category(p.get("field_category")) for p in proposals):
                created.append(_persist_merged(db, tenant_id, batch_id, proposals, new_version))
            elif len(proposals) > 1 and _all_agree([p.get("value") for p in proposals]):
                created.append(_persist_merged(db, tenant_id, batch_id, proposals, new_version))
            else:
                # sources disagree overall but may still contain sub-groups that
                # agree with each other, so cluster by value first: each distinct
                # value becomes one row for the Conflict to point at
                for cluster in _cluster_by_value(proposals):
                    if len(cluster) > 1:
                        created.append(_persist_merged(db, tenant_id, batch_id, cluster, new_version))
                    else:
                        created.append(_persist_one(db, tenant_id, batch_id, cluster[0], new_version))

        # map normalized field_name -> all currently-active rows (survivors + new)
        still_active = [row for row in active if not row.superseded] + created
        by_field: dict[str, list[Extraction]] = {}
        for row in still_active:
            by_field.setdefault(normalize_field_name(row.field_name), []).append(row)

        for field_name in conflicted_fields:
            rows = by_field.get(field_name, [])
            if len(rows) < 2:
                continue
            for row in rows:
                row.evidence_type = "conflict"
            conflict = Conflict(
                tenant_id=tenant_id,
                batch_id=batch_id,
                field_name=field_name,
                conflicting_extraction_ids=[row.id for row in rows],
                conflict_summary=_summarize(rows),
                status="OPEN",
            )
            db.add(conflict)

        return [str(row.id) for row in created]


def _persist_one(db, tenant_id: str, batch_id: str, proposal: dict, version: int) -> Extraction:
    ref = proposal.get("source_ref") or {}
    citation_type = ref.get("citation_type", "document_block")

    extraction = Extraction(
        tenant_id=tenant_id,
        batch_id=batch_id,
        field_name=proposal.get("field_name", ""),
        field_category=proposal.get("field_category", "unknown"),
        value=proposal.get("value"),
        epistemic_status=proposal.get("epistemic_status", "undetermined"),
        evidence_type=_classify_evidence_type(proposal, citation_type),
        reasoning_note=proposal.get("verification_reason"),
        reconciliation_version=version,
        superseded=False,
    )
    db.add(extraction)
    db.flush()  # need extraction.id before attaching the citation
    _add_citation(db, tenant_id, extraction.id, proposal)
    return extraction


def _persist_merged(db, tenant_id: str, batch_id: str, proposals: list[dict], version: int) -> Extraction:
    # the most-explicit proposal supplies the row's headline value/status; the
    # other agreeing proposals still get their own Citation below
    best = min(proposals, key=_headline_priority)
    best_ref = best.get("source_ref") or {}
    best_citation_type = best_ref.get("citation_type", "document_block")
    evidence_type = _classify_evidence_type(best, best_citation_type)
    if any((p.get("source_ref") or {}).get("citation_type") == "formula_edge_path" for p in proposals):
        evidence_type = "formula_trace" if is_logic_category(best.get("field_category")) else "calculated_output"

    extraction = Extraction(
        tenant_id=tenant_id,
        batch_id=batch_id,
        field_name=best.get("field_name", ""),
        field_category=best.get("field_category", "unknown"),
        value=best.get("value"),
        epistemic_status=best.get("epistemic_status", "undetermined"),
        evidence_type=evidence_type,
        reasoning_note=best.get("verification_reason"),
        reconciliation_version=version,
        superseded=False,
    )
    db.add(extraction)
    db.flush()  # need extraction.id before attaching citations

    # two proposals citing the same block or cell are one source, not two
    cited: set[tuple] = set()
    for proposal in sorted(proposals, key=_headline_priority):
        ref = proposal.get("source_ref") or {}
        key = (ref.get("document_block_id"), ref.get("spreadsheet_cell_id"))
        if key != (None, None) and key in cited:
            continue
        cited.add(key)
        _add_citation(db, tenant_id, extraction.id, proposal)

    return extraction


def _headline_priority(proposal: dict) -> tuple[int, int]:
    """Most explicit first; for logic, a narrative rule's own wording beats a
    formula's machine description as the headline (the formula chain is still
    attached as a citation)."""
    epistemic = EPISTEMIC_PRIORITY.get(proposal.get("epistemic_status"), 2)
    citation_type = (proposal.get("source_ref") or {}).get("citation_type")
    narrative_logic = is_logic_category(proposal.get("field_category")) and citation_type == "document_block"
    return epistemic, 0 if narrative_logic else 1


def _add_citation(db, tenant_id: str, extraction_id, proposal: dict) -> None:
    ref = proposal.get("source_ref") or {}
    verification = proposal.get("_citation_verification") or {}
    citation_type = ref.get("citation_type", "document_block")

    file_id = verification.get("file_id") or ref.get("file_id")
    if not file_id:
        return
    citation = Citation(
        tenant_id=tenant_id,
        extraction_id=extraction_id,
        file_id=file_id,
        citation_type=citation_type,
        document_block_id=ref.get("document_block_id"),
        spreadsheet_cell_id=ref.get("spreadsheet_cell_id"),
        # server-derived by verify_citations (extraction.formula_trace)
        formula_path=verification.get("chain"),
        quote_or_formula=ref.get("quote_or_formula"),
        verified=verification.get("verified", False),
    )
    db.add(citation)


LOGIC_CATEGORIES = {"logic", "methodology"}


def _classify_evidence_type(proposal: dict, citation_type: str) -> str | None:
    """Tags a row with what kind of evidence it is. DATA: a value a formula
    computes is a calculated_output, a value typed into a cell is a
    supporting_input, a value stated in a document is left untagged. LOGIC: a
    traced formula, a narrative rule, or an inferred/undetermined derivation.
    """
    field_category = (proposal.get("field_category") or "").lower()
    if field_category not in LOGIC_CATEGORIES:
        if citation_type == "formula_edge_path":
            return "calculated_output"
        if citation_type == "spreadsheet_cell":
            return "supporting_input"
        return None
    if citation_type == "formula_edge_path":
        return "formula_trace"
    # no explicit formula/formula_edges chain behind this row - fall back to
    # whatever tag_epistemic_status already settled on, so the FE can tell a
    # layout/phrasing-implied derivation (inferred) apart from one with no
    # derivation evidence at all (undetermined), instead of showing nothing
    epistemic_status = proposal.get("epistemic_status")
    if epistemic_status == "inferred":
        return "formula_inferred"
    if epistemic_status == "undetermined":
        return "formula_undetermined"
    if citation_type == "document_block":
        return "narrative_rule"
    if citation_type == "spreadsheet_cell":
        return "supporting_input"
    return None


def _summarize(rows: list[Extraction]) -> str:
    values = ", ".join(repr(row.value) for row in rows)
    return f"Disagreeing values found: {values}"
