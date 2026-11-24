import type { MouseEvent } from "react";
import type { SessionOut } from "../api/client";

interface SidebarProps {
  sessions: SessionOut[];
  activeSessionId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
}

// left-hand session list
export default function Sidebar({ sessions, activeSessionId, onSelect, onCreate, onDelete }: SidebarProps) {
  function handleDelete(e: MouseEvent, session: SessionOut) {
    e.stopPropagation(); // don't also trigger onSelect on the row underneath
    if (window.confirm(`Delete "${session.name ?? "Untitled session"}"? This can't be undone.`)) {
      onDelete(session.id);
    }
  }

  return (
    <aside className="w-64 bg-gray-900 text-gray-100 flex flex-col h-screen">
      <div className="p-3">
        <button
          onClick={onCreate}
          className="w-full rounded-md border border-gray-700 px-3 py-2 text-sm hover:bg-gray-800"
        >
          + New session
        </button>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 space-y-1">
        {sessions.map((session) => (
          <div
            key={session.id}
            className={`group flex items-center rounded-md hover:bg-gray-800 ${
              session.id === activeSessionId ? "bg-gray-800" : ""
            }`}
          >
            <button
              onClick={() => onSelect(session.id)}
              className="flex-1 min-w-0 text-left truncate px-3 py-2 text-sm"
            >
              {session.name ?? "Untitled session"}
            </button>
            <button
              onClick={(e) => handleDelete(e, session)}
              title="Delete session"
              aria-label="Delete session"
              className="shrink-0 px-2 py-2 text-gray-500 opacity-0 group-hover:opacity-100 hover:text-red-400"
            >
              ×
            </button>
          </div>
        ))}
      </nav>
    </aside>
  );
}
