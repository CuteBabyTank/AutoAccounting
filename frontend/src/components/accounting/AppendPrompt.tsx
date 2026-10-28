"use client";

import { useState } from "react";
import { CheckCircle, X } from "@phosphor-icons/react";
import { CHANGED_STYLE, apiErrorMessage } from "@/lib/accounting-format";
import type { AffectedPeriod } from "@/types/accounting";

interface Props {
  periods: AffectedPeriod[];
  onGenerate: (period: AffectedPeriod) => Promise<void>;
  onReview: (period: AffectedPeriod) => void;
  onClose: () => void;
}

const keyOf = (p: AffectedPeriod) => `${p.company_id}:${p.year}:${p.quarter}`;

export default function AppendPrompt({ periods, onGenerate, onReview, onClose }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");

  async function add(p: AffectedPeriod) {
    setBusy(keyOf(p));
    setError("");
    try {
      await onGenerate(p);
      setDone((prev) => new Set(prev).add(keyOf(p)));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't create the new version"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-xl rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">Add to an existing quarter?</h2>
          <button onClick={onClose} className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="space-y-4">
          {periods.map((p) => {
            const next = p.latest_version + 1;
            const finished = done.has(keyOf(p));
            return (
              <div key={keyOf(p)} className="rounded-xl border border-[var(--border)] p-4 text-sm text-[var(--text-primary)]">
                <p className="font-semibold">Add to {p.company_name}, {p.label}?</p>
                <p className="mt-1">
                  This quarter already has output <strong>v{p.latest_version}</strong>. {p.new_documents} new document
                  {p.new_documents === 1 ? "" : "s"} will be <strong>added to v{p.latest_version}</strong> and saved as{" "}
                  <strong>v{next}</strong>. Changed values will be <span className="rounded px-1" style={CHANGED_STYLE}>highlighted in yellow</span>.
                </p>
                {p.filed && (
                  <p className="mt-2 rounded-lg border border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)] px-3 py-2 text-[var(--alert-warning-text)]">
                    {p.label} was marked filed. Any filed form whose figures change in v{next} becomes an amended return (the Amended Return box is ticked).
                  </p>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  {finished ? (
                    <span className="flex items-center gap-1.5 font-medium text-[var(--accent)]">
                      <CheckCircle size={16} weight="fill" /> Saved as v{next}
                    </span>
                  ) : (
                    <>
                      <button
                        className="rounded-lg bg-[var(--accent)] px-3 py-1.5 font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60"
                        disabled={busy !== null}
                        onClick={() => add(p)}
                      >
                        {busy === keyOf(p) ? "Creating…" : `Add and create v${next}`}
                      </button>
                      <button
                        className="rounded-lg border border-[var(--border)] px-3 py-1.5 font-medium hover:bg-[var(--bg-hover)]"
                        onClick={() => onReview(p)}
                      >
                        Review files first
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
        {error && <p className="mt-3 text-sm text-[var(--alert-error-text)]">{error}</p>}
        <div className="mt-5 flex justify-end">
          <button className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]" onClick={onClose}>
            {done.size === periods.length ? "Done" : "Cancel"}
          </button>
        </div>
      </div>
    </div>
  );
}
