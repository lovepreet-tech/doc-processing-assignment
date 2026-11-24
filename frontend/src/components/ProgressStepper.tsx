interface ProgressStepperProps {
  steps: string[];
  currentStep: string | null;
  status: "running" | "done" | "failed";
  detail?: string | null;
}

// compact single-row progress indicator: a thin bar plus the current step
export default function ProgressStepper({ steps, currentStep, status, detail }: ProgressStepperProps) {
  const currentIndex = currentStep ? steps.indexOf(currentStep) : -1;
  const lastIndex = steps.length - 1;
  const percent =
    status === "done"
      ? 100
      : currentIndex < 0
      ? 0
      : Math.round((currentIndex / Math.max(lastIndex, 1)) * 100);
  const label = (currentStep ?? steps[0]).replace(/_/g, " ");

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        {status === "failed" ? (
          <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full bg-red-100 text-[9px] font-bold text-red-600">
            ✕
          </span>
        ) : (
          <span className="h-2.5 w-2.5 shrink-0 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        )}
        <span
          className={`shrink-0 text-xs capitalize ${status === "failed" ? "font-medium text-red-700" : "font-medium text-blue-700"}`}
        >
          {label}
        </span>
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-gray-100">
          <div
            className={`h-full rounded-full transition-all duration-500 ${
              status === "failed" ? "bg-red-500" : "bg-blue-600"
            }`}
            style={{ width: `${percent}%` }}
          />
        </div>
        <span className="shrink-0 text-[10px] font-medium tabular-nums text-gray-400">
          {status === "done" ? steps.length : Math.max(currentIndex, 0) + 1}/{steps.length}
        </span>
      </div>
      {status === "running" && detail && <p className="pl-5 text-[11px] text-gray-400">{detail}</p>}
    </div>
  );
}
