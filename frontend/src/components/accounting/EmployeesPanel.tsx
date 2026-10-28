"use client";

import { useEffect, useRef, useState } from "react";
import AmountInput from "@/components/AmountInput";
import Hint from "@/components/guide/Hint";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, formatPeso, saveBlob } from "@/lib/accounting-format";
import PdfPreview from "@/components/accounting/PdfPreview";
import { useWorkbookPreview } from "@/components/accounting/WorkbookPreview";
import type { Certificate, Employee, EmployeeData, EmployeesYear, PayrollPreview } from "@/types/accounting";

interface Props {
  companyId: string;
  companyName: string;
  year: number;
  canManage: boolean;
}

const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50";
const PRIMARY = "rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50";
const INPUT = "w-full rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1 text-sm text-[var(--text-primary)]";

// Edit form groups, in 2316 order.
const GROUPS: { title: string; keys: string[] }[] = [
  { title: "Employee", keys: ["last_name", "first_name", "middle_name", "tin", "status", "employed_from", "employed_to", "separation", "nationality", "birth_date", "address", "zip_code", "contact"] },
  { title: "Minimum wage earner", keys: ["mwe", "region", "smw_day", "smw_month", "smw_year", "factor"] },
  { title: "Non-taxable / exempt (present employer)", keys: ["nt_basic", "nt_holiday", "nt_overtime", "nt_night", "nt_hazard", "nt_13th", "nt_deminimis", "nt_contributions", "nt_other"] },
  { title: "Taxable (present employer)", keys: ["t_basic", "t_representation", "t_transportation", "t_cola", "t_housing", "t_others", "t_commission", "t_profit_sharing", "t_fees", "t_13th", "t_hazard", "t_overtime", "t_supp_others"] },
  { title: "Previous employer (same year)", keys: ["prev_tin", "prev_name", "prev_from", "prev_to", "prev_13th", "prev_deminimis", "prev_contributions", "prev_nt_other", "prev_t_basic", "prev_t_13th", "prev_t_other", "tax_withheld_prev"] },
  { title: "Tax withheld", keys: ["tax_withheld_jan_nov", "tax_withheld_dec", "pera_credit", "substituted_filing"] },
];
const DATE_KEYS = new Set(["employed_from", "employed_to", "birth_date", "prev_from", "prev_to"]);

const name = (e: Employee) =>
  [String(e.data.last_name ?? ""), [e.data.first_name, e.data.middle_name].filter(Boolean).join(" ")].filter(Boolean).join(", ");

