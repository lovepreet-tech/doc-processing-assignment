import { useEffect, useState } from "react";
import {
  getExtractionJob,
  listJobConflicts,
  listJobExtractions,
  resolveConflict,
  subscribeToExtractionProgress,
  type ConflictOut,
  type ExtractionOut,
  type GuidanceOut,
  type MissingFieldOut,
} from "../api/client";
import ProgressStepper from "./ProgressStepper";
import ExtractionResultCard from "./ExtractionResultCard";
import DownloadReportButton from "./DownloadReportButton";
import { groupExtractions } from "../lib/extractionGrouping";

const EXTRACTION_STEPS = [
  "check_cache",
  "retrieve",
  "propose_extractions",
  "verify_citations",
  "tag_epistemic_status",
  "review_proposals",
  "detect_conflicts",
  "persist",
  "done",
];

// SSE can silently stop delivering events (dropped connection, idle timeout) with
// no error the client can see, so this is a safety net: if the stream goes quiet
// for a while, fall back to polling the job's real status instead of sitting on
// a stale step forever.
const STALL_POLL_MS = 8000;

interface ExtractionTurnProps {
  jobId: string;
  batchId: string;
  displayQuery: string;
  onFollowUp: (query: string) => void;
}

// one extraction run: starts in a live SSE-driven progress state and settles
// into either an EXTRACTION result (fields/conflicts) or GUIDANCE
export default function ExtractionTurn({ jobId, batchId, displayQuery, onFollowUp }: ExtractionTurnProps) {
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const [status, setStatus] = useState<"running" | "done" | "failed">("running");
  const [extractions, setExtractions] = useState<ExtractionOut[]>([]);
  const [conflicts, setConflicts] = useState<ConflictOut[]>([]);
  const [guidance, setGuidance] = useState<GuidanceOut | null>(null);
  const [missingFields, setMissingFields] = useState<MissingFieldOut[]>([]);

  // resolves the job's real status on mount, in case the redis progress cache
  // has expired and the SSE stream below has nothing to replay
  useEffect(() => {
    getExtractionJob(jobId)
      .then((job) => {
        if (job.status === "DONE") setStatus("done");
        else if (job.status === "FAILED") setStatus("failed");
      })
      .catch(() => {});
  }, [jobId]);

  useEffect(() => {
    const es = subscribeToExtractionProgress(jobId, (raw) => {
      const event = JSON.parse(raw);
      setCurrentStep(event.step);
      setDetail(event.detail ?? null);
      if (event.status === "done" && event.step === "done") setStatus("done");
      if (event.status === "failed") setStatus("failed");
      // closes the stream explicitly on a terminal status, since EventSource
      // otherwise treats the backend ending it as a dropped connection and retries
      if (event.status === "done" || event.status === "failed") es.close();
    });
    return () => es.close();
  }, [jobId]);

  // belt-and-suspenders: if the SSE stream above stalls (connection dropped with
  // no error event, or the job finished before/without a terminal message ever
  // arriving), this keeps polling the job's real status so the UI doesn't get
  // stuck showing "running" forever even though the backend already finished
  useEffect(() => {
    if (status !== "running") return;
    const interval = setInterval(() => {
      getExtractionJob(jobId)
        .then((job) => {
          if (job.status === "DONE") setStatus("done");
          else if (job.status === "FAILED") setStatus("failed");
        })
        .catch(() => {});
    }, STALL_POLL_MS);
    return () => clearInterval(interval);
  }, [status, jobId]);

  useEffect(() => {
    if (status !== "done") return;
    getExtractionJob(jobId)
      .then((job) => {
        if (job.result_kind === "GUIDANCE") {
          setGuidance(job.guidance);
          return;
        }
        setMissingFields(job.missing_fields ?? []);
        listJobExtractions(jobId).then(setExtractions).catch(console.error);
        listJobConflicts(jobId).then(setConflicts).catch(console.error);
      })
      .catch(console.error);
  }, [status, jobId, batchId]);

  async function handleResolve(conflictId: string) {
    const updated = await resolveConflict(conflictId);
    setConflicts((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
  }

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg bg-blue-600 text-white px-3 py-2 text-sm">{displayQuery}</div>
      </div>
      <div className="rounded-lg border border-gray-200 p-3 bg-white shadow-sm space-y-3">
        {status !== "done" && (
          <ProgressStepper steps={EXTRACTION_STEPS} currentStep={currentStep} status={status} detail={detail} />
        )}
        {status === "done" && guidance && (
          <div className="space-y-3">
            <p className="text-sm text-gray-700">{guidance.message}</p>
            {guidance.suggested_queries.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {guidance.suggested_queries.map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => onFollowUp(suggestion)}
                    className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {status === "done" && !guidance && (
          <>
            {extractions.length > 0 && (
              <>
                <div className="rounded-lg border border-gray-200">
                  {renderRows(extractions, conflicts, handleResolve)}
                </div>
                <div className="flex justify-end">
                  <DownloadReportButton reportTitle={displayQuery} extractions={extractions} conflicts={conflicts} />
                </div>
              </>
            )}
            {extractions.length === 0 && conflicts.length === 0 && missingFields.length === 0 && (
              <p className="text-sm text-gray-400">No extractions found for this query.</p>
            )}
            {missingFields.length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50/40 p-3 space-y-1">
                <p className="text-xs font-medium text-amber-800">Not found in the uploaded files:</p>
                {missingFields.map((mf) => (
                  <div key={mf.field_name} className="flex items-baseline gap-2 text-sm">
                    <span className="font-medium text-gray-800">{mf.field_name}</span>
                    <span className="text-xs text-gray-500">{mf.reason}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function renderRows(extractions: ExtractionOut[], conflicts: ConflictOut[], onResolve: (id: string) => void) {
  return groupExtractions(extractions, conflicts).map(({ extraction, conflict, logic }) => (
    <ExtractionResultCard
      key={extraction.id}
      extraction={extraction}
      conflict={conflict}
      onResolve={onResolve}
      logic={logic}
    />
  ));
}
