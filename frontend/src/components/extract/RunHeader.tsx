"use client";

import { ArrowLeft, Spinner } from "@phosphor-icons/react";
import PrivacyToggle from "@/components/accounting/PrivacyToggle";
import { when } from "@/components/extract/RunHistory";
import { FlagMark } from "@/components/extract/FlagMark";
import { plural } from "@/lib/extract-flags";
import type { ExtractFormatCount, ExtractRun } from "@/types/extract";

interface Props {
  run: ExtractRun | null;
  /** The run's formats that have records (their counts add up to the run's). */
  formats: ExtractFormatCount[];
  reviewOnly: boolean;
  onFilter: (reviewOnly: boolean) => void;
  onBack: () => void;
}

/** The run screen's top strip: back, format, who and when, counts, the All / Needs review filter, Hide amounts. */
export default function RunHeader({ run, formats, reviewOnly, onFilter, onBack }: Props) {
  const totals = formats.reduce((t, f) => ({ n: t.n + f.records, red: t.red + f.red, yellow: t.yellow + f.yellow }), { n: 0, red: 0, yellow: 0 });
  return (
    <section className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-3">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
      >
        <ArrowLeft size={14} /> Past extracts
      </button>
      {run ? (
        <div className="min-w-0 flex-1 basis-48">
          <h2 className="flex items-center gap-2 truncate text-base font-semibold text-[var(--text-primary)]">
            <span className="truncate">{run.format_name}</span>
            {run.status === "reading" && (
              <span className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-[var(--text-secondary)]">
                <Spinner size={12} className="animate-spin" /> Reading
              </span>
            )}
            {run.status === "failed" && (
              <span className="shrink-0 rounded-full bg-[var(--badge-red-bg)] px-2 py-0.5 text-xs font-medium text-[var(--badge-red-text)]">Failed</span>
            )}
          </h2>
          <p className="flex flex-wrap items-center gap-x-2 text-xs text-[var(--text-secondary)]">
            <span>{run.created_by_name || "Someone"} · {when(run.created_at)}</span>
            <span>· {plural(totals.n, "record")}</span>
            {totals.red + totals.yellow > 0 && (
              <>
                <span>· {totals.red + totals.yellow} need review</span>
                {totals.red > 0 && <span className="inline-flex items-center gap-1"><FlagMark level="red" /> {totals.red} red</span>}
                {totals.yellow > 0 && <span className="inline-flex items-center gap-1"><FlagMark level="yellow" /> {totals.yellow} yellow</span>}
              </>
            )}
          </p>
        </div>
      ) : (
        <span className="flex-1" />
      )}
      <div role="group" aria-label="Show" className="inline-flex rounded-lg border border-[var(--border)] p-0.5 text-sm">
        {([["All", false], ["Needs review", true]] as const).map(([label, on]) => (
          <button
            key={label}
            type="button"
            aria-pressed={reviewOnly === on}
            onClick={() => onFilter(on)}
            className={`rounded-md px-3 py-1 font-medium ${reviewOnly === on ? "bg-[var(--accent-subtle)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}
          >
            {label}
          </button>
        ))}
      </div>
      <PrivacyToggle />
    </section>
  );
}
