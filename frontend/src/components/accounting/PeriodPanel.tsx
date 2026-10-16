"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CaretDown, CaretRight, FileXls, Spinner } from "@phosphor-icons/react";
import OutputViewer from "@/components/accounting/OutputViewer";
import PrepareReturns from "@/components/accounting/PrepareReturns";
import Hint from "@/components/guide/Hint";
import GuideTour from "@/components/guide/GuideTour";
import { QUARTER_TOUR } from "@/components/guide/tours";
import { useGuide } from "@/lib/guides";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { PayrollMonth, Period, PeriodInputs } from "@/types/accounting";

type FieldKey = Exclude<keyof PeriodInputs, "cit_rate" | "mcit_applies" | "payroll">;
interface Field {
  key: FieldKey;
  label: string;
  hint: string;
  optional?: boolean;
  show: (p: Period) => boolean;
}

const always = () => true;
const vat = (p: Period) => p.forms_expected.includes("2550Q");
const ewt = (p: Period) => p.forms_expected.includes("1601EQ");
// "Paid on the original" applies once that return is filed (per form; the API back-fills quarters filed earlier).
const filedAny = (p: Period, forms: string[]) => forms.some((f) => f in (p.filed_forms ?? {}));
const FIELDS: Field[] = [
  { key: "ending_inventory", label: "Ending inventory", hint: "Stock on hand at quarter end", optional: true, show: always },
  { key: "opening_inventory", label: "Opening inventory", hint: "Only if last quarter's ending inventory isn't on AutoAccounting", optional: true, show: always },
  { key: "opening_excess_input_vat", label: "Excess input VAT carried in", hint: "Only if the carry-in isn't from a quarter on AutoAccounting", show: vat },
  { key: "vat_withheld", label: "VAT withheld (2307, ATC WV…)", hint: "2550-Q item 16", show: vat },
  { key: "advance_vat", label: "Advance VAT payments", hint: "2550-Q item 17", show: vat },
  { key: "uncollected_output_vat", label: "Output VAT on uncollected receivables", hint: "2550-Q 35B: credit sales past due, VAT already declared, not written off (RR 3-2024). Claim in the quarter after the due date", show: vat },
  { key: "recovered_output_vat", label: "Output VAT on recovered receivables", hint: "2550-Q 36B: receivables deducted in 35B before and collected this quarter", show: vat },
  { key: "unpaid_input_vat", label: "Input VAT on unpaid payables", hint: "2550-Q 55B: purchases on credit past due and still unpaid", show: vat },
  { key: "settled_input_vat", label: "Input VAT on settled payables", hint: "2550-Q 58B: payables deducted in 55B before and paid this quarter", show: vat },
  { key: "percentage_tax_withheld", label: "Percentage tax withheld", hint: "2551-Q item 15", show: (p) => p.forms_expected.includes("2551Q") },
  { key: "non_operating_income", label: "Non-operating income", hint: "Interest, gains and other income this quarter", show: always },
  { key: "prior_year_excess_credits", label: "Prior year's excess credits", hint: "Income tax credit carried from last year", show: always },
  { key: "prior_taxable_income", label: "Earlier quarters: taxable income", hint: "Only if earlier quarters were filed outside AutoAccounting", optional: true, show: (p) => p.quarter > 1 },
  { key: "prior_tax_paid", label: "Earlier quarters: tax paid", hint: "", optional: true, show: (p) => p.quarter > 1 },
  { key: "prior_cwt", label: "Earlier quarters: tax withheld (2307)", hint: "", optional: true, show: (p) => p.quarter > 1 },
  { key: "prior_gross_income", label: "Earlier quarters: gross income", hint: "For MCIT (1702-Q Schedule 3)", optional: true, show: (p) => p.quarter > 1 && p.forms_expected.includes("1702Q") },
  { key: "amended_paid_business_tax", label: "Paid on the original VAT/percentage tax return", hint: "Amended returns only (2550-Q 18 / 2551-Q 16)", show: (p) => filedAny(p, ["2550Q", "2551Q"]) },
  { key: "amended_paid_income_tax", label: "Paid on the original income tax return", hint: "Amended returns only (1702-Q Sched 4 · 6 / 1701-Q 59)", show: (p) => filedAny(p, ["1701Q", "1702Q"]) },
  { key: "ewt_remitted_m1", label: "EWT actually remitted — month 1", hint: "Only if the 0619-E paid differs from the computed amount", optional: true, show: ewt },
  { key: "ewt_remitted_m2", label: "EWT actually remitted — month 2", hint: "Only if the 0619-E paid differs from the computed amount", optional: true, show: ewt },
  { key: "ewt_over_remittance", label: "EWT over-remitted last quarter", hint: "1601-EQ item 23", show: ewt },
  { key: "amended_paid_withholding", label: "Paid on the original 1601-EQ", hint: "Amended returns only (1601-EQ item 22)", show: (p) => ewt(p) && filedAny(p, ["1601EQ"]) },
];

