import type { CitationOut, ConflictOut, ExtractionOut, FormulaTraceHop } from "../api/client";
import { groupExtractions, rowSourceCount, traceOwners, uniqueCitations } from "./extractionGrouping";

const CATEGORY_LABELS: Record<string, string> = {
  client_info: "Client",
  property_detail: "Property",
  valuation_info: "Valuation",
  logic: "Logic",
  methodology: "Logic",
};

const EVIDENCE_LABELS: Record<string, string> = {
  formula_trace: "Formula trace",
  formula_inferred: "Inferred formula",
  formula_undetermined: "Formula undetermined",
  narrative_rule: "Narrative rule",
  supporting_input: "Supporting input",
  calculated_output: "Calculated output",
  conflict: "Conflicting",
};

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// showTrace=false keeps the formula but leaves its dependency chain to the one
// place in the same field that draws it (see traceOwners)
function renderCitation(citation: CitationOut, showTrace = true): string {
  const header = `${escapeHtml(citation.file_name ?? "Unknown file")}${
    citation.location ? ` &middot; ${escapeHtml(citation.location)}` : ""
  }`;
  const verifiedLabel = citation.verified ? "Verified" : "Unverified";
  const verifiedClass = citation.verified ? "badge badge-verified" : "badge badge-muted";
  const quote = citation.quote_or_formula
    ? `<p class="quote">${escapeHtml(citation.quote_or_formula)}</p>`
    : "";
  const trace = showTrace && citation.formula_path ? renderFormulaTrace(citation.formula_path) : "";
  return `
    <div class="citation">
      <div class="citation-head">
        <span class="badge badge-file">${header}</span>
        <span class="muted">${escapeHtml(citation.citation_type.replace(/_/g, " "))}</span>
        <span class="${verifiedClass}">${verifiedLabel}</span>
      </div>
      ${quote}
      ${trace}
    </div>`;
}

function renderFormulaTrace(hops: FormulaTraceHop[]): string {
  const rows = hops
    .map((hop) => {
      const mark = hop.derivation_matched === true ? "&#10003;" : hop.derivation_matched === false ? "&#10007;" : "&bull;";
      const markClass = hop.derivation_matched === true ? "mark-ok" : hop.derivation_matched === false ? "mark-bad" : "mark-none";
      const formula = hop.raw_formula ? `<span class="mono">${escapeHtml(hop.raw_formula)}</span>` : "";
      const parentRefs = hop.parent_cell_refs ?? [];
      const parent =
        parentRefs.length > 0 ? `<span class="muted">&rarr; feeds ${escapeHtml(parentRefs.join(", "))}</span>` : "";
      return `<div class="trace-row" style="padding-left:${hop.depth * 12}px">
        <span class="${markClass}">${mark}</span>
        <span class="mono">${escapeHtml(hop.sheet_name)}!${escapeHtml(hop.cell_ref)}</span>
        ${formula}
        <span class="muted">= ${escapeHtml(hop.cached_value ?? "—")}</span>
        ${parent}
      </div>`;
    })
    .join("");
  return `<div class="trace"><p class="label">Dependency chain</p>${rows}</div>`;
}

function renderLogicRow(row: ExtractionOut, showTrace: (c: CitationOut) => boolean): string {
  const evidence = row.evidence_type
    ? `<span class="badge badge-evidence">${escapeHtml(EVIDENCE_LABELS[row.evidence_type] ?? row.evidence_type)}</span>`
    : "";
  return `
    <div class="logic-row">
      <div class="logic-head">
        <span class="field-name">${escapeHtml(row.field_name)}</span>
        ${evidence}
        <span class="badge badge-status status-${row.epistemic_status}">${escapeHtml(row.epistemic_status)}</span>
      </div>
      <p class="value">${escapeHtml(row.value ?? "No value extracted.")}</p>
      ${uniqueCitations(row.citations).map((c) => renderCitation(c, showTrace(c))).join("")}
    </div>`;
}

function renderConflict(conflict: ConflictOut, showTrace: (c: CitationOut) => boolean): string {
  const values = conflict.conflicting_values
    .map(
      (cv) => `
      <div class="conflict-value">
        <div class="conflict-value-head">
          <span class="field-name">${escapeHtml(cv.value ?? "—")}</span>
          <span class="badge badge-status status-${cv.epistemic_status}">${escapeHtml(cv.epistemic_status)}</span>
        </div>
        ${uniqueCitations(cv.citations).map((c) => renderCitation(c, showTrace(c))).join("")}
      </div>`
    )
    .join("");
  return `<div class="conflict"><p class="muted">${conflict.conflicting_values.length} conflicting values &middot; ${escapeHtml(conflict.status)}</p>${values}</div>`;
}

