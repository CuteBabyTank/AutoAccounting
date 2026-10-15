"use client";

import { useEffect, useState } from "react";
import { Buildings, CaretDown, CaretRight, Plus } from "@phosphor-icons/react";
import type { FolderRef, TreeAnnual, TreeCompany } from "@/types/accounting";

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
    (selected.view ?? null) === (ref.view ?? null);

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
          <li>{leaf({ companyId: c.id, year: null, quarter: null, view: "atc" }, "ATC databank", null, 0)}</li>
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
      {canManage && (
        <button onClick={onAddCompany} className="mt-3 flex items-center gap-1.5 px-2 text-sm font-semibold text-[var(--accent)]">
          <Plus size={14} /> Add company
        </button>
      )}
    </nav>
  );
}
