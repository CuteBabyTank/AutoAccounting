"use client";

import { useState } from "react";
import { createPortal } from "react-dom";
import { X } from "@phosphor-icons/react";
import QuickPicks from "@/components/QuickPicks";
import TaskHistory from "@/components/work/TaskHistory";
import { workApi } from "@/lib/work-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import { PRESETS } from "@/lib/quick-picks";
import type { Person, Task, TaskInput } from "@/types/work";
import { BTN, BTN_PRIMARY, INPUT } from "@/components/work/ui";

interface Props {
  task?: Task;
  /** Prefilled links for a new task (company page, document panel). */
  defaults?: Partial<TaskInput>;
  companies: { id: string; registered_name: string }[];
  people: Person[];
  onClose: () => void;
  onSaved: (task: Task) => void;
}

const LABEL = "block text-xs font-medium text-[var(--text-secondary)] mb-1";
const SHORTCUT = "rounded-full border border-[var(--border)] px-2 py-0.5 text-xs text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--text-primary)] aria-pressed:border-[var(--accent)] aria-pressed:text-[var(--accent)]";

/** Local calendar date as YYYY-MM-DD (toISOString would shift to UTC). */
function isoDay(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function dueShortcuts(): [string, string][] {
  const today = new Date();
  const at = (days: number) => isoDay(new Date(today.getFullYear(), today.getMonth(), today.getDate() + days));
  const friday = (5 - today.getDay() + 7) % 7 || 7;
  return [
    ["Today", at(0)],
    ["Tomorrow", at(1)],
    ["Friday", at(friday)],
    ["In a week", at(7)],
    ["Month end", isoDay(new Date(today.getFullYear(), today.getMonth() + 1, 0))],
  ];
}

/** Add or edit a task: what to do, for whom, by when, about which client and period. */
export default function TaskForm({ task, defaults, companies, people, onClose, onSaved }: Props) {
  const [form, setForm] = useState<TaskInput>({
    title: task?.title ?? defaults?.title ?? "",
    notes: task?.notes ?? defaults?.notes ?? "",
    due_date: task?.due_date ?? defaults?.due_date ?? null,
    assignee_id: task?.assignee_id ?? defaults?.assignee_id ?? null,
    status: task?.status ?? "open",
    priority: task?.priority ?? defaults?.priority ?? "normal",
    company_id: task?.company_id ?? defaults?.company_id ?? null,
    document_id: task?.document_id ?? defaults?.document_id ?? null,
    period_year: task?.period_year ?? defaults?.period_year ?? null,
    period_quarter: task?.period_quarter ?? defaults?.period_quarter ?? null,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const set = <K extends keyof TaskInput>(key: K, value: TaskInput[K]) => setForm((f) => ({ ...f, [key]: value }));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title.trim()) {
      setError("Give the task a title.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const body = { ...form, title: form.title.trim(), period_quarter: form.period_year ? form.period_quarter : null };
      if (task) {
        // Omit unchanged fields so editing notes never turns an automatic assignment into a manual one.
        const changes = Object.fromEntries(Object.entries(body).filter(([key, value]) => value !== task[key as keyof TaskInput]));
        onSaved(await workApi.updateTask(task.id, changes));
      } else {
        onSaved(await workApi.createTask(body));
      }
    } catch (err) {
      setError(apiErrorMessage(err, "Couldn't save the task"));
    } finally {
      setSaving(false);
    }
  }

  return createPortal(
    <div className="lp-skin overlay-enter fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <form
        onSubmit={save}
        onClick={(e) => e.stopPropagation()}
        className="modal-enter max-h-[90dvh] w-full max-w-lg overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-5 shadow-xl"
        aria-label={task ? "Edit task" : "New task"}
      >
        <div className="mb-4 flex items-center">
          <h3 className="text-lg font-semibold text-[var(--text-primary)]">{task ? "Edit task" : "New task"}</h3>
          <button type="button" onClick={onClose} aria-label="Close" className="ml-auto rounded p-1 hover:bg-[var(--bg-hover)]">
            <X size={18} />
          </button>
        </div>
        <div className="space-y-3">
          <div>
            <label className={LABEL} htmlFor="task-title">Task</label>
            <input
              id="task-title"
              autoFocus
              maxLength={200}
              className={`${INPUT} w-full`}
              placeholder="Ask client for the Oct–Nov bank statement"
              value={form.title}
              onChange={(e) => set("title", e.target.value)}
            />
            {!task && <QuickPicks kind="task-title" presets={PRESETS.task} value={form.title} onPick={(t) => set("title", t)} />}
          </div>
          <div>
            <label className={LABEL} htmlFor="task-notes">Notes</label>
            <textarea id="task-notes" rows={3} maxLength={4000} className={`${INPUT} w-full`} value={form.notes} onChange={(e) => set("notes", e.target.value)} />
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className={LABEL} htmlFor="task-assignee">Assigned to</label>
              <select id="task-assignee" className={`${INPUT} w-full`} value={form.assignee_id ?? ""} onChange={(e) => set("assignee_id", e.target.value || null)}>
                <option value="">Nobody yet</option>
                {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="task-due">Due</label>
              <input id="task-due" type="date" className={`${INPUT} w-full`} value={form.due_date ?? ""} onChange={(e) => set("due_date", e.target.value || null)} />
              <div className="mt-1.5 flex flex-wrap gap-1">
                {dueShortcuts().map(([label, day]) => (
                  <button key={label} type="button" className={SHORTCUT} aria-pressed={form.due_date === day} onClick={() => set("due_date", day)}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className={LABEL} htmlFor="task-priority">Priority</label>
              <select id="task-priority" className={`${INPUT} w-full`} value={form.priority} onChange={(e) => set("priority", e.target.value as TaskInput["priority"])}>
                <option value="high">High</option>
                <option value="normal">Normal</option>
                <option value="low">Low</option>
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="task-status">Status</label>
              <select id="task-status" className={`${INPUT} w-full`} value={form.status} onChange={(e) => set("status", e.target.value as TaskInput["status"])}>
                <option value="open">To do</option>
                <option value="in_progress">In progress</option>
                <option value="done">Done</option>
              </select>
            </div>
            <div className="sm:col-span-2">
              <label className={LABEL} htmlFor="task-company">Client</label>
              <select
                id="task-company"
                className={`${INPUT} w-full`}
                value={form.company_id ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, company_id: e.target.value || null, document_id: null, period_year: e.target.value ? f.period_year : null }))}
              >
                <option value="">No client (firm task)</option>
                {companies.map((c) => <option key={c.id} value={c.id}>{c.registered_name}</option>)}
              </select>
            </div>
            {form.company_id && (
              <>
                <div>
                  <label className={LABEL} htmlFor="task-year">Year</label>
                  <input
                    id="task-year"
                    type="number"
                    min={2000}
                    max={2100}
                    className={`${INPUT} w-full`}
                    value={form.period_year ?? ""}
                    onChange={(e) => set("period_year", e.target.value ? Number(e.target.value) : null)}
                  />
                </div>
                <div>
                  <label className={LABEL} htmlFor="task-quarter">Period</label>
                  <select
                    id="task-quarter"
                    className={`${INPUT} w-full`}
                    disabled={!form.period_year}
                    value={form.period_quarter ?? ""}
                    onChange={(e) => set("period_quarter", e.target.value === "" ? null : Number(e.target.value))}
                  >
                    <option value="">Whole year</option>
                    {[1, 2, 3, 4].map((q) => <option key={q} value={q}>Q{q}</option>)}
                  </select>
                </div>
              </>
            )}
            {task?.document_label && form.document_id && (
              <p className="sm:col-span-2 text-xs text-[var(--text-secondary)]">About document {task.document_label}</p>
            )}
          </div>
        </div>
        {task && <TaskHistory taskId={task.id} people={people} />}
        {error && <p className="mt-3 text-sm text-[var(--alert-error-text)]">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className={BTN} onClick={onClose}>Cancel</button>
          <button type="submit" className={BTN_PRIMARY} disabled={saving}>{saving ? "Saving…" : "Save task"}</button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
