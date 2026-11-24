import { useEffect, useRef, useState } from "react";
import {
  createBatch,
  createSession,
  deleteSession,
  getFileStatus,
  listBatches,
  listExtractionJobs,
  listFiles,
  listSessions,
  submitExtraction,
  uploadFiles,
  type FileOut,
  type SessionOut,
} from "./api/client";
import Composer from "./components/Composer";
import ExtractionTurn from "./components/ExtractionTurn";
import FileAttachmentCard from "./components/FileAttachmentCard";
import Sidebar from "./components/Sidebar";

const TERMINAL_FILE_STATUSES = ["PARSED", "REUSED", "FAILED"];

// URL shape: /s/{sessionId} for an existing session, / for a fresh draft
function sessionIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/s\/([^/]+)/);
  return match ? match[1] : null;
}

const MAX_TITLE_LENGTH = 60;

function truncate(text: string): string {
  return text.length > MAX_TITLE_LENGTH
    ? `${text.slice(0, MAX_TITLE_LENGTH - 1)}…`
    : text;
}

// title is the typed query if there was one, otherwise the attached filename(s)
function deriveSessionTitle(files: File[], query: string): string {
  if (query.trim()) return truncate(query.trim());
  return truncate(files.map((f) => f.name).join(", "));
}

function pushSessionUrl(sessionId: string) {
  window.history.pushState({}, "", `/s/${sessionId}`);
}

