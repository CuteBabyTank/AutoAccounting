"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Spinner } from "@phosphor-icons/react";
import { extractApi } from "@/lib/extract-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import { when } from "@/components/extract/RunHistory";
import type { ExtractFileStatus, ExtractRun } from "@/types/extract";

const POLL_MS = 2000;
const FILE_STATUS: Record<ExtractFileStatus, string> = {
  queued: "Waiting",
  detecting: "Finding the format",
  reading: "Reading",
  choose: "Pick a format",
  done: "Done",
  error: "Couldn't read",
};

interface Props {
  runId: string;
  onBack: () => void;
  /** The run finished reading (Past extracts' counts changed). */
  onChanged: () => void;
}

/** Placeholder for the run screen (records table, review, Excel); the run-table task replaces this file. */
export default function RunTable({ runId, onBack, onChanged }: Props) {
  const [run, setRun] = useState<ExtractRun | null>(null);
  const [error, setError] = useState("");
  const changed = useRef(onChanged);
  useEffect(() => {
    changed.current = onChanged;
  });

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let wasReading = false;
    const load = () =>
      extractApi
        .run(runId)
        .then((r) => {
          if (!alive) return;
          setRun(r);
          setError("");
          if (r.status === "reading") {
            wasReading = true;
            timer = setTimeout(load, POLL_MS);
          } else if (wasReading) {
            changed.current();
          }
        })
        .catch((e) => alive && setError(apiErrorMessage(e, "Couldn't open this extract")));
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [runId]);

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
        >
          <ArrowLeft size={14} /> Past extracts
        </button>
        {run && (
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-semibold text-[var(--text-primary)]">{run.format_name}</h2>
            <p className="text-xs text-[var(--text-secondary)]">
              {run.created_by_name || "Someone"} · {when(run.created_at)}
            </p>
          </div>
        )}
        {run?.status === "reading" && (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-[var(--text-secondary)]">
            <Spinner size={12} className="animate-spin" /> Reading
          </span>
        )}
        {run?.status === "failed" && (
          <span className="rounded-full bg-[var(--badge-red-bg)] px-2 py-0.5 text-xs font-medium text-[var(--badge-red-text)]">Failed</span>
        )}
      </div>
      {error && <p className="text-sm text-[var(--alert-error-text)]">{error}</p>}
      {!run && !error && (
        <p className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
          <Spinner size={14} className="animate-spin" /> Loading
        </p>
      )}
      {run && (
        <>
          {run.formats.length > 0 && (
            <ul className="mb-3 flex flex-wrap gap-2">
              {run.formats.map((f) => (
                <li key={f.format_key} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--text-secondary)]">
                  <span className="font-medium text-[var(--text-primary)]">{f.name}</span> · {f.records} records
                  {f.red > 0 && <span className="text-[var(--badge-red-text)]"> · {f.red} red</span>}
                  {f.yellow > 0 && <span className="text-[var(--badge-yellow-text)]"> · {f.yellow} yellow</span>}
                </li>
              ))}
            </ul>
          )}
          <ul className="divide-y divide-[var(--border)] rounded-lg border border-[var(--border)]">
            {run.files.map((f) => (
              <li key={f.id} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-2 text-sm">
                <span className="min-w-0 flex-1 truncate text-[var(--text-primary)]">{f.name}</span>
                <span className={`text-xs ${f.status === "error" ? "text-[var(--alert-error-text)]" : "text-[var(--text-secondary)]"}`}>
                  {f.status === "error" && f.error ? f.error : FILE_STATUS[f.status]}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
