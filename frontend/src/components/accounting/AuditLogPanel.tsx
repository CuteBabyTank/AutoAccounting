"use client";

import { useEffect, useState } from "react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { AuditEvent, AuditFilters, AuditPage } from "@/types/accounting";

const INPUT = "w-full rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2.5 py-1.5 text-sm text-[var(--text-primary)]";
const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50";
const ENTITIES = [["document", "Documents"], ["account", "Accounts"], ["journal_entry", "Journal entries"], ["book_close", "Month close / binding"]];
const formatValue = (value: unknown) => value === undefined ? "—" : JSON.stringify(value, null, 2);

function EventDetails({ event }: { event: AuditEvent }) {
  const keys = Array.from(new Set([...Object.keys(event.before), ...Object.keys(event.after)]))
    .filter((key) => JSON.stringify(event.before[key]) !== JSON.stringify(event.after[key]));
  return (
    <details className="mt-2">
      <summary className="cursor-pointer text-xs font-medium text-[var(--accent)]">Before / after · {keys.length} changed fields</summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead><tr><th className="p-2">Field</th><th className="p-2">Before</th><th className="p-2">After</th></tr></thead>
          <tbody>{keys.map((key) => (
            <tr key={key} className="border-t border-[var(--border)] align-top">
              <th className="break-words p-2 font-medium">{key.replaceAll("_", " ")}</th>
              <td className="p-2"><pre className="max-w-sm whitespace-pre-wrap break-words font-sans">{formatValue(event.before[key])}</pre></td>
              <td className="p-2"><pre className="max-w-sm whitespace-pre-wrap break-words font-sans">{formatValue(event.after[key])}</pre></td>
            </tr>
          ))}</tbody>
        </table>
        {keys.length === 0 && <p className="py-2">No field values changed.</p>}
      </div>
    </details>
  );
}

export default function AuditLogPanel({ companyId, entityId, refreshKey = "", companyName }: {
  companyId: string; entityId?: string; refreshKey?: string; companyName?: string;
}) {
  const [filters, setFilters] = useState<AuditFilters>({});
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<AuditPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    accountingApi.auditEvents({ ...filters, company_id: companyId,
      ...(entityId ? { entity: "document", entity_id: entityId } : {}), offset, limit: 50 })
      .then((result) => { if (!cancelled) setPage(result); })
      .catch((e: unknown) => { if (!cancelled) { setPage(null); setError(apiErrorMessage(e, "Couldn't load history")); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [companyId, entityId, filters, offset, refreshKey, reload]);
  const filter = (key: keyof AuditFilters, value: string) => {
    setOffset(0);
    setFilters((old) => ({ ...old, [key]: value || undefined }));
  };
  return (
    <section aria-label={entityId ? "Document history" : "Company audit log"}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">{entityId ? "History" : `Audit log${companyName ? ` · ${companyName}` : ""}`}</h2>
        <button className={BTN} disabled={loading} onClick={() => setReload((n) => n + 1)}>Refresh</button>
      </div>
      <div className="mb-4 grid grid-cols-2 gap-3">
        <label className="text-xs text-[var(--text-secondary)]">User
          <select className={`${INPUT} mt-1`} value={filters.user_id ?? ""} onChange={(e) => filter("user_id", e.target.value)}>
            <option value="">All users</option>
            {page?.users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </label>
        {!entityId && <label className="text-xs text-[var(--text-secondary)]">Entity
          <select className={`${INPUT} mt-1`} value={filters.entity ?? ""} onChange={(e) => filter("entity", e.target.value)}>
            <option value="">All entities</option>
            {ENTITIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>}
        <label className="text-xs text-[var(--text-secondary)]">From (Manila)
          <input className={`${INPUT} mt-1`} type="date" value={filters.date_from ?? ""} onChange={(e) => filter("date_from", e.target.value)} />
        </label>
        <label className="text-xs text-[var(--text-secondary)]">Through (Manila)
          <input className={`${INPUT} mt-1`} type="date" value={filters.date_to ?? ""} onChange={(e) => filter("date_to", e.target.value)} />
        </label>
        {!entityId && <label className="col-span-2 text-xs text-[var(--text-secondary)]">Entity ID
          <input className={`${INPUT} mt-1`} value={filters.entity_id ?? ""} onChange={(e) => filter("entity_id", e.target.value.trim())} />
        </label>}
      </div>
      {loading && <p role="status" className="py-3 text-sm text-[var(--text-secondary)]">Loading history…</p>}
      {error && <p role="alert" className="py-3 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {!loading && page && <>
        {page.events.length === 0 && <p className="py-6 text-sm text-[var(--text-secondary)]">No events match these filters.</p>}
        <ol className="space-y-3">{page.events.map((event) => (
          <li key={event.id} className="rounded-lg border border-[var(--border)] p-3 text-sm text-[var(--text-primary)]">
            <p className="font-medium">{event.user_name} · {event.action.replaceAll("_", " ")}</p>
            <p className="mt-1 text-xs text-[var(--text-secondary)]">
              {new Date(event.at).toLocaleString("en-PH", { timeZone: "Asia/Manila" })} (Manila) · {event.entity.replaceAll("_", " ")}
            </p>
            {!entityId && <p className="mt-1 break-all text-xs text-[var(--text-secondary)]">{event.entity_id}</p>}
            {event.reason && <p className="mt-2 whitespace-pre-wrap break-words">Reason: {event.reason}</p>}
            <EventDetails event={event} />
          </li>
        ))}</ol>
        <div className="mt-4 flex items-center gap-3">
          <button className={BTN} disabled={offset === 0} onClick={() => setOffset((n) => Math.max(0, n - 50))}>Previous</button>
          <span className="text-xs text-[var(--text-secondary)]">Page {offset / 50 + 1}</span>
          <button className={BTN} disabled={!page.has_more} onClick={() => setOffset((n) => n + 50)}>Next</button>
        </div>
      </>}
    </section>
  );
}
