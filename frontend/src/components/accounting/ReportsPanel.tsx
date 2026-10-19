"use client";

import { useEffect, useMemo, useState } from "react";
import { DownloadSimple, Warning } from "@phosphor-icons/react";
import Hint from "@/components/guide/Hint";
import ManagementPackSection from "@/components/accounting/ManagementPackSection";
import ReportDrill, { type DrillTarget } from "@/components/accounting/ReportDrill";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, formatAmount, saveBlob } from "@/lib/accounting-format";
import { PreviewButton, useFilePreview } from "@/components/accounting/PdfPreview";
import { PRESETS, presetRange, type PresetKey } from "@/lib/report-periods";
import { BTN, Chip, INPUT, shortDate } from "@/components/work/ui";
import type {
  AdjustingRow, InvalidRow, Report, ReportGridRow, ReportKind, ReportParams, TransactionRow,
} from "@/types/accounting";

interface Props {
  companyId: string;
  companyName: string;
  fiscalYearEndMonth: number;
  onOpenDocument: (id: string, page?: number) => void;
}

const REPORTS: { kind: ReportKind; label: string }[] = [
  { kind: "pnl", label: "Profit and loss" },
  { kind: "balance-sheet", label: "Balance sheet" },
  { kind: "gl", label: "General ledger detail" },
  { kind: "transactions", label: "Transaction list by date" },
  { kind: "adjusted-tb", label: "Adjusted trial balance" },
  { kind: "adjusting", label: "Adjusting journal entries" },
  { kind: "invalid", label: "Invalid journal transactions" },
];
const GRID: ReportKind[] = ["pnl", "balance-sheet", "adjusted-tb"];
const COLUMNS: ReportKind[] = ["pnl", "balance-sheet"];
const FILTERS: ReportKind[] = ["gl", "transactions"];
const LABEL = "block text-[11px] font-medium text-[var(--text-secondary)] mb-1";
const TH_BASE = "px-2 py-1.5 text-[11px] font-semibold text-[var(--text-secondary)] whitespace-nowrap";
const TH = `${TH_BASE} text-right`;
const THL = `${TH_BASE} text-left`;
const TD = "px-2 py-1 text-right tabular-nums whitespace-nowrap";