function renderRow(extraction: ExtractionOut, conflict: ConflictOut | null, logic: ExtractionOut[]): string {
  const hasConflict = !!conflict && conflict.conflicting_values.length > 0;
  const evidence = extraction.evidence_type
    ? `<span class="badge badge-evidence">${escapeHtml(EVIDENCE_LABELS[extraction.evidence_type] ?? extraction.evidence_type)}</span>`
    : "";
  const logicBadge = logic.length > 0 ? `<span class="badge badge-evidence">Logic</span>` : "";
  const traces = traceOwners(logic);
  const sourceCount = rowSourceCount(extraction, conflict);

  const body = hasConflict
    ? renderConflict(conflict!, traces.showInValue)
    : `
      <p class="value">${escapeHtml(extraction.value ?? "No value extracted.")}</p>
      ${extraction.reasoning_note ? `<p class="reasoning">${escapeHtml(extraction.reasoning_note)}</p>` : ""}
      <p class="muted small">Extracted ${escapeHtml(new Date(extraction.created_at).toLocaleString())}</p>
      ${extraction.citations.length === 0 ? '<p class="muted small">No supporting citation recorded.</p>' : ""}
      ${uniqueCitations(extraction.citations).map((c) => renderCitation(c, traces.showInValue(c))).join("")}`;

  const logicBlock =
    logic.length > 0
      ? `<div class="logic-block"><p class="label">Underlying logic</p>${logic.map((row) => renderLogicRow(row, traces.showInLogic)).join("")}</div>`
      : "";

  const statusBadge = hasConflict
    ? `<span class="badge badge-status conflict-status-${conflict!.status}">${escapeHtml(conflict!.status)}</span>`
    : `<span class="badge badge-status status-${extraction.epistemic_status}">${escapeHtml(extraction.epistemic_status)}</span>`;

  return `
    <section class="row">
      <div class="row-head">
        <span class="category">${escapeHtml(CATEGORY_LABELS[extraction.field_category] ?? extraction.field_category)}</span>
        <span class="field-name">${escapeHtml(extraction.field_name)}</span>
        ${logicBadge}
        ${evidence}
        ${statusBadge}
        <span class="muted small">${sourceCount} source${sourceCount === 1 ? "" : "s"}</span>
      </div>
      <div class="row-body">
        ${body}
        ${logicBlock}
      </div>
    </section>`;
}

const STYLES = `
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; color: #111827; margin: 0; padding: 24px; background: #fff; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .generated { color: #9ca3af; font-size: 12px; margin: 0 0 20px; }
  .row { border: 1px solid #e5e7eb; border-radius: 8px; margin-bottom: 12px; overflow: hidden; }
  .row-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; background: #f9fafb; padding: 8px 12px; border-bottom: 1px solid #e5e7eb; }
  .row-body { padding: 10px 12px; }
  .category { width: 100px; flex-shrink: 0; font-size: 11px; font-weight: 500; color: #6b7280; }
  .field-name { font-size: 13px; font-weight: 600; color: #111827; }
  .value { font-size: 13px; color: #1f2937; margin: 0 0 4px; white-space: pre-wrap; }
  .reasoning { font-size: 11px; color: #6b7280; margin: 0 0 4px; }
  .muted { color: #9ca3af; font-size: 11px; }
  .small { font-size: 10px; }
  .label { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; color: #9ca3af; margin: 0 0 4px; }
  .badge { border-radius: 999px; padding: 2px 8px; font-size: 10px; font-weight: 600; }
  .badge-evidence { background: #eef2ff; color: #4338ca; }
  .badge-file { background: #f3f4f6; color: #374151; }
  .badge-verified { background: #dcfce7; color: #15803d; }
  .badge-muted { background: #f3f4f6; color: #6b7280; }
  .status-explicit { background: #dcfce7; color: #15803d; }
  .status-inferred { background: #fef9c3; color: #a16207; }
  .status-undetermined { background: #f3f4f6; color: #6b7280; }
  .conflict-status-OPEN { background: #fee2e2; color: #b91c1c; }
  .conflict-status-ACKNOWLEDGED { background: #fef9c3; color: #a16207; }
  .conflict-status-RESOLVED { background: #dcfce7; color: #15803d; }
  .citation { border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px; margin: 6px 0; background: #fff; }
  .citation-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
  .quote { font-size: 11px; color: #374151; white-space: pre-wrap; margin: 0 0 4px; }
  .trace { border-top: 1px solid #f3f4f6; margin-top: 4px; padding-top: 4px; }
  .trace-row { display: flex; align-items: center; gap: 8px; font-size: 11px; padding: 1px 0; }
  .mono { font-family: ui-monospace, Menlo, monospace; color: #374151; }
  .mark-ok { color: #15803d; } .mark-bad { color: #b91c1c; } .mark-none { color: #d1d5db; }
  .logic-block { border-top: 1px solid #e5e7eb; margin-top: 8px; padding-top: 8px; }
  .logic-row { border: 1px solid #e0e7ff; background: #eef2ff22; border-radius: 6px; padding: 8px; margin-bottom: 6px; }
  .logic-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
  .conflict-value { border: 1px solid #fee2e2; border-radius: 6px; padding: 8px; margin: 6px 0; background: #fff; }
  .conflict-value-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
`;

export function buildReportHtml(title: string, extractions: ExtractionOut[], conflicts: ConflictOut[]): string {
  const rows = groupExtractions(extractions, conflicts)
    .map(({ extraction, conflict, logic }) => renderRow(extraction, conflict, logic))
    .join("");
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>${escapeHtml(title)}</title>
<style>${STYLES}</style>
</head>
<body>
  <h1>${escapeHtml(title)}</h1>
  <p class="generated">Generated ${escapeHtml(new Date().toLocaleString())}</p>
  ${rows || '<p class="muted">No extraction results yet.</p>'}
</body>
</html>`;
}

export function downloadTextFile(filename: string, content: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Opens the report in a new tab and triggers the browser's print dialog, where
// "Save as PDF" produces a real, selectable-text PDF - no PDF library needed.
export function printReportHtml(html: string): void {
  const printWindow = window.open("", "_blank");
  if (!printWindow) return;
  printWindow.document.open();
  printWindow.document.write(html);
  printWindow.document.close();
  printWindow.onload = () => {
    printWindow.focus();
    printWindow.print();
  };
}
