"use client";

import { useEffect, useState } from "react";
import { Bank, Buildings, CaretDown, CaretRight, Plus } from "@phosphor-icons/react";
import Hint from "@/components/guide/Hint";
import type { FolderRef, TreeAnnual, TreeBankAccount, TreeCompany } from "@/types/accounting";

interface Props {
  tree: TreeCompany[];
  selected: FolderRef | null;
  onSelect: (ref: FolderRef) => void;
  canManage: boolean;
  onAddCompany: () => void;
}

const ROW = "flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm hover:bg-[var(--bg-hover)]";

export default function FolderTree({ tree, selected, onSelect, canManage, onAddCompany }: Props) {
  const [open, setOpen] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!selected) return;
    setOpen((prev) => (prev.has(selected.companyId) ? prev : new Set(prev).add(selected.companyId)));
  }, [selected]);

  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const isSelected = (ref: FolderRef) =>
    selected?.companyId === ref.companyId && selected.year === ref.year && selected.quarter === ref.quarter &&
    (selected.view ?? null) === (ref.view ?? null) && (selected.bankAccount ?? null) === (ref.bankAccount ?? null) &&
    (selected.month ?? null) === (ref.month ?? null);

  const monthLabel = (iso: string) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString("en-PH", { month: "short", year: "numeric" });

  // Company → Year → Bank → account → month: each month leaf shows lines still open, or Reconciled.
  const bank = (companyId: string, year: number, accounts: TreeBankAccount[]) => {
    const key = `${companyId}:${year}:bank`;
    const open_lines = accounts.reduce((n, a) => n + a.months.reduce((m, x) => m + x.open, 0), 0);
    return (
      <li>
        <button onClick={() => toggle(key)} className={`${ROW} text-[var(--text-primary)]`}>
          {open.has(key) ? <CaretDown size={12} /> : <CaretRight size={12} />}
          <Bank size={14} className="shrink-0 text-[var(--text-secondary)]" />
          <span className="truncate">Bank</span>
          {open_lines > 0 && (
            <span className="ml-auto rounded-full bg-[var(--badge-yellow-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-yellow-text)]">{open_lines}</span>
          )}
        </button>
        {open.has(key) && (
          <ul className="ml-3 border-l border-[var(--border)] pl-2">
            {accounts.map((a) => (
              <li key={a.account_code || "unset"}>
                <div className="truncate px-2 pt-1 text-xs text-[var(--text-secondary)]">
                  {a.account_code ? `${a.account_code} ${a.name}` : a.name}
                  {a.last4 && ` ····${a.last4}`}
                </div>
                <ul>
                  {a.months.map((m) => {
                    const ref: FolderRef = {
                      companyId, year, quarter: null, view: "bank", bankAccount: a.account_code, month: m.month_start.slice(0, 7),
                    };
                    return (
                      <li key={m.month_start}>
                        <button
                          onClick={() => onSelect(ref)}
                          className={`${ROW} ${isSelected(ref) ? "bg-[var(--accent-subtle)] font-semibold" : ""} text-[var(--text-primary)]`}
                        >
                          <span className="truncate">{monthLabel(m.month_start)}</span>
                          <span className="ml-auto text-xs text-[var(--text-secondary)]">{m.lines}</span>
                          {m.open > 0 && (
                            <span className="rounded-full bg-[var(--badge-yellow-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-yellow-text)]">{m.open}</span>
                          )}
                          {m.reconciled && (
                            <span className="rounded-full bg-[var(--badge-green-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-green-text)]">Reconciled</span>
                          )}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </li>
    );
  };

  const leaf = (ref: FolderRef, label: string, count: number | null, review: number, status?: TreeAnnual) => (
    <button
      onClick={() => onSelect(ref)}
      className={`${ROW} ${isSelected(ref) ? "bg-[var(--accent-subtle)] font-semibold text-[var(--text-primary)]" : "text-[var(--text-primary)]"}`}
    >
      <span className="truncate">{label}</span>
      <span className="ml-auto text-xs text-[var(--text-secondary)]">{count ?? ""}</span>
      {review > 0 && (
        <span className="rounded-full bg-[var(--badge-yellow-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-yellow-text)]">
          {review}
        </span>
      )}
      {status?.filed && (
        <span className="rounded-full bg-[var(--badge-green-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-green-text)]">Filed</span>
      )}
      {status?.stale ? (
        <span className="rounded-full bg-[var(--badge-yellow-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-yellow-text)]">Stale</span>
      ) : status?.latest_version && !status.filed ? (
        <span className="rounded-full bg-[var(--badge-blue-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-blue-text)]">v{status.latest_version}</span>
      ) : null}
    </button>
  );

  const company = (c: TreeCompany) => (
    <li key={c.id}>
      <button onClick={() => toggle(c.id)} className={`${ROW} text-[var(--text-primary)]`}>
        {open.has(c.id) ? <CaretDown size={12} /> : <CaretRight size={12} />}
        <Buildings size={15} className="shrink-0 text-[var(--text-secondary)]" />
        <span className="truncate font-medium">{c.registered_name}</span>
      </button>
      {open.has(c.id) && (
        <ul className="ml-4 border-l border-[var(--border)] pl-2">
          <li>{leaf({ companyId: c.id, year: null, quarter: null, view: "overview" }, "Overview", null, 0)}</li>
          {c.years.length === 0 && c.undated_count === 0 && (
            <li className="px-2 py-1 text-xs text-[var(--text-secondary)]">No documents yet</li>
          )}
          {c.years.map((y) => (
            <li key={y.year}>
              <div className="px-2 pt-1.5 text-xs font-semibold text-[var(--text-secondary)]">{y.year}</div>
              <ul>
                {c.books_start && (
                  <li>{leaf({ companyId: c.id, year: y.year, quarter: null, view: "books" }, "Books", null, 0)}</li>
                )}
                {y.bank && y.bank.length > 0 && bank(c.id, y.year, y.bank)}
                <li>{leaf({ companyId: c.id, year: y.year, quarter: 0 }, "Annual return", null, 0, y.annual)}</li>
                {c.has_employees && (
                  <li>{leaf({ companyId: c.id, year: y.year, quarter: null, view: "employees" }, "Employees (1604-C)", null, 0)}</li>
                )}
                {y.quarters.map((q) => (
                  <li key={q.quarter}>
                    {leaf({ companyId: c.id, year: q.year, quarter: q.quarter }, q.label, q.document_count, q.review_count, q)}
                  </li>
                ))}
              </ul>
            </li>
          ))}
          {c.books_start && (
            <li>{leaf({ companyId: c.id, year: null, quarter: null, view: "reports" }, "Reports", null, 0)}</li>
          )}
          {c.books_start && (
            <li>{leaf({ companyId: c.id, year: null, quarter: null, view: "reclassify" }, "Reclassify", null, 0)}</li>
          )}
          {c.books_start && (
            <li>{leaf({ companyId: c.id, year: null, quarter: null, view: "import" }, "Import", null, 0)}</li>
          )}
          <li>{leaf({ companyId: c.id, year: null, quarter: null, view: "customers" }, "Customers", null, 0)}</li>
          <li>{leaf({ companyId: c.id, year: null, quarter: null, view: "suppliers" }, "Suppliers", null, 0)}</li>
          <li>{leaf({ companyId: c.id, year: null, quarter: null, view: "atc" }, "ATC databank", null, 0)}</li>
          <li>{leaf({ companyId: c.id, year: null, quarter: null, view: "audit" }, "Audit log", null, 0)}</li>
          {c.undated_count > 0 && (
            <li>{leaf({ companyId: c.id, year: null, quarter: null }, "Undated", c.undated_count, c.undated_count)}</li>
          )}
        </ul>
      )}
    </li>
  );

  const pinned = tree.filter((c) => c.pinned);
  const others = tree.filter((c) => !c.pinned);
  const heading = "px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]";

  return (
    <nav aria-label="Companies">
      {pinned.length > 0 && (
        <>
          <p className={heading}>Pinned</p>
          <ul>{pinned.map(company)}</ul>
        </>
      )}
      {others.length > 0 && (
        <>
          <p className={heading}>{pinned.length ? "All companies" : "Companies"}</p>
          <ul>{others.map(company)}</ul>
        </>
      )}
      {tree.length === 0 && (
        <p className="px-2 py-3 text-sm text-[var(--text-secondary)]">No companies yet. Drop documents or add a company.</p>
      )}
      {tree.length > 0 && (
        <p className="mt-2 flex items-center gap-1 px-2 text-xs text-[var(--text-secondary)]">
          What the badges mean
          <Hint align="right">
            <span className="block"><b className="text-[var(--badge-yellow-text)]">3</b> documents to review</span>
            <span className="block"><b className="text-[var(--badge-blue-text)]">v2</b> returns generated (version 2)</span>
            <span className="block"><b className="text-[var(--badge-yellow-text)]">Stale</b> changed since the last version; generate again</span>
            <span className="block"><b className="text-[var(--badge-green-text)]">Filed</b> marked as filed with the BIR</span>
            <span className="mt-1 block">Books, Employees and the ATC databank show up once a company has books or payroll set up.</span>
            <span className="mt-1 block">Overview shows the client&apos;s filings coming due, a health check and its tasks.</span>
            <span className="mt-1 block">Reports (once books are on) show the P&amp;L, balance sheet, ledger detail and more, with every amount traced to its document.</span>
            <span className="mt-1 block">Reclassify moves what was posted to one account (or ATC) to another in bulk, with a preview first.</span>
            <span className="mt-1 block">Customers and Suppliers show who owes the company and whom it owes, with aging and 2307s.</span>
            <span className="mt-1 block">Audit log lists every change people made to the company, with who, when and why.</span>
            <span className="mt-1 block">Bank lists each bank account&apos;s statement months: <b className="text-[var(--badge-yellow-text)]">2</b> lines still to match, <b className="text-[var(--badge-green-text)]">Reconciled</b> once the books agree with the statement.</span>
          </Hint>
        </p>
      )}
      {canManage && (
        <button onClick={onAddCompany} className="mt-3 flex items-center gap-1.5 px-2 text-sm font-semibold text-[var(--accent)]">
          <Plus size={14} /> Add company
        </button>
      )}
    </nav>
  );
}
