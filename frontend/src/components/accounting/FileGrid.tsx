"use client";

import { FolderSimple } from "@phosphor-icons/react";
import { CATEGORY_LABELS, counterpartyName, formatPeso } from "@/lib/accounting-format";
import type { AADocument, Folder } from "@/types/accounting";

const TILES = ["sales", "purchases", "expenses", "payroll", "2307", "support", "unsorted", "review"] as const;

interface Props {
  folder: Folder;
  category: string | null;
  onCategory: (category: string | null) => void;
  onOpen: (doc: AADocument) => void;
  onEditCompany?: () => void;
}

function inCategory(doc: AADocument, category: string): boolean {
  if (category === "review") return doc.needs_review && !doc.reviewed && !doc.excluded;
  return doc.category === category;
}

export default function FileGrid({ folder, category, onCategory, onOpen, onEditCompany }: Props) {
  const docs = category ? folder.documents.filter((d) => inCategory(d, category)) : [];

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <button onClick={() => onCategory(null)} className="font-semibold text-[var(--text-primary)] hover:underline">
          {folder.company.registered_name} / {folder.label}
        </button>
        {category && <span className="text-[var(--text-secondary)]">/ {CATEGORY_LABELS[category]}</span>}
        <div className="ml-auto flex items-center gap-3">
          {folder.counts.review > 0 && (
            <span className="rounded-full bg-[var(--badge-yellow-bg)] px-2.5 py-0.5 text-xs font-medium text-[var(--badge-yellow-text)]">
              {folder.counts.review} to review
            </span>
          )}
          {onEditCompany && (
            <button onClick={onEditCompany} className="text-xs text-[var(--text-secondary)] underline hover:text-[var(--text-primary)]">
              Edit company
            </button>
          )}
        </div>
      </div>

      {category === null ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {TILES.map((key) => (
            <button
              key={key}
              onClick={() => onCategory(key)}
              className="rounded-xl border border-[var(--border)] p-3 text-left transition-colors hover:border-[var(--accent)]"
            >
              <FolderSimple size={22} className="text-[var(--text-secondary)]" weight="fill" />
              <div className="mt-2 text-sm font-semibold text-[var(--text-primary)]">{CATEGORY_LABELS[key]}</div>
              <div className="text-xs text-[var(--text-secondary)]">
                {folder.counts[key] ?? 0}{" "}
                {key === "review" ? "open" : (folder.counts[key] ?? 0) === 1 ? "document" : "documents"}
              </div>
            </button>
          ))}
        </div>
      ) : docs.length === 0 ? (
        <p className="py-10 text-center text-sm text-[var(--text-secondary)]">Nothing here.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--text-secondary)]">
                <th className="py-2 pr-3 font-medium">Date</th>
                <th className="py-2 pr-3 font-medium">Document</th>
                <th className="py-2 pr-3 font-medium">Counterparty</th>
                <th className="py-2 pr-3 text-right font-medium">Total</th>
                <th className="py-2 pr-3 text-right font-medium">VAT</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr
                  key={d.id}
                  onClick={() => onOpen(d)}
                  className="cursor-pointer border-t border-[var(--border)] text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
                >
                  <td className="py-2 pr-3 whitespace-nowrap">{d.doc_date ?? "—"}</td>
                  <td className="py-2 pr-3">
                    {d.document_title || CATEGORY_LABELS[d.category]}
                    {d.doc_number && <span className="text-[var(--text-secondary)]"> #{d.doc_number}</span>}
                  </td>
                  <td className="py-2 pr-3">{counterpartyName(d) || "—"}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{formatPeso(d.gross_amount)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{formatPeso(d.vat_amount)}</td>
                  <td className="py-2 text-right">
                    {d.excluded ? (
                      <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-xs text-[var(--text-secondary)]">Excluded</span>
                    ) : d.needs_review && !d.reviewed && d.review_reasons.includes("possible_duplicate") ? (
                      <span className="rounded-full bg-[var(--badge-red-bg)] px-2 py-0.5 text-xs font-medium text-[var(--badge-red-text)]">Duplicate?</span>
                    ) : d.needs_review && !d.reviewed ? (
                      <span className="rounded-full bg-[var(--badge-yellow-bg)] px-2 py-0.5 text-xs font-medium text-[var(--badge-yellow-text)]">Review</span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