const PAYROLL_FIELDS: [Exclude<keyof PayrollMonth, "no_payroll">, string][] = [
  ["mwe_basic", "Statutory minimum wage (MWEs)"],
  ["mwe_premium", "Holiday, overtime, night shift, hazard pay (MWEs)"],
  ["thirteenth_month", "13th month pay and other benefits (up to ₱90,000)"],
  ["de_minimis", "De minimis benefits"],
  ["contributions", "SSS, PhilHealth, Pag-IBIG, union dues (employee share)"],
  ["employer_contributions", "SSS, PhilHealth, Pag-IBIG (employer share; books and deductions, not on the 1601-C)"],
  ["other_non_taxable", "Other non-taxable compensation"],
  ["not_subject", "Taxable compensation not subject to withholding"],
  ["adjustment", "Adjustment from previous months (+/−)"],
  ["amended_paid", "Paid on the original 1601-C (amended only)"],
];

const CHIP = {
  filed: "bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]",
  stale: "bg-[var(--badge-yellow-bg)] text-[var(--badge-yellow-text)]",
  generated: "bg-[var(--badge-blue-bg)] text-[var(--badge-blue-text)]",
  collecting: "bg-[var(--bg-primary)] text-[var(--text-secondary)]",
};
const INPUT = "w-full px-2.5 py-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const BTN = "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";
const PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60";

interface Props {
  companyId: string;
  year: number;
  quarter: number;
  refreshKey: number;
  onChanged: () => void;
  onEditCompany?: () => void;
}

