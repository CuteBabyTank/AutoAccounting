"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import AmountInput from "@/components/AmountInput";
import { CaretDown, CaretRight, FileXls, Plus, Spinner, Trash } from "@phosphor-icons/react";
import OutputViewer from "@/components/accounting/OutputViewer";
import Hint from "@/components/guide/Hint";
import { accountingApi } from "@/lib/accounting-api";
import { FILING_LOCKED_TITLE, useCanFile } from "@/lib/use-can-file";
import { apiErrorMessage, formatAmount } from "@/lib/accounting-format";
import type { AnnualInputs, AnnualPeriod, Asset, OpeningRow } from "@/types/accounting";

type AmountKey = Exclude<keyof AnnualInputs, "cit_20_percent" | "refund_overpayment" | "opening_nolco" | "opening_excess_mcit">;
interface Field {
  key: AmountKey;
  label: string;
  hint: string;
  optional?: boolean;
  show?: (p: AnnualPeriod) => boolean;
}
interface Group {
  title: string;
  note?: string;
  fields: Field[];
}

const preBooks = (p: AnnualPeriod) =>
  p.pre_books_quarters.length > 0 ||
  [p.inputs.pre_books_sales, p.inputs.pre_books_cost_of_sales, p.inputs.pre_books_deductions, p.inputs.pre_books_cwt].some((v) => Number(v) !== 0);

const mixed = (p: AnnualPeriod) => p.has_compensation_income;

const GROUPS: Group[] = [
  {
    title: "Before the books started",
    note: "The client moved onto AutoAccounting mid-year: totals for this fiscal year's months before the books start, from their old records. Enter those quarters' income tax paid under Credits.",
    fields: [
      { key: "pre_books_sales", label: "Net sales / receipts", hint: "Before the books start", show: preBooks },
      { key: "pre_books_cost_of_sales", label: "Cost of sales", hint: "Added to the year's purchases", show: preBooks },
      { key: "pre_books_deductions", label: "Itemized deductions", hint: "Operating expenses; ignored under OSD", show: preBooks },
      { key: "pre_books_cwt", label: "Creditable tax withheld", hint: "From 2307s received for those months", show: preBooks },
    ],
  },
  {
    title: "Compensation income (BIR 2316)",
    note: "The client also earns a salary, so this year's return is the 1701: compensation is taxed with the business income, and the 8% option loses its ₱250,000 reduction. Add up every employer's 2316.",
    fields: [
      { key: "compensation_income", label: "Gross compensation income", hint: "2316 gross compensation", show: mixed },
      { key: "compensation_nontaxable", label: "Non-taxable / exempt compensation", hint: "13th month up to ₱90,000, de minimis, SSS / PhilHealth / Pag-IBIG", show: mixed },
      { key: "compensation_tax_withheld", label: "Tax withheld by the employer", hint: "2316 tax withheld; credited in Part VII", show: mixed },
    ],
  },
  {
    title: "Income",
    fields: [
      { key: "ending_inventory", label: "Ending inventory", hint: "Stock at year end. Blank uses Q4's ending inventory", optional: true },
      { key: "non_operating_income", label: "Non-operating income", hint: "Blank adds up the quarters' inputs", optional: true },
    ],
  },
  {
    title: "Credits and overrides",
    fields: [
      { key: "prior_year_excess_credits", label: "Prior year's excess credits", hint: "Blank uses last year's carried-over overpayment", optional: true },
      { key: "q1_paid", label: "Q1 income tax paid", hint: "Blank uses the Q1 return (filed version, else latest)", optional: true },
      { key: "q2_paid", label: "Q2 income tax paid", hint: "Blank uses the Q2 return", optional: true },
      { key: "q3_paid", label: "Q3 income tax paid", hint: "Blank uses the Q3 return", optional: true },
      { key: "amended_paid_income_tax", label: "Paid on the original annual return", hint: "Amended returns only", show: (p) => p.filed_at !== null },
    ],
  },
  {
    title: "Balance sheet",
    note: "Not printed on the January 2018 returns; kept in the workbook and checked to balance.",
    fields: [
      { key: "current_assets", label: "Current assets", hint: "", optional: true },
      { key: "ppe_net", label: "Property, plant and equipment, net", hint: "Blank uses the asset register's net book value", optional: true },
      { key: "other_noncurrent_assets", label: "Other non-current assets", hint: "", optional: true },
      { key: "current_liabilities", label: "Current liabilities", hint: "", optional: true },
      { key: "noncurrent_liabilities", label: "Non-current liabilities", hint: "", optional: true },
      { key: "equity", label: "Equity", hint: "", optional: true },
    ],
  },
  {
    title: "Reconciliation with the books",
    note: "Fills the return's reconciliation part (1702-RT Schedule V / 1701 Part IX) once net income per books is entered.",
    fields: [
      { key: "book_net_income", label: "Net income/(loss) per books", hint: "", optional: true },
      { key: "nondeductible_expenses", label: "Non-deductible expenses", hint: "Added back" },
      { key: "nontaxable_income", label: "Non-taxable income / income under final tax", hint: "Taken off" },
      { key: "other_reconciling", label: "Other reconciling items (+/−)", hint: "Positive adds, negative takes off" },
    ],
  },
];
const ALL_FIELDS = GROUPS.flatMap((g) => g.fields);

