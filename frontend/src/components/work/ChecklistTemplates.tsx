"use client";

import { useEffect, useState } from "react";
import { Plus, Trash } from "@phosphor-icons/react";
import Hint from "@/components/guide/Hint";
import { extrasApi } from "@/lib/extras-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import { useAuth } from "@/lib/auth";
import type { Cadence, ChecklistInput, ChecklistItem, ChecklistTemplate } from "@/types/extras";
import { BTN, BTN_PRIMARY, Chip, INPUT } from "@/components/work/ui";

const CADENCE: Record<Cadence, string> = { monthly: "Monthly", quarterly: "Quarterly", annual: "Yearly" };
const BLANK_ITEM: ChecklistItem = { title: "", notes: "", offset_days: 5, priority: "normal" };

/** Team page: the firm's close checklists. Everyone sees them; owners and managers add, edit and delete. */
export default function ChecklistTemplates() {
  const { user } = useAuth();
  const canManage = user?.role === "admin" || user?.role === "enterprise" || user?.role === "manager";
  const [rows, setRows] = useState<ChecklistTemplate[]>([]);
  const [draft, setDraft] = useState<(ChecklistInput & { id?: string }) | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    extrasApi.checklists().then(setRows).catch((e) => setError(apiErrorMessage(e, "Couldn't load the checklists")));
  }, []);

  const setItem = (i: number, patch: Partial<ChecklistItem>) =>
    setDraft((d) => (d ? { ...d, items: d.items.map((x, j) => (j === i ? { ...x, ...patch } : x)) } : d));

  async function save() {
    if (!draft) return;
    const items = draft.items.filter((i) => i.title.trim());
    if (!draft.name.trim() || items.length === 0) {
      setError("Give the checklist a name and at least one step");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body = { name: draft.name.trim(), cadence: draft.cadence, items };
      if (draft.id) await extrasApi.updateChecklist(draft.id, body);
      else await extrasApi.createChecklist(body);
      setDraft(null);
      setRows(await extrasApi.checklists());
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save the checklist"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(t: ChecklistTemplate) {
    if (!window.confirm(`Delete the checklist "${t.name}"? Tasks it already created stay.`)) return;
    setBusy(true);
    try {
      await extrasApi.deleteChecklist(t.id);
      setRows(await extrasApi.checklists());
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't delete the checklist"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-6 rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          Close checklists{" "}
          <Hint align="right">
            Lists of the steps your firm follows to close a client&apos;s month, quarter or year. On a client&apos;s
            Overview, &quot;Add a close checklist&quot; turns one into tasks for a period, each due a set number of days
            after the period ends. The two built-in lists can&apos;t be changed; copy one to make your own.
          </Hint>
        </h2>
        {canManage && !draft && (
          <button className={`${BTN} ml-auto`} onClick={() => setDraft({ name: "", cadence: "monthly", items: [{ ...BLANK_ITEM }] })}>
            <Plus size={14} /> New checklist
          </button>
        )}
      </div>
      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {draft && (
        <div className="mb-3 space-y-2 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-3">
          <div className="flex flex-wrap gap-2">
            <input className={`${INPUT} min-w-[14rem] flex-1`} placeholder="Name (e.g. Monthly close, VAT clients)" maxLength={80} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <select className={INPUT} aria-label="Cadence" value={draft.cadence} onChange={(e) => setDraft({ ...draft, cadence: e.target.value as Cadence })}>
              {(Object.keys(CADENCE) as Cadence[]).map((c) => <option key={c} value={c}>{CADENCE[c]}</option>)}
            </select>
          </div>
          {draft.items.map((it, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <input className={`${INPUT} min-w-[12rem] flex-1`} placeholder={`Step ${i + 1}`} maxLength={150} value={it.title} onChange={(e) => setItem(i, { title: e.target.value })} />
              <label className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
                due <input type="number" min={-60} max={365} className={`${INPUT} w-20`} value={it.offset_days} onChange={(e) => setItem(i, { offset_days: Math.round(Number(e.target.value) || 0) })} /> days after
              </label>
              <select className={INPUT} aria-label="Priority" value={it.priority} onChange={(e) => setItem(i, { priority: e.target.value as ChecklistItem["priority"] })}>
                <option value="high">High</option>
                <option value="normal">Normal</option>
                <option value="low">Low</option>
              </select>
              {draft.items.length > 1 && (
                <button aria-label="Remove step" className="p-1 text-[var(--text-secondary)]" onClick={() => setDraft({ ...draft, items: draft.items.filter((_, j) => j !== i) })}>
                  <Trash size={14} />
                </button>
              )}
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2">
            {draft.items.length < 50 && (
              <button className="flex items-center gap-1 text-sm text-[var(--accent)]" onClick={() => setDraft({ ...draft, items: [...draft.items, { ...BLANK_ITEM }] })}>
                <Plus size={13} /> Step
              </button>
            )}
            <span className="ml-auto flex gap-2">
              <button className={BTN} onClick={() => setDraft(null)}>Cancel</button>
              <button className={BTN_PRIMARY} disabled={busy} onClick={save}>Save</button>
            </span>
          </div>
        </div>
      )}
      <ul className="divide-y divide-[var(--border)]">
        {rows.map((t) => (
          <li key={t.id} className="py-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <button className="font-medium text-[var(--text-primary)] hover:underline" onClick={() => setOpen(open === t.id ? null : t.id)}>{t.name}</button>
              <Chip>{CADENCE[t.cadence]}</Chip>
              <span className="text-xs text-[var(--text-secondary)]">{t.items.length} steps</span>
              {t.builtin && <Chip tone="blue">Built in</Chip>}
              {canManage && !draft && (
                <span className="ml-auto flex gap-3 text-sm">
                  <button
                    className="text-[var(--accent)]"
                    onClick={() => setDraft({ id: t.builtin ? undefined : t.id, name: t.builtin ? `${t.name} (copy)` : t.name, cadence: t.cadence, items: t.items.map((x) => ({ ...x })) })}
                  >
                    {t.builtin ? "Copy" : "Edit"}
                  </button>
                  {!t.builtin && <button className="text-[var(--alert-error-text)]" disabled={busy} onClick={() => remove(t)}>Delete</button>}
                </span>
              )}
            </div>
            {open === t.id && (
              <ol className="mt-1 list-decimal pl-6 text-xs text-[var(--text-secondary)]">
                {t.items.map((x, i) => (
                  <li key={i}>{x.title} · {x.offset_days >= 0 ? `${x.offset_days} days after` : `${-x.offset_days} days before`} the period end{x.priority === "high" ? " · high" : ""}</li>
                ))}
              </ol>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
