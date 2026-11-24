import type { ConflictOut, ExtractionOut } from "../api/client";
import { buildReportHtml, downloadTextFile, printReportHtml } from "../lib/downloadReport";

interface DownloadReportButtonProps {
  reportTitle: string;
  extractions: ExtractionOut[];
  conflicts: ConflictOut[];
}

const ICON_BUTTON_CLASS =
  "flex h-6 w-6 items-center justify-center rounded-md border border-gray-300 text-gray-500 hover:bg-gray-50";

// Two small icon-only actions for this one answer's extraction results, both
// with every row/section already expanded rather than whatever is currently
// toggled open on screen. Built entirely from data this turn already has in
// memory, so neither needs an extra API call.
export default function DownloadReportButton({ reportTitle, extractions, conflicts }: DownloadReportButtonProps) {
  function handleDownload() {
    const html = buildReportHtml(reportTitle, extractions, conflicts);
    const filename = `${reportTitle.trim().replace(/[^a-z0-9]+/gi, "_").slice(0, 60) || "extraction_report"}.html`;
    downloadTextFile(filename, html, "text/html");
  }

  function handlePrint() {
    const html = buildReportHtml(reportTitle, extractions, conflicts);
    printReportHtml(html);
  }

  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={handlePrint}
        title="Print this answer's full report (save as PDF)"
        aria-label="Print this answer's full report"
        className={ICON_BUTTON_CLASS}
      >
        <svg viewBox="0 0 24 24" fill="none" className="h-3 w-3 shrink-0">
          <path
            d="M6 9V4h12v5M6 18H4a1 1 0 0 1-1-1v-5a1 1 0 0 1 1-1h16a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1h-2M6 14h12v6H6z"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      <button
        onClick={handleDownload}
        title="Download this answer's full report"
        aria-label="Download this answer's full report"
        className={ICON_BUTTON_CLASS}
      >
        <svg viewBox="0 0 24 24" fill="none" className="h-3 w-3 shrink-0">
          <path
            d="M12 3v12m0 0l-4-4m4 4l4-4M5 19h14"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    </div>
  );
}
