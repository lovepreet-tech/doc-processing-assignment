import { useEffect, useState } from "react";
import { fileContentUrl, getFileStatus, subscribeToFileProgress } from "../api/client";
import ProgressStepper from "./ProgressStepper";

const INGESTION_STEPS = [
  "queued",
  "parsing_blocks",
  "building_formula_graph",
  "embedding_chunks",
  "persisting",
  "ready",
];

interface FileAttachmentCardProps {
  batchId: string;
  fileId: string;
  filename: string;
}

// one card per uploaded file, live-updating as the ingestion pipeline moves
// through each step (consumes the SSE stream from progress/events.py)
export default function FileAttachmentCard({ batchId, fileId, filename }: FileAttachmentCardProps) {
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  // "checking" until the initial status check resolves, so the card doesn't
  // flash "ingesting" before settling on its real state
  const [status, setStatus] = useState<"checking" | "running" | "done" | "failed">("checking");

  // resolves the file's real status on mount, so reopening a session doesn't
  // show every card as "running" until the next SSE/poll tick
  useEffect(() => {
    getFileStatus(batchId, fileId)
      .then((file) => {
        if (file.status === "PARSED" || file.status === "REUSED") setStatus("done");
        else if (file.status === "FAILED") setStatus("failed");
        else setStatus("running");
      })
      .catch(() => setStatus("running"));
  }, [batchId, fileId]);

  useEffect(() => {
    const es = subscribeToFileProgress(batchId, fileId, (raw) => {
      const event = JSON.parse(raw);
      setCurrentStep(event.step);
      if (event.status === "done" && event.step === "ready") setStatus("done");
      if (event.status === "failed") setStatus("failed");
      // closes the stream explicitly on a terminal status, since EventSource
      // otherwise treats the backend ending it as a dropped connection and retries
      if (event.status === "done" || event.status === "failed") es.close();
    });
    return () => es.close();
  }, [batchId, fileId]);

  return (
    <div className="flex items-center gap-2.5 rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-sm">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-gray-50 text-gray-400">
        <svg viewBox="0 0 24 24" fill="none" className="h-3.5 w-3.5">
          <path
            d="M6 2.5h8l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 20V4A1.5 1.5 0 0 1 5.5 2.5H6Z"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
          <path d="M14 2.5V6a1 1 0 0 0 1 1h3.5" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        </svg>
      </span>
      <a
        href={fileContentUrl(batchId, fileId)}
        target="_blank"
        rel="noopener noreferrer"
        title={`Open ${filename} in a new tab`}
        className="min-w-0 flex-1 truncate text-sm font-medium text-gray-900 hover:text-blue-600 hover:underline"
      >
        {filename}
      </a>
      {(status === "running" || status === "failed") && (
        <div className="w-40 shrink-0">
          <ProgressStepper steps={INGESTION_STEPS} currentStep={currentStep} status={status} />
        </div>
      )}
      {status === "checking" && <span className="shrink-0 text-xs text-gray-400">Checking…</span>}
      {status === "done" && (
        <span className="shrink-0 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
          Ready
        </span>
      )}
    </div>
  );
}
