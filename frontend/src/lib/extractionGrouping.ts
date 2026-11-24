import type { CitationOut, ConflictOut, ExtractionOut } from "../api/client";

// mirrors extraction/nodes/detect_conflicts.py's normalize_field_name
export function normalizeFieldName(name: string): string {
  return name.trim().toLowerCase().replace(/[\s_-]+/g, "_");
}

export const LOGIC_CATEGORIES = new Set(["logic", "methodology"]);

export interface GroupedRow {
  extraction: ExtractionOut;
  conflict: ConflictOut | null;
  logic: ExtractionOut[];
}

// Groups a flat extractions+conflicts list the way the UI displays it: a
// conflicted field collapses to one row, and a LOGIC/methodology extraction
// whose field_name identifies it as explaining a DATA row (field_canon.py's
// " Logic" suffix convention) is attached to that row instead of standing alone.
export function groupExtractions(extractions: ExtractionOut[], conflicts: ConflictOut[]): GroupedRow[] {
  const conflictByField = new Map(conflicts.map((c) => [normalizeFieldName(c.field_name), c]));

  const dataRows = extractions.filter((e) => !LOGIC_CATEGORIES.has(e.field_category));
  const logicRows = extractions.filter((e) => LOGIC_CATEGORIES.has(e.field_category));

  const logicByBase = new Map<string, ExtractionOut[]>();
  const attachedLogicIds = new Set<string>();
  for (const base of dataRows) {
    const baseKey = normalizeFieldName(base.field_name);
    const matches = logicRows.filter((l) => {
      const logicKey = normalizeFieldName(l.field_name);
      return logicKey !== baseKey && logicKey.startsWith(baseKey);
    });
    if (matches.length > 0) {
      logicByBase.set(base.id, matches);
      matches.forEach((m) => attachedLogicIds.add(m.id));
    }
  }

  const seenFields = new Set<string>();
  const rows: GroupedRow[] = [];
  for (const extraction of [...dataRows, ...logicRows.filter((l) => !attachedLogicIds.has(l.id))]) {
    const key = normalizeFieldName(extraction.field_name);
    if (seenFields.has(key)) continue; // conflict already rendered once from its first member
    seenFields.add(key);
    rows.push({
      extraction,
      conflict: conflictByField.get(key) ?? null,
      logic: logicByBase.get(extraction.id) ?? [],
    });
  }
  return rows;
}

// one source = one place in one file; two citations to the same block or cell
// (e.g. a cell cited by both a narrative and a formula proposal) count once
export function citationKey(citation: CitationOut): string {
  return `${citation.file_id}:${citation.document_block_id ?? citation.spreadsheet_cell_id ?? citation.id}`;
}

export function uniqueCitations(citations: CitationOut[]): CitationOut[] {
  const seen = new Set<string>();
  return citations.filter((c) => {
    const key = citationKey(c);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// a conflicted field's sources are every disagreeing value's sources, not the
// first row's alone
export function rowSourceCount(extraction: ExtractionOut, conflict: ConflictOut | null): number {
  const citations =
    conflict && conflict.conflicting_values.length > 0
      ? conflict.conflicting_values.flatMap((cv) => cv.citations)
      : extraction.citations;
  return uniqueCitations(citations).length;
}

// Decides where each formula's dependency chain is drawn so it appears once per
// field: under "Underlying logic" when a logic row traces that same cell (on
// its first occurrence only), otherwise under the value itself.
export function traceOwners(logic: ExtractionOut[]): { showInValue: (c: CitationOut) => boolean; showInLogic: (c: CitationOut) => boolean } {
  const hasTrace = (c: CitationOut) => !!c.formula_path && c.formula_path.length > 0;
  const logicFirst = new Map<string, string>();
  for (const row of logic) {
    for (const c of row.citations) {
      if (hasTrace(c) && c.spreadsheet_cell_id && !logicFirst.has(c.spreadsheet_cell_id)) {
        logicFirst.set(c.spreadsheet_cell_id, c.id);
      }
    }
  }
  return {
    showInValue: (c) => hasTrace(c) && !(c.spreadsheet_cell_id && logicFirst.has(c.spreadsheet_cell_id)),
    showInLogic: (c) => hasTrace(c) && !!c.spreadsheet_cell_id && logicFirst.get(c.spreadsheet_cell_id) === c.id,
  };
}
