"use client";

import { useCallback, useEffect, useState } from "react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import { useFilePreview } from "@/components/accounting/PdfPreview";
import { FeatureOff, useFeatures } from "@/lib/features";
import type { BooksYear } from "@/types/accounting";
import QuickPicks from "@/components/QuickPicks";
import { PRESETS } from "@/lib/quick-picks";

interface Props {
  companyId: string;
  year: number;
  canManage: boolean;
  onChanged: () => void;
}

const BTN = "rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50";
const monthName = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-PH", { month: "short", year: "numeric" });

// Closing a month freezes its entries, gives them final numbers and prints its loose-leaf pages; binding the year
// adds covers and the sworn declaration once every month is closed.
export default function BookMonths({ companyId, year, canManage: canManageBooks, onChanged }: Props) {
  // Month close can be switched off for maintenance; the books stay readable.
  const closeOn = useFeatures().on("close");
  const canManage = canManageBooks && closeOn;
  const [data, setData] = useState<BooksYear | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [confirmReopen, setConfirmReopen] = useState(false);
  const [reopenReason, setReopenReason] = useState("");
  // A month whose bank statement isn't reconciled can still close, with a reason for the audit log.
  const [bankBlock, setBankBlock] = useState<{ month: string; message: string } | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  // Months before the books started have nothing to show; folded away unless asked for.
  const [showBefore, setShowBefore] = useState(false);
  const file = useFilePreview();

  const load = useCallback(() => accountingApi.booksYear(companyId, year).then(setData), [companyId, year]);

  useEffect(() => {
    let cancelled = false;
    accountingApi.booksYear(companyId, year)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(apiErrorMessage(e, "Couldn't load the closed months")); });
    return () => { cancelled = true; };
  }, [companyId, year]);

  async function run(label: string, action: () => Promise<BooksYear>, month?: string) {
    setBusy(label);
    setError("");
    try {
      setData(await action());
      setConfirmReopen(false);
      setReopenReason("");
      setBankBlock(null);
      setOverrideReason("");
      onChanged();
    } catch (e) {
      const message = apiErrorMessage(e, "That didn't work");
      if (month && message.startsWith("bank_unreconciled:")) {
        setBankBlock({ month, message: message.replace(/^bank_unreconciled:\s*/, "") });
      } else {
        setError(message);
      }
      await load().catch(() => undefined);
    } finally {
      setBusy("");
    }
  }

  /** A book opens in the preview first; it downloads from there. */
  function download(book: string, monthStart?: string) {
    const label = book === "declaration" ? "Sworn declaration" : book;
    file.open(monthStart ? `${label} · ${monthStart.slice(0, 7)}` : `${label} · FY ${year}`,
      () => accountingApi.booksFile(companyId, year, book, monthStart),
      monthStart ? `${book} ${monthStart.slice(0, 7)}.pdf` : `${book} FY${year}.pdf`);
  }

  if (!data) return error ? <p className="mb-3 text-sm text-[var(--alert-error-text)]">{error}</p> : null;
  const nextOpen = data.months.find((m) => m.status === "open");
  const lastClosed = [...data.months].reverse().find((m) => m.status === "closed");
  const allClosed = data.months.every((m) => m.status !== "open") && Boolean(lastClosed);

  return (
    <section className="mb-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">Loose-leaf books</h3>
        <span className="text-xs text-[var(--text-secondary)]">
          {data.bound ? "Bound" : `Bind by ${data.bind_by}`} · months close in order; changes to a closed month post as corrections
        </span>
      </div>
      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {canManageBooks && !closeOn && <div className="mb-2"><FeatureOff label="Month close" compact /></div>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="text-left text-xs text-[var(--text-secondary)]">
              <th className="py-1 pr-3 font-medium">Month</th>
              <th className="py-1 pr-3 font-medium">Status</th>
              <th className="py-1 pr-3 font-medium">Pages</th>
              <th className="py-1 font-medium">PDFs</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]">
            {data.months.filter((m) => showBefore || m.status !== "before_books").map((m) => (
              <tr key={m.start}>
                <td className="py-1.5 pr-3 text-[var(--text-primary)]">{monthName(m.start)}</td>
                <td className="py-1.5 pr-3 text-[var(--text-secondary)]">
                  {m.status === "closed" ? "Closed" : m.status === "open" ? "Open" : "Before books"}
                </td>
                <td className="py-1.5 pr-3 text-xs tabular-nums text-[var(--text-secondary)]">
                  {Object.entries(m.pages).map(([b, [f, l]]) => `${b} ${f === l ? f : `${f}–${l}`}`).join(" · ")}
                </td>
                <td className="py-1.5">
                  <div className="flex flex-wrap gap-1">
                    {m.books.map((b) => (
                      <button key={b} className={BTN} onClick={() => download(b, m.start)}>{b}</button>
                    ))}
                    {canManage && !data.bound && m === nextOpen && (
                      <button className={BTN} disabled={Boolean(busy)}
                        onClick={() => run("close", () => accountingApi.closeBooksMonth(companyId, m.start), m.start)}>
                        {busy === "close" ? "Closing…" : "Close month"}
                      </button>
                    )}
                    {canManage && bankBlock?.month === m.start && (
                      <span className="flex w-full flex-wrap items-center gap-1">
                        <span className="text-xs text-[var(--alert-warning-text)]">{bankBlock.message}</span>
                        <input
                          aria-label="Why close without reconciling"
                          className="w-56 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                          maxLength={500}
                          placeholder="Reason (audit log, required)"
                          value={overrideReason}
                          onChange={(e) => setOverrideReason(e.target.value)}
                        />
                        <QuickPicks kind="close-reason" presets={PRESETS.close} value={overrideReason} onPick={setOverrideReason} className="order-last w-full" />
                        <button className={BTN} disabled={Boolean(busy) || overrideReason.trim().length < 5}
                          onClick={() => run("close", () => accountingApi.closeBooksMonth(companyId, m.start, overrideReason.trim()), m.start)}>
                          Close anyway
                        </button>
                        <button className={BTN} onClick={() => setBankBlock(null)}>Cancel</button>
                      </span>
                    )}
                    {canManage && !data.bound && m === lastClosed && !confirmReopen && (
                      <button className={BTN} disabled={Boolean(busy)} onClick={() => setConfirmReopen(true)}>Reopen</button>
                    )}
                    {canManage && m === lastClosed && confirmReopen && (
                      <>
                        <span className="text-xs text-[var(--alert-error-text)]">Printed pages for this month must be discarded.</span>
                        <input
                          aria-label="Why reopen (optional)"
                          className="w-44 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                          maxLength={500}
                          placeholder="Why? (optional, audit log)"
                          value={reopenReason}
                          onChange={(e) => setReopenReason(e.target.value)}
                        />
                        <QuickPicks kind="reopen-reason" presets={PRESETS.reopen} value={reopenReason} onPick={setReopenReason} className="order-last w-full" />
                        <button className={BTN} disabled={Boolean(busy)}
                          onClick={() => run("reopen", () => accountingApi.reopenBooksMonth(companyId, reopenReason.trim()))}>Confirm reopen</button>
                        <button className={BTN} onClick={() => setConfirmReopen(false)}>Cancel</button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.months.some((m) => m.status === "before_books") && (
        <button className="mt-1 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)]" onClick={() => setShowBefore((v) => !v)}>
          {showBefore ? "Hide months before the books started" : `Show ${data.months.filter((m) => m.status === "before_books").length} months before the books started`}
        </button>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {data.bound ? (
          data.bound_books.map((b) => (
            <button key={b} className={BTN} onClick={() => download(b)}>
              {b === "declaration" ? "Sworn declaration" : `${b} bound`}
            </button>
          ))
        ) : (
          canManage && allClosed && (
            <button className={BTN} disabled={Boolean(busy)}
              onClick={() => run("bind", () => accountingApi.bindBooksYear(companyId, year))}>
              {busy === "bind" ? "Binding…" : `Bind FY ${year}`}
            </button>
          )
        )}
      </div>
      {file.node}
    </section>
  );
}
