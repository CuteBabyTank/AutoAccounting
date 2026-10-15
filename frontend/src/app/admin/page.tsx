"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { MagnifyingGlass } from "@phosphor-icons/react";
import AppBackdrop from "@/components/layout/AppBackdrop";
import { useAuth } from "@/lib/auth";
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

  return (
    <div className="lp relative min-h-screen">
      <AppBackdrop />
      <div className="p-4 sm:p-8 max-w-6xl page-enter">
        <div className="mb-6 flex flex-wrap items-end gap-3">
          <div className="mr-auto">
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">Platform admin</h1>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              New sign-ups wait here as unverified. Turn one into a firm, or attach them to an existing firm.
            </p>
          </div>
          <form onSubmit={saveRate} className="flex items-center gap-2 text-sm">
            <label className="text-[var(--text-secondary)]" htmlFor="page-rate">₱ per page</label>
            <input
              id="page-rate"
              inputMode="decimal"
              value={pageRate}
              onChange={(e) => setPageRate(e.target.value)}
              placeholder="Free"
              className="w-24 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-1.5 text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
            />
            <button
              type="submit"
              disabled={busy || pageRate.trim() === (savedRate == null ? "" : String(savedRate))}
              className="rounded-lg bg-[var(--accent)] px-3 py-1.5 font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
            >
              Save
            </button>
          </form>
        </div>

        <p className="mb-4 text-xs text-[var(--text-secondary)]">
          {savedRate == null
            ? "Billing is off: uploads are never blocked on budget."
            : `Billing is on: each extracted page costs ₱${formatPeso(savedRate)} and uploads stop when a firm's budget reaches zero.`}
        </p>

        <label className="relative mb-4 inline-block">
          <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search email, name or firm"
            className="w-64 rounded-full border border-[var(--border)] bg-[var(--bg-secondary)] py-1.5 pl-8 pr-3 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
          />
        </label>

        {error && (
          <div className="mb-4 rounded-lg border border-[var(--alert-error-border)] bg-[var(--alert-error-bg)] px-4 py-2 text-sm text-[var(--alert-error-text)]">
            {error}
          </div>
        )}

        <div className="overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--text-secondary)]">
                <th className="px-4 py-3 font-medium">Account</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Firm</th>
                <th className="px-4 py-3 font-medium text-right">Pages (month)</th>
                <th className="px-4 py-3 font-medium text-right">Budget</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((a) => {
                const isSelf = a.id === user?.id;
                const isFirm = a.role === "enterprise";
                return (
                  <tr key={a.id} className={`border-t border-[var(--border)] text-[var(--text-primary)] ${a.is_active ? "" : "opacity-60"}`}>
                    <td className="px-4 py-3">
                      <div className="font-medium">{a.nickname || a.email}</div>
                      {a.nickname && <div className="text-xs text-[var(--text-secondary)]">{a.email}</div>}
                      {!a.is_active && <div className="text-xs text-[var(--error)]">Deactivated</div>}
                    </td>
                    <td className="px-4 py-3">
                      {a.role === "admin" ? (
                        roleLabel(a.role)
                      ) : (
                        <select
                          value={a.role}
                          disabled={busy}
                          onChange={(e) => changeRole(a, e.target.value as AssignableRole)}
                          className="rounded-md border border-[var(--border)] bg-[var(--bg-secondary)] px-2 py-1 text-sm text-[var(--text-primary)]"
                        >
                          <option value="unverified">Unverified</option>
                          <option value="enterprise" disabled={a.role === "unverified"}>Firm owner</option>
                          <option value="manager">Manager</option>
                          <option value="employee">Employee</option>
                        </select>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[var(--text-secondary)]">
                      {isFirm ? a.organization_name || "—" : a.enterprise_email || "—"}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">{isFirm ? a.pages_used.toLocaleString() : ""}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{isFirm ? `₱${formatPeso(a.budget)}` : ""}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap justify-end gap-3 text-xs">
                        {a.role === "unverified" && (
                          <button disabled={busy} onClick={() => promoteFirm(a)} className="text-[var(--accent)] hover:underline">
                            Make firm
                          </button>
                        )}
                        {isFirm && (
                          <>
                            <button disabled={busy} onClick={() => adjustBudget(a, "add")} className="text-[var(--accent)] hover:underline">Top up</button>
                            <button disabled={busy} onClick={() => adjustBudget(a, "subtract")} className="text-[var(--accent)] hover:underline">Deduct</button>
                            <button disabled={busy} onClick={() => adjustBudget(a, "set")} className="text-[var(--accent)] hover:underline">Set</button>
                          </>
                        )}
                        {!isSelf && a.role !== "admin" && (
                          <button disabled={busy} onClick={() => run(() => adminApi.toggleActive(a.id), "Couldn't update")} className="text-[var(--accent)] hover:underline">
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
      </div>
    </div>
  );
}