export default function PeriodPanel({ companyId, year, quarter, refreshKey, onChanged, onEditCompany }: Props) {
  const [period, setPeriod] = useState<Period | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [citRate, setCitRate] = useState<20 | 25>(25);
  const [mcit, setMcit] = useState(false);
  const [payroll, setPayroll] = useState<PayrollMonth[]>([]);
  const [showInputs, setShowInputs] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const newestSeen = useRef<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // The Documents tour already walks through this on a first visit; here it opens on request.
  const guide = useGuide("quarter", { autoOpen: false });

  const apply = useCallback((p: Period) => {
    setPeriod(p);
    const next: Record<string, string> = {};
    for (const f of FIELDS) next[f.key] = p.inputs[f.key] ?? "";
    setDraft(next);
    setCitRate(p.inputs.cit_rate);
    setMcit(p.inputs.mcit_applies);
    setPayroll(p.inputs.payroll.map((m) => ({ ...m })));
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
    accountingApi.period(companyId, year, quarter).then(apply).catch((e) => setError(apiErrorMessage(e, "Couldn't load this quarter")));
  }, [companyId, year, quarter, refreshKey, apply]);

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

  const saveInputs = () =>
    act(async () => {
      const inputs: Record<string, unknown> = { cit_rate: citRate, mcit_applies: mcit };
      for (const f of FIELDS) {
        const value = (draft[f.key] ?? "").replace(/,/g, "").trim();
        inputs[f.key] = value === "" ? (f.optional ? null : "0") : value;
      }
      inputs.payroll = payroll.map((month) => ({
        ...Object.fromEntries(PAYROLL_FIELDS.map(([key]) => [key, (month[key] ?? "").replace(/,/g, "").trim() || "0"])),
        no_payroll: month.no_payroll,
      }));
      apply(await accountingApi.savePeriodInputs(companyId, year, quarter, inputs as unknown as PeriodInputs));
      onChanged();
    }, "Couldn't save the inputs");

  const generate = () =>
    act(async () => {
      const output = await accountingApi.generate(companyId, year, quarter);
      setSelected(output.id);
      apply(await accountingApi.period(companyId, year, quarter));
      onChanged();
    }, "Couldn't generate the returns");

  const toggleFiled = () =>
    act(async () => {
      apply(await accountingApi.setFiled(companyId, year, quarter, !period?.filed_at));
      onChanged();
    }, "Couldn't update the filed status");

  if (!period) return error ? <p className="mb-4 text-sm text-[var(--alert-error-text)]">{error}</p> : null;

  const next = (period.latest_version ?? 0) + 1;
  const chip = period.filed_at
    ? period.stale
      ? { text: `Filed — changed since v${period.latest_version}`, cls: CHIP.stale }
      : { text: "Filed", cls: CHIP.filed }
    : period.stale
      ? { text: `Stale — new changes since v${period.latest_version}`, cls: CHIP.stale }
      : period.latest_version
        ? { text: `Generated v${period.latest_version}`, cls: CHIP.generated }
        : { text: "Collecting", cls: CHIP.collecting };
  const due = Object.entries(period.due_dates)
    .map(([form, day]) => `${form} due ${new Date(`${day}T00:00:00`).toLocaleDateString("en-PH", { month: "short", day: "numeric" })}`)
    .join(" · ");
  const corporate = period.forms_expected.includes("1702Q");

  return (
    <div className="mb-5 rounded-xl border border-[var(--border)] p-4">
      <GuideTour open={guide.open} onClose={guide.dismiss} label="Quarter" slides={QUARTER_TOUR} />
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex items-center gap-1">
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${chip.cls}`}>{chip.text}</span>
          <Hint align="right">
            <span className="block"><b>Collecting</b>: documents are coming in; nothing generated yet.</span>
            <span className="block"><b>Generated</b>: returns are ready to download.</span>
            <span className="block"><b>Stale</b>: something changed since that version, so generate again.</span>
            <span className="block"><b>Filed</b>: you marked it submitted to the BIR.</span>
          </Hint>
        </span>
        <button onClick={guide.toggle} className="text-xs font-medium text-[var(--accent)] hover:underline">
          How to prepare a quarter
        </button>
        {due && <span className="text-xs text-[var(--text-secondary)]">{due}</span>}
        <div className="ml-auto flex flex-wrap gap-2">
          <button className={BTN} onClick={() => setShowInputs((s) => !s)}>
            {showInputs ? <CaretDown size={14} /> : <CaretRight size={14} />} Quarter inputs
          </button>
          {period.latest_version && (
            <button className={BTN} disabled={busy} onClick={toggleFiled}>
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
          {period.open_reviews} document(s) still need review — new versions will be marked DRAFT.
        </p>
      )}
      {period.books_stale && (
        <p className="mt-1 text-xs text-[var(--alert-warning-text)]">
          Books changed since v{period.latest_version} — generate a new version to update the book tabs.
        </p>
      )}
      {period.filed_at && (
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          Marked filed on {new Date(period.filed_at).toLocaleDateString("en-PH")}. A new version is an amended return only for the forms whose figures change.
        </p>
      )}

      {showInputs && (
        <div className="mt-4 rounded-lg border border-[var(--border)] p-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {FIELDS.filter((f) => f.show(period)).map((f) => (
              <label key={f.key} className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">{f.label}</span>
                <input
                  inputMode="decimal"
                  className={INPUT}
                  value={draft[f.key] ?? ""}
                  placeholder={f.optional ? "Not provided" : "0.00"}
                  onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                />
                {f.hint && <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">{f.hint}</span>}
              </label>
            ))}
            {corporate && (
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">Corporate income tax rate</span>
                <select className={INPUT} value={citRate} onChange={(e) => setCitRate(Number(e.target.value) as 20 | 25)}>
                  <option value={25}>25% (regular)</option>
                  <option value={20}>20% (net taxable income ≤ ₱5M and assets ≤ ₱100M)</option>
                </select>
              </label>
            )}
            {corporate && (
              <label className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
                <input type="checkbox" checked={mcit} onChange={(e) => setMcit(e.target.checked)} />
                MCIT applies (4th year of operations onwards)
              </label>
            )}
          </div>
          {period.forms_expected.includes("1601C-M1") && payroll.length === 3 && (
            <div className="mt-4">
              <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">
                1601-C — amounts the payroll register doesn&apos;t show (gross pay and tax withheld come from the payroll documents)
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-[var(--text-secondary)]">
                      <th className="py-1 pr-3 font-medium">Item</th>
                      {[1, 2, 3].map((m) => (
                        <th key={m} className="py-1 pr-2 font-medium">Month {m}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-t border-[var(--border)]">
                      <td className="py-1 pr-3 text-[var(--text-primary)]">
                        No payroll this month
                        <span className="block text-[11px] text-[var(--text-secondary)]">Files a nil 1601-C instead of waiting for payroll documents</span>
                      </td>
                      {payroll.map((month, i) => (
                        <td key={i} className="py-1 pr-2">
                          <input
                            type="checkbox"
                            aria-label={`No payroll, month ${i + 1}`}
                            checked={month.no_payroll}
                            onChange={(e) =>
                              setPayroll((all) => all.map((m, j) => (j === i ? { ...m, no_payroll: e.target.checked } : m)))
                            }
                          />
                        </td>
                      ))}
                    </tr>
                    {PAYROLL_FIELDS.map(([key, label]) => (
                      <tr key={key} className="border-t border-[var(--border)]">
                        <td className="py-1 pr-3 text-[var(--text-primary)]">{label}</td>
                        {payroll.map((month, i) => (
                          <td key={i} className="py-1 pr-2">
                            <input
                              inputMode="decimal"
                              className={INPUT}
                              aria-label={`${label}, month ${i + 1}`}
                              value={month[key]}
                              onChange={(e) =>
                                setPayroll((all) => all.map((m, j) => (j === i ? { ...m, [key]: e.target.value } : m)))
                              }
                            />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          <div className="mt-3 flex justify-end">
            <button className={PRIMARY} disabled={busy} onClick={saveInputs}>Save inputs</button>
          </div>
        </div>
      )}

      {error && <p className="mt-3 text-sm text-[var(--alert-error-text)]">{error}</p>}

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
            <>
              <OutputViewer outputId={selected} />
              <PrepareReturns outputId={selected} companyId={companyId} year={year} quarter={quarter} onPeriod={apply}
                onEditCompany={onEditCompany} />
            </>
          )}
        </div>
      )}
    </div>
  );
}
