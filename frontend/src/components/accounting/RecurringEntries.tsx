"use client";

import { useEffect, useState } from "react";
import Hint from "@/components/guide/Hint";
import JournalEntryForm from "@/components/accounting/JournalEntryForm";
import { extrasApi } from "@/lib/extras-api";
import { focusName } from "@/lib/focus";
import { apiErrorMessage, formatPeso } from "@/lib/accounting-format";
import type { Account, JournalEntryInput } from "@/types/accounting";
import type { Frequency, RecurringEntry, RecurringInput } from "@/types/extras";

const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]";
const INPUT = "px-2 py-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";

interface Props {
  companyId: string;
  accounts: Account[];
  defaultDate: string;
  onPosted: () => void;
}

interface Draft {
  id?: string;
  name: string;
  frequency: Frequency;
  end_date: string;
  active: boolean;
  entry: JournalEntryInput;
}

function fmt(d: string): string {
  return new Date(`${d}T00:00:00`).toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" });
}

/** Books → Recurring entries: JE templates on a schedule. Due entries post only when someone presses the button. */
export default function RecurringEntries({ companyId, accounts, defaultDate, onPosted }: Props) {
  const [rows, setRows] = useState<RecurringEntry[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    let cancelled = false;
    extrasApi
      .recurring(companyId)
      .then((r) => !cancelled && setRows(r))
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the recurring entries")));
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  const reload = async () => setRows(await extrasApi.recurring(companyId));

  const blank = (): Draft => ({
    name: "", frequency: "monthly", end_date: "", active: true,
    entry: { kind: "manual", book: "GJ", entry_date: defaultDate, reference: "", particulars: "", lines: [] },
  });
  const fromRow = (r: RecurringEntry): Draft => ({
    id: r.id, name: r.name, frequency: r.frequency, end_date: r.end_date ?? "", active: r.active,
    entry: {
      kind: "manual", book: r.book, entry_date: r.next_date, reference: r.reference, particulars: r.particulars,
      is_adjusting: r.is_adjusting,
      lines: r.lines.map((l) => ({ ...l, debit: Number(l.debit) ? l.debit : "", credit: Number(l.credit) ? l.credit : "" })),
    },
  });

  async function save(entry: JournalEntryInput) {
    if (!draft) return;
    if (!draft.name.trim()) {
      setError("Name the recurring entry");
      return;
    }
    const body: RecurringInput = {
      name: draft.name.trim(), book: entry.book, reference: entry.reference, particulars: entry.particulars,
      lines: entry.lines, is_adjusting: !!entry.is_adjusting, frequency: draft.frequency, next_date: entry.entry_date,
      end_date: draft.end_date || null, active: draft.active,
    };
    setBusy(true);
    setError("");
    try {
      if (draft.id) await extrasApi.updateRecurring(draft.id, body);
      else await extrasApi.createRecurring(companyId, body);
      setDraft(null);
      await reload();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save the recurring entry"));
    } finally {
      setBusy(false);
    }
  }

  async function post(r: RecurringEntry) {
    const dates = r.due.map(fmt).join(", ");
    if (!window.confirm(`Post ${r.due.length} entr${r.due.length === 1 ? "y" : "ies"} of "${r.name}" dated ${dates}?`)) return;
    setBusy(true);
    setError("");
    setNote("");
    try {
      const out = await extrasApi.postRecurring(r.id);
      setNote(`Posted ${out.posted.length} entr${out.posted.length === 1 ? "y" : "ies"} of "${r.name}". Next: ${fmt(out.template.next_date)}.`);
      await reload();
      onPosted();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't post the due entries"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(r: RecurringEntry) {
    if (!window.confirm(`Delete the recurring entry "${r.name}"? Entries it already posted stay in the books.`)) return;
    setBusy(true);
    try {
      await extrasApi.deleteRecurring(r.id);
      await reload();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't delete the recurring entry"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section data-focus={focusName.recurring(companyId)} className="mb-4">
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">
          Recurring entries{" "}
          <Hint>
            Templates for entries that repeat, like a monthly rent accrual or a retainer. Nothing posts by itself: when an
            entry is due it shows here, and pressing Post adds it to the journal (audited) on its due date. A template on
            the 31st posts on the last day of shorter months.
          </Hint>
        </h3>
        {!draft && <button className={BTN} onClick={() => setDraft(blank())}>New recurring entry</button>}
      </div>
      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {note && <p className="mb-2 text-sm text-[var(--text-secondary)]">{note}</p>}
      {draft && (
        <div className="mb-2 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <input className={`${INPUT} min-w-[14rem] flex-1`} placeholder="Name (e.g. Rent accrual)" maxLength={80} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <select className={INPUT} value={draft.frequency} onChange={(e) => setDraft({ ...draft, frequency: e.target.value as Frequency })}>
              <option value="monthly">Every month</option>
              <option value="quarterly">Every quarter</option>
            </select>
            <label className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
              Ends <input type="date" className={INPUT} value={draft.end_date} onChange={(e) => setDraft({ ...draft, end_date: e.target.value })} />
            </label>
            <label className="flex items-center gap-1 text-sm text-[var(--text-primary)]">
              <input type="checkbox" checked={draft.active} onChange={(e) => setDraft({ ...draft, active: e.target.checked })} /> Active
            </label>
          </div>
          <p className="text-xs text-[var(--text-secondary)]">The date below is the next date it falls due.</p>
          <JournalEntryForm key={draft.id ?? "new"} accounts={accounts} initial={draft.entry} busy={busy} onCancel={() => setDraft(null)} onSave={save} />
        </div>
      )}
      {rows.length === 0 && !draft && <p className="text-xs text-[var(--text-secondary)]">No recurring entries yet.</p>}
      <ul className="divide-y divide-[var(--border)]">
        {rows.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
            <span className="font-medium text-[var(--text-primary)]">{r.name}</span>
            <span className="text-xs text-[var(--text-secondary)]">
              {r.frequency === "monthly" ? "Monthly" : "Quarterly"} · ₱{formatPeso(Number(r.amount))} · next {fmt(r.next_date)}
              {r.end_date && ` · ends ${fmt(r.end_date)}`}
            </span>
            {!r.active && <span className="rounded-full bg-[var(--bg-secondary)] px-1.5 text-[11px] text-[var(--text-secondary)]">Paused</span>}
            {r.due.length > 0 && (
              <span className="rounded-full bg-[var(--badge-yellow-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-yellow-text)]">{r.due.length} due</span>
            )}
            <span className="ml-auto flex gap-3">
              {r.due.length > 0 && (
                <button className="font-medium text-[var(--accent)] disabled:opacity-60" disabled={busy} onClick={() => post(r)}>
                  Post {r.due.length} due entr{r.due.length === 1 ? "y" : "ies"}
                </button>
              )}
              <button className="text-[var(--accent)]" onClick={() => setDraft(fromRow(r))}>Edit</button>
              <button className="text-[var(--alert-error-text)]" disabled={busy} onClick={() => remove(r)}>Delete</button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
