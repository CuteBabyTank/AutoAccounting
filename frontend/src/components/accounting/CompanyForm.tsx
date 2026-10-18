"use client";

import { useEffect, useState, type FormEvent } from "react";
import { X } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/accounting-api";
import { BOOK_LABELS, apiErrorMessage } from "@/lib/accounting-format";
import type { CoaTemplate, Company, CompanyInput } from "@/types/accounting";

const EMPTY: CompanyInput = {
  registered_name: "",
  aliases: [],
  owner_names: [],
  tin: "",
  branch_code: "00000",
  rdo_code: "",
  address: "",
  zip_code: "",
  taxpayer_type: "corporation",
  vat_status: "vat",
  income_tax_option: "graduated",
  deduction_method: "itemized",
  business_type: "trading",
  is_withholding_agent: false,
  is_top_withholding_agent: false,
  has_employees: false,
  has_compensation_income: false,
  fiscal_year_end_month: 12,
  operations_start_year: null,
  contact_number: "",
  email: "",
  taxpayer_classification: "",
  pinned: false,
  books_start: null,
  books_kept: [],
  books_signatory: "",
  books_signatory_title: "",
};

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const INPUT = "w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const LABEL = "block text-xs font-medium text-[var(--text-secondary)] mb-1";

interface Props {
  initial?: Partial<CompanyInput>;
  companyId?: string;
  onClose: () => void;
  onSaved: (company: Company) => void;
}

