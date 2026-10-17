"use client";

import { useEffect, useState } from "react";
import Hint from "@/components/guide/Hint";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, formatAmount } from "@/lib/accounting-format";
import { shortDate } from "@/components/work/ui";
import type { CompanyKpis } from "@/types/accounting";

const TILE = "rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2";

function ratio(value: string | null, pct: boolean): string {
  if (value === null) return "—";
  const n = Number(value);
  return pct ? `${n.toLocaleString("en-PH", { maximumFractionDigits: 1 })}%` : n.toLocaleString("en-PH", { maximumFractionDigits: 2 });
}

/** Company KPIs for the current fiscal quarter: margins, liquidity ratios, A/R and A/P aging buckets. */
export default function KpiTiles({ companyId }: { companyId: string }) {
  const [data, setData] = useState<CompanyKpis | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    accountingApi
      .kpis(companyId)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the key figures")));
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  if (error) return <p className="text-sm text-[var(--alert-error-text)]">{error}</p>;
  if (!data) return <p className="text-sm text-[var(--text-secondary)]">Loading…</p>;
  const k = data.kpis;
  const tiles: [string, string, string][] = k
    ? [
        ["Gross margin", ratio(k.gross_margin, true), `Gross profit ${formatAmount(k.gross_profit)} on sales ${formatAmount(k.net_sales)}`],
        ["Net margin", ratio(k.net_margin, true), `Net income ${formatAmount(k.net_income)}`],
        ["Opex ratio", ratio(k.opex_ratio, true), `Operating expenses ${formatAmount(k.operating_expenses)}`],
        ["Current ratio", ratio(k.current_ratio, false), `Current assets ${formatAmount(k.current_assets)} / liabilities ${formatAmount(k.current_liabilities)}`],
        ["Quick ratio", ratio(k.quick_ratio, false), `Cash, receivables and CWT ${formatAmount(k.quick_assets)}`],
      ]
    : [];
  return (
    <div className="space-y-3">
      <p className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
        {shortDate(data.start)} – {shortDate(data.end)} · from the books
        <Hint>
          Margins and the opex ratio are % of net sales for the quarter. Current ratio = current assets ÷ current
          liabilities; quick ratio counts only cash, receivables and creditable withholding tax. &quot;—&quot; means
          there&apos;s nothing to divide by yet.
        </Hint>
      </p>
      {!data.books_on && <p className="text-sm text-[var(--text-secondary)]">Ratios need the books: set a Books start on the company.</p>}
      {data.note && <p className="text-sm text-[var(--alert-error-text)]">{data.note}</p>}
      {tiles.length > 0 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {tiles.map(([label, value, detail]) => (
            <div key={label} className={TILE} title={detail}>
              <p className="text-[11px] font-medium text-[var(--text-secondary)]">{label}</p>
              <p className="text-lg font-semibold tabular-nums text-[var(--text-primary)]">{value}</p>
            </div>
          ))}
        </div>
      )}
      <div className="grid gap-2 sm:grid-cols-2">
        {(["ar", "ap"] as const).map((kind) => {
          const a = data.aging[kind];
          return (
            <div key={kind} className={TILE}>
              <p className="mb-1 text-[11px] font-medium text-[var(--text-secondary)]">
                {kind === "ar" ? "Receivables aging" : "Payables aging"} · {formatAmount(a.totals.total ?? "0")}
              </p>
              <div className="grid grid-cols-5 gap-1 text-center">
                {a.buckets.map((b) => (
                  <div key={b}>
                    <p className="text-[10px] text-[var(--text-secondary)]">{a.labels[b]}</p>
                    <p className={`text-xs tabular-nums ${b === "90+" && Number(a.totals[b]) > 0 ? "font-semibold text-[var(--badge-red-text)]" : "text-[var(--text-primary)]"}`}>
                      {formatAmount(a.totals[b] ?? "0", true)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
