"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import PrivacyToggle from "@/components/accounting/PrivacyToggle";
import { ArrowSquareOut, Warning } from "@phosphor-icons/react";
import Hint from "@/components/guide/Hint";
import { GuideButton } from "@/components/guide/GuideTour";
import PageGuide from "@/components/guide/PageGuide";
import { WORK_TOUR } from "@/components/guide/tours";
import { WORK_SPOTS } from "@/components/guide/tours/spots";
import CompanyHealth from "@/components/work/CompanyHealth";
import TaskList from "@/components/work/TaskList";
import WorkHistory from "@/components/work/WorkHistory";
import { BTN, Chip, INPUT, STATUS_META, STATUS_ORDER, addDays, dueText, shortDate, todayIso } from "@/components/work/ui";
import { useGuide } from "@/lib/guides";
import { firmSettings, safeId, workApi } from "@/lib/work-api";
import { WORK_TARGET_EVENT, focusName } from "@/lib/focus";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { Board, BoardFilters, CompanySummary, FirmSettings, WorkCard, WorkItemInput } from "@/types/work";

type Tab = "filings" | "clients" | "tasks" | "history";
type Window = "default" | "next7" | "next30" | "overdue" | "year";

const WINDOWS: { value: Window; label: string }[] = [
  { value: "default", label: "Last 90 days and next 45" },
  { value: "next7", label: "Due in the next 7 days" },
  { value: "next30", label: "Due in the next 30 days" },
  { value: "overdue", label: "Overdue (past year)" },
  { value: "year", label: "This calendar year" },
];

function windowDates(w: Window): Pick<BoardFilters, "start" | "end"> {
  const today = todayIso();
  switch (w) {
    case "next7":
      return { start: today, end: addDays(today, 7) };
    case "next30":
      return { start: today, end: addDays(today, 30) };
    case "overdue":
      return { start: addDays(today, -365), end: addDays(today, -1) };
    case "year":
      return { start: `${today.slice(0, 4)}-01-01`, end: `${today.slice(0, 4)}-12-31` };
    default:
      return {};
  }
}

const TABS: Tab[] = ["filings", "clients", "tasks", "history"];

const itemKey = (c: WorkCard): Pick<WorkItemInput, "company_id" | "year" | "quarter" | "form"> => ({
  company_id: c.company_id,
  year: c.year,
  quarter: c.quarter,
  form: c.form,
});

