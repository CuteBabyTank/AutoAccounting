"use client";

import { useCallback, useEffect, useState } from "react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, saveBlob } from "@/lib/accounting-format";
import type { BooksYear } from "@/types/accounting";

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
export default function BookMonths({ companyId, year, canManage, onChanged }: Props) {
  const [data, setData] = useState<BooksYear | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [confirmReopen, setConfirmReopen] = useState(false);
  const [reopenReason, setReopenReason] = useState("");

  const load = useCallback(() => accountingApi.booksYear(companyId, year).then(setData), [companyId, year]);

  useEffect(() => {
    let cancelled = false;
    accountingApi.booksYear(companyId, year)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(apiErrorMessage(e, "Couldn't load the closed months")); });
    return () => { cancelled = true; };
  }, [companyId, year]);

  async function run(label: string, action: () => Promise<BooksYear>) {
    setBusy(label);
    setError("");
    try {
      setData(await action());
      setConfirmReopen(false);
      setReopenReason("");
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "That didn't work"));
      await load().catch(() => undefined);
    } finally {
      setBusy("");
    }
  }

  async function download(book: string, monthStart?: string) {
    try {
      const blob = await accountingApi.booksFile(companyId, year, book, monthStart);
      saveBlob(blob, monthStart ? `${book} ${monthStart.slice(0, 7)}.pdf` : `${book} FY${year}.pdf`);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't download the PDF"));
    }
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
            {data.months.map((m) => (
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
                        onClick={() => run("close", () => accountingApi.closeBooksMonth(companyId, m.start))}>
                        {busy === "close" ? "Closing…" : "Close month"}
                      </button>
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
    </section>
  );
}