export default function App() {
  const [sessions, setSessions] = useState<SessionOut[]>([]);
  // null = landing on a fresh draft session with no id yet
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() =>
    sessionIdFromPath(window.location.pathname),
  );
  // one batch per session, created lazily the first time you touch a session
  const [batchIdBySession, setBatchIdBySession] = useState<
    Record<string, string>
  >({});
  const [filesByBatch, setFilesByBatch] = useState<Record<string, FileOut[]>>(
    {},
  );
  // extraction turns keyed by batch, in submission order. displayQuery is the
  // chat-bubble label shown to the user, which may differ from the actual query sent
  const [turnsByBatch, setTurnsByBatch] = useState<
    Record<string, { jobId: string; displayQuery: string }[]>
  >({});

  useEffect(() => {
    listSessions().then(setSessions).catch(console.error);
  }, []);

  // pins the chat log to the bottom as messages/content grow, unless the user has
  // scrolled up, in which case a "new message" button is shown instead
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const [showScrollButton, setShowScrollButton] = useState(false);

  const NEAR_BOTTOM_THRESHOLD = 48;

  function isNearBottom(el: HTMLDivElement): boolean {
    return (
      el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_THRESHOLD
    );
  }

  function scrollToBottom() {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
    atBottomRef.current = true;
    setShowScrollButton(false);
  }

  function handleScroll() {
    const container = scrollContainerRef.current;
    if (!container) return;
    const atBottom = isNearBottom(container);
    atBottomRef.current = atBottom;
    if (atBottom) setShowScrollButton(false);
  }

  useEffect(() => {
    const messages = messagesRef.current;
    if (!messages) return;
    scrollToBottom();
    const observer = new ResizeObserver(() => {
      if (atBottomRef.current) {
        scrollToBottom();
      } else {
        setShowScrollButton(true);
      }
    });
    observer.observe(messages);
    return () => observer.disconnect();
  }, [activeSessionId]);

  useEffect(() => {
    const onPopState = () =>
      setActiveSessionId(sessionIdFromPath(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  // loads a session's history from the backend when it becomes active and isn't
  // already in memory
  useEffect(() => {
    if (!activeSessionId || batchIdBySession[activeSessionId]) return;
    const sessionId = activeSessionId;

    listBatches(sessionId)
      .then(async (batches) => {
        const batch = batches[batches.length - 1];
        if (!batch) return;

        setBatchIdBySession((prev) => ({ ...prev, [sessionId]: batch.id }));

        const [files, jobs] = await Promise.all([
          listFiles(batch.id),
          listExtractionJobs(batch.id),
        ]);
        setFilesByBatch((prev) => ({ ...prev, [batch.id]: files }));
        setTurnsByBatch((prev) => ({
          ...prev,
          [batch.id]: jobs.map((job) => ({
            jobId: job.id,
            displayQuery: job.query?.trim()
              ? job.query
              : "Reviewing uploaded files...",
          })),
        }));
      })
      .catch(console.error);
  }, [activeSessionId, batchIdBySession]);

  function selectSession(id: string) {
    pushSessionUrl(id);
    setActiveSessionId(id);
  }

  // no session is created until something is actually submitted in the draft
  function startNewDraft() {
    window.history.pushState({}, "", "/");
    setActiveSessionId(null);
  }

  async function handleDeleteSession(id: string) {
    try {
      await deleteSession(id);
    } catch (err) {
      console.error("failed to delete session", err);
      window.alert("Couldn't delete this session. Please try again.");
      return;
    }
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (activeSessionId === id) {
      startNewDraft();
    }
  }

  async function getOrCreateBatchId(sessionId: string): Promise<string> {
    if (batchIdBySession[sessionId]) return batchIdBySession[sessionId];
    const batch = await createBatch(sessionId);
    setBatchIdBySession((prev) => ({ ...prev, [sessionId]: batch.id }));
    return batch.id;
  }

  function addTurn(batchId: string, jobId: string, displayQuery: string) {
    setTurnsByBatch((prev) => ({
      ...prev,
      [batchId]: [...(prev[batchId] ?? []), { jobId, displayQuery }],
    }));
  }

  async function submitQuery(
    batchId: string,
    query: string,
    displayQuery: string,
    force = false,
  ) {
    const { job_id } = await submitExtraction(batchId, query, force);
    addTurn(batchId, job_id, displayQuery);
  }

  // broad query for the automatic post-upload pass, covering every data/logic
  // field the system knows how to extract
  const COMPREHENSIVE_EXTRACTION_QUERY =
    "Extract all client information, property details, and valuation information " +
    "(client name, property address, property area, valuation date, methodology, " +
    "assessed value), and the underlying logic, formulas, assumptions, and " +
    "methodology behind any values or model outputs in these files.";

  // polls until every just-uploaded file has finished ingestion, then kicks off a
  // forced comprehensive extraction
  async function reviewFilesOnceIngested(batchId: string, fileIds: string[]) {
    while (true) {
      const statuses = await Promise.all(
        fileIds.map((id) => getFileStatus(batchId, id).catch(() => null)),
      );
      if (statuses.every((f) => f && TERMINAL_FILE_STATUSES.includes(f.status)))
        break;
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    await submitQuery(
      batchId,
      COMPREHENSIVE_EXTRACTION_QUERY,
      "Reviewing uploaded files...",
      true,
    );
  }

  async function handleComposerSubmit(files: File[], query: string) {
    // draft session: create the real session now and move the URL to /s/{id}
    let sessionId = activeSessionId;
    if (!sessionId) {
      const session = await createSession(deriveSessionTitle(files, query));
      setSessions((prev) => [session, ...prev]);
      sessionId = session.id;
      pushSessionUrl(sessionId);
      setActiveSessionId(sessionId);
    }

    const batchId = await getOrCreateBatchId(sessionId);

    if (files.length > 0) {
      const uploaded = await uploadFiles(batchId, files);
      setFilesByBatch((prev) => ({
        ...prev,
        [batchId]: [...(prev[batchId] ?? []), ...uploaded],
      }));

      if (!query.trim()) {
        reviewFilesOnceIngested(
          batchId,
          uploaded.map((f) => f.id),
        ).catch(console.error);
      }
    }

    if (query.trim()) {
      await submitQuery(batchId, query, query);
    }
  }

  function handleFollowUp(batchId: string, suggestion: string) {
    submitQuery(batchId, suggestion, suggestion).catch(console.error);
  }

  const activeBatchId = activeSessionId
    ? batchIdBySession[activeSessionId]
    : null;
  const activeFiles = activeBatchId ? (filesByBatch[activeBatchId] ?? []) : [];
  const activeTurns = activeBatchId ? (turnsByBatch[activeBatchId] ?? []) : [];

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelect={selectSession}
        onCreate={startNewDraft}
        onDelete={handleDeleteSession}
      />
      <main className="flex-1 min-w-0 flex flex-col relative">
        <div
          ref={scrollContainerRef}
          onScroll={handleScroll}
          className="flex-1 min-w-0 overflow-y-auto overflow-x-hidden p-4"
        >
          <div ref={messagesRef} className="space-y-3">
            {activeFiles.map((file) => (
              <FileAttachmentCard
                key={file.id}
                batchId={file.batch_id}
                fileId={file.id}
                filename={file.original_filename}
              />
            ))}
            {activeFiles.length === 0 && (
              <p className="text-sm text-gray-400">
                Attach files or ask a question below to start this session.
              </p>
            )}
            {activeBatchId &&
              activeTurns.map((turn) => (
                <ExtractionTurn
                  key={turn.jobId}
                  jobId={turn.jobId}
                  batchId={activeBatchId}
                  displayQuery={turn.displayQuery}
                  onFollowUp={(q) => handleFollowUp(activeBatchId, q)}
                />
              ))}
          </div>
        </div>
        {showScrollButton && (
          <button
            onClick={scrollToBottom}
            className="absolute bottom-20 left-1/2 -translate-x-1/2 rounded-full bg-gray-900 text-white text-xs font-medium px-4 py-2 shadow-lg hover:bg-gray-700"
          >
            New message ↓
          </button>
        )}
        <Composer onSubmit={handleComposerSubmit} />
      </main>
    </div>
  );
}
