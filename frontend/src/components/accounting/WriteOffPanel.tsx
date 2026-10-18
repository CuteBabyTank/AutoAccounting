"use client";

import { useEffect, useMemo, useState } from "react";
import Hint from "@/components/guide/Hint";
import { accountingApi } from "@/lib/accounting-api";
import { extrasApi } from "@/lib/extras-api";
import { apiErrorMessage, formatPeso } from "@/lib/accounting-format";
import type { Account } from "@/types/accounting";
import type { WriteOffCandidates } from "@/types/extras";

const BTN = "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";
const INPUT = "rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const TH = "px-2 py-1.5 text-left text-[11px] font-medium text-[var(--text-secondary)]";
const TD = "px-2 py-1.5";

interface Props {
  companyId: string;
  asOf: string;
  onClose: () => void;
  onDone: () => void;
}

/** Customers → Write off: choose old or small open invoices and post one bad-debts entry for them. */
export default function WriteOffPanel({ companyId, asOf, onClose, onDone }: Props) {
  const [minDays, setMinDays] = useState("90");
  const [maxBalance, setMaxBalance] = useState("");
  const [data, setData] = useState<WriteOffCandidates | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [account, setAccount] = useState("");
  const [entryDate, setEntryDate] = useState(asOf);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    accountingApi.accounts(companyId).then((a) => {
      if (cancelled) return;
      const usable = a.filter((x) => x.type === "expense" && x.active && !x.locked);
      setAccounts(usable);
      setAccount((cur) => cur || usable.find((x) => x.system_key === "bad_debts")?.code || "");
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  useEffect(() => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(asOf)) return;
    const days = Math.max(0, Math.floor(Number(minDays) || 0));
    const max = maxBalance.trim() && Number(maxBalance) >= 0 ? maxBalance.trim() : undefined;
    let cancelled = false;
    const t = setTimeout(() => {
      extrasApi
        .writeOffCandidates(companyId, { as_of: asOf, min_days: days, max_balance: max })
        .then((d) => {
          if (cancelled) return;
          setData(d);
          setPicked(new Set());
        })
        .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the open invoices")));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [companyId, asOf, minDays, maxBalance]);

  const chosen = useMemo(() => (data?.items ?? []).filter((i) => picked.has(i.document_id)), [data, picked]);
  const total = chosen.reduce((s, i) => s + Number(i.open), 0);
  const all = (data?.items.length ?? 0) > 0 && chosen.length === data?.items.length;

  async function submit() {
    if (!chosen.length || !account || !reason.trim()) return;
    if (!window.confirm(`Write off ${chosen.length} invoice${chosen.length === 1 ? "" : "s"} for ₱${formatPeso(total)} to ${account} on ${entryDate}?`)) return;
    setBusy(true);
    setError("");
    try {
      await extrasApi.writeOff(companyId, { entry_date: entryDate, item_ids: chosen.map((i) => i.document_id), account, reason: reason.trim() });
      onDone();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't write off the invoices"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">
          Write off invoices{" "}
          <Hint>
            Posts one General Journal entry: debit the account you choose (Bad debts), credit Accounts receivable for each
            invoice&apos;s open balance as of the list date. The invoices drop off the aging from the entry date. Output VAT
            is not reversed. Delete the entry in Books to reopen them. The date must be in an open month.
          </Hint>
        </h3>
        <button className={`${BTN} ml-auto`} onClick={onClose}>Close</button>
      </div>
      <div className="mb-2 flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-1 text-[var(--text-secondary)]">
          At least <input className={`${INPUT} w-20`} inputMode="numeric" value={minDays} onChange={(e) => setMinDays(e.target.value)} /> days past due
        </label>
        <label className="flex items-center gap-1 text-[var(--text-secondary)]">
          Balance up to ₱ <input className={`${INPUT} w-28`} inputMode="decimal" placeholder="any" value={maxBalance} onChange={(e) => setMaxBalance(e.target.value)} />
        </label>
        <span className="text-xs text-[var(--text-secondary)]">Open as of {asOf}{data?.last_closed ? ` · books closed through ${data.last_closed}` : ""}</span>
      </div>
      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {!data ? (
        !error && <p className="text-sm text-[var(--text-secondary)]">Loading…</p>
      ) : data.items.length === 0 ? (
        <p className="py-3 text-sm text-[var(--text-secondary)]">No open invoices match.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className={TH}>
                  <input type="checkbox" aria-label="Select all" checked={all} onChange={(e) => setPicked(e.target.checked ? new Set(data.items.map((i) => i.document_id)) : new Set())} />
                </th>
                <th className={TH}>Customer</th><th className={TH}>Invoice</th><th className={TH}>Due</th>
                <th className={`${TH} text-right`}>Days past due</th><th className={`${TH} text-right`}>Open</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {data.items.map((i) => (
                <tr key={i.document_id}>
                  <td className={TD}>
                    <input
                      type="checkbox"
                      aria-label={`Select ${i.doc_number}`}
                      checked={picked.has(i.document_id)}
                      onChange={(e) => setPicked((prev) => {
                        const next = new Set(prev);
                        if (e.target.checked) next.add(i.document_id);
                        else next.delete(i.document_id);
                        return next;
                      })}
                    />
                  </td>
                  <td className={`${TD} text-[var(--text-primary)]`}>{i.contact_name}</td>
                  <td className={TD}>{i.doc_number || "—"}{i.opening ? " · opening" : ""}</td>
                  <td className={TD}>{i.due}</td>
                  <td className={`${TD} text-right tabular-nums`}>{Math.max(i.days_past_due, 0)}</td>
                  <td className={`${TD} text-right tabular-nums`}>{formatPeso(i.open)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <select className={INPUT} value={account} onChange={(e) => setAccount(e.target.value)} aria-label="Expense account">
          <option value="">Expense account…</option>
          {accounts.map((a) => <option key={a.id} value={a.code}>{a.code} {a.name}</option>)}
        </select>
        <label className="flex items-center gap-1 text-[var(--text-secondary)]">
          Dated <input type="date" className={INPUT} value={entryDate} onChange={(e) => setEntryDate(e.target.value)} />
        </label>
        <input className={`${INPUT} min-w-[14rem] flex-1`} maxLength={500} placeholder="Reason (required, kept in the audit log)" value={reason} onChange={(e) => setReason(e.target.value)} />
        <button
          className="rounded-lg bg-[var(--accent)] px-3 py-1.5 font-medium text-white disabled:opacity-60"
          disabled={busy || !chosen.length || !account || !reason.trim()}
          onClick={submit}
        >
          Write off {chosen.length || ""} · ₱{formatPeso(total)}
        </button>
      </div>
    </section>
  );
}