/** Company → Reports: live reports from the books with drill-down to the source, exports and the management pack. */
export default function ReportsPanel({ companyId, companyName, fiscalYearEndMonth, onOpenDocument }: Props) {
  const [kind, setKind] = useState<ReportKind>("pnl");
  const [preset, setPreset] = useState<PresetKey>("this_quarter");
  const initial = presetRange("this_quarter", new Date(), fiscalYearEndMonth);
  const [start, setStart] = useState(initial.start);
  const [end, setEnd] = useState(initial.end);
  const [by, setBy] = useState<"total" | "month" | "quarter">("total");
  const [compare, setCompare] = useState<"none" | "period" | "year">("none");
  const [nonzero, setNonzero] = useState(true);
  const [thousands, setThousands] = useState(false);
  const [account, setAccount] = useState("");
  const [party, setParty] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [drill, setDrill] = useState<DrillTarget | null>(null);
  const file = useFilePreview();

  const params: ReportParams = useMemo(() => ({
    start, end,
    ...(COLUMNS.includes(kind) ? { by: compare === "none" ? by : "total", compare } : {}),
    ...(GRID.includes(kind) ? { nonzero, thousands } : {}),
    ...(FILTERS.includes(kind) ? { ...(account ? { account } : {}), ...(party.trim() ? { party: party.trim() } : {}) } : {}),
  }), [kind, start, end, by, compare, nonzero, thousands, account, party]);

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      setLoading(true);
      setError("");
      accountingApi
        .report(companyId, kind, params)
        .then((r) => !cancelled && setReport(r))
        .catch((e) => {
          if (cancelled) return;
          setReport(null);
          setError(apiErrorMessage(e, "Couldn't build the report"));
        })
        .finally(() => !cancelled && setLoading(false));
    }, 250); // typing a party or a date doesn't fire a request per keystroke
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [companyId, kind, params]);

  const choosePreset = (key: PresetKey) => {
    setPreset(key);
    if (key === "custom") return;
    const range = presetRange(key, new Date(), fiscalYearEndMonth);
    setStart(range.start);
    setEnd(range.end);
  };

  const exportAs = async (format: "xlsx" | "pdf") => {
    try {
      const blob = await accountingApi.reportFile(companyId, kind, params, format);
      const title = REPORTS.find((r) => r.kind === kind)?.label ?? kind;
      saveBlob(blob, `${companyName} ${title} ${start} to ${end}.${format}`);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't export the report"));
    }
  };

  const showDates = kind !== "invalid";
  return (
    <div className="mb-6">
      <h2 className="mb-3 flex items-center gap-1 text-base font-semibold text-[var(--text-primary)]">
        Reports · {companyName}
        <Hint align="right">
          Built live from the books (accrual basis), so they always match the journals and ledger. Click any amount to see
          the postings behind it, then open the document page, journal entry or bank line each came from. Export to
          Excel or PDF from here; the management pack for a quarter is at the bottom.
        </Hint>
      </h2>

      <div className="mb-3 flex flex-wrap gap-1.5">
        {REPORTS.map((r) => (
          <button key={r.kind} onClick={() => setKind(r.kind)}
            className={`rounded-full border px-3 py-1 text-xs font-medium ${kind === r.kind
              ? "border-[var(--accent)] bg-[var(--accent-subtle)] text-[var(--text-primary)]"
              : "border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"}`}>
            {r.label}
          </button>
        ))}
      </div>

      <div className="mb-3 flex flex-wrap items-end gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-3">
        {showDates && (
          <>
            <div>
              <label className={LABEL} htmlFor="rp-preset">Period</label>
              <select id="rp-preset" className={INPUT} value={preset} onChange={(e) => choosePreset(e.target.value as PresetKey)}>
                {PRESETS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="rp-start">{kind === "balance-sheet" || kind === "adjusted-tb" ? "From (columns)" : "From"}</label>
              <input id="rp-start" type="date" className={INPUT} value={start}
                onChange={(e) => { setPreset("custom"); setStart(e.target.value); }} />
            </div>
            <div>
              <label className={LABEL} htmlFor="rp-end">{kind === "balance-sheet" || kind === "adjusted-tb" ? "As of" : "To"}</label>
              <input id="rp-end" type="date" className={INPUT} value={end}
                onChange={(e) => { setPreset("custom"); setEnd(e.target.value); }} />
            </div>
          </>
        )}
        {COLUMNS.includes(kind) && (
          <>
            <div>
              <label className={LABEL} htmlFor="rp-by">Columns</label>
              <select id="rp-by" className={INPUT} value={compare === "none" ? by : "total"} disabled={compare !== "none"}
                onChange={(e) => setBy(e.target.value as typeof by)}>
                <option value="total">Total only</option>
                <option value="month">Months</option>
                <option value="quarter">Quarters</option>
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="rp-compare">Compare to</label>
              <select id="rp-compare" className={INPUT} value={compare} onChange={(e) => setCompare(e.target.value as typeof compare)}>
                <option value="none">Nothing</option>
                <option value="period">Previous period</option>
                <option value="year">Same period last year</option>
              </select>
            </div>
          </>
        )}
        {GRID.includes(kind) && (
          <div className="flex flex-col gap-1 text-xs text-[var(--text-primary)]">
            {kind !== "adjusted-tb" && (
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={nonzero} onChange={(e) => setNonzero(e.target.checked)} /> Non-zero rows only
              </label>
            )}
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={thousands} onChange={(e) => setThousands(e.target.checked)} /> In thousands (÷1000)
            </label>
          </div>
        )}
        {FILTERS.includes(kind) && (
          <>
            <div>
              <label className={LABEL} htmlFor="rp-account">Account code</label>
              <input id="rp-account" className={`${INPUT} w-24`} maxLength={10} value={account}
                onChange={(e) => setAccount(e.target.value.replace(/\D/g, ""))} placeholder="All" />
            </div>
            <div>
              <label className={LABEL} htmlFor="rp-party">Customer / supplier</label>
              <input id="rp-party" className={`${INPUT} w-48`} maxLength={120} value={party}
                onChange={(e) => setParty(e.target.value)} placeholder="Name or TIN" />
            </div>
          </>
        )}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-[var(--text-secondary)]" title="The books post on the accrual basis; a cash-basis view isn't available yet.">
            Accrual basis
          </span>
          <button className={BTN} onClick={() => exportAs("xlsx")} disabled={!report}><DownloadSimple size={14} /> Excel</button>
          <PreviewButton compact label="Preview PDF" disabled={!report} onClick={() => {
            const title = REPORTS.find((r) => r.kind === kind)?.label ?? kind;
            file.open(`${title} · ${start} to ${end}`, () => accountingApi.reportFile(companyId, kind, params, "pdf"),
              `${companyName} ${title} ${start} to ${end}.pdf`);
          }} />
          <button className={BTN} onClick={() => exportAs("pdf")} disabled={!report}><DownloadSimple size={14} /> PDF</button>
          {file.node}
        </div>
      </div>

      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {loading && !report && <p className="text-sm text-[var(--text-secondary)]">Building the report…</p>}
      {report && report.kind === kind && (
        <div className={loading ? "opacity-60" : ""}>
          <p className="mb-2 text-xs text-[var(--text-secondary)]">
            {report.subtitle}
            {report.balanced === false && <span className="ml-2"><Chip tone="red">Doesn&apos;t balance</Chip></span>}
          </p>
          {GRID.includes(kind) && <GridReport report={report} onDrill={setDrill} />}
          {kind === "gl" && <GlReport report={report} onEntry={setDrill} />}
          {kind === "transactions" && <TransactionsReport rows={(report.rows ?? []) as TransactionRow[]} onEntry={setDrill} />}
          {kind === "adjusting" && <AdjustingReport rows={(report.rows ?? []) as AdjustingRow[]} onEntry={setDrill} />}
          {kind === "invalid" && <InvalidReport report={report} onEntry={setDrill} />}
        </div>
      )}

      <ManagementPackSection companyId={companyId} companyName={companyName} fiscalYearEndMonth={fiscalYearEndMonth} />

      {drill && (
        <ReportDrill companyId={companyId} target={drill} onClose={() => setDrill(null)} onOpenDocument={onOpenDocument} />
      )}
    </div>
  );
}

