// Fetch wrapper for the backend API, keeping headers/base-url logic in one place.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// stand-in identity, matching core/security.py's header-based stub on the backend
const TENANT_ID = "00000000-0000-0000-0000-000000000001";
const USER_ID = "00000000-0000-0000-0000-000000000002";

function authHeaders(): HeadersInit {
  return { "X-Tenant-Id": TENANT_ID, "X-User-Id": USER_ID };
}

// EventSource can't set custom headers, so SSE endpoints take identity as query params
function authQuery(): string {
  return `tenant_id=${TENANT_ID}&user_id=${USER_ID}`;
}

export interface SessionOut {
  id: string;
  name: string | null;
  status: string;
  created_at: string;
}

export interface BatchOut {
  id: string;
  session_id: string;
  status: string;
  reconciliation_version: number;
}

export interface FileOut {
  id: string;
  batch_id: string;
  original_filename: string;
  status: string;
}

export async function listSessions(): Promise<SessionOut[]> {
  const res = await fetch(`${API_BASE_URL}/sessions`, { headers: authHeaders() });
  if (!res.ok) throw new Error("failed to list sessions");
  return res.json();
}

export async function createSession(name?: string): Promise<SessionOut> {
  const res = await fetch(`${API_BASE_URL}/sessions`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error("failed to create session");
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/sessions/${sessionId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("failed to delete session");
}

export async function createBatch(sessionId: string): Promise<BatchOut> {
  const res = await fetch(`${API_BASE_URL}/sessions/${sessionId}/batches`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("failed to create batch");
  return res.json();
}

export async function listBatches(sessionId: string): Promise<BatchOut[]> {
  const res = await fetch(`${API_BASE_URL}/sessions/${sessionId}/batches`, { headers: authHeaders() });
  if (!res.ok) throw new Error("failed to list batches");
  return res.json();
}

export async function listFiles(batchId: string): Promise<FileOut[]> {
  const res = await fetch(`${API_BASE_URL}/batches/${batchId}/files`, { headers: authHeaders() });
  if (!res.ok) throw new Error("failed to list files");
  return res.json();
}

export async function uploadFiles(batchId: string, files: File[]): Promise<FileOut[]> {
  const form = new FormData();
  files.forEach((f) => form.append("uploads", f));
  const res = await fetch(`${API_BASE_URL}/batches/${batchId}/files`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  if (!res.ok) throw new Error("failed to upload files");
  return res.json();
}

export async function getFileStatus(batchId: string, fileId: string): Promise<FileOut> {
  const res = await fetch(`${API_BASE_URL}/batches/${batchId}/files/${fileId}/status`, { headers: authHeaders() });
  if (!res.ok) throw new Error("failed to get file status");
  return res.json();
}

export function subscribeToFileProgress(
  batchId: string,
  fileId: string,
  onEvent: (data: string) => void
): EventSource {
  const es = new EventSource(`${API_BASE_URL}/batches/${batchId}/files/${fileId}/progress?${authQuery()}`);
  es.onmessage = (e) => onEvent(e.data);
  return es;
}

// opened directly as a new browser tab (window.open), so identity travels as
// query params like the SSE progress stream above
export function fileContentUrl(batchId: string, fileId: string): string {
  return `${API_BASE_URL}/batches/${batchId}/files/${fileId}/content?${authQuery()}`;
}

export interface GuidanceOut {
  message: string;
  file_summaries: { filename: string; status: string }[];
  available_fields: string[];
  suggested_queries: string[];
}

export interface MissingFieldOut {
  field_name: string;
  field_category: string;
  reason: string;
}

export interface ExtractionJobOut {
  id: string;
  batch_id: string;
  query: string | null;
  status: string;
  error: string | null;
  result_kind: "EXTRACTION" | "GUIDANCE";
  guidance: GuidanceOut | null;
  missing_fields: MissingFieldOut[] | null;
}

export interface FormulaTraceHop {
  cell_id: string;
  parent_cell_ids: string[];
  parent_cell_refs: string[];
  sheet_name: string;
  cell_ref: string;
  raw_formula: string | null;
  cached_value: string | null;
  is_formula: boolean;
  depth: number;
  derivation_matched: boolean | null;
}

export interface CitationOut {
  id: string;
  citation_type: string;
  document_block_id: string | null;
  spreadsheet_cell_id: string | null;
  formula_path: FormulaTraceHop[] | null;
  quote_or_formula: string | null;
  verified: boolean;
  file_id: string;
  file_name: string | null;
  location: string | null;
}

export interface ExtractionOut {
  id: string;
  field_name: string;
  field_category: string;
  value: string | null;
  epistemic_status: string;
  evidence_type: string | null;
  reasoning_note: string | null;
  created_at: string;
  citations: CitationOut[];
}

export interface ConflictingValueOut {
  extraction_id: string;
  value: string | null;
  epistemic_status: string;
  citations: CitationOut[];
}

export interface ConflictOut {
  id: string;
  field_name: string;
  conflict_summary: string | null;
  status: string;
  conflicting_extraction_ids: string[];
  conflicting_values: ConflictingValueOut[];
}

export async function submitExtraction(
  batchId: string,
  query: string,
  force = false
): Promise<{ job_id: string }> {
  const res = await fetch(`${API_BASE_URL}/batches/${batchId}/extract`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ query, force }),
  });
  if (!res.ok) throw new Error("failed to submit extraction");
  // backend's ExtractionJobOut names the id field "id", not "job_id"
  const job: { id: string } = await res.json();
  return { job_id: job.id };
}

export function subscribeToExtractionProgress(
  jobId: string,
  onEvent: (data: string) => void
): EventSource {
  const es = new EventSource(`${API_BASE_URL}/extraction-jobs/${jobId}/progress?${authQuery()}`);
  es.onmessage = (e) => onEvent(e.data);
  return es;
}

export async function getExtractionJob(jobId: string): Promise<ExtractionJobOut> {
  const res = await fetch(`${API_BASE_URL}/extraction-jobs/${jobId}`, { headers: authHeaders() });
  if (!res.ok) throw new Error("failed to get extraction job");
  return res.json();
}

export async function listExtractionJobs(batchId: string): Promise<ExtractionJobOut[]> {
  const res = await fetch(`${API_BASE_URL}/batches/${batchId}/extraction-jobs`, { headers: authHeaders() });
  if (!res.ok) throw new Error("failed to list extraction jobs");
  return res.json();
}

export async function listExtractions(batchId: string): Promise<ExtractionOut[]> {
  const res = await fetch(`${API_BASE_URL}/batches/${batchId}/extractions`, { headers: authHeaders() });
  if (!res.ok) throw new Error("failed to list extractions");
  return res.json();
}

export async function listConflicts(batchId: string): Promise<ConflictOut[]> {
  const res = await fetch(`${API_BASE_URL}/batches/${batchId}/conflicts`, { headers: authHeaders() });
  if (!res.ok) throw new Error("failed to list conflicts");
  return res.json();
}

// scoped to one extraction job's query, not the whole batch's history
export async function listJobExtractions(jobId: string): Promise<ExtractionOut[]> {
  const res = await fetch(`${API_BASE_URL}/extraction-jobs/${jobId}/extractions`, { headers: authHeaders() });
  if (!res.ok) throw new Error("failed to list job extractions");
  return res.json();
}

export async function listJobConflicts(jobId: string): Promise<ConflictOut[]> {
  const res = await fetch(`${API_BASE_URL}/extraction-jobs/${jobId}/conflicts`, { headers: authHeaders() });
  if (!res.ok) throw new Error("failed to list job conflicts");
  return res.json();
}

export async function resolveConflict(conflictId: string): Promise<ConflictOut> {
  const res = await fetch(`${API_BASE_URL}/conflicts/${conflictId}/resolve`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error("failed to resolve conflict");
  return res.json();
}
