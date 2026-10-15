"use client";

import { useEffect, useState } from "react";
import { accountingApi } from "@/lib/accounting-api";
import type { AlphalistStatus } from "@/types/accounting";

interface Props {
  onOpen: (companyId: string, year: number) => void;
}

const LABEL: Record<AlphalistStatus["status"], string> = {
  ready: "Ready",
  needs_review: "Needs review",
  no_payroll: "No payroll imported",
};

// Year-end season: until February the alphalist being prepared is last year's.
function defaultYear(): number {
  const now = new Date();
  return now.getMonth() <= 1 ? now.getFullYear() - 1 : now.getFullYear();
}

/** Every client with employees and whether its 1604-C alphalist and 2316s are ready (due January 31). */
export default function AlphalistChecklist({ onOpen }: Props) {
  const [year, setYear] = useState(defaultYear);
  const [rows, setRows] = useState<AlphalistStatus[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    accountingApi.alphalistStatus(year).then((r) => { if (!cancelled) setRows(r); }).catch(() => { if (!cancelled) setRows([]); });
    return () => { cancelled = true; };
  }, [year]);

  if (!rows || rows.length === 0) return null;
  const ready = rows.filter((r) => r.status === "ready").length;

  return (
    <section className="mt-4 rounded-xl border border-[var(--border)] p-4 text-left">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">1604-C alphalists · {year}</h3>
        <span className="text-xs text-[var(--text-secondary)]">{ready} of {rows.length} ready · due Jan 31, {year + 1}</span>
        <div className="ml-auto flex gap-1">
          <button className="rounded-md border border-[var(--border)] px-2 text-xs" aria-label="Previous year" onClick={() => setYear((y) => y - 1)}>‹</button>
          <button className="rounded-md border border-[var(--border)] px-2 text-xs" aria-label="Next year" onClick={() => setYear((y) => y + 1)}>›</button>
        </div>
      </div>
      <ul className="divide-y divide-[var(--border)]">
        {rows.map((r) => (
          <li key={r.company_id}>
            <button className="flex w-full items-center gap-3 py-1.5 text-left text-sm hover:bg-[var(--bg-hover)]" onClick={() => onOpen(r.company_id, year)}>
              <span className="min-w-0 flex-1 truncate text-[var(--text-primary)]">{r.company}</span>
              <span className="text-xs tabular-nums text-[var(--text-secondary)]">{r.employees} employees</span>
              <span className={`w-36 text-right text-xs ${r.status === "ready" ? "text-[var(--text-secondary)]" : "text-[var(--alert-warning-text)]"}`}>
                {LABEL[r.status]}{r.issues ? ` (${r.issues})` : ""}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
