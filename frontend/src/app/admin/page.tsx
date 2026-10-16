"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { MagnifyingGlass } from "@phosphor-icons/react";
import { useAuth } from "@/lib/auth";
import Hint from "@/components/guide/Hint";
import GuideTour, { GuideButton } from "@/components/guide/GuideTour";
import { ADMIN_TOUR } from "@/components/guide/tours";
import { useGuide } from "@/lib/guides";
import { adminApi } from "@/lib/api";
import { apiErrorMessage, formatPeso } from "@/lib/accounting-format";
import { roleLabel } from "@/lib/roles";
import type { Account, BudgetOperation, UserRole } from "@/types";

type AssignableRole = Exclude<UserRole, "admin">;

export default function AdminPage() {
  const { user } = useAuth();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [pageRate, setPageRate] = useState<string>("");
  const [savedRate, setSavedRate] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const guide = useGuide("admin");

  const load = useCallback(async () => {
    try {
      const [a, r] = await Promise.all([adminApi.accounts(), adminApi.pageRate()]);
      setAccounts(a);
      setSavedRate(r.page_rate);
      setPageRate(r.page_rate == null ? "" : String(r.page_rate));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't load accounts"));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function run(action: () => Promise<unknown>, fallback: string) {
    setError("");
    setBusy(true);
    try {
      await action();
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, fallback));
    } finally {
      setBusy(false);
    }
  }

  const firms = useMemo(() => accounts.filter((a) => a.role === "enterprise"), [accounts]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return accounts;
    return accounts.filter((a) =>
      [a.email, a.nickname, a.organization_name, a.enterprise_email].some((v) => v?.toLowerCase().includes(q)),
    );
  }, [accounts, search]);

  function promoteFirm(a: Account) {
    const name = window.prompt(`Firm name for ${a.email}`, a.organization_name ?? "");
    if (name === null) return;
    run(() => adminApi.promoteFirm(a.id, name), "Couldn't create the firm");
  }

  function changeRole(a: Account, role: AssignableRole) {
    if (role === "employee" || role === "manager") {
      if (firms.length === 0) {
        setError("Create a firm first, then assign members to it.");
        return;
      }
      const current = a.enterprise_id ?? firms[0].id;
      const choice = window.prompt(
        `Firm for ${a.email}:\n${firms.map((f, i) => `${i + 1}. ${f.organization_name || f.email}`).join("\n")}`,
        String(Math.max(1, firms.findIndex((f) => f.id === current) + 1)),
      );
      if (choice === null) return;
      const firm = firms[Number(choice) - 1];
      if (!firm) {
        setError("Pick a firm by its number.");
        return;
      }
      run(() => adminApi.setRole(a.id, role, firm.id), "Couldn't change the role");
      return;
    }
    run(() => adminApi.setRole(a.id, role), "Couldn't change the role");
  }

  function adjustBudget(a: Account, operation: BudgetOperation) {
    const verb = operation === "add" ? "Top up" : operation === "subtract" ? "Deduct from" : "Set";
    const raw = window.prompt(`${verb} ${a.organization_name || a.email}'s budget (₱)`, "");
    if (raw === null) return;
    const amount = Number(raw);
    if (!Number.isFinite(amount) || amount < 0) {
      setError("Enter a positive amount.");
      return;
    }
    run(() => adminApi.adjustBudget(a.id, operation, amount), "Couldn't update the budget");
  }

  function saveRate(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = pageRate.trim();
    const value = trimmed === "" ? null : Number(trimmed);
    if (value !== null && (!Number.isFinite(value) || value <= 0)) {
      setError("The page rate must be a positive number, or empty to turn billing off.");
      return;
    }
    run(() => adminApi.setPageRate(value), "Couldn't save the page rate");
  }

  const sectionLabel = (text: string) => (
    <>
      <p className="px-1 text-[11px] font-medium text-[var(--lp-muted)]">{text}</p>
      <div className="h-px mt-1.5 mb-3 bg-[var(--lp-border)]" />
    </>
  );

  return (
    <div className="lp min-h-screen">
      <div className="px-4 sm:px-10 pt-6 sm:pt-8 pb-12 max-w-6xl page-enter">
        <header className="mb-8 flex flex-wrap items-center gap-3">
          <div className="mr-auto">
            <h1 className="text-[22px] font-semibold tracking-tight text-[var(--lp-text)]">Platform admin</h1>
            <p className="mt-1 text-sm text-[var(--lp-muted)]">
              New sign-ups wait here as unverified. Turn one into a firm, or attach them to an existing firm.
            </p>
          </div>
          <GuideButton open={guide.open} onClick={guide.toggle} />
        </header>

        <GuideTour open={guide.open} onClose={guide.dismiss} label="Platform admin" slides={ADMIN_TOUR} />

        {error && (
          <div className="mb-6 rounded-xl border border-[var(--alert-error-border)] bg-[var(--alert-error-bg)] px-4 py-2.5 text-sm text-[var(--alert-error-text)]">
            {error}
          </div>
        )}

        <section className="mb-8">
          {sectionLabel("Billing")}
          <form onSubmit={saveRate} className="aa-card rounded-2xl p-1.5 pl-4 flex flex-wrap items-center gap-3">
            <div className="mr-auto min-w-0 py-1.5">
              <label htmlFor="page-rate" className="block text-sm font-medium text-[var(--lp-text)]">Price per page</label>
              <p className="text-xs text-[var(--lp-muted)]">
                {savedRate == null
                  ? "Billing is off: uploads are never blocked on budget."
                  : `Each extracted page costs ₱${formatPeso(savedRate)}. Uploads stop when a firm's budget reaches zero.`}
              </p>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="relative">
                <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-[var(--lp-faint)]">₱</span>
                <input
                  id="page-rate"
                  inputMode="decimal"
                  value={pageRate}
                  onChange={(e) => setPageRate(e.target.value)}
                  placeholder="Free"
                  className="aa-field w-28 pl-7 pr-3 tabular-nums"
                />
              </div>
              <button
                type="submit"
                disabled={busy || pageRate.trim() === (savedRate == null ? "" : String(savedRate))}
                className="aa-btn"
              >
                Save
              </button>
            </div>
          </form>
        </section>

        <section>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <p className="px-1 text-[11px] font-medium text-[var(--lp-muted)]">
              Accounts <span className="text-[var(--lp-faint)] tabular-nums">· {accounts.length}</span>
            </p>
            <label className="relative">
              <MagnifyingGlass size={16} weight="light" className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--lp-muted)]" />
              <span className="sr-only">Search accounts</span>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search email, name or firm"
                className="aa-field w-64 max-w-full pl-9 pr-3"
              />
            </label>
          </div>
          <div className="h-px mt-2 mb-3 bg-[var(--lp-border)]" />

          <div className="aa-card overflow-x-auto rounded-2xl p-1.5">
            <table className="aa-table w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-[var(--lp-muted)]">
                  <th className="px-3 pt-2 pb-2.5 font-medium">Account</th>
                  <th className="px-3 pt-2 pb-2.5 font-medium">
                    Role <Hint align="right">Firm owner runs a firm and its Team page. Manager and Employee join an existing firm (you&apos;ll be asked which). Unverified sees nothing until you choose.</Hint>
                  </th>
                  <th className="px-3 pt-2 pb-2.5 font-medium">Firm</th>
                  <th className="px-3 pt-2 pb-2.5 font-medium text-right">Pages this month</th>
                  <th className="px-3 pt-2 pb-2.5 font-medium text-right">
                    Budget <Hint align="left">Prepaid pesos per firm. Only used while a price per page is set; Top up adds, Deduct removes, Set overwrites.</Hint>
                  </th>
                  <th className="px-3 pt-2 pb-2.5"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-3 py-8 text-center text-sm text-[var(--lp-muted)]">
                      {accounts.length === 0 ? "No accounts yet." : "No accounts match that search."}
                    </td>
                  </tr>
                )}
                {filtered.map((a) => {
                  const isSelf = a.id === user?.id;
                  const isFirm = a.role === "enterprise";
                  const name = a.nickname || a.email;
                  return (
                    <tr key={a.id} className={`text-[var(--lp-text)] ${a.is_active ? "" : "opacity-60"}`}>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2.5 min-w-0">
                          <span className="shrink-0 grid place-items-center w-9 h-9 rounded-xl bg-[var(--lp-accent-soft)] text-[var(--lp-accent)] text-[13px] font-semibold">
                            {name.charAt(0).toUpperCase()}
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate font-medium">
                              {name}
                              {isSelf && <span className="ml-1.5 font-normal text-[var(--lp-faint)]">(you)</span>}
                            </span>
                            {a.nickname && <span className="block truncate text-xs text-[var(--lp-muted)]">{a.email}</span>}
                            {!a.is_active && <span className="block text-xs text-[var(--error)]">Deactivated</span>}
                          </span>
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        {a.role === "admin" ? (
                          <span className="text-[var(--lp-muted)]">{roleLabel(a.role)}</span>
                        ) : (
                          <select
                            value={a.role}
                            disabled={busy}
                            onChange={(e) => changeRole(a, e.target.value as AssignableRole)}
                            aria-label={`Role for ${a.email}`}
                            className="aa-field !h-8 !rounded-[9px] px-2 text-[13px]"
                          >
                            <option value="unverified">Unverified</option>
                            <option value="enterprise" disabled={a.role === "unverified"}>Firm owner</option>
                            <option value="manager">Manager</option>
                            <option value="employee">Employee</option>
                          </select>
                        )}
                      </td>
                      <td className="px-3 py-2 text-[var(--lp-muted)]">
                        {isFirm ? a.organization_name || "—" : a.enterprise_email || "—"}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{isFirm ? a.pages_used.toLocaleString() : ""}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{isFirm ? `₱${formatPeso(a.budget)}` : ""}</td>
                      <td className="px-2 py-2">
                        <div className="flex flex-wrap justify-end gap-0.5">
                          {a.role === "unverified" && (
                            <button disabled={busy} onClick={() => promoteFirm(a)} className="aa-ghost !text-[var(--lp-accent)]">
                              Make firm
                            </button>
                          )}
                          {isFirm && (
                            <>
                              <button disabled={busy} onClick={() => adjustBudget(a, "add")} className="aa-ghost">Top up</button>
                              <button disabled={busy} onClick={() => adjustBudget(a, "subtract")} className="aa-ghost">Deduct</button>
                              <button disabled={busy} onClick={() => adjustBudget(a, "set")} className="aa-ghost">Set</button>
                            </>
                          )}
                          {!isSelf && a.role !== "admin" && (
                            <button disabled={busy} onClick={() => run(() => adminApi.toggleActive(a.id), "Couldn't update")} className="aa-ghost">
                              {a.is_active ? "Deactivate" : "Reactivate"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
