"use client";

import { useState } from "react";
import { BookOpen } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { Company, TreeCompany } from "@/types/accounting";

interface Props {
  company: Company;
  tree: TreeCompany | undefined;
  canManage: boolean;
  /** Called with the start date as people read it, e.g. "Jul 1, 2026". */
  onTurnedOn: (booksStart: string) => void;
}

const iso = (y: number, m: number) => `${y}-${String(m).padStart(2, "0")}-01`;

/** First day of a fiscal quarter. Fiscal year Y ends in its year-end month of calendar year Y. */
function quarterStart(year: number, quarter: number, fyEnd: number): string {
  const months = (fyEnd % 12) + 3 * (quarter - 1); // months after January of the year the fiscal year starts in
  const startYear = fyEnd === 12 ? year : year - 1;
  return iso(startYear + Math.floor(months / 12), (months % 12) + 1);
}

/** The start of the first quarter with documents, else the start of this fiscal year. */
function suggestedStart(tree: TreeCompany | undefined, fyEnd: number): { date: string; why: string } {
  const quarters = (tree?.years ?? []).flatMap((y) => y.quarters).filter((q) => q.document_count > 0);
  const first = quarters.sort((a, b) => a.year - b.year || a.quarter - b.quarter)[0];
  if (first) return { date: quarterStart(first.year, first.quarter, fyEnd), why: `the start of ${first.label} ${first.year}, its first quarter with documents` };
  const now = new Date();
  const year = now.getMonth() + 1 <= fyEnd ? now.getFullYear() : now.getFullYear() + 1;
  return { date: quarterStart(year, 1, fyEnd), why: "the start of this fiscal year" };
}

const longDate = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" });

/** Company Overview, returns-only clients: says the books are off and turns them on with a start date. */
export default function BooksOffCard({ company, tree, canManage, onTurnedOn }: Props) {
  const suggestion = suggestedStart(tree, company.fiscal_year_end_month);
  // follows the suggestion (the folder list can load after this) until someone picks a date
  const [picked, setDate] = useState<string | null>(null);
  const date = picked ?? suggestion.date;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function turnOn() {
    if (!date) return;
    setBusy(true);
    setError("");
    try {
      await accountingApi.updateCompany(company.id, { ...company, books_start: date });
      onTurnedOn(longDate(date));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't turn on the books"));
      setBusy(false);
    }
  }

  return (
    <div data-tour="books-off" className="mb-6 rounded-xl border border-dashed border-[var(--border)] p-4">
      <div className="flex items-start gap-3">
        <BookOpen size={20} className="mt-0.5 shrink-0 text-[var(--text-secondary)]" />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Books are off for this client</h3>
          <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
            We only prepare their BIR returns. Turn on books to also keep their journals, ledger, trial balance and
            financial statements, and to get Reports, Reclassify and Import.
          </p>
          {canManage ? (
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <label className="text-xs text-[var(--text-secondary)]">
                <span className="mb-1 block">Start the books on</span>
                <input
                  type="date"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                  className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-2.5 py-1.5 text-sm text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                />
              </label>
              <button
                type="button"
                onClick={turnOn}
                disabled={busy || !date}
                className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
              >
                {busy ? "Turning on…" : "Turn on books"}
              </button>
              <p className="w-full text-[11px] text-[var(--text-secondary)]">
                {date === suggestion.date
                  ? `${longDate(suggestion.date)} is ${suggestion.why}.`
                  : "Documents dated before this stay out of the books."}{" "}
                You&apos;ll enter the opening balances as of this date next. You can change it later under Edit company.
              </p>
            </div>
          ) : (
            <p className="mt-2 text-xs text-[var(--text-secondary)]">Ask a manager or the firm owner to turn them on.</p>
          )}
          {error && <p className="mt-2 text-xs text-[var(--alert-error-text)]">{error}</p>}
        </div>
      </div>
    </div>
  );
}
