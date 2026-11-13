"use client";

import { useEffect } from "react";
import type { ExtractFormat } from "@/types/extract";

interface Props {
  mode: "new" | "edit";
  format?: ExtractFormat;
  onClose: () => void;
  onSaved: (format: ExtractFormat) => void;
}

/** Placeholder for the format builder (dropped sample → fields and checks); the builder task replaces this file. */
export default function FormatBuilder({ mode, format, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="extract-builder-title"
        onClick={(e) => e.stopPropagation()}
        className="page-enter w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-5 shadow-2xl"
      >
        <h2 id="extract-builder-title" className="text-base font-semibold text-[var(--text-primary)]">
          {mode === "edit" && format ? `Edit ${format.name}` : "Add a format"}
        </h2>
        <p className="mt-1.5 text-sm leading-relaxed text-[var(--text-secondary)]">The format builder is coming soon.</p>
        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