export default function CompanyForm({ initial, companyId, onClose, onSaved }: Props) {
  const [form, setForm] = useState<CompanyInput>({ ...EMPTY, ...initial });
  const [aliases, setAliases] = useState((initial?.aliases ?? []).join(", "));
  const [owners, setOwners] = useState((initial?.owner_names ?? []).join(", "));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [templates, setTemplates] = useState<CoaTemplate[]>([]);
  const [template, setTemplate] = useState("");

  useEffect(() => {
    if (!companyId) accountingApi.coaTemplates().then(setTemplates).catch(() => undefined);
  }, [companyId]);

  const set = <K extends keyof CompanyInput>(key: K, value: CompanyInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    const payload: CompanyInput = {
      ...EMPTY,
      ...form,
      aliases: aliases.split(",").map((a) => a.trim()).filter(Boolean),
      owner_names: owners.split(",").map((a) => a.trim()).filter(Boolean),
      income_tax_option: form.taxpayer_type === "individual" ? form.income_tax_option : "graduated",
      operations_start_year: form.taxpayer_type === "individual" ? null : form.operations_start_year,
      has_compensation_income: form.taxpayer_type === "individual" && form.has_compensation_income,
    };
    try {
      const saved = companyId
        ? await accountingApi.updateCompany(companyId, payload)
        : await accountingApi.createCompany({ ...payload, coa_template: template });
      onSaved(saved);
    } catch (err) {
      setError(apiErrorMessage(err, "Couldn't save the company"));
    } finally {
      setSaving(false);
    }
  }

  const check = (key: "is_withholding_agent" | "is_top_withholding_agent" | "has_employees" | "has_compensation_income" | "pinned", text: string) => (
    <label className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
      <input type="checkbox" checked={form[key]} onChange={(e) => set(key, e.target.checked)} />
      {text}
    </label>
  );

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-6"
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">
            {companyId ? "Edit company" : "Add company to databank"}
          </h2>
          <button type="button" onClick={onClose} className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className={LABEL}>Registered name *</label>
            <input className={INPUT} required value={form.registered_name} onChange={(e) => set("registered_name", e.target.value)} />
          </div>
          <div className="sm:col-span-2">
            <label className={LABEL}>Trade names / aliases (comma-separated)</label>
            <input className={INPUT} value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="JCT, Juan Cloth Shop" />
          </div>
          <div className="sm:col-span-2">
            <label className={LABEL}>Owner / officer names (comma-separated)</label>
            <input className={INPUT} value={owners} onChange={(e) => setOwners(e.target.value)} placeholder="Juan Dela Cruz" />
            <p className="mt-1 text-xs text-[var(--text-secondary)]">Receipts made out to these people personally are excluded as personal purchases.</p>
          </div>
          <div>
            <label className={LABEL}>TIN *</label>
            <input className={INPUT} required value={form.tin} onChange={(e) => set("tin", e.target.value)} placeholder="123-456-789" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL}>Branch code</label>
              <input className={INPUT} value={form.branch_code} onChange={(e) => set("branch_code", e.target.value)} />
            </div>
            <div>
              <label className={LABEL}>RDO code</label>
              <input className={INPUT} value={form.rdo_code} onChange={(e) => set("rdo_code", e.target.value)} />
            </div>
          </div>
          <div className="sm:col-span-2 grid grid-cols-[1fr_120px] gap-3">
            <div>
              <label className={LABEL}>Registered address</label>
              <input className={INPUT} value={form.address} onChange={(e) => set("address", e.target.value)} />
            </div>
            <div>
              <label className={LABEL}>ZIP</label>
              <input className={INPUT} value={form.zip_code} onChange={(e) => set("zip_code", e.target.value)} />
            </div>
          </div>
          <div>
            <label className={LABEL}>Contact number</label>
            <input className={INPUT} value={form.contact_number} maxLength={20} onChange={(e) => set("contact_number", e.target.value)} />
          </div>
          <div>
            <label className={LABEL}>Email address</label>
            <input className={INPUT} type="email" value={form.email} maxLength={255} onChange={(e) => set("email", e.target.value)} />
          </div>
          <div>
            <label className={LABEL}>Taxpayer type</label>
            <select className={INPUT} value={form.taxpayer_type} onChange={(e) => set("taxpayer_type", e.target.value as CompanyInput["taxpayer_type"])}>
              <option value="corporation">Corporation</option>
              <option value="partnership">Partnership</option>
              <option value="individual">Individual</option>
            </select>
          </div>
          <div>
            <label className={LABEL}>Tax registration</label>
            <select className={INPUT} value={form.vat_status} onChange={(e) => set("vat_status", e.target.value as CompanyInput["vat_status"])}>
              <option value="vat">VAT-registered</option>
              <option value="non_vat">Non-VAT</option>
            </select>
          </div>
          {form.vat_status === "vat" && (
            <div>
              <label className={LABEL}>VAT taxpayer classification</label>
              <select className={INPUT} value={form.taxpayer_classification} onChange={(e) => set("taxpayer_classification", e.target.value as CompanyInput["taxpayer_classification"])}>
                <option value="">Not set</option>
                <option value="micro">Micro (below ₱3M)</option>
                <option value="small">Small (₱3M to below ₱20M)</option>
                <option value="medium">Medium (₱20M to below ₱1B)</option>
                <option value="large">Large (₱1B and above)</option>
              </select>
            </div>
          )}
          {form.taxpayer_type === "individual" && (
            <div>
              <label className={LABEL}>Income tax option</label>
              <select className={INPUT} value={form.income_tax_option} onChange={(e) => set("income_tax_option", e.target.value as CompanyInput["income_tax_option"])}>
                <option value="graduated">Graduated rates</option>
                <option value="eight_percent">8% on gross</option>
              </select>
            </div>
          )}
          <div>
            <label className={LABEL}>Deduction method</label>
            <select className={INPUT} value={form.deduction_method} onChange={(e) => set("deduction_method", e.target.value as CompanyInput["deduction_method"])}>
              <option value="itemized">Itemized</option>
              <option value="osd">OSD (40%)</option>
            </select>
          </div>
          <div>
            <label className={LABEL}>Business type</label>
            <select className={INPUT} value={form.business_type} onChange={(e) => set("business_type", e.target.value as CompanyInput["business_type"])}>
              <option value="trading">Trading</option>
              <option value="manufacturing">Manufacturing</option>
              <option value="services">Services</option>
            </select>
          </div>
          {!companyId && templates.length > 0 && (
            <div>
              <label className={LABEL}>Chart of accounts</label>
              <select className={INPUT} value={template} onChange={(e) => setTemplate(e.target.value)}>
                <option value="">Standard PH chart</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id} title={t.description}>
                    {t.name}{t.builtin ? "" : " (firm template)"}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label className={LABEL}>Fiscal year ends</label>
            <select className={INPUT} value={form.fiscal_year_end_month} onChange={(e) => set("fiscal_year_end_month", Number(e.target.value))}>
              {MONTHS.map((m, i) => (
                <option key={m} value={i + 1}>{m}</option>
              ))}
            </select>
          </div>
          {form.taxpayer_type !== "individual" && (
            <div>
              <label className={LABEL}>Year operations began</label>
              <input
                className={INPUT}
                inputMode="numeric"
                value={form.operations_start_year ?? ""}
                placeholder="e.g. 2019"
                onChange={(e) => {
                  const digits = e.target.value.replace(/\D/g, "").slice(0, 4);
                  set("operations_start_year", digits ? Number(digits) : null);
                }}
              />
              <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">MCIT applies from the 4th taxable year after this one</span>
            </div>
          )}
          <div className="sm:col-span-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {check("is_withholding_agent", "Withholds tax on supplier payments")}
            {check("is_top_withholding_agent", "Top Withholding Agent")}
            {check("has_employees", "Has employees")}
            {form.taxpayer_type === "individual" && check("has_compensation_income", "Also earns a salary (mixed income)")}
            {check("pinned", "Pin to top of lists")}
          </div>
          <fieldset className="sm:col-span-2 mt-2 rounded-lg border border-[var(--border)] p-3">
            <legend className="px-1 text-xs font-semibold text-[var(--text-secondary)]">Books of accounts</legend>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className={LABEL}>Books start</label>
                <input
                  type="date"
                  className={INPUT}
                  value={form.books_start ?? ""}
                  onChange={(e) => set("books_start", e.target.value || null)}
                />
                <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">
                  Leave empty to keep returns only. Enter the opening balances as of this date in Books.
                </span>
              </div>
              <div>
                <label className={LABEL}>Registered books</label>
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {(["SJ", "PJ", "CRJ", "CDJ"] as const).map((b) => (
                    <label key={b} className="flex items-center gap-1.5 text-sm text-[var(--text-primary)]">
                      <input
                        type="checkbox"
                        checked={form.books_kept.includes(b)}
                        onChange={(e) =>
                          set("books_kept", e.target.checked ? [...form.books_kept, b] : form.books_kept.filter((x) => x !== b))
                        }
                      />
                      {BOOK_LABELS[b]}
                    </label>
                  ))}
                </div>
                <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">
                  General Journal and General Ledger are always kept. Empty = the usual set for the VAT status.
                </span>
              </div>
              <div>
                <label className={LABEL}>Signatory (sworn declaration)</label>
                <input className={INPUT} maxLength={120} value={form.books_signatory} onChange={(e) => set("books_signatory", e.target.value)} />
              </div>
              <div>
                <label className={LABEL}>Signatory title</label>
                <input className={INPUT} maxLength={60} value={form.books_signatory_title} onChange={(e) => set("books_signatory_title", e.target.value)} />
              </div>
            </div>
          </fieldset>
        </div>

        {error && <p className="mt-4 text-sm text-[var(--alert-error-text)]">{error}</p>}

        <div className="mt-6 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]">
            Cancel
          </button>
          <button type="submit" disabled={saving} className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60">
            {saving ? "Saving…" : companyId ? "Save changes" : "Add to databank"}
          </button>
        </div>
      </form>
    </div>
  );
}
