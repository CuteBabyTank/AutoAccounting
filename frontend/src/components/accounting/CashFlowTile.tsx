"use client";

import { useEffect, useState } from "react";
import Hint from "@/components/guide/Hint";
import { extrasApi } from "@/lib/extras-api";
import { apiErrorMessage, formatAmount } from "@/lib/accounting-format";
import { shortDate } from "@/components/work/ui";
import type { CashForecast } from "@/types/extras";

const TILE = "rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2";
const INPUT = "rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";

function todayIso(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

/** Cash in the books plus open receivables minus open payables by due date, for the next 8 weeks. */
export default function CashFlowTile({ companyId }: { companyId: string }) {
  const [asOf, setAsOf] = useState(todayIso);
  const [data, setData] = useState<CashForecast | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(asOf)) return;
    let cancelled = false;
    setError("");
    extrasApi
      .cashForecast(companyId, { as_of: asOf, weeks: 8 })
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the cash projection")));
    return () => {
      cancelled = true;
    };
  }, [companyId, asOf]);

  const weeks = data?.weeks ?? [];
  const totalIn = weeks.reduce((s, w) => s + Number(w.inflow), 0);
  const totalOut = weeks.reduce((s, w) => s + Number(w.outflow), 0);
  const scale = Math.max(1, ...weeks.map((w) => Math.max(Number(w.inflow), Number(w.outflow))));
  const tiles: [string, string | null, string][] = data
    ? [
        ["Cash now", data.opening, "Cash on hand, banks and e-wallets in the books"],
        ["Coming in", String(totalIn), "Open receivables due in the next 8 weeks"],
        ["Going out", String(totalOut), "Open payables due in the next 8 weeks"],
        ["In 8 weeks", data.closing, "Cash now + coming in − going out"],
      ]
    : [];

  return (
    <div className="space-y-2">
      <p className="flex flex-wrap items-center gap-2 text-xs text-[var(--text-secondary)]">
        <label className="flex items-center gap-1">
          As of <input type="date" className={INPUT} value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        </label>
        <Hint>
          A simple projection: the cash the books show on the date, plus customer invoices and minus supplier bills by
          their due dates. Overdue items are listed apart and not counted, since nobody knows when they&apos;ll be paid.
          Nothing else (payroll, taxes, rent without a bill) is in it.
        </Hint>
      </p>
      {error && <p className="text-sm text-[var(--alert-error-text)]">{error}</p>}
      {!data ? (
        !error && <p className="text-sm text-[var(--text-secondary)]">Loading…</p>
      ) : (
        <>
          {data.note && <p className="text-xs text-[var(--text-secondary)]">{data.note}</p>}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {tiles.map(([label, value, detail]) => (
              <div key={label} className={TILE} title={detail}>
                <p className="text-[11px] font-medium text-[var(--text-secondary)]">{label}</p>
                <p className={`aa-amount text-lg font-semibold tabular-nums ${value !== null && Number(value) < 0 ? "text-[var(--badge-red-text)]" : "text-[var(--text-primary)]"}`}>
                  {value === null ? "—" : `₱${formatAmount(value, true)}`}
                </p>
              </div>
            ))}
          </div>
          <div className={`${TILE} overflow-x-auto`}>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] text-[var(--text-secondary)]">
                  <th className="py-1 pr-2 font-medium">Week</th>
                  <th className="py-1 pr-2 text-right font-medium">In</th>
                  <th className="py-1 pr-2 text-right font-medium">Out</th>
                  <th className="hidden py-1 pr-2 font-medium sm:table-cell" aria-hidden />
                  <th className="py-1 text-right font-medium">Cash after</th>
                </tr>
              </thead>
              <tbody>
                {weeks.map((w) => (
                  <tr key={w.start} className="border-t border-[var(--border)]">
                    <td className="whitespace-nowrap py-1 pr-2 text-[var(--text-secondary)]">{shortDate(w.start)} – {shortDate(w.end)}</td>
                    <td className="aa-amount py-1 pr-2 text-right tabular-nums text-[var(--text-primary)]">{Number(w.inflow) ? formatAmount(w.inflow, true) : "—"}</td>
                    <td className="aa-amount py-1 pr-2 text-right tabular-nums text-[var(--text-primary)]">{Number(w.outflow) ? formatAmount(w.outflow, true) : "—"}</td>
                    <td className="hidden w-1/3 py-1 pr-2 sm:table-cell">
                      <div className="flex flex-col gap-0.5">
                        <span className="block h-1.5 rounded-full bg-[var(--accent)]" style={{ width: `${(Number(w.inflow) / scale) * 100}%` }} />
                        <span className="block h-1.5 rounded-full bg-[var(--badge-red-text)] opacity-70" style={{ width: `${(Number(w.outflow) / scale) * 100}%` }} />
                      </div>
                    </td>
                    <td className={`aa-amount py-1 text-right tabular-nums ${w.closing !== null && Number(w.closing) < 0 ? "font-semibold text-[var(--badge-red-text)]" : "text-[var(--text-primary)]"}`}>
                      {w.closing === null ? "—" : formatAmount(w.closing, true)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(Number(data.overdue_in) > 0 || Number(data.overdue_out) > 0 || Number(data.later_in) > 0 || Number(data.later_out) > 0) && (
            <p className="text-xs text-[var(--text-secondary)]">
              Not counted: overdue receivables <span className="aa-amount">₱{formatAmount(data.overdue_in, true)}</span>, overdue payables{" "}
              <span className="aa-amount">₱{formatAmount(data.overdue_out, true)}</span>; due later than 8 weeks{" "}
              <span className="aa-amount">₱{formatAmount(data.later_in, true)}</span> in, <span className="aa-amount">₱{formatAmount(data.later_out, true)}</span> out.
            </p>
          )}
        </>
      )}
    </div>
  );
}
