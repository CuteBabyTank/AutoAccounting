"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle, Circle, PencilSimple, Plus, Trash } from "@phosphor-icons/react";
import TaskForm from "@/components/work/TaskForm";
import { workApi } from "@/lib/work-api";
import { focusName } from "@/lib/focus";
import { apiErrorMessage } from "@/lib/accounting-format";
import { useAuth } from "@/lib/auth";
import type { Person, Task, TaskFilters, TaskInput } from "@/types/work";
import { BTN, Chip, INPUT, completionWhen, shortDate } from "@/components/work/ui";
import { confirmDialog } from "@/components/ui/Dialogs";

interface Props {
  companies: { id: string; registered_name: string }[];
  people: Person[];
  /** Fixed filter (a company's page); the list's own filters are hidden for those keys. */
  fixed?: TaskFilters;
  defaults?: Partial<TaskInput>;
  compact?: boolean;
  onChanged?: () => void;
  refreshKey?: number;
  autoAssignControl?: React.ReactNode;
}

const PRIORITY_TONE = { high: "red", normal: "gray", low: "gray" } as const;

function periodText(t: Task): string {
  if (!t.period_year) return "";
  return t.period_quarter ? `Q${t.period_quarter} ${t.period_year}` : String(t.period_year);
}

/** The firm's to-dos: tick to complete, edit, or add one about a client, document or period. */
export default function TaskList({ companies, people, fixed, defaults, compact, onChanged, refreshKey = 0, autoAssignControl }: Props) {
  const { user } = useAuth();
  const canManage = user?.role === "admin" || user?.role === "enterprise" || user?.role === "manager";
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [status, setStatus] = useState<"open" | "done" | "all">("open");
  const [assignee, setAssignee] = useState("");
  const [editing, setEditing] = useState<Task | "new" | null>(null);
  const [error, setError] = useState("");
  const fixedKey = JSON.stringify(fixed ?? {});
  const loadId = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++loadId.current;
    setError("");
    try {
      const filters: TaskFilters = { ...JSON.parse(fixedKey), status };
      if (assignee) filters.assignee = assignee;
      const next = await workApi.tasks(filters);
      if (requestId === loadId.current) setTasks(next);
    } catch (e) {
      if (requestId === loadId.current) setError(apiErrorMessage(e, "Couldn't load the tasks"));
    }
  }, [fixedKey, status, assignee]);

  useEffect(() => {
    load();
    return () => { loadId.current += 1; };
  }, [load, refreshKey]);

  const changed = () => {
    load();
    onChanged?.();
  };

  async function toggle(t: Task) {
    setError("");
    try {
      await workApi.updateTask(t.id, { status: t.status === "done" ? "open" : "done" });
      changed();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't update the task"));
    }
  }

  async function remove(t: Task) {
    if (!(await confirmDialog({ title: `Delete the task "${t.title}"?`, confirmLabel: "Delete", danger: true }))) return;
    try {
      await workApi.deleteTask(t.id);
      changed();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't delete the task"));
    }
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <select aria-label="Which tasks" className={INPUT} value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
          <option value="open">To do</option>
          <option value="done">Done</option>
          <option value="all">All</option>
        </select>
        {!fixed?.assignee && (
          <select aria-label="Assigned to" className={INPUT} value={assignee} onChange={(e) => setAssignee(e.target.value)}>
            <option value="">Anyone</option>
            <option value="me">Me</option>
            <option value="unassigned">Nobody yet</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        )}
        {autoAssignControl}
        <button className={`${BTN} ml-auto`} onClick={() => setEditing("new")}>
          <Plus size={16} /> Add task
        </button>
      </div>
      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {tasks === null ? (
        !error && <p className="text-sm text-[var(--text-secondary)]">Loading…</p>
      ) : tasks.length === 0 ? (
        <p className="py-6 text-center text-sm text-[var(--text-secondary)]">
          {status === "done" ? "No finished tasks yet." : "Nothing to do. Add a task for anything you need to chase, like a missing bank statement."}
        </p>
      ) : (
        <ul className="divide-y divide-[var(--border)] rounded-lg border border-[var(--border)] bg-[var(--bg-primary)]">
          {tasks.map((t) => {
            const mine = t.created_by === user?.id;
            return (
              <li key={t.id} data-focus={focusName.task(t.id)} className="flex items-start gap-3 px-3 py-2.5">
                <button
                  onClick={() => toggle(t)}
                  aria-label={t.status === "done" ? `Reopen ${t.title}` : `Mark ${t.title} done`}
                  className="mt-0.5 shrink-0 text-[var(--text-secondary)] hover:text-[var(--accent)]"
                >
                  {t.status === "done" ? <CheckCircle size={20} weight="fill" className="text-[var(--accent)]" /> : <Circle size={20} />}
                </button>
                <div className="min-w-0 flex-1">
                  <p className={`text-sm text-[var(--text-primary)] ${t.status === "done" ? "line-through opacity-60" : ""}`}>{t.title}</p>
                  {t.notes && !compact && <p className="mt-0.5 whitespace-pre-line text-xs text-[var(--text-secondary)]">{t.notes}</p>}
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                    {t.priority !== "normal" && <Chip tone={PRIORITY_TONE[t.priority]}>{t.priority === "high" ? "High" : "Low"}</Chip>}
                    {t.status === "in_progress" && <Chip tone="blue">In progress</Chip>}
                    {t.due_date && (
                      <Chip tone={t.overdue ? "red" : "gray"}>{t.overdue ? "Overdue · " : "Due "}{shortDate(t.due_date)}</Chip>
                    )}
                    {!fixed?.company_id && t.company_name && <span>{t.company_name}</span>}
                    {periodText(t) && <span>· {periodText(t)}</span>}
                    {t.document_label && <span>· {t.document_label}</span>}
                    <span>· {t.assignee_name || "Nobody yet"}</span>
                    {t.assignee_id && t.assigned_auto && <Chip tone="blue" title="Automatically assigned">Auto</Chip>}
                    {t.status === "done" && <span>· Completed by {t.completed_by_name || "Unknown"}{t.completed_at ? ` on ${completionWhen(t.completed_at)}` : ""}</span>}
                  </div>
                </div>
                <button onClick={() => setEditing(t)} aria-label={`Edit ${t.title}`} className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]">
                  <PencilSimple size={16} />
                </button>
                {(mine || canManage) && (
                  <button onClick={() => remove(t)} aria-label={`Delete ${t.title}`} className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]">
                    <Trash size={16} />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {editing && (
        <TaskForm
          task={editing === "new" ? undefined : editing}
          defaults={{ ...defaults, company_id: fixed?.company_id ?? defaults?.company_id, document_id: fixed?.document_id ?? defaults?.document_id }}
          companies={companies}
          people={people}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            changed();
          }}
        />
      )}
    </div>
  );
}