export default function EmployeesPanel({ companyId, companyName, year, canManage }: Props) {
  const [data, setData] = useState<EmployeesYear | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [certificates, setCertificates] = useState<Certificate[] | null>(null);
  const sheet = useWorkbookPreview();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PayrollPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState<{ id?: string; data: EmployeeData } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState("");
  const [showChecks, setShowChecks] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    accountingApi.employees(companyId, year)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(apiErrorMessage(e, "Couldn't load the employees")); });
    return () => { cancelled = true; };
  }, [companyId, year]);

  async function run<T>(label: string, action: () => Promise<T>): Promise<T | undefined> {
    setBusy(label);
    setError("");
    try {
      return await action();
    } catch (e) {
      setError(apiErrorMessage(e, "That didn't work"));
      return undefined;
    } finally {
      setBusy("");
    }
  }

  async function pick(f: File | undefined) {
    if (!f) return;
    setFile(f);
    setNotice("");
    const p = await run("preview", () => accountingApi.previewPayroll(companyId, year, f));
    if (p) {
      setPreview(p);
      setMapping(p.mapping);
    }
  }

  async function doImport() {
    if (!file) return;
    const result = await run("import", () => accountingApi.importPayroll(companyId, year, file, mapping));
    if (result) {
      setData(result);
      setPreview(null);
      setFile(null);
      setNotice(`Imported ${result.imported} employee(s).` + (result.errors.length ? ` Skipped: ${result.errors.join("; ")}` : ""));
    }
  }

  async function save() {
    if (!editing) return;
    const payload = Object.fromEntries(Object.entries(editing.data).filter(([, v]) => v !== "" && v !== undefined));
    const result = await run("save", () =>
      editing.id ? accountingApi.updateEmployee(editing.id, payload) : accountingApi.addEmployee(companyId, year, payload));
    if (result) {
      setData(result);
      setEditing(null);
    }
  }

  async function open2316s() {
    const list = await run("zip", () => accountingApi.certificates2316(companyId, year));
    if (list) setCertificates(list);
  }

  if (!data) return error ? <p className="text-sm text-[var(--alert-error-text)]">{error}</p> : null;
  const mappedName = Object.values(mapping).some((v) => v === "full_name" || v === "last_name");

  return (
    <div className="mb-6">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">
          Employees · {year}{" "}
          <Hint align="right">
            Import the payroll register (Excel or CSV) and match its columns once. We build the 1604-C alphalist and each
            employee&apos;s 2316 from it. Anything flagged needs a fix before the year-end deadline.
          </Hint>
        </h2>
        <span className="text-xs text-[var(--text-secondary)]">1604-C alphalist and 2316s due {data.due}</span>
        <div className="ml-auto flex flex-wrap gap-2">
          {canManage && (
            <>
              <input ref={fileInput} type="file" accept=".xlsx,.xlsm,.csv" className="hidden"
                onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
              <button className={BTN} disabled={Boolean(busy)} onClick={() => fileInput.current?.click()}>
                {busy === "preview" ? "Reading…" : "Import payroll sheet"}
              </button>
              <button className={BTN} onClick={() => setEditing({ data: { status: "R" } })}>Add employee</button>
            </>
          )}
          <button className={BTN} disabled={!data.employees.length || Boolean(busy)} onClick={() =>
            sheet.open(`1604-C alphalist · ${companyName} ${year}`, () => accountingApi.alphalistPreview(companyId, year),
              () => accountingApi.alphalistXlsx(companyId, year), `${companyName} 1604-C alphalist ${year}.xlsx`)}>
            {busy === "xlsx" ? "Preparing…" : "Alphalist (Excel)"}
          </button>
          <button className={BTN} disabled={!data.employees.length || Boolean(busy)} onClick={open2316s}>
            {busy === "zip" ? "Preparing…" : "2316s (PDF)"}
          </button>
        </div>
      </div>
      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {notice && <p className="mb-2 text-sm text-[var(--text-secondary)]">{notice}</p>}

      {preview && (
        <section className="mb-4 rounded-lg border border-[var(--border)] p-3">
          <div className="mb-2 flex flex-wrap items-baseline gap-2">
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Match the columns · {file?.name}</h3>
            <span className="text-xs text-[var(--text-secondary)]">{preview.rows} rows. The mapping is remembered for {companyName}. Importing replaces this year&apos;s employees.</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="text-left text-xs text-[var(--text-secondary)]">
                  <th className="py-1 pr-3 font-medium">Column in the sheet</th>
                  <th className="py-1 pr-3 font-medium">Example</th>
                  <th className="py-1 font-medium">Goes to</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {preview.headers.map((h, i) => h && (
                  <tr key={`${h}-${i}`}>
                    <td className="py-1 pr-3 text-[var(--text-primary)]">{h}</td>
                    <td className="max-w-[200px] truncate py-1 pr-3 text-xs text-[var(--text-secondary)]">{preview.sample.map((r) => r[i]).filter(Boolean).slice(0, 2).join(" · ")}</td>
                    <td className="py-1">
                      <select className={INPUT} value={mapping[h] ?? ""}
                        onChange={(e) => setMapping((m) => ({ ...m, [h]: e.target.value }))}>
                        <option value="">Ignore this column</option>
                        {Object.entries(preview.fields).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex gap-2">
            <button className={PRIMARY} disabled={!mappedName || Boolean(busy)} onClick={doImport}>
              {busy === "import" ? "Importing…" : `Import ${preview.rows} rows`}
            </button>
            <button className={BTN} onClick={() => { setPreview(null); setFile(null); }}>Cancel</button>
            {!mappedName && <span className="self-center text-xs text-[var(--alert-error-text)]">Map a name column first.</span>}
          </div>
        </section>
      )}

      {editing && (
        <section className="mb-4 rounded-lg border border-[var(--border)] p-3">
          <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">{editing.id ? "Edit employee" : "Add employee"}</h3>
          {GROUPS.map((g) => (
            <fieldset key={g.title} className="mb-3">
              <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">{g.title}</legend>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {g.keys.map((k) => (
                  <label key={k} className="block text-xs text-[var(--text-secondary)]">
                    {data.fields[k] ?? k}
                    {k === "mwe" ? (
                      <input type="checkbox" className="ml-2 align-middle" checked={Boolean(editing.data.mwe)}
                        onChange={(e) => setEditing({ ...editing, data: { ...editing.data, mwe: e.target.checked } })} />
                    ) : k === "substituted_filing" ? (
                      <select className={INPUT} value={editing.data[k] === undefined || editing.data[k] === "" ? "" : editing.data[k] ? "Y" : "N"}
                        onChange={(e) => setEditing({ ...editing, data: { ...editing.data, [k]: e.target.value === "" ? "" : e.target.value === "Y" } })}>
                        <option value="">Decide automatically</option>
                        <option value="Y">Yes</option>
                        <option value="N">No</option>
                      </select>
                    ) : k.startsWith("nt_") || k.startsWith("t_") || k.startsWith("tax_") ? (
                      <AmountInput className={INPUT} value={String(editing.data[k] ?? "")}
                        onValueChange={(v) => setEditing({ ...editing, data: { ...editing.data, [k]: v } })} />
                    ) : (
                      <input className={INPUT} type={DATE_KEYS.has(k) ? "date" : "text"} value={String(editing.data[k] ?? "")}
                        onChange={(e) => setEditing({ ...editing, data: { ...editing.data, [k]: e.target.value } })} />
                    )}
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
          <div className="flex gap-2">
            <button className={PRIMARY} disabled={Boolean(busy) || !editing.data.last_name} onClick={save}>{busy === "save" ? "Saving…" : "Save"}</button>
            <button className={BTN} onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </section>
      )}

      {data.warnings.length > 0 && (
        <ul className="mb-3 list-disc space-y-0.5 pl-5 text-xs text-[var(--alert-warning-text)]">
          {data.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}

      {data.employees.length === 0 ? (
        <p className="text-sm text-[var(--text-secondary)]">
          No employees for {year} yet. Import the client&apos;s payroll summary (one row per employee, Excel or CSV) or add them one by one.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--text-secondary)]">
                <th className="py-1 pr-3 font-medium">Employee</th>
                <th className="py-1 pr-3 font-medium">TIN</th>
                <th className="py-1 pr-3 font-medium">Sched.</th>
                <th className="py-1 pr-3 text-right font-medium">Gross</th>
                <th className="py-1 pr-3 text-right font-medium">Taxable</th>
                <th className="py-1 pr-3 text-right font-medium">Tax due</th>
                <th className="py-1 pr-3 text-right font-medium">Withheld Jan–Nov</th>
                <th className="py-1 pr-3 text-right font-medium">December / refund</th>
                <th className="py-1 pr-3 font-medium">Subst.</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)] tabular-nums">
              {data.employees.map((e) => (
                <tr key={e.id}>
                  <td className="py-1.5 pr-3 text-[var(--text-primary)]">{name(e)}</td>
                  <td className="whitespace-nowrap py-1.5 pr-3 text-xs text-[var(--text-secondary)]">{String(e.data.tin ?? "")}</td>
                  <td className="py-1.5 pr-3 text-xs text-[var(--text-secondary)]">{e.schedule === 2 ? "MWE" : "1"}</td>
                  <td className="py-1.5 pr-3 text-right">{formatPeso(e.gross)}</td>
                  <td className="py-1.5 pr-3 text-right">{formatPeso(e.taxable)}</td>
                  <td className="py-1.5 pr-3 text-right">{formatPeso(e.tax_due)}</td>
                  <td className="py-1.5 pr-3 text-right">{formatPeso(e.withheld)}</td>
                  <td className="py-1.5 pr-3 text-right">
                    {Number(e.december) ? formatPeso(e.december) : Number(e.refund) ? `(${formatPeso(e.refund)})` : "0.00"}
                  </td>
                  <td className="py-1.5 pr-3 text-xs">{e.substituted ? "Yes" : "No"}</td>
                  <td className="py-1.5 text-right text-xs">
                    {canManage && confirmDelete !== e.id && (
                      <>
                        <button className="mr-3 text-[var(--accent)]" onClick={() => setEditing({ id: e.id, data: { ...e.data } })}>Edit</button>
                        <button className="text-[var(--alert-error-text)]" onClick={() => setConfirmDelete(e.id)}>Delete</button>
                      </>
                    )}
                    {confirmDelete === e.id && (
                      <>
                        <button className="mr-3 text-[var(--alert-error-text)]" disabled={Boolean(busy)}
                          onClick={async () => {
                            const r = await run("delete", () => accountingApi.deleteEmployee(e.id));
                            if (r) setData(r);
                            setConfirmDelete("");
                          }}>Confirm delete</button>
                        <button className="text-[var(--text-secondary)]" onClick={() => setConfirmDelete("")}>Cancel</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <button className="mt-3 text-xs font-medium text-[var(--accent)]" onClick={() => setShowChecks((s) => !s)}>
        {showChecks ? "Hide" : "Show"} 1601-C remittances and checks
      </button>
      {showChecks && (
        <div className="mt-2 grid gap-4 lg:grid-cols-2">
          <div className="min-w-0 overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="text-left text-xs text-[var(--text-secondary)]">
                  <th className="py-1 pr-3 font-medium">Month</th>
                  <th className="py-1 pr-3 font-medium">Remitted</th>
                  <th className="py-1 pr-3 text-right font-medium">Withheld</th>
                  <th className="py-1 text-right font-medium">Adjustment</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {data.remittances.map((r) => (
                  <tr key={r.key} className={r.key === "~total" ? "font-semibold" : ""}>
                    <td className="py-1 pr-3">{r.month}</td>
                    <td className="py-1 pr-3 text-xs text-[var(--text-secondary)]">{r.source === "missing" ? "no 1601-C" : r.remitted_on || (r.source === "latest" ? "not filed" : "")}</td>
                    <td className="py-1 pr-3 text-right">{formatPeso(r.withheld)}</td>
                    <td className="py-1 text-right">{formatPeso(r.adjustment)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="min-w-0 overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="text-left text-xs text-[var(--text-secondary)]">
                  <th className="py-1 pr-3 font-medium">Check</th>
                  <th className="py-1 pr-3 text-right font-medium">Alphalist</th>
                  <th className="py-1 pr-3 text-right font-medium">1601-C</th>
                  <th className="py-1 text-right font-medium">Difference</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {data.checks.map((c) => (
                  <tr key={c.key}>
                    <td className="py-1 pr-3 text-xs">{c.check}</td>
                    <td className="py-1 pr-3 text-right">{formatPeso(c.alphalist)}</td>
                    <td className="py-1 pr-3 text-right">{formatPeso(c.returns)}</td>
                    <td className={`py-1 text-right ${Number(c.difference) ? "text-[var(--alert-error-text)]" : ""}`}>{formatPeso(c.difference)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {sheet.node}
      {certificates && (
        <PdfPreview
          title={`2316s · ${companyName} ${year}`}
          docs={certificates}
          render={(id, values) => accountingApi.preview2316(companyId, year, id, values)}
          note="Edits change only the certificates you download now. To keep a change, edit the employee instead."
          exportLabel={(edited) => (edited ? "Download edited 2316s (zip)" : "Download 2316s (zip)")}
          onExport={async (edits) => saveBlob(await accountingApi.zip2316(companyId, year, edits), `${companyName} 2316s ${year}.zip`)}
          onClose={() => setCertificates(null)}
        />
      )}
    </div>
  );
}
