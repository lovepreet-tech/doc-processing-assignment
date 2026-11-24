import { useState } from "react";
import type { CitationOut, ConflictOut, ExtractionOut, FormulaTraceHop } from "../api/client";
import { rowSourceCount, traceOwners, uniqueCitations } from "../lib/extractionGrouping";

const STATUS_STYLES: Record<string, string> = {
  explicit: "bg-green-100 text-green-700",
  inferred: "bg-yellow-100 text-yellow-700",
  undetermined: "bg-gray-100 text-gray-500",
};

const CONFLICT_STATUS_STYLES: Record<string, string> = {
  OPEN: "bg-red-100 text-red-700",
  ACKNOWLEDGED: "bg-yellow-100 text-yellow-700",
  RESOLVED: "bg-green-100 text-green-700",
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

const CATEGORY_LABELS: Record<string, string> = {
  client_info: "Client",
  property_detail: "Property",
  valuation_info: "Valuation",
  logic: "Logic",
  methodology: "Logic",
};

interface ExtractionResultCardProps {
  extraction: ExtractionOut;
  // set when this field's value is disputed; shown inline in this row's expand
  conflict?: ConflictOut | null;
  onResolve?: (conflictId: string) => void;
  // LOGIC/methodology extractions explaining this row's value, shown inline in the expand
  logic?: ExtractionOut[];
}

// a single extracted field as a compact row; the chevron expands a details panel
// with the full value, reasoning, citations, any disputing values, and any logic
export default function ExtractionResultCard({ extraction, conflict, onResolve, logic = [] }: ExtractionResultCardProps) {
  const [expanded, setExpanded] = useState(false);
  const hasConflict = !!conflict && conflict.conflicting_values.length > 0;
  const sourceCount = rowSourceCount(extraction, conflict ?? null);
  const traces = traceOwners(logic);

  return (
    <div className="border-b border-gray-100 last:border-b-0">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-gray-50"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          className={`h-3 w-3 shrink-0 text-gray-400 transition-transform ${expanded ? "rotate-90" : ""}`}
        >
          <path d="M9 5l7 7-7 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="w-36 shrink-0 truncate text-xs font-medium text-gray-500">
          {CATEGORY_LABELS[extraction.field_category] ?? extraction.field_category}
        </span>
        <span className="w-40 shrink-0 truncate text-sm font-medium text-gray-900">{extraction.field_name}</span>
        {hasConflict ? (
          <span className="min-w-0 flex-1 truncate text-sm text-red-700">
            {conflict!.conflicting_values.length} conflicting values
          </span>
        ) : (
          <span className="min-w-0 flex-1 truncate text-sm text-gray-700">{extraction.value ?? "—"}</span>
        )}
        {logic.length > 0 && (
          <span className="shrink-0 rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-medium text-indigo-700">
            Logic
          </span>
        )}
        {!hasConflict && extraction.evidence_type && (
          <span className="shrink-0 rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-medium text-indigo-700">
            {EVIDENCE_LABELS[extraction.evidence_type] ?? extraction.evidence_type}
          </span>
        )}
        {hasConflict ? (
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${
              CONFLICT_STATUS_STYLES[conflict!.status] ?? CONFLICT_STATUS_STYLES.OPEN
            }`}
          >
            {conflict!.status}
          </span>
        ) : (
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${
              STATUS_STYLES[extraction.epistemic_status] ?? STATUS_STYLES.undetermined
            }`}
          >
            {extraction.epistemic_status}
          </span>
        )}
        <span className="shrink-0 text-[10px] text-gray-300">{sourceCount} source{sourceCount === 1 ? "" : "s"}</span>
      </button>

      {expanded && (
        <div className="mx-3 mb-2 space-y-3 rounded-md bg-gray-50 p-3 text-sm">
          {hasConflict ? (
            <ConflictDetails conflict={conflict!} onResolve={onResolve} showTrace={traces.showInValue} />
          ) : (
            <div className="space-y-2">
              <p className="text-gray-800">{extraction.value ?? "No value extracted."}</p>
              {extraction.reasoning_note && <p className="text-xs text-gray-500">{extraction.reasoning_note}</p>}
              <p className="text-[10px] uppercase tracking-wide text-gray-400">
                Extracted {new Date(extraction.created_at).toLocaleString()}
              </p>
              {extraction.citations.length === 0 && (
                <p className="text-xs text-gray-400">No supporting citation recorded.</p>
              )}
              {uniqueCitations(extraction.citations).map((citation) => (
                <CitationCard key={citation.id} citation={citation} showTrace={traces.showInValue(citation)} />
              ))}
            </div>
          )}

          {logic.length > 0 && (
            <div className="space-y-2 border-t border-gray-200 pt-2">
              <p className="text-[10px] font-medium uppercase tracking-wide text-gray-400">
                Underlying logic
              </p>
              {logic.map((row) => (
                <div key={row.id} className="space-y-1 rounded border border-indigo-100 bg-indigo-50/40 p-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-gray-800">{row.field_name}</span>
                    {row.evidence_type && (
                      <span className="shrink-0 rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-medium text-indigo-700">
                        {EVIDENCE_LABELS[row.evidence_type] ?? row.evidence_type}
                      </span>
                    )}
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        STATUS_STYLES[row.epistemic_status] ?? STATUS_STYLES.undetermined
                      }`}
                    >
                      {row.epistemic_status}
                    </span>
                  </div>
                  <p className="text-xs text-gray-700">{row.value ?? "No value extracted."}</p>
                  {uniqueCitations(row.citations).map((citation) => (
                    <CitationCard key={citation.id} citation={citation} showTrace={traces.showInLogic(citation)} />
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// every disagreeing value for this field, each with every one of its own
// corroborating citations (a value several files agree on still shows every
// one of them, not just the first), plus a resolve action
function ConflictDetails({
  conflict,
  onResolve,
  showTrace,
}: {
  conflict: ConflictOut;
  onResolve?: (conflictId: string) => void;
  showTrace: (citation: CitationOut) => boolean;
}) {
  return (
    <div className="space-y-2">
      {conflict.conflicting_values.map((cv) => (
        <div key={cv.extraction_id} className="space-y-1 rounded border border-red-100 bg-white p-2">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-medium text-gray-900">{cv.value ?? "—"}</span>
            <span
              className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                STATUS_STYLES[cv.epistemic_status] ?? STATUS_STYLES.undetermined
              }`}
            >
              {cv.epistemic_status}
            </span>
          </div>
          {uniqueCitations(cv.citations).map((citation) => (
            <CitationCard key={citation.id} citation={citation} showTrace={showTrace(citation)} />
          ))}
        </div>
      ))}
      {conflict.status !== "RESOLVED" && onResolve && (
        <button
          onClick={() => onResolve(conflict.id)}
          className="text-xs rounded-md border border-gray-300 px-2 py-1 hover:bg-gray-50"
        >
          Mark resolved
        </button>
      )}
    </div>
  );
}

// showTrace=false still shows the formula itself; its dependency chain is drawn
// once elsewhere in the same field (see traceOwners)
function CitationCard({ citation, showTrace }: { citation: CitationOut; showTrace: boolean }) {
  return (
    <div className="rounded border border-gray-200 bg-white p-2">
      <div className="mb-1 flex items-center gap-2">
        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-700">
          {citation.file_name ?? "Unknown file"}
          {citation.location && <span className="font-normal text-gray-500"> · {citation.location}</span>}
        </span>
        <span className="text-[10px] text-gray-400">{citation.citation_type.replace(/_/g, " ")}</span>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
            citation.verified ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
          }`}
          title={
            citation.verified
              ? "The cited formula was re-derived and matched its cached value - this does not confirm the cited cell is the right one for this field, only that its own math checks out."
              : "Could not re-derive and confirm this citation's formula against its cached value."
          }
        >
          {citation.verified ? "Verified" : "Unverified"}
        </span>
      </div>
      {citation.quote_or_formula && (
        <p className="mb-1 whitespace-pre-wrap text-xs text-gray-700">{citation.quote_or_formula}</p>
      )}
      {showTrace && citation.formula_path && <FormulaTrace hops={citation.formula_path} />}
    </div>
  );
}

// the formula dependency chain behind a formula_edge_path citation: output cell
// first, then each input, with a check/cross for whether that hop re-derived cleanly.
// Indentation alone can't disambiguate siblings (two inputs at the same depth
// feeding different parents), so each non-root hop also names its own parent.
function FormulaTrace({ hops }: { hops: FormulaTraceHop[] }) {
  return (
    <div className="mt-1 space-y-1 border-t border-gray-100 pt-1">
      <p className="text-[10px] font-medium uppercase tracking-wide text-gray-400">Dependency chain</p>
      {hops.map((hop) => (
        <div key={hop.cell_id} className="flex flex-wrap items-center gap-2 text-xs" style={{ paddingLeft: hop.depth * 12 }}>
          {hop.derivation_matched === true && <span className="text-green-600 shrink-0">✓</span>}
          {hop.derivation_matched === false && <span className="text-red-600 shrink-0">✕</span>}
          {hop.derivation_matched === null && <span className="text-gray-300 shrink-0">•</span>}
          <span className="font-mono text-gray-700 shrink-0">
            {hop.sheet_name}!{hop.cell_ref}
          </span>
          {hop.raw_formula && <span className="font-mono text-gray-500 break-words">{hop.raw_formula}</span>}
          <span className="text-gray-400 shrink-0">= {hop.cached_value ?? "—"}</span>
          {hop.parent_cell_refs?.length > 0 && (
            <span className="text-gray-400 shrink-0">→ feeds {hop.parent_cell_refs.join(", ")}</span>
          )}
        </div>
      ))}
    </div>
  );
}
