"use client";

import { useEffect, useState } from "react";
import Hint from "@/components/guide/Hint";
import AuditTrail, { ENTITY_LABELS } from "@/components/accounting/AuditTrail";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { AuditEvent, AuditFilters } from "@/types/accounting";

interface Props {
  companyId: string;
  companyName: string;
}

const PAGE = 50;
const INPUT = "rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const LABEL = "block text-[11px] font-medium text-[var(--text-secondary)] mb-1";
const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";

function buildFilters(companyId: string, userId: string, start: string, end: string, entity: string,
  offset: number): AuditFilters {
  return {
    company_id: companyId,
    ...(userId && { user_id: userId }),
    ...(start && { start }),
    ...(end && { end }),
    ...(entity && { entity }),
    limit: PAGE,
    offset,
  };
}

/** Company-level audit log: every change people made to this client's data, filterable by person, day and kind. */
export default function AuditLogPanel({ companyId, companyName }: Props) {
  const [userId, setUserId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [entity, setEntity] = useState("");
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [users, setUsers] = useState<{ id: string; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    accountingApi
      .auditEvents(buildFilters(companyId, userId, start, end, entity, 0))
      .then((page) => {
        if (cancelled) return;
        setEvents(page.events);
        setTotal(page.total);
        if (!userId) setUsers(page.users);
      })
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the audit log")))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [companyId, userId, start, end, entity]);

  async function more() {
    setLoading(true);
    try {
      const page = await accountingApi.auditEvents(buildFilters(companyId, userId, start, end, entity, events.length));
      setEvents((prev) => [...prev, ...page.events]);
      setTotal(page.total);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't load more"));
    } finally {
      setLoading(false);
    }
  }

  const filtered = Boolean(userId || start || end || entity);

  return (
    <div className="mb-6">
      <h2 className="mb-1 text-base font-semibold text-[var(--text-primary)]">
        Audit log · {companyName}{" "}
        <Hint align="right">
          Every change someone in your firm made to this client: document edits, flags accepted anyway (with the reason
          given), chart and journal entries, months closed or reopened, returns marked filed, and more. Each entry shows
          who, when, and the values before and after. Nobody can edit or delete it.
        </Hint>
      </h2>
      <p className="mb-3 text-sm text-[var(--text-secondary)]">Newest first. Only people in your firm can see it.</p>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div>
          <label className={LABEL} htmlFor="audit-user">Person</label>
          <select id="audit-user" className={INPUT} value={userId} onChange={(e) => setUserId(e.target.value)}>
            <option value="">Everyone</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>{u.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="audit-entity">Kind</label>
          <select id="audit-entity" className={INPUT} value={entity} onChange={(e) => setEntity(e.target.value)}>
            <option value="">Everything</option>
            {Object.entries(ENTITY_LABELS).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="audit-start">From</label>
          <input id="audit-start" type="date" className={INPUT} value={start} onChange={(e) => setStart(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="audit-end">To</label>
          <input id="audit-end" type="date" className={INPUT} value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} />
        </div>
        {filtered && (
          <button
            className={BTN}
            onClick={() => {
              setUserId("");
              setStart("");
              setEnd("");
              setEntity("");
            }}
          >
            Clear filters
          </button>
        )}
      </div>

      {error && <p className="mb-3 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {!loading && events.length === 0 && !error && (
        <p className="py-6 text-center text-sm text-[var(--text-secondary)]">
          {filtered ? "No changes match these filters." : "No changes recorded yet. Edits made from now on show up here."}
        </p>
      )}
      <AuditTrail events={events} showEntity />
      <div className="mt-3 flex items-center gap-3 text-xs text-[var(--text-secondary)]">
        {events.length > 0 && <span>Showing {events.length} of {total}</span>}
        {events.length < total && (
          <button className={BTN} disabled={loading} onClick={more}>
            {loading ? "Loading…" : "Load more"}
          </button>
        )}
      </div>
    </div>
  );
}
