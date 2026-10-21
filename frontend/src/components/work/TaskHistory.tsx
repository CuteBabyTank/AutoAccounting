"use client";

import { useEffect, useState } from "react";
import AuditTrail from "@/components/accounting/AuditTrail";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { AuditEvent } from "@/types/accounting";
import type { Person } from "@/types/work";
import { BTN } from "@/components/work/ui";

/** A task's assignment, status and completion trail, from the firm's append-only audit log. */
export default function TaskHistory({ taskId, people }: { taskId: string; people: Person[] }) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState({ offset: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const { offset } = page;
    let cancelled = false;
    setLoading(true);
    setError("");
    accountingApi.auditEvents({ entity: "task", entity_id: taskId, limit: 20, offset })
      .then((page) => {
        if (!cancelled) { setEvents((prev) => offset ? [...prev, ...page.events] : page.events); setTotal(page.total); }
      })
      .catch((e) => { if (!cancelled) setError(apiErrorMessage(e, "Couldn't load task history")); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [taskId, page]);

  const names = new Map(people.map((p) => [p.id, p.name]));
  const withNames = (fields: Record<string, unknown>) => Object.fromEntries(Object.entries(fields).map(([key, value]) =>
    [key, ["assignee_id", "completed_by", "created_by"].includes(key) && typeof value === "string" ? names.get(value) ?? "Former firm member" : value],
  ));
  return <section className="mt-5 border-t border-[var(--border)] pt-4" aria-label="Task history">
    <h4 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">Task history</h4>
    <AuditTrail events={events.map((event) => ({ ...event, before: withNames(event.before), after: withNames(event.after) }))} />
    {error && <p className="mt-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
    {loading ? <p className="mt-2 text-xs text-[var(--text-secondary)]">Loading history…</p> : events.length === 0 && !error ? <p className="text-xs text-[var(--text-secondary)]">No recorded changes yet.</p> : null}
    {events.length < total && <button type="button" className={`${BTN} mt-2`} disabled={loading} onClick={() => setPage({ offset: events.length })}>Older changes</button>}
  </section>;
}
