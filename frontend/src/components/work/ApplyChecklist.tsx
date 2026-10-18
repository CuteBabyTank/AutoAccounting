"use client";

import { useEffect, useState } from "react";
import Hint from "@/components/guide/Hint";
import { extrasApi } from "@/lib/extras-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { ChecklistTemplate } from "@/types/extras";
import type { Person } from "@/types/work";
import { BTN, INPUT } from "@/components/work/ui";

/** The last day of the month before today (the usual period being closed). */
function lastMonthEnd(): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth(), 0);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

interface Props {
  companyId: string;
  people: Person[];
  onApplied: () => void;
}

/** Company overview: add a close checklist's steps as tasks for one period. */
export default function ApplyChecklist({ companyId, people, onApplied }: Props) {
  const [templates, setTemplates] = useState<ChecklistTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [periodEnd, setPeriodEnd] = useState(lastMonthEnd);
  const [assignee, setAssignee] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    extrasApi
      .checklists()
      .then((t) => {
        if (cancelled) return;
        setTemplates(t);
        setTemplateId((cur) => cur || t[0]?.id || "");
      })
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the checklists")));
    return () => {
      cancelled = true;
    };
  }, []);

  async function apply() {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const out = await extrasApi.applyChecklist(templateId, { company_id: companyId, period_end: periodEnd, assignee_id: assignee || null });
      setNote(
        out.created.length
          ? `Added ${out.created.length} task${out.created.length === 1 ? "" : "s"}${out.skipped ? `; ${out.skipped} already there` : ""}.`
          : "Every step of this checklist is already a task for that period.",
      );
      onApplied();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't add the checklist"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
      <span className="flex items-center gap-1 font-medium text-[var(--text-primary)]">
        Add a close checklist
        <Hint>
          Creates one task per step for the period ending on the date you pick, due the set number of days after it.
          Steps already added for that period are skipped. The firm&apos;s own checklists are managed on Team.
        </Hint>
      </span>
      <select className={INPUT} aria-label="Checklist" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
        {templates.map((t) => (
          <option key={t.id} value={t.id}>{t.name} ({t.items.length} steps)</option>
        ))}
      </select>
      <label className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
        Period ending <input type="date" className={INPUT} value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
      </label>
      <select className={INPUT} aria-label="Assign to" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
        <option value="">Nobody assigned</option>
        {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
      <button className={BTN} disabled={busy || !templateId || !/^\d{4}-\d{2}-\d{2}$/.test(periodEnd)} onClick={apply}>Add tasks</button>
      {note && <span className="text-xs text-[var(--text-secondary)]">{note}</span>}
      {error && <span className="text-xs text-[var(--alert-error-text)]">{error}</span>}
    </div>
  );
}
