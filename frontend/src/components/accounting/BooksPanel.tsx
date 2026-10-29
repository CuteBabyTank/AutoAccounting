"use client";

import { useCallback, useEffect, useState } from "react";
import Hint from "@/components/guide/Hint";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, formatPeso } from "@/lib/accounting-format";
import BookMonths from "@/components/accounting/BookMonths";
import ChartEditor from "@/components/accounting/ChartEditor";
import JournalEntryForm from "@/components/accounting/JournalEntryForm";
import OpeningAssets from "@/components/accounting/OpeningAssets";
import RecurringEntries from "@/components/accounting/RecurringEntries";
import { useFeatures } from "@/lib/features";
import type { Account, JournalEntry, JournalEntryInput } from "@/types/accounting";

interface Props {
  companyId: string;
  year: number;
  booksStart: string;
  fiscalYearEndMonth: number;
  canManage: boolean;
  onChanged: () => void;
}

const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]";

export default function BooksPanel({ companyId, year, booksStart, fiscalYearEndMonth, canManage, onChanged }: Props) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const recurringOn = useFeatures().on("recurring");
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [editing, setEditing] = useState<{ id?: string; input: JournalEntryInput } | null>(null);
  const [showChart, setShowChart] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [a, e] = await Promise.all([accountingApi.accounts(companyId), accountingApi.journalEntries(companyId, year)]);
    setAccounts(a);
    setEntries(e);
  }, [companyId, year]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([accountingApi.accounts(companyId), accountingApi.journalEntries(companyId, year)])
      .then(([a, e]) => {
        if (cancelled) return;
        setAccounts(a);
        setEntries(e);
      })
      .catch((e) => {
        if (!cancelled) setError(apiErrorMessage(e, "Couldn't load the books"));
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, year]);

  const opening = entries.find((e) => e.kind === "opening");
  // First day of the fiscal year being viewed (month after the year-end month, in year-1; Jan 1 for 12).
  const fyStart = fiscalYearEndMonth === 12
    ? `${year}-01-01`
    : `${year - 1}-${String(fiscalYearEndMonth + 1).padStart(2, "0")}-01`;
  const manualDate = fyStart > booksStart ? fyStart : booksStart;
  // Fiscal year of booksStart (the year its fiscal year ends in): the only year the opening balances belong to.
  const [startYear, startMonth] = booksStart.split("-").map(Number);
  const booksFy = startMonth > fiscalYearEndMonth ? startYear + 1 : startYear;
  const blank = (kind: "opening" | "manual"): JournalEntryInput => ({
    kind, book: "GJ", entry_date: kind === "opening" ? booksStart : manualDate, reference: kind === "opening" ? "OB" : "",
    particulars: kind === "opening" ? "Opening balances" : "", lines: [],
  });
  const ppeCodes = new Set(accounts.filter((a) => a.system_key === "ppe" || a.system_key === "accum_dep").map((a) => a.code));
  const openingPpe = (opening?.lines ?? [])
    .filter((l) => ppeCodes.has(l.account_code))
    .reduce((s, l) => s + Number(l.debit || 0) - Number(l.credit || 0), 0);
  const title = (code: string) => accounts.find((a) => a.code === code)?.name ?? code;
  // Stored lines carry "0" on the empty side; the form wants it blank.
  const editable = (e: JournalEntry): JournalEntryInput => ({
    ...e,
    lines: e.lines.map((l) => ({ ...l, debit: Number(l.debit) ? l.debit : "", credit: Number(l.credit) ? l.credit : "" })),
  });

  async function save(input: JournalEntryInput) {
    setBusy(true);
    setError("");
    try {
      if (editing?.id) await accountingApi.updateJournalEntry(editing.id, input);
      else await accountingApi.createJournalEntry(companyId, input);
      setEditing(null);
      await load();
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save the entry"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (!window.confirm("Delete this journal entry? It will be removed from the live books and retained in the audit history. Deleting a write-off reopens its invoices.")) return;
    setBusy(true);
    setError("");
    try {
      await accountingApi.deleteJournalEntry(id);
      await load();
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't delete the entry"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-6">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">
          Books · FY {year}{" "}
          <Hint align="right">
            Your client&apos;s BIR loose-leaf books. Filed documents post to the journals automatically; add manual entries
            (accruals, adjustments) below. Months close in order, and only once their documents are reviewed. Changes to a
            closed month post as corrections.
          </Hint>
        </h2>
        <span className="text-xs text-[var(--text-secondary)]">Books start {booksStart}. Journals, ledger and trial balance are in each quarter&apos;s workbook.</span>
        <button className={`${BTN} ml-auto`} onClick={() => setShowChart((s) => !s)}>{showChart ? "Hide" : "Chart of accounts"}</button>
      </div>
      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {showChart && (
        <div className="mb-4 rounded-lg border border-[var(--border)] p-3">
          <ChartEditor companyId={companyId} canManage={canManage} />
        </div>
      )}

      <BookMonths companyId={companyId} year={year} canManage={canManage} onChanged={onChanged} />

      <section className="mb-4">
        <div className="mb-2 flex items-center gap-2">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Opening balances</h3>
          {!editing && (opening || booksFy === year) && (
            <button className={BTN} onClick={() => setEditing(opening ? { id: opening.id, input: editable(opening) } : { input: blank("opening") })}>
              {opening ? "Edit" : "Enter opening balances"}
            </button>
          )}
        </div>
        {!opening && booksFy !== year && (
          <p className="text-xs text-[var(--text-secondary)]">Opening balances are in FY {booksFy}.</p>
        )}
        {opening && editing?.id !== opening.id && (
          <p className="text-xs text-[var(--text-secondary)]">
            {opening.lines.length} accounts as of {opening.entry_date} · total {formatPeso(opening.lines.reduce((s, l) => s + Number(l.debit), 0))}
          </p>
        )}
        {opening && !editing && <button className="mt-2 text-xs text-[var(--alert-error-text)]" disabled={busy} onClick={() => remove(opening.id)}>Delete opening balances</button>}
        {opening && booksFy === year && (
          <OpeningAssets companyId={companyId} year={year} openingPpe={openingPpe} onChanged={onChanged} />
        )}
      </section>

      {recurringOn && <RecurringEntries
        companyId={companyId}
        accounts={accounts}
        defaultDate={manualDate}
        onPosted={() => {
          load().catch(() => undefined);
          onChanged();
        }}
      />}

      <section>
        <div className="mb-2 flex items-center gap-2">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Journal entries</h3>
          {!editing && <button className={BTN} onClick={() => setEditing({ input: blank("manual") })}>New entry</button>}
        </div>
        {editing && (
          <JournalEntryForm accounts={accounts} initial={editing.input} busy={busy} onCancel={() => setEditing(null)} onSave={save} />
        )}
        <ul className="mt-2 divide-y divide-[var(--border)]">
          {entries.filter((e) => e.kind === "manual").map((e) => (
            <li key={e.id} className="flex flex-wrap items-baseline gap-3 py-2 text-sm">
              <span className="w-24 text-[var(--text-secondary)]">{e.entry_date}</span>
              <span className="w-10 text-xs text-[var(--text-secondary)]">{e.book}</span>
              {e.is_adjusting && (
                <span className="rounded-full bg-[var(--badge-blue-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-blue-text)]">Adjusting</span>
              )}
              <span className="flex-1 text-[var(--text-primary)]">
                {e.particulars || e.reference || "(no particulars)"} ·{" "}
                {e.lines.map((l) => `${title(l.account_code)} ${Number(l.debit) ? "Dr" : "Cr"} ${formatPeso(Number(l.debit) || Number(l.credit))}`).join(" / ")}
              </span>
              {e.recurring && (
                <span className="rounded-full bg-[var(--bg-secondary)] px-1.5 text-[11px] text-[var(--text-secondary)]">Recurring</span>
              )}
              {e.is_writeoff ? (
                <span className="rounded-full bg-[var(--badge-yellow-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-yellow-text)]" title="Delete it to reopen the invoices">Write-off</span>
              ) : (
                <button className="text-[var(--accent)]" onClick={() => setEditing({ id: e.id, input: editable(e) })}>Edit</button>
              )}
              <button className="text-[var(--alert-error-text)]" disabled={busy} onClick={() => remove(e.id)}>Delete</button>
            </li>
          ))}
        </ul>
        {entries.every((e) => e.kind !== "manual") && !editing && <p className="mt-2 text-sm text-[var(--text-secondary)]">No manual journal entries yet.</p>}
      </section>
    </div>
  );
}
