"use client";

import { Spinner, Trash } from "@phosphor-icons/react";
import type { ExtractRunSummary } from "@/types/extract";

export const when = (iso: string) => new Date(iso).toLocaleString("en-PH", { dateStyle: "medium", timeStyle: "short" });
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

interface Props {
  runs: ExtractRunSummary[];
  loaded: boolean;
  /** The signed-in person; a run's creator may delete it, as may owners and managers. */
  userId: string | null;
  canManage: boolean;
  onOpen: (id: string) => void;
  onDelete: (run: ExtractRunSummary) => void;
}

/** "Past extracts": the firm's latest runs, newest first. */
export default function RunHistory({ runs, loaded, userId, canManage, onOpen, onDelete }: Props) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)]">
      <h2 className="px-4 pb-2 pt-4 text-sm font-semibold text-[var(--text-primary)]">Past extracts</h2>
      {loaded && runs.length === 0 && (
        <p className="px-4 pb-8 pt-4 text-center text-sm text-[var(--text-secondary)]">
          Nothing extracted yet. Pick a format and drop a few files above to get started.
        </p>
      )}
      {!loaded && (
        <p className="flex items-center justify-center gap-2 px-4 pb-8 pt-4 text-sm text-[var(--text-secondary)]">
          <Spinner size={14} className="animate-spin" /> Loading
        </p>
      )}
      <ul>
        {runs.map((run) => {
          const mayDelete = canManage || (!!userId && run.created_by === userId);
          return (
            <li key={run.id} className="flex items-center gap-2 border-t border-[var(--border)] px-2 py-1">
              <button
                type="button"
                onClick={() => onOpen(run.id)}
                className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-2 py-2 text-left hover:bg-[var(--bg-hover)]"
              >
                <span className="min-w-0 flex-1 basis-48">
                  <span className="block truncate text-sm font-medium text-[var(--text-primary)]">{run.format_name}</span>
                  <span className="block text-xs text-[var(--text-secondary)]">
                    {plural(run.file_count, "file")} · {plural(run.record_count, "record")} ·{" "}
                    {run.created_by_name || "Someone"} · {when(run.created_at)}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-1.5 text-xs font-medium">
                  {run.status === "reading" && (
                    <span className="inline-flex items-center gap-1 text-[var(--text-secondary)]">
                      <Spinner size={12} className="animate-spin" /> Reading
                    </span>
                  )}
                  {run.status === "failed" && (
                    <span className="rounded-full bg-[var(--badge-red-bg)] px-2 py-0.5 text-[var(--badge-red-text)]">Failed</span>
                  )}
                  {run.red_count > 0 && (
                    <span className="rounded-full bg-[var(--badge-red-bg)] px-2 py-0.5 text-[var(--badge-red-text)]">
                      {run.red_count} red
                    </span>
                  )}
                  {run.yellow_count > 0 && (
                    <span className="rounded-full bg-[var(--badge-yellow-bg)] px-2 py-0.5 text-[var(--badge-yellow-text)]">
                      {run.yellow_count} yellow
                    </span>
                  )}
                </span>
              </button>
              {mayDelete && (
                <button
                  type="button"
                  onClick={() => onDelete(run)}
                  title="Delete this extract"
                  aria-label={`Delete the ${run.format_name} extract from ${when(run.created_at)}`}
                  className="shrink-0 rounded-lg p-2 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--badge-red-text)]"
                >
                  <Trash size={16} />
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
