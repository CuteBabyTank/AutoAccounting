"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { MagnifyingGlass, Plus, PushPin } from "@phosphor-icons/react";
import CompanyForm from "@/components/accounting/CompanyForm";
import Hint from "@/components/guide/Hint";
import { GuideButton } from "@/components/guide/GuideTour";
import PageGuide from "@/components/guide/PageGuide";
import { COMPANIES_TOUR } from "@/components/guide/tours";
import { COMPANIES_SPOTS } from "@/components/guide/tours/spots";
import { useGuide } from "@/lib/guides";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, formatTin } from "@/lib/accounting-format";
import { useAuth } from "@/lib/auth";
import type { Company } from "@/types/accounting";
import { confirmDialog } from "@/components/ui/Dialogs";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const TYPE_LABELS: Record<Company["taxpayer_type"], string> = {
  corporation: "Corporation",
  partnership: "Partnership",
  individual: "Individual",
};

export default function AccountingCompaniesPage() {
  const { user } = useAuth();
  const canManage = user?.role === "admin" || user?.role === "enterprise" || user?.role === "manager";
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<Company | "new" | null>(null);
  const [error, setError] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [busy, setBusy] = useState(false);
  const guide = useGuide("companies");

  const load = useCallback(async () => {
    try {
      setCompanies(await accountingApi.listCompanies("", true));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't load the company databank"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const visible = companies.filter((c) => showArchived || !c.archived_at);
    if (!q) return visible;
    const digits = q.replace(/\D/g, "");
    return visible.filter(
      (c) =>
        c.registered_name.toLowerCase().includes(q) ||
        c.aliases.some((a) => a.toLowerCase().includes(q)) ||
        (digits.length > 0 && c.tin.includes(digits)),
    );
  }, [companies, search, showArchived]);

  async function changeArchive(c: Company) {
    if (!c.archived_at && !(await confirmDialog({
      title: `Archive ${c.registered_name}?`,
      message: "Documents, books and tax records are retained. Restore it from Show archived companies.",
      confirmLabel: "Archive",
      danger: true,
    }))) return;
    setBusy(true);
    setError("");
    try {
      if (c.archived_at) await accountingApi.restoreCompany(c.id);
      else await accountingApi.archiveCompany(c.id);
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't change the company's archive status"));
    } finally {
      setBusy(false);
    }
  }

  async function togglePin(c: Company) {
    setError("");
    try {
      // Extra id/created_at keys are ignored by the API's CompanyIn schema.
      await accountingApi.updateCompany(c.id, { ...c, pinned: !c.pinned });
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't update the company"));
    }
  }

  return (
    <div className="lp relative min-h-screen">
      <div className="p-4 sm:p-8 max-w-6xl page-enter">
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <div className="mr-auto min-w-[16rem] flex-1">
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">Companies</h1>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              Your firm&apos;s client databank. Dropped documents are matched against these by TIN and name.
            </p>
          </div>
          <GuideButton open={guide.open} onClick={guide.toggle} />
          <label data-tour="company-search" className="relative">
            <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search name, alias or TIN"
              className="w-64 rounded-full border border-[var(--border)] bg-[var(--bg-secondary)] py-1.5 pl-8 pr-3 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
            />
          </label>
          {canManage && (
            <button
              onClick={() => setEditing("new")}
              data-tour="add-company"
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)]"
            >
              <Plus size={16} /> Add company
            </button>
          )}
        </div>

        <PageGuide open={guide.open} onClose={guide.dismiss} label="Companies" spots={COMPANIES_SPOTS} slides={COMPANIES_TOUR} />
        <label className="mb-3 flex items-center gap-2 text-sm text-[var(--text-secondary)]">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          Show archived companies
        </label>

        {error && (
          <div className="mb-4 rounded-lg border border-[var(--alert-error-border)] bg-[var(--alert-error-bg)] px-4 py-2 text-sm text-[var(--alert-error-text)]">
            {error}
          </div>
        )}

        <div data-tour="company-list" className="overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--text-secondary)]">
                <th className="px-4 py-3 font-medium">Company</th>
                <th className="px-4 py-3 font-medium">
                  TIN <Hint>The 9-digit tax ID plus the branch code (000 for the head office). This is how dropped documents are matched to the company.</Hint>
                </th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">
                  Tax <Hint>VAT clients file the 2550-Q. Non-VAT clients file the 2551-Q percentage tax, unless they chose the 8% income tax rate, which replaces it.</Hint>
                </th>
                <th className="px-4 py-3 font-medium">
                  FY ends <Hint align="left">The last month of the client&apos;s fiscal year. Quarters and the annual return follow it, so a June year-end makes July–September Q1.</Hint>
                </th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr key={c.id} className="border-t border-[var(--border)] text-[var(--text-primary)]">
                  <td className="px-4 py-3">
                    <div className="font-medium">{c.registered_name}{c.archived_at && <span className="ml-2 text-xs text-[var(--text-secondary)]">Archived</span>}</div>
                    {c.aliases.length > 0 && (
                      <div className="text-xs text-[var(--text-secondary)]">{c.aliases.join(", ")}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap tabular-nums">
                    {formatTin(c.tin)}-{c.branch_code}
                  </td>
                  <td className="px-4 py-3">{TYPE_LABELS[c.taxpayer_type]}</td>
                  <td className="px-4 py-3">
                    {c.vat_status === "vat" ? "VAT" : c.income_tax_option === "eight_percent" ? "Non-VAT · 8%" : "Non-VAT"}
                  </td>
                  <td className="px-4 py-3">{MONTHS[c.fiscal_year_end_month - 1]}</td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    {canManage && !c.archived_at && (
                      <>
                        <button
                          onClick={() => togglePin(c)}
                          title={c.pinned ? "Unpin" : "Pin to top"}
                          aria-label={c.pinned ? "Unpin" : "Pin to top"}
                          className={`mr-2 rounded p-1 hover:bg-[var(--bg-hover)] ${c.pinned ? "text-[var(--accent)]" : "text-[var(--text-secondary)]"}`}
                        >
                          <PushPin size={16} weight={c.pinned ? "fill" : "regular"} />
                        </button>
                        <button
                          onClick={() => setEditing(c)}
                          className="rounded-lg border border-[var(--border)] px-3 py-1 text-xs font-medium hover:bg-[var(--bg-hover)]"
                        >
                          Edit
                        </button>
                      </>
                    )}
                    {canManage && <button disabled={busy} onClick={() => changeArchive(c)} className="ml-2 rounded-lg border border-[var(--border)] px-3 py-1 text-xs font-medium hover:bg-[var(--bg-hover)] disabled:opacity-60">{c.archived_at ? "Restore" : "Archive"}</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && filtered.length === 0 && (
            <p className="px-4 py-10 text-center text-sm text-[var(--text-secondary)]">
              {companies.length === 0
                ? canManage
                  ? "No clients yet. Click Add company, or just drop their documents on the Documents page and add the company when we ask."
                  : "No clients yet. A manager or the firm owner adds them, or they're created when documents are dropped."
                : "No company matches your search."}
            </p>
          )}
        </div>
      </div>

      {editing && (
        <CompanyForm
          initial={editing === "new" ? undefined : editing}
          companyId={editing === "new" ? undefined : editing.id}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await load();
          }}
        />
      )}
    </div>
  );
}