const CHIP = {
  filed: "bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]",
  stale: "bg-[var(--badge-yellow-bg)] text-[var(--badge-yellow-text)]",
  generated: "bg-[var(--badge-blue-bg)] text-[var(--badge-blue-text)]",
  collecting: "bg-[var(--bg-primary)] text-[var(--text-secondary)]",
};
const INPUT = "w-full px-2.5 py-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const BTN = "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";
const PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60";
const FORM_NAMES: Record<string, string> = { "1702RT": "1702-RT", "1701": "1701", "1701A": "1701-A" };

interface DraftRow {
  year: string;
  amount: string;
  used: string;
}

const toRows = (rows: OpeningRow[]): DraftRow[] => rows.map((r) => ({ year: String(r.year), amount: r.amount, used: r.used }));
const clean = (value: string) => value.replace(/,/g, "").trim();

interface Props {
  companyId: string;
  companyName: string;
  year: number;
  refreshKey: number;
  onChanged: () => void;
}

export default function AnnualPanel({ companyId, companyName, year, refreshKey, onChanged }: Props) {
  const canFile = useCanFile();
  const [period, setPeriod] = useState<AnnualPeriod | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [cit20, setCit20] = useState(false);
  const [refund, setRefund] = useState(false);
  const [nolco, setNolco] = useState<DraftRow[]>([]);
  const [mcit, setMcit] = useState<DraftRow[]>([]);
  const [showInputs, setShowInputs] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const newestSeen = useRef<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const apply = useCallback((p: AnnualPeriod) => {
    setPeriod(p);
    const next: Record<string, string> = {};
    for (const f of ALL_FIELDS) next[f.key] = (p.inputs[f.key] as string | null) ?? "";
    setDraft(next);
    setCit20(p.inputs.cit_20_percent);
    setRefund(p.inputs.refund_overpayment);
    setNolco(toRows(p.inputs.opening_nolco));
    setMcit(toRows(p.inputs.opening_excess_mcit));
    // A version created elsewhere (e.g. from the "add documents" prompt) is shown as soon as it appears.
    const newest = p.outputs[0]?.id ?? null;
    const appeared = newest !== null && newest !== newestSeen.current;
    newestSeen.current = newest;
    setSelected((current) =>
      !appeared && current && p.outputs.some((o) => o.id === current) ? current : newest,
    );
  }, []);

  useEffect(() => {
    setError("");
    accountingApi.annualPeriod(companyId, year).then(apply).catch((e) => setError(apiErrorMessage(e, "Couldn't load the annual return")));
    accountingApi.assets(companyId, year).then(setAssets).catch(() => setAssets([]));
  }, [companyId, year, refreshKey, apply]);

  async function act(task: () => Promise<void>, fallback: string) {
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (e) {
      setError(apiErrorMessage(e, fallback));
    } finally {
      setBusy(false);
    }
  }

  const rowsOut = (rows: DraftRow[]): OpeningRow[] =>
    rows
      .filter((r) => r.year.trim() && clean(r.amount))
      .map((r) => ({ year: Number(r.year), amount: clean(r.amount), used: clean(r.used) || "0" }));

  const saveInputs = () =>
    act(async () => {
      const inputs: Record<string, unknown> = {
        cit_20_percent: cit20,
        refund_overpayment: refund,
        opening_nolco: rowsOut(nolco),
        opening_excess_mcit: rowsOut(mcit),
      };
      for (const f of ALL_FIELDS) {
        const value = clean(draft[f.key] ?? "");
        inputs[f.key] = value === "" ? (f.optional ? null : "0") : value;
      }
      apply(await accountingApi.saveAnnualInputs(companyId, year, inputs as unknown as AnnualInputs));
      onChanged();
    }, "Couldn't save the inputs");

  const generate = () =>
    act(async () => {
      const output = await accountingApi.generateAnnual(companyId, year);
      setSelected(output.id);
      apply(await accountingApi.annualPeriod(companyId, year));
      setAssets(await accountingApi.assets(companyId, year));
      onChanged();
    }, "Couldn't generate the annual return");

  const toggleFiled = () =>
    act(async () => {
      apply(await accountingApi.setAnnualFiled(companyId, year, !period?.filed_at));
      onChanged();
    }, "Couldn't update the filed status");

  if (!period) return error ? <p className="mb-4 text-sm text-[var(--alert-error-text)]">{error}</p> : null;

  const corporate = period.form === "1702RT";
  const next = (period.latest_version ?? 0) + 1;
  const chip = period.filed_at
    ? period.stale
      ? { text: `Filed — changed since v${period.latest_version}`, cls: CHIP.stale }
      : { text: "Filed", cls: CHIP.filed }
    : period.stale
      ? { text: `Stale — new changes since v${period.latest_version}`, cls: CHIP.stale }
      : period.latest_version
        ? { text: `Generated v${period.latest_version}`, cls: CHIP.generated }
        : { text: "Not generated yet", cls: CHIP.collecting };
  const due = Object.entries(period.due_dates)
    .map(([form, day]) => `${FORM_NAMES[form] ?? form} due ${new Date(`${day}T00:00:00`).toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" })}`)
    .join(" · ");

  const schedule = (title: string, rows: DraftRow[], setRows: (rows: DraftRow[]) => void) => (
    <div>
      <p className="mb-1 text-xs font-medium text-[var(--text-primary)]">{title}</p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-[var(--text-secondary)]">
            <th className="py-1 pr-2 font-medium">Year incurred</th>
            <th className="py-1 pr-2 font-medium">Amount</th>
            <th className="py-1 pr-2 font-medium">Already used</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {(["year", "amount", "used"] as const).map((key) => (
                <td key={key} className="py-1 pr-2">
                  <input
                    inputMode={key === "year" ? "numeric" : "decimal"}
                    className={INPUT}
                    aria-label={`${title} row ${i + 1} ${key}`}
                    value={row[key]}
                    onChange={(e) => setRows(rows.map((r, j) => (j === i ? { ...r, [key]: e.target.value } : r)))}
                  />
                </td>
              ))}
              <td className="py-1">
                <button className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]" aria-label="Remove row" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                  <Trash size={14} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-[var(--accent)]" onClick={() => setRows([...rows, { year: "", amount: "", used: "0" }])}>
        <Plus size={12} /> Add year
      </button>
    </div>
  );

  return (
    <div className="mb-5 rounded-xl border border-[var(--border)] p-4">
      <div className="mb-3">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">
          {companyName} — FY {year} annual return ({FORM_NAMES[period.form] ?? period.form}){" "}
          <Hint align="right">
            Generate this after the last quarter is in. It adds up all four quarters, subtracts the income tax already paid
            on the quarterly returns, and uses the asset register for depreciation. Fill in anything the documents can&apos;t
            show below, then generate and file as you would a quarter.
          </Hint>
        </h2>
        <p className="text-xs text-[var(--text-secondary)]">
          Built from all four quarters&apos; documents ({period.document_count}), the asset register and the carry-overs.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${chip.cls}`}>{chip.text}</span>
        {due && <span className="text-xs text-[var(--text-secondary)]">{due}</span>}
        <div className="ml-auto flex flex-wrap gap-2">
          <button className={BTN} onClick={() => setShowInputs((s) => !s)}>
            {showInputs ? <CaretDown size={14} /> : <CaretRight size={14} />} Annual inputs
          </button>
          {period.latest_version && (
            <button className={BTN} disabled={busy || !canFile} title={canFile ? undefined : FILING_LOCKED_TITLE} onClick={toggleFiled}>
              {period.filed_at ? "Unmark filed" : "Mark as filed"}
            </button>
          )}
          <button className={PRIMARY} disabled={busy} onClick={generate}>
            {busy ? <Spinner size={16} className="animate-spin" /> : <FileXls size={16} />} Generate v{next}
          </button>
        </div>
      </div>

      {period.open_reviews > 0 && (
        <p className="mt-2 text-xs text-[var(--alert-warning-text)]">
          {period.open_reviews} document(s) this year still need review — new versions will be marked DRAFT.
        </p>
      )}
      {period.filed_at && (
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          Marked filed on {new Date(period.filed_at).toLocaleDateString("en-PH")}. A new version is an amended return only for the forms whose figures change.
        </p>
      )}
      <p className="mt-1 text-xs text-[var(--text-secondary)]">
        {period.carry_source === "previous_year"
          ? `NOLCO, excess MCIT and excess credits carry in from FY ${year - 1}'s annual return v${period.previous_year_version}.`
          : `No FY ${year - 1} annual return on AutoAccounting: enter any NOLCO${corporate ? " or excess MCIT" : ""} from earlier years in the opening schedules.`}
      </p>

      {showInputs && (
        <div className="mt-4 space-y-4 rounded-lg border border-[var(--border)] p-3">
          {GROUPS.map((group) => {
            const fields = group.fields.filter((f) => !f.show || f.show(period));
            if (fields.length === 0) return null;
            return (
              <section key={group.title}>
                <p className="text-xs font-semibold text-[var(--text-primary)]">{group.title}</p>
                {group.note && <p className="mb-2 text-[11px] text-[var(--text-secondary)]">{group.note}</p>}
                <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {fields.map((f) => (
                    <label key={f.key} className="block">
                      <span className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">{f.label}</span>
                      <AmountInput
                        className={INPUT}
                        value={draft[f.key] ?? ""}
                        placeholder={f.optional ? "Not provided" : "0.00"}
                        onValueChange={(v) => setDraft((d) => ({ ...d, [f.key]: v }))}
                      />
                      {f.hint && <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">{f.hint}</span>}
                    </label>
                  ))}
                  {group.title === "Credits and overrides" && corporate && (
                    <label className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
                      <input type="checkbox" checked={cit20} onChange={(e) => setCit20(e.target.checked)} />
                      20% rate (net taxable income ≤ ₱5M and assets ≤ ₱100M)
                    </label>
                  )}
                  {group.title === "Credits and overrides" && (
                    <label className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
                      <input type="checkbox" checked={refund} onChange={(e) => setRefund(e.target.checked)} />
                      Refund an overpayment instead of carrying it over
                    </label>
                  )}
                </div>
              </section>
            );
          })}
          <section>
            <p className="text-xs font-semibold text-[var(--text-primary)]">Opening schedules</p>
            <p className="mb-2 text-[11px] text-[var(--text-secondary)]">
              Only for years before AutoAccounting. Once the previous year&apos;s annual return is generated here, its closing schedules are used instead.
            </p>
            <div className={`grid gap-4 ${corporate ? "lg:grid-cols-2" : ""}`}>
              {schedule("NOLCO", nolco, setNolco)}
              {corporate && schedule("Excess MCIT", mcit, setMcit)}
            </div>
          </section>
          <div className="flex justify-end">
            <button className={PRIMARY} disabled={busy} onClick={saveInputs}>Save inputs</button>
          </div>
        </div>
      )}

      {error && <p className="mt-3 text-sm text-[var(--alert-error-text)]">{error}</p>}

      {assets.length > 0 && (
        <div className="mt-4">
          <p className="mb-1 text-xs font-semibold text-[var(--text-primary)]">Asset register — FY {year}</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-[var(--text-secondary)]">
                  <th className="py-1 pr-3 font-medium">Asset</th>
                  <th className="py-1 pr-3 font-medium">In service</th>
                  <th className="py-1 pr-3 text-right font-medium">Cost</th>
                  <th className="py-1 pr-3 text-right font-medium">Life</th>
                  <th className="py-1 pr-3 text-right font-medium">This year</th>
                  <th className="py-1 text-right font-medium">Net book value</th>
                </tr>
              </thead>
              <tbody>
                {assets.map((a) => (
                  <tr key={a.id} className={`border-t border-[var(--border)] ${a.active ? "text-[var(--text-primary)]" : "text-[var(--text-secondary)] line-through"}`}>
                    <td className="py-1 pr-3">{a.description}</td>
                    <td className="py-1 pr-3">{a.in_service}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{formatAmount(a.cost)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{a.useful_life_months} mo</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{formatAmount(a.this_year)}</td>
                    <td className="py-1 text-right tabular-nums">{formatAmount(a.net_book_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-1 text-[11px] text-[var(--text-secondary)]">Open a capital-goods document to change its useful life or in-service date.</p>
        </div>
      )}

      {period.outputs.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 flex flex-wrap gap-1.5">
            {period.outputs.map((o) => (
              <button
                key={o.id}
                onClick={() => setSelected(o.id)}
                className={`rounded-md border px-2.5 py-1 text-xs ${o.id === selected ? "border-[var(--accent)] text-[var(--text-primary)]" : "border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"}`}
              >
                v{o.version} · {new Date(o.created_at).toLocaleDateString("en-PH", { month: "short", day: "numeric" })}
                {o.version > 1 && ` · ${o.changes} change${o.changes === 1 ? "" : "s"}`}
                {o.review_open > 0 && " · DRAFT"}
                {o.amended && " · amended"}
              </button>
            ))}
          </div>
          {selected && (
            <OutputViewer
              key={selected}
              outputId={selected}
              latest={period.outputs[0]?.id === selected}
              onNewVersion={(o) => {
                setSelected(o.id);
                accountingApi.annualPeriod(companyId, year).then(apply).catch(() => undefined);
                onChanged();
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}
