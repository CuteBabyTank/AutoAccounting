"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { workApi } from "@/lib/work-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { Person, WorkHistory as History, WorkHistoryFilters } from "@/types/work";
import { BTN, Chip, INPUT, completionWhen, shortDate, todayIso } from "@/components/work/ui";

type Period = "month" | "last_month" | "quarter" | "custom";
const PAGE_SIZE = 50;

function periodDates(period: Period): { from: string; to: string } {
  const today = todayIso();
  const year = Number(today.slice(0, 4));
  const month = Number(today.slice(5, 7));
  if (period === "last_month") {
    const last = new Date(Date.UTC(year, month - 1, 0));
    return { from: `${last.toISOString().slice(0, 7)}-01`, to: last.toISOString().slice(0, 10) };
  }
  const firstMonth = period === "quarter" ? Math.floor((month - 1) / 3) * 3 + 1 : month;
  return { from: `${year}-${String(firstMonth).padStart(2, "0")}-01`, to: today };
}

/** Firm completion tracker. Employee visibility is also enforced by the history endpoint. */
export default function WorkHistory({ people, companies }: { people: Person[]; companies: { id: string; registered_name: string }[] }) {
  const { user } = useAuth();
  const ownOnly = user?.role === "employee";
  const [period, setPeriod] = useState<Period>("month");
  const [dates, setDates] = useState(() => periodDates("month"));
  const [custom, setCustom] = useState(dates);
  const [person, setPerson] = useState("");
  const [company, setCompany] = useState("");
  const [kind, setKind] = useState<"" | "task" | "filing">("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<History | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const filters: WorkHistoryFilters = { ...dates, person: ownOnly ? user?.id : person || undefined, company: company || undefined, kind: kind || undefined, offset, limit: PAGE_SIZE };
    workApi.history(filters)
      .then((next) => { if (!cancelled) setData(next); })
      .catch((e) => { if (!cancelled) setError(apiErrorMessage(e, "Couldn't load completion history")); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [dates, person, ownOnly, user?.id, company, kind, offset]);

  function changePeriod(next: Period) {
    setPeriod(next);
    if (next !== "custom") {
      const nextDates = periodDates(next);
      setDates(nextDates);
      setCustom(nextDates);
      setOffset(0);
    }
  }

  function applyDates(e: React.FormEvent) {
    e.preventDefault();
    if (!custom.from || !custom.to || custom.from > custom.to || (Date.parse(custom.to) - Date.parse(custom.from)) / 86400000 > 731) {
      setError("Choose a valid date range of up to two years.");
      return;
    }
    setDates({ ...custom });
    setOffset(0);
  }

  const personOptions = new Map(people.map((p) => [p.id, p.name]));
  for (const row of data?.summary ?? []) {
    if (row.person_id) personOptions.set(row.person_id, row.person_name);
  }

  return (
    <section aria-label="Completion history" className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="History period" className={INPUT} value={period} onChange={(e) => changePeriod(e.target.value as Period)}>
          <option value="month">This month</option><option value="last_month">Last month</option><option value="quarter">This quarter</option><option value="custom">Custom dates</option>
        </select>
        {!ownOnly && <select aria-label="Completed by" className={INPUT} value={person} onChange={(e) => { setPerson(e.target.value); setOffset(0); }}>
          <option value="">Everyone</option>{Array.from(personOptions).sort((a, b) => a[1].localeCompare(b[1])).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>}
        <select aria-label="History client" className={INPUT} value={company} onChange={(e) => { setCompany(e.target.value); setOffset(0); }}>
          <option value="">All clients</option>{companies.map((c) => <option key={c.id} value={c.id}>{c.registered_name}</option>)}
        </select>
        <select aria-label="History type" className={INPUT} value={kind} onChange={(e) => { setKind(e.target.value as typeof kind); setOffset(0); }}>
          <option value="">Tasks and filings</option><option value="task">Tasks</option><option value="filing">Filings</option>
        </select>
      </div>
      {period === "custom" && <form onSubmit={applyDates} className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-[var(--text-secondary)]">From<input aria-label="History from" type="date" className={`${INPUT} ml-2`} value={custom.from} onChange={(e) => setCustom((d) => ({ ...d, from: e.target.value }))} required /></label>
        <label className="text-xs text-[var(--text-secondary)]">To<input aria-label="History to" type="date" className={`${INPUT} ml-2`} value={custom.to} onChange={(e) => setCustom((d) => ({ ...d, to: e.target.value }))} required /></label>
        <button className={BTN} type="submit">Apply dates</button>
      </form>}
      <p className="text-xs text-[var(--text-secondary)]">{ownOnly ? "Your completions" : "Completions"} · {shortDate(dates.from)} to {shortDate(dates.to)}. Open now counts current open tasks and filings in the board&apos;s default due window (the window applies to filings). Completion times are Philippine time.</p>
      {error && <p role="alert" className="text-sm text-[var(--alert-error-text)]">{error}</p>}
      {loading ? <p className="py-6 text-sm text-[var(--text-secondary)]">Loading history…</p> : !error && data && <>
        {data.summary.length > 0 && <div className="overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)]">
          <table className="w-full text-left text-sm"><caption className="sr-only">Completion totals by person</caption>
            <thead className="text-xs text-[var(--text-secondary)]"><tr>{["Person", "Completed", "On time", "Late", "Open now"].map((label) => <th key={label} className="px-4 py-3 font-medium">{label}</th>)}</tr></thead>
            <tbody>{data.summary.map((s) => <tr key={s.person_id ?? "unknown"} className="border-t border-[var(--border)] text-[var(--text-primary)]">
              <th className="px-4 py-3 font-medium">{s.person_name || "Unknown"}</th><td className="px-4 py-3 tabular-nums">{s.completed}</td><td className="px-4 py-3 tabular-nums">{s.on_time}</td><td className="px-4 py-3 tabular-nums">{s.late}</td><td className="px-4 py-3 tabular-nums">{s.open_now}</td>
            </tr>)}</tbody>
          </table>
        </div>}
        {data.items.length === 0 ? <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-10 text-center text-sm text-[var(--text-secondary)]">No completed work in this period. Mark a task done or a return filed to start tracking completions, or choose another period.</div> : <div className="overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)]">
          <table className="w-full text-left text-sm"><caption className="sr-only">Completed tasks and filings, newest first</caption>
            <thead className="text-xs text-[var(--text-secondary)]"><tr>{["Completed", "Work", "Client", "Completed by", "Assigned to", "Due / timing"].map((label) => <th key={label} className="px-4 py-3 font-medium">{label}</th>)}</tr></thead>
            <tbody>{data.items.map((item) => <tr key={`${item.kind}:${item.source}:${item.id}`} className="border-t border-[var(--border)] align-top text-[var(--text-primary)]">
              <td className="whitespace-nowrap px-4 py-3">{completionWhen(item.completed_at, item.kind === "filing")}</td>
              <td className="px-4 py-3"><p className="font-medium">{item.title}</p><span className="text-xs text-[var(--text-secondary)]">{item.kind === "task" ? "Task" : item.source === "board" ? "Filing · work board" : "Filing · return version"}</span></td>
              <td className="px-4 py-3">{item.company_name || "Firm task"}</td><td className="px-4 py-3">{item.completed_by_name || "Unknown"}</td><td className="px-4 py-3">{item.assignee_name || "Unassigned"}</td>
              <td className="px-4 py-3"><div className="mb-1 text-xs text-[var(--text-secondary)]">{item.due_date ? shortDate(item.due_date) : "No due date"}</div>{item.on_time !== null && <Chip tone={item.on_time ? "green" : "red"}>{item.on_time ? "On time" : "Late"}</Chip>}</td>
            </tr>)}</tbody>
          </table>
        </div>}
        {data.total > 0 && <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-[var(--text-secondary)]">
          <span>{offset + 1}–{Math.min(offset + data.items.length, data.total)} of {data.total}</span>
          <div className="flex gap-2"><button className={BTN} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button><button className={BTN} disabled={offset + data.items.length >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button></div>
        </div>}
      </>}
    </section>
  );
}