export default function WorkBoardPage() {
  const [tab, setTab] = useState<Tab>("filings");
  const [board, setBoard] = useState<Board | null>(null);
  const [settings, setSettings] = useState<FirmSettings | null>(null);
  const [company, setCompany] = useState("");
  const [win, setWin] = useState<Window>("default");
  const [status, setStatus] = useState("open");
  const [assignee, setAssignee] = useState("");
  const [filing, setFiling] = useState<{ key: string; date: string } | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [assigning, setAssigning] = useState(false);
  const [handlerBusy, setHandlerBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const guide = useGuide("work");
  const loadId = useRef(0);

  useEffect(() => {
    const open = (params: URLSearchParams) => {
      const t = params.get("tab");
      setTab(t === "clients" || t === "tasks" || t === "history" ? t : "filings");
      setCompany(safeId(params.get("company")) ?? "");
    };
    open(new URLSearchParams(window.location.search));
    firmSettings().then(setSettings).catch(() => undefined);
    // a notification clicked while already here: show everything not yet filed so its card is on the list
    const onTarget = (e: Event) => {
      const detail = (e as CustomEvent<unknown>).detail;
      if (typeof detail !== "string") return;
      setWin("default");
      setStatus("open");
      setAssignee("");
      open(new URLSearchParams(detail));
    };
    window.addEventListener(WORK_TARGET_EVENT, onTarget);
    return () => window.removeEventListener(WORK_TARGET_EVENT, onTarget);
  }, []);

  const load = useCallback(async () => {
    const requestId = ++loadId.current;
    setLoading(true);
    setError("");
    try {
      // Status / assignee filter on the client so the Clients tab keeps every company's counts.
      const next = await workApi.board({ ...windowDates(win), company_id: company || undefined });
      if (requestId === loadId.current) setBoard(next);
    } catch (e) {
      if (requestId === loadId.current) setError(apiErrorMessage(e, "Couldn't load the work board"));
    } finally {
      if (requestId === loadId.current) setLoading(false);
    }
  }, [win, company]);

  useEffect(() => {
    load();
    return () => { loadId.current += 1; };
  }, [load]);

  const cards = useMemo(() => {
    return (board?.cards ?? []).filter(
      (c) =>
        (status === "all" || (status === "open" ? c.status !== "filed" : c.status === status)) &&
        (!assignee || (assignee === "unassigned" ? !c.assignee_id : c.assignee_id === assignee)),
    );
  }, [board, status, assignee]);
  const overdue = cards.filter((c) => c.overdue).length;
  const companies = useMemo(
    () => (board?.companies ?? []).map((s) => ({ id: s.company_id, registered_name: s.company_name })),
    [board],
  );

  async function update(c: WorkCard, change: Partial<WorkItemInput>) {
    setError("");
    try {
      const next = await workApi.updateItem({ ...itemKey(c), ...change });
      setBoard((b) => (b ? { ...b, cards: b.cards.map((x) => (x.key === next.key ? next : x)) } : b));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't update the filing"));
    }
  }

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 8000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  async function autoAssign(companyId = company) {
    setAssigning(true);
    setError("");
    try {
      const result = await workApi.autoAssign({ start: board?.start, end: board?.end, company_id: companyId || undefined });
      setNotice(result.total ? `Assigned ${result.total}: ${result.people.map((p) => `${p.name} ${p.count}`).join(", ")}` : "No unassigned open items in this window.");
      setRefreshKey((n) => n + 1);
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't auto-assign work"));
    } finally {
      setAssigning(false);
    }
  }

  async function setHandler(summary: CompanySummary, handlerId: string | null) {
    setHandlerBusy(summary.company_id);
    setError("");
    try {
      const result = await workApi.setHandler(summary.company_id, handlerId);
      setBoard((b) => b ? { ...b, companies: b.companies.map((c) => c.company_id === summary.company_id ? { ...c, handler_id: result.handler_id } : c) } : b);
      if (handlerId && settings?.auto_assign && summary.unassigned_open_items > 0) {
        const name = board?.people.find((p) => p.id === handlerId)?.name || "this handler";
        if (window.confirm(`Also give ${name} this client's ${summary.unassigned_open_items} unassigned open items in the current board window?`)) await autoAssign(summary.company_id);
      }
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't update the client handler"));
    } finally {
      setHandlerBusy(null);
    }
  }

  const autoAssignControl = settings?.can_auto_assign && settings.auto_assign ? (
    <button className={BTN} disabled={assigning || loading || !board} onClick={() => autoAssign()} title="Assign every unassigned open task and not-filed return in the current board window">
      {assigning ? "Assigning…" : "Auto-assign"}
    </button>
  ) : null;
  const canFile = settings?.can_file ?? true;
  const shownCompanies: CompanySummary[] = (board?.companies ?? []).filter((s) => !company || s.company_id === company);

  return (
    <div className="lp relative min-h-screen">
      <div className="p-4 sm:p-8 page-enter">
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <div className="mr-auto min-w-[16rem] flex-1">
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">Work</h1>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">Every client&apos;s BIR returns by due date, their health and the firm&apos;s tasks, assignments and completion history.</p>
          </div>
          <PrivacyToggle />
          <GuideButton open={guide.open} onClick={guide.toggle} />
        </div>
        <PageGuide open={guide.open} onClose={guide.dismiss} label="Work" spots={WORK_SPOTS} slides={WORK_TOUR} />

        <div data-tour="work-filters" className="mb-4 flex flex-wrap items-center gap-2">
          <div role="tablist" data-tour="work-tabs" className="flex rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-0.5">
            {TABS.map((t) => (
              <button
                key={t}
                role="tab"
                id={`work-tab-${t}`}
                aria-controls={`work-panel-${t}`}
                tabIndex={tab === t ? 0 : -1}
                onKeyDown={(e) => {
                  const current = TABS.indexOf(t);
                  const next = e.key === "ArrowRight" ? (current + 1) % TABS.length : e.key === "ArrowLeft" ? (current + TABS.length - 1) % TABS.length : e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1 : -1;
                  if (next < 0) return;
                  e.preventDefault();
                  setTab(TABS[next]);
                  document.getElementById(`work-tab-${TABS[next]}`)?.focus();
                }}
                data-tour={t === "history" ? "work-history" : undefined}
                aria-selected={tab === t}
                onClick={() => setTab(t)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium ${tab === t ? "bg-[var(--accent-subtle)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}
              >
                {t === "filings" ? "Filings" : t === "clients" ? "Clients" : t === "tasks" ? "Tasks" : "History"}
              </button>
            ))}
          </div>
          {(tab === "filings" || tab === "clients") && (
            <select aria-label="Client" className={INPUT} value={company} onChange={(e) => setCompany(e.target.value)}>
              <option value="">All clients</option>
              {companies.map((c) => <option key={c.id} value={c.id}>{c.registered_name}</option>)}
            </select>
          )}
          {tab === "filings" && (
            <>
              <select aria-label="Due window" className={INPUT} value={win} onChange={(e) => setWin(e.target.value as Window)}>
                {WINDOWS.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
              </select>
              <select aria-label="Status" className={INPUT} value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="open">Not filed</option>
                <option value="all">Any status</option>
                {STATUS_ORDER.map((s) => <option key={s} value={s}>{STATUS_META[s].label}</option>)}
              </select>
              <select aria-label="Assigned to" className={INPUT} value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                <option value="">Anyone</option>
                <option value="unassigned">Nobody yet</option>
                {(board?.people ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              {autoAssignControl}
              <Hint align="left">
                One row per return a client owes, from its company profile: VAT or percentage tax, income tax, withholding
                and the annual return, plus the 1604-C for employers. Status follows the documents: none yet, documents in,
                some need review, a version generated, filed. Pick a status to override it; a real filing always wins.
              </Hint>
            </>
          )}
        </div>

        {notice && <div role="status" className="fixed bottom-5 left-4 right-4 z-40 flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-3 text-sm text-[var(--text-primary)] shadow-lg sm:left-auto sm:max-w-lg">
          <span>{notice}</span><button className="ml-auto text-[var(--text-secondary)] hover:text-[var(--text-primary)]" aria-label="Dismiss assignment result" onClick={() => setNotice("")}>×</button>
        </div>}
        {settings?.approve_before_close && (
          <p className="mb-3 text-xs text-[var(--text-secondary)]">
            Managers approve filing: only managers and the firm owner can mark returns filed or close a month.
          </p>
        )}
        {error && (
          <div className="mb-4 rounded-lg border border-[var(--alert-error-border)] bg-[var(--alert-error-bg)] px-4 py-2 text-sm text-[var(--alert-error-text)]">
            {error}
          </div>
        )}

        {tab === "filings" && (
          <section role="tabpanel" id="work-panel-filings" aria-labelledby="work-tab-filings" data-tour="work-board" className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)]">
            {overdue > 0 && (
              <p className="flex items-center gap-1.5 border-b border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--badge-red-text)]">
                <Warning size={16} /> {overdue} overdue
              </p>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-[var(--text-secondary)]">
                    <th className="px-4 py-3 font-medium">Due</th>
                    <th className="px-4 py-3 font-medium">Client</th>
                    <th className="px-4 py-3 font-medium">Return</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Assigned to</th>
                    <th className="px-4 py-3 font-medium">
                      Filed <Hint align="left">Marking a version filed on the quarter posts the payment in the books. Mark filed here only for a return filed outside AutoAccounting; it doesn&apos;t touch the books.</Hint>
                    </th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {cards.map((c) => (
                    <tr key={c.key} data-focus={focusName.card(c.key)} className={`border-t border-[var(--border)] align-top text-[var(--text-primary)] ${c.overdue ? "bg-[var(--badge-red-bg)]/40" : ""}`}>
                      <td className="whitespace-nowrap px-4 py-3">
                        <div className={c.overdue ? "font-semibold text-[var(--badge-red-text)]" : ""}>{shortDate(c.due_date)}</div>
                        {c.status !== "filed" && (
                          <div className={`text-xs ${c.overdue ? "text-[var(--badge-red-text)]" : "text-[var(--text-secondary)]"}`}>{dueText(c.days_left)}</div>
                        )}
                      </td>
                      <td className="px-4 py-3">{c.company_name}</td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <span className="font-medium">{c.form_label}</span> <span className="text-[var(--text-secondary)]">{c.period_label}</span>
                        <div className="text-xs text-[var(--text-secondary)]">
                          {c.documents} {c.form === "1604C" ? "employee" : "document"}{c.documents === 1 ? "" : "s"}
                          {c.open_reviews > 0 && ` · ${c.open_reviews} to review`}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Chip tone={STATUS_META[c.status].tone}>{STATUS_META[c.status].label}</Chip>
                          {c.status !== "filed" && (
                            <select
                              aria-label={`Status of ${c.form_label} ${c.period_label} for ${c.company_name}`}
                              className={`${INPUT} py-0.5 text-xs`}
                              value={c.status_override}
                              onChange={(e) => update(c, { status_override: e.target.value as WorkItemInput["status_override"] })}
                            >
                              <option value="">Automatic ({STATUS_META[c.auto_status].label.toLowerCase()})</option>
                              {STATUS_ORDER.filter((s) => s !== "filed").map((s) => <option key={s} value={s}>{STATUS_META[s].label}</option>)}
                            </select>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <select
                          aria-label={`Assignee of ${c.form_label} ${c.period_label} for ${c.company_name}`}
                          className={`${INPUT} py-0.5 text-xs`}
                          value={c.assignee_id ?? ""}
                          onChange={(e) => update(c, { assignee_id: e.target.value || null })}
                        >
                          <option value="">Nobody yet</option>
                          {(board?.people ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </select>
                        {c.assignee_id && c.assigned_auto && <span className="ml-1.5"><Chip tone="blue" title="Automatically assigned">Auto</Chip></span>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs">
                        {c.filed_on ? (
                          <span className="flex items-center gap-2">
                            {shortDate(c.filed_on)}
                            {c.filed_source === "board" ? (
                              canFile && <button className="text-[var(--accent)] hover:underline" onClick={() => update(c, { filed_on: null })}>Undo</button>
                            ) : (
                              <span className="text-[var(--text-secondary)]">from the return</span>
                            )}
                          </span>
                        ) : filing?.key === c.key ? (
                          <span className="flex items-center gap-1">
                            <input type="date" aria-label="Filed on" className={`${INPUT} py-0.5 text-xs`} max={todayIso()} value={filing.date} onChange={(e) => setFiling({ key: c.key, date: e.target.value })} />
                            <button
                              className="font-medium text-[var(--accent)] hover:underline"
                              onClick={async () => {
                                await update(c, { filed_on: filing.date });
                                setFiling(null);
                              }}
                            >
                              Save
                            </button>
                            <button className="text-[var(--text-secondary)] hover:underline" onClick={() => setFiling(null)}>Cancel</button>
                          </span>
                        ) : canFile ? (
                          <button className="text-[var(--accent)] hover:underline" onClick={() => setFiling({ key: c.key, date: todayIso() })}>Mark filed</button>
                        ) : (
                          <span className="text-[var(--text-secondary)]" title="Your firm has managers approve filings">Manager marks filed</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link href={`/accounting?company=${encodeURIComponent(c.company_id)}`} aria-label={`Open ${c.company_name}`} className="inline-flex rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]">
                          <ArrowSquareOut size={16} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!loading && cards.length === 0 && (
              <p className="px-4 py-10 text-center text-sm text-[var(--text-secondary)]">
                {board?.cards.length ? "Nothing matches these filters." : "No returns due in this window. Add clients on Companies and their returns show up here."}
              </p>
            )}
            {loading && <p className="px-4 py-10 text-center text-sm text-[var(--text-secondary)]">Loading…</p>}
          </section>
        )}

        {tab === "clients" && (
          <div role="tabpanel" id="work-panel-clients" aria-labelledby="work-tab-clients" className="grid grid-cols-1 gap-3 lg:grid-cols-2 2xl:grid-cols-3">
            {shownCompanies.map((s) => {
              const open = expanded.has(s.company_id);
              const counts: [string, number][] = [
                ["overdue returns", s.overdue_filings],
                ["to review", s.open_reviews],
                ["bank lines to match", s.unmatched_bank_lines],
                ["bank months not reconciled", s.unreconciled_months],
                ["months not closed", s.months_not_closed],
                ["open tasks", s.open_tasks],
              ];
              const issues = counts.filter(([, n]) => n > 0);
              return (
                <section key={s.company_id} className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
                  <div className="flex items-start gap-2">
                    <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-[var(--text-primary)]">{s.company_name}</h2>
                    <Link href={`/accounting?company=${encodeURIComponent(s.company_id)}`} className="text-xs font-medium text-[var(--accent)] hover:underline">Overview</Link>
                  </div>
                  <div className="mt-3 flex items-center gap-2 text-xs text-[var(--text-secondary)]">
                    <label htmlFor={`handler-${s.company_id}`}>Handler</label>
                    <select id={`handler-${s.company_id}`} className={`${INPUT} min-w-0 flex-1 text-xs`} value={s.handler_id ?? ""} disabled={!settings?.can_auto_assign || handlerBusy !== null || assigning} onChange={(e) => setHandler(s, e.target.value || null)}>
                      <option value="">No handler</option>
                      {(board?.people ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {issues.length === 0 ? (
                      <Chip tone="green">Nothing waiting</Chip>
                    ) : (
                      issues.map(([label, n]) => (
                        <Chip key={label} tone={label === "overdue returns" ? "red" : "yellow"}>{n} {label}</Chip>
                      ))
                    )}
                    {!s.books_on && <Chip>Books off</Chip>}
                  </div>
                  <button
                    className={`${BTN} mt-3 py-1 text-xs`}
                    onClick={() => setExpanded((prev) => {
                      const next = new Set(prev);
                      if (next.has(s.company_id)) next.delete(s.company_id);
                      else next.add(s.company_id);
                      return next;
                    })}
                  >
                    {open ? "Hide health check" : "Full health check"}
                  </button>
                  {open && <div className="mt-3"><CompanyHealth companyId={s.company_id} compact /></div>}
                </section>
              );
            })}
            {!loading && shownCompanies.length === 0 && (
              <p className="py-10 text-center text-sm text-[var(--text-secondary)]">No clients yet.</p>
            )}
          </div>
        )}

        {tab === "tasks" && (
          <section role="tabpanel" id="work-panel-tasks" aria-labelledby="work-tab-tasks" className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
            <TaskList companies={companies} people={board?.people ?? []} onChanged={load} refreshKey={refreshKey} autoAssignControl={autoAssignControl && <div className="flex flex-wrap items-center gap-2">
              {autoAssignControl}
              <span className="text-xs text-[var(--text-secondary)]">{company ? board?.companies.find((c) => c.company_id === company)?.company_name || "Selected client" : "All clients"}{board ? ` · due ${shortDate(board.start)}–${shortDate(board.end)}` : ""}</span>
            </div>} />
          </section>
        )}
        {tab === "history" && <div role="tabpanel" id="work-panel-history" aria-labelledby="work-tab-history"><WorkHistory people={board?.people ?? []} companies={companies} /></div>}
      </div>
    </div>
  );
}