function cell(value: string | null, kind: string): string {
  if (value === null) return "";
  return kind === "pct" ? `${Number(value).toLocaleString("en-PH", { maximumFractionDigits: 2 })}%` : formatAmount(value);
}

function GridReport({ report, onDrill }: { report: Report; onDrill: (t: DrillTarget) => void }) {
  const columns = report.columns ?? [];
  const rows = (report.rows ?? []) as ReportGridRow[];
  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--bg-primary)]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--border)]">
            <th className={`${THL}`}>{report.kind === "adjusted-tb" ? "Account (debit +, credit −)" : "Account"}</th>
            {columns.map((c) => <th key={c.key} className={TH}>{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className={r.kind === "total" ? "border-t border-[var(--border)] font-semibold" : ""}>
              <td className={`px-2 py-1 text-[var(--text-primary)] ${r.kind === "header" ? "pt-3 font-semibold" : ""}`}
                style={{ paddingLeft: `${0.5 + r.level * 1.25}rem` }}>
                {r.label}
              </td>
              {r.values.map((v, i) => {
                const d = r.drill[i];
                const text = cell(v, columns[i]?.kind ?? "amount");
                return (
                  <td key={i} className={TD}>
                    {d && v !== null && Number(v) !== 0 ? (
                      <button className="text-[var(--accent)] hover:underline"
                        title="Show the postings behind this amount"
                        onClick={() => onDrill({ mode: "postings", label: `${r.label} · ${columns[i]?.label ?? ""}`, codes: r.codes, start: d.start, end: d.end })}>
                        {text}
                      </button>
                    ) : (
                      <span className="text-[var(--text-primary)]">{text}</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {report.thousands && <p className="px-2 py-1 text-[11px] text-[var(--text-secondary)]">Amounts in thousands of pesos.</p>}
    </div>
  );
}

function entryTarget(entryId: string, label: string): DrillTarget {
  return { mode: "entry", entryId, label };
}

function GlReport({ report, onEntry }: { report: Report; onEntry: (t: DrillTarget) => void }) {
  const accounts = report.accounts ?? [];
  if (accounts.length === 0) return <p className="text-sm text-[var(--text-secondary)]">No postings in this period.</p>;
  return (
    <div className="space-y-4">
      {accounts.map((a) => (
        <div key={a.code} className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--bg-primary)]">
          <p className="border-b border-[var(--border)] px-2 py-1.5 text-sm font-semibold text-[var(--text-primary)]">{a.code} {a.name}</p>
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className={`${THL}`}>Date</th><th className={`${THL}`}>Ref</th>
                <th className={`${THL}`}>Particulars</th><th className={TH}>Debit</th><th className={TH}>Credit</th><th className={TH}>Balance</th>
              </tr>
            </thead>
            <tbody>
              <tr><td className="px-2 py-1 text-[var(--text-secondary)]" colSpan={5}>Opening balance</td><td className={TD}>{formatAmount(a.opening)}</td></tr>
              {a.lines.map((l, i) => (
                <tr key={`${l.entry_id}-${i}`} className="cursor-pointer hover:bg-[var(--bg-hover)]"
                  onClick={() => onEntry(entryTarget(l.entry_id, `${a.code} ${a.name} · ${l.particulars || l.reference}`))}>
                  <td className="whitespace-nowrap px-2 py-1 text-[var(--text-secondary)]">{shortDate(l.date)}</td>
                  <td className="whitespace-nowrap px-2 py-1 text-[var(--text-secondary)]">{l.book} {l.reference}</td>
                  <td className="px-2 py-1 text-[var(--text-primary)]">{l.particulars}{l.party && <span className="text-[var(--text-secondary)]"> · {l.party}</span>}</td>
                  <td className={TD}>{Number(l.debit) ? formatAmount(l.debit) : ""}</td>
                  <td className={TD}>{Number(l.credit) ? formatAmount(l.credit) : ""}</td>
                  <td className={TD}>{formatAmount(l.balance ?? "0")}</td>
                </tr>
              ))}
              <tr className="border-t border-[var(--border)] font-semibold"><td className="px-2 py-1" colSpan={5}>Closing balance</td><td className={TD}>{formatAmount(a.closing)}</td></tr>
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

function TransactionsReport({ rows, onEntry }: { rows: TransactionRow[]; onEntry: (t: DrillTarget) => void }) {
  if (rows.length === 0) return <p className="text-sm text-[var(--text-secondary)]">No transactions in this period.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--bg-primary)]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--border)]">
            <th className={`${THL}`}>Date</th><th className={`${THL}`}>Ref</th><th className={`${THL}`}>Party</th>
            <th className={`${THL}`}>Particulars</th><th className={`${THL}`}>Accounts</th><th className={TH}>Amount</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.entry_id} className="cursor-pointer hover:bg-[var(--bg-hover)]" onClick={() => onEntry(entryTarget(r.entry_id, r.particulars || r.reference))}>
              <td className="whitespace-nowrap px-2 py-1 text-[var(--text-secondary)]">{shortDate(r.date)}</td>
              <td className="whitespace-nowrap px-2 py-1 text-[var(--text-secondary)]">{r.book} {r.reference}</td>
              <td className="px-2 py-1 text-[var(--text-primary)]">{r.party}</td>
              <td className="px-2 py-1 text-[var(--text-primary)]">{r.particulars}</td>
              <td className="px-2 py-1 text-xs text-[var(--text-secondary)]" title={r.account_names.join(", ")}>{r.accounts.join(", ")}</td>
              <td className={TD}>{formatAmount(r.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AdjustingReport({ rows, onEntry }: { rows: AdjustingRow[]; onEntry: (t: DrillTarget) => void }) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-[var(--text-secondary)]">
        No adjusting entries in this period. Tick &quot;Adjusting entry&quot; on a journal entry under Books to list it here;
        depreciation and inventory counts are listed automatically.
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {rows.map((e) => (
        <li key={e.entry_id} className="rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-2">
          <button className="flex w-full flex-wrap items-baseline gap-2 text-left text-sm" onClick={() => onEntry(entryTarget(e.entry_id, e.particulars || e.reference))}>
            <span className="text-[var(--text-secondary)]">{shortDate(e.date)}</span>
            <Chip tone={e.kind === "Adjusting journal entry" ? "blue" : "gray"}>{e.kind}</Chip>
            <span className="flex-1 text-[var(--text-primary)]">{e.particulars} {e.reference && <span className="text-[var(--text-secondary)]">· {e.reference}</span>}</span>
            <span className="tabular-nums">{formatAmount(e.amount)}</span>
          </button>
          <table className="mt-1 w-full text-xs">
            <tbody>
              {e.lines.map((l, i) => (
                <tr key={i}>
                  <td className="py-0.5 pl-4 text-[var(--text-secondary)]">{l.code} {l.name}</td>
                  <td className={TD}>{Number(l.debit) ? formatAmount(l.debit) : ""}</td>
                  <td className={TD}>{Number(l.credit) ? formatAmount(l.credit) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </li>
      ))}
    </ul>
  );
}

function InvalidReport({ report, onEntry }: { report: Report; onEntry: (t: DrillTarget) => void }) {
  const rows = (report.rows ?? []) as InvalidRow[];
  if (rows.length === 0) {
    return <p className="text-sm text-[var(--badge-green-text)]">Every entry balances and posts to an active account in the chart.</p>;
  }
  return (
    <ul className="divide-y divide-[var(--border)] rounded-lg border border-[var(--border)] bg-[var(--bg-primary)]">
      {rows.map((r, i) => (
        <li key={`${r.entry_id}-${r.problem}-${i}`} className="flex flex-wrap items-baseline gap-2 px-3 py-2 text-sm">
          <Warning size={14} className="self-center text-[var(--alert-error-text)]" />
          <span className="font-medium text-[var(--text-primary)]">{r.label}</span>
          <span className="text-[var(--text-secondary)]">{r.detail}</span>
          <span className="ml-auto text-xs text-[var(--text-secondary)]">{r.date ? shortDate(r.date) : ""} {r.reference}</span>
          {r.entry_id && (
            <button className="text-xs text-[var(--accent)]" onClick={() => onEntry(entryTarget(r.entry_id, r.label))}>Source</button>
          )}
        </li>
      ))}
    </ul>
  );
}
