import { useRef, useState } from "react";

interface ComposerProps {
  onSubmit: (files: File[], query: string) => void;
  disabled?: boolean;
}

// bottom chat composer - one input handles both attaching files and asking a question
export default function Composer({ onSubmit, disabled }: ComposerProps) {
  const [query, setQuery] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleSubmit() {
    if (!query.trim() && files.length === 0) return;
    onSubmit(files, query);
    setQuery("");
    setFiles([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  return (
    <div className="border-t border-gray-200 p-4 bg-white">
      {files.length > 0 && (
        <div className="flex gap-2 mb-2 flex-wrap">
          {files.map((f, i) => (
            <span
              key={i}
              className="flex items-center gap-1 text-xs bg-gray-100 rounded-full px-3 py-1"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                className="w-3 h-3 flex-shrink-0"
              >
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
              </svg>
              {f.name}
            </span>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          className="rounded-md border border-gray-300 p-2 text-sm hover:bg-gray-50"
          disabled={disabled}
          aria-label="Attach files"
          title="Attach files"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="w-4 h-4"
          >
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
          </svg>
        </button>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          placeholder="Ask about this batch, or just attach files to ingest them..."
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm"
          disabled={disabled}
        />
        <button
          onClick={handleSubmit}
          className="rounded-md bg-blue-600 text-white px-4 py-2 text-sm hover:bg-blue-700"
          disabled={disabled}
        >
          Send
        </button>
      </div>
    </div>
  );
}
