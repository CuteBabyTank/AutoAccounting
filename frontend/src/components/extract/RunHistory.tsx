"use client";

import { Spinner, Trash } from "@phosphor-icons/react";
import type { ExtractRunSummary } from "@/types/extract";

export const when = (iso: string) => new Date(iso).toLocaleString("en-PH", { dateStyle: "medium", timeStyle: "short" });
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Newest first: `a` sorts after `b` (the server's order: created_at descending, then id). */
const after = (a: ExtractRunSummary, b: ExtractRunSummary) =>
  a.created_at < b.created_at || (a.created_at === b.created_at && a.id > b.id);

/** A fresh first page merged into the runs shown so far: the page replaces everything in its window (a run missing
 * from it was deleted), runs loaded by "Show more" past that window stay. */
export function mergeFirstPage(shown: ExtractRunSummary[], page: ExtractRunSummary[], limit: number): ExtractRunSummary[] {
  if (page.length < limit) return page; // the whole list fits on the first page
  const ids = new Set(page.map((r) => r.id));
  const last = page[page.length - 1];
  return [...page, ...shown.filter((r) => !ids.has(r.id) && after(r, last))];
}

/** The next page appended to the runs shown, each run once. */
export function appendPage(shown: ExtractRunSummary[], page: ExtractRunSummary[]): ExtractRunSummary[] {
  const ids = new Set(shown.map((r) => r.id));
  return [...shown, ...page.filter((r) => !ids.has(r.id))];
}

interface Props {
  runs: ExtractRunSummary[];
  /** How many runs the firm has; "Show more" shows while fewer are listed. */
  total: number;
  loaded: boolean;
  loadingMore: boolean;
  onMore: () => void;
  /** The signed-in person; a run's creator may delete it, as may owners and managers. */
  userId: string | null;
  canManage: boolean;
  onOpen: (id: string) => void;
  onDelete: (run: ExtractRunSummary) => void;
}

/** "Past extracts": the firm's runs, newest first, 50 at a time. */
export default function RunHistory({ runs, total, loaded, loadingMore, onMore, userId, canManage, onOpen, onDelete }: Props) {
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
      {loaded && runs.length < total && (
        <div className="border-t border-[var(--border)] px-4 py-3 text-center">
          <button
            type="button"
            onClick={onMore}
            disabled={loadingMore}
            className="inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60"
          >
            {loadingMore && <Spinner size={14} className="animate-spin" />}
            Show more ({total - runs.length} older)
          </button>
        </div>
      )}
    </section>
  );
}
