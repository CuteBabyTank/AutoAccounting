"use client";

import { useEffect, useState } from "react";
import Hint from "@/components/guide/Hint";
import { workApi } from "@/lib/work-api";
import { REASON_LABELS, apiErrorMessage, formatPeso } from "@/lib/accounting-format";
import type { CompanyHealth as Health } from "@/types/work";
import { Chip, monthLabel, reasonName, shortDate } from "@/components/work/ui";

interface Props {
  companyId: string;
  refreshKey?: number;
  /** Tighter layout for a tile on the work board. */
  compact?: boolean;
}

function Check({ ok, label, hint, children }: { ok: boolean; label: React.ReactNode; hint?: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2">
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className={`h-2 w-2 shrink-0 rounded-full ${ok ? "bg-[var(--badge-green-text)]" : "bg-[var(--badge-yellow-text)]"}`}
        />
        <p className="text-sm font-medium text-[var(--text-primary)]">{label}</p>
        {hint && <Hint align="left">{hint}</Hint>}
      </div>
      {children && <div className="mt-1 pl-4 text-xs text-[var(--text-secondary)]">{children}</div>}
    </div>
  );
}

/** QBO-style client overview: the common issues to fix before filing or closing, for one company. */
export default function CompanyHealth({ companyId, refreshKey = 0, compact }: Props) {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError("");
    workApi
      .health(companyId)
      .then((h) => !cancelled && setHealth(h))
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't run the health check")));
    return () => {
      cancelled = true;
    };
  }, [companyId, refreshKey]);

  if (error) return <p className="text-sm text-[var(--alert-error-text)]">{error}</p>;
  if (!health) return <p className="text-sm text-[var(--text-secondary)]">Checking…</p>;

  const reasons = Object.entries(health.reviews_by_reason).sort((a, b) => b[1] - a[1]);
  const grid = compact ? "grid grid-cols-1 gap-2" : "grid grid-cols-1 gap-2 lg:grid-cols-2";
  return (
    <div>
      {health.notes.map((n) => (
        <p key={n} className="mb-2 text-xs text-[var(--text-secondary)]">{n}</p>
      ))}
      <div className={grid}>
        <Check ok={health.open_reviews === 0} label={health.open_reviews ? `${health.open_reviews} document${health.open_reviews === 1 ? "" : "s"} to review` : "No documents waiting for review"}>
          {reasons.length > 0 && (
            <ul className="space-y-0.5">
              {reasons.map(([r, n]) => (
                <li key={r} className="flex items-center gap-1">
                  <span className="tabular-nums">{n}</span> · {reasonName(r)}
                  {REASON_LABELS[r] && <Hint align="right">{REASON_LABELS[r]}</Hint>}
                </li>
              ))}
            </ul>
          )}
        </Check>
        <Check
          ok={health.unmatched_bank_lines === 0 && health.unassigned_statements === 0 && health.bank_accounts.every((a) => a.unreconciled_months.length === 0)}
          label="Bank"
          hint="Reconciled through is the last day of an unbroken run of reconciled months. A month counts as unreconciled once it has ended and has statement lines but no reconciliation."
        >
          {health.bank_accounts.length === 0 ? (
            <span>No bank accounts yet.</span>
          ) : (
            <ul className="space-y-1">
              {health.bank_accounts.map((a) => (
                <li key={a.code}>
                  <span className="text-[var(--text-primary)]">{a.code} {a.name}</span> · {a.reconciled_through ? `reconciled through ${shortDate(a.reconciled_through)}` : "never reconciled"}
                  {a.unmatched_lines > 0 && <> · {a.unmatched_lines} line{a.unmatched_lines === 1 ? "" : "s"} to match</>}
                  {a.unreconciled_months.length > 0 && (
                    <span className="mt-0.5 flex flex-wrap gap-1">
                      {a.unreconciled_months.map((m) => <Chip key={m} tone="yellow">{monthLabel(m)}</Chip>)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {health.unassigned_statements > 0 && (
            <p className="mt-1">{health.unassigned_statements} statement{health.unassigned_statements === 1 ? "" : "s"} not assigned to an account.</p>
          )}
        </Check>
        <Check
          ok={health.cwt_pending_count === 0}
          label={health.cwt_pending_count ? <>{health.cwt_pending_count} 2307{health.cwt_pending_count === 1 ? "" : "s"} to receive · <span className="aa-amount">₱{formatPeso(health.cwt_pending_amount)}</span></> : "No 2307s waiting"}
          hint="Sales where the customer withheld tax and no matching 2307 for that quarter is filed yet. Without it the credit can't be claimed."
        />
        <Check
          ok={health.months_not_closed.length === 0}
          label={!health.books_on ? "Books are off" : health.months_not_closed.length ? `${health.months_not_closed.length} month${health.months_not_closed.length === 1 ? "" : "s"} not closed` : "Every month closed"}
        >
          {health.months_not_closed.length > 0 && (
            <span className="flex flex-wrap gap-1">
              {health.months_not_closed.slice(0, 12).map((m) => <Chip key={m} tone="yellow">{monthLabel(m)}</Chip>)}
              {health.months_not_closed.length > 12 && <span>+{health.months_not_closed.length - 12} more</span>}
            </span>
          )}
        </Check>
        <Check
          ok={health.ar_over_90_count === 0 && health.ap_over_90_count === 0}
          label="Over 90 days"
          hint="Invoices and bills more than 90 days past their due date and still open. Old receivables may need follow-up or a write-off; old payables may be paid but missing the receipt."
        >
          A/R {health.ar_over_90_count} · <span className="aa-amount">₱{formatPeso(health.ar_over_90_amount)}</span> — A/P {health.ap_over_90_count} · <span className="aa-amount">₱{formatPeso(health.ap_over_90_amount)}</span>
        </Check>
        <Check
          ok={health.negative_balances.length === 0}
          label={health.negative_balances.length ? "Balances on the wrong side" : "No negative asset or liability balances"}
          hint="An asset below zero (like negative Cash on hand) or a liability with a debit balance usually means a missing opening balance, receipt or deposit."
        >
          {health.negative_balances.map((b) => (
            <p key={b.code}>{b.code} {b.name} · <span className="aa-amount">₱{formatPeso(b.balance)}</span> {b.type === "asset" ? "below zero" : "debit balance"}</p>
          ))}
        </Check>
        <Check
          ok={health.review_balances.length === 0}
          label={health.review_balances.length ? "Balances parked for review" : "Nothing parked in review accounts"}
          hint="VAT difference - for review and any Suspense account should end up at zero once each item is looked at and reclassified."
        >
          {health.review_balances.map((b) => (
            <p key={b.code}>{b.code} {b.name} · <span className="aa-amount">₱{formatPeso(b.balance)}</span></p>
          ))}
        </Check>
      </div>
    </div>
  );
}
