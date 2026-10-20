"use client";

import { useState } from "react";
import AmountInput from "@/components/AmountInput";
import { Plus, Trash } from "@phosphor-icons/react";
import type { Account, JournalEntryInput, JournalLine } from "@/types/accounting";

const INPUT = "w-full px-2 py-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const BLANK: JournalLine = { account_code: "", debit: "", credit: "", party_name: "", party_tin: "" };

interface Props {
  accounts: Account[];
  initial: JournalEntryInput;
  busy: boolean;
  onCancel: () => void;
  onSave: (entry: JournalEntryInput) => void;
}

const cents = (v: string) => Math.round((Number(v) || 0) * 100);

export default function JournalEntryForm({ accounts, initial, busy, onCancel, onSave }: Props) {
  const [entry, setEntry] = useState<JournalEntryInput>(initial);
  const lines = entry.lines.length >= 2 ? entry.lines : [...entry.lines, BLANK, BLANK].slice(0, 2);
  const badNumber = (v: string) => v !== "" && !(Number(v) > 0);
  const used = lines.filter((l) => l.account_code && (l.debit || l.credit));
  const debit = used.reduce((s, l) => s + cents(l.debit), 0);
  const credit = used.reduce((s, l) => s + cents(l.credit), 0);
  const problem = lines.some((l) => !l.account_code && (l.debit || l.credit))
    ? "Choose an account for every line with an amount"
    : lines.some((l) => badNumber(l.debit) || badNumber(l.credit))
      ? "Amounts must be positive numbers (no commas)"
      : used.length < 2
        ? "Enter at least two lines"
        : debit !== credit || debit === 0
          ? "must balance"
          : "";
  const setLine = (i: number, patch: Partial<JournalLine>) =>
    setEntry((e) => ({ ...e, lines: lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));
  // Locked accounts take no new lines; a line already on one (posted before the lock) keeps it.
  const active = accounts.filter((a) => a.active && (!a.locked || initial.lines.some((l) => l.account_code === a.code)));
  const opening = entry.kind === "opening";

  return (
    <div className="rounded-lg border border-[var(--border)] p-3">
      <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        {!opening && (
          <>
            <input type="date" className={INPUT} value={entry.entry_date} onChange={(e) => setEntry({ ...entry, entry_date: e.target.value })} />
            <select className={INPUT} value={entry.book} onChange={(e) => setEntry({ ...entry, book: e.target.value as JournalEntryInput["book"] })}>
              <option value="GJ">General Journal</option>
              <option value="CRJ">Cash Receipts Journal</option>
              <option value="CDJ">Cash Disbursements Journal</option>
            </select>
          </>
        )}
        <input className={INPUT} placeholder="Reference" maxLength={60} value={entry.reference} onChange={(e) => setEntry({ ...entry, reference: e.target.value })} />
        <input className={INPUT} placeholder="Particulars" maxLength={255} value={entry.particulars} onChange={(e) => setEntry({ ...entry, particulars: e.target.value })} />
        {!opening && (
          <label className="col-span-2 flex items-center gap-2 text-sm text-[var(--text-primary)] md:col-span-4">
            <input
              type="checkbox"
              checked={!!entry.is_adjusting}
              onChange={(e) => setEntry({ ...entry, is_adjusting: e.target.checked })}
            />
            Adjusting entry
            <span className="text-xs text-[var(--text-secondary)]">(period-end accrual or correction; shows in the Adjusted TB)</span>
          </label>
        )}
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] text-[var(--text-secondary)]">
            <th className="pb-1">Account</th><th className="pb-1">Debit</th><th className="pb-1">Credit</th><th className="pb-1">Party (AR/AP)</th><th />
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i}>
              <td className="py-0.5 pr-2">
                <select className={INPUT} value={l.account_code} onChange={(e) => setLine(i, { account_code: e.target.value })}>
                  <option value="">Choose…</option>
                  {active.map((a) => (
                    <option key={a.id} value={a.code}>{a.code} {a.name}</option>
                  ))}
                </select>
              </td>
              <td className="py-0.5 pr-2"><AmountInput className={INPUT} aria-label="Debit" value={l.debit} onValueChange={(v) => setLine(i, { debit: v, credit: v ? "" : l.credit })} /></td>
              <td className="py-0.5 pr-2"><AmountInput className={INPUT} aria-label="Credit" value={l.credit} onValueChange={(v) => setLine(i, { credit: v, debit: v ? "" : l.debit })} /></td>
              <td className="py-0.5 pr-2"><input className={INPUT} maxLength={255} value={l.party_name} onChange={(e) => setLine(i, { party_name: e.target.value })} /></td>
              <td>
                {lines.length > 2 && (
                  <button aria-label="Remove line" className="p-1 text-[var(--text-secondary)]" onClick={() => setEntry({ ...entry, lines: lines.filter((_, j) => j !== i) })}>
                    <Trash size={14} />
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
        <button className="flex items-center gap-1 text-[var(--accent)]" onClick={() => setEntry({ ...entry, lines: [...lines, BLANK] })}>
          <Plus size={13} /> Line
        </button>
        <span className={problem ? "text-[var(--alert-error-text)]" : "text-[var(--text-secondary)]"}>
          Debits ₱{(debit / 100).toLocaleString("en-PH", { minimumFractionDigits: 2 })} · Credits ₱{(credit / 100).toLocaleString("en-PH", { minimumFractionDigits: 2 })}
          {problem && ` — ${problem}`}
        </span>
        <span className="ml-auto flex gap-2">
          <button className="rounded-lg border border-[var(--border)] px-3 py-1.5" onClick={onCancel}>Cancel</button>
          <button
            className="rounded-lg bg-[var(--accent)] px-3 py-1.5 font-medium text-white disabled:opacity-60"
            disabled={busy || !!problem}
            onClick={() =>
              onSave({
                ...entry,
                is_adjusting: !opening && !!entry.is_adjusting,
                lines: used
                  .map((l) => ({ ...l, debit: l.debit || "0", credit: l.credit || "0" })),
              })
            }
          >
            Save
          </button>
        </span>
      </div>
    </div>
  );
}
