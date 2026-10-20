"use client";

import { useState } from "react";
import { ArrowLeft, FolderSimple } from "@phosphor-icons/react";
import Hint from "@/components/guide/Hint";
import { accountingApi } from "@/lib/accounting-api";
import { CATEGORY_LABELS, REASON_LABELS, SOFT_REASONS, apiErrorMessage, counterpartyName, formatPeso } from "@/lib/accounting-format";
import type { AADocument, Folder } from "@/types/accounting";

const TILES = ["sales", "purchases", "expenses", "payroll", "2307", "support", "unsorted", "review"] as const;

interface Props {
  folder: Folder;
  category: string | null;
  onCategory: (category: string | null) => void;
  onOpen: (doc: AADocument) => void;
  onEditCompany?: () => void;
  /** After a bulk resolve in the review queue: reload the folder and tree. */
  onBulkResolved?: () => void;
}

const SHORT_REASON: Record<string, string> = {
  low_confidence: "Low confidence", missing_date: "No date", missing_amount: "No amount", unsorted: "Unsorted",
  not_addressed_to_client: "Not addressed to client", seller_not_vat_registered: "Seller not VAT", not_an_invoice: "Not an invoice",
  vat_math_mismatch: "VAT not 12%", amounts_dont_add_up: "Amounts don't add up", possible_duplicate: "Possible duplicate",
  other_company_tin: "Other company's TIN", nothing_extracted: "Nothing read", possible_payment: "Possible payment",
  supplier_rule_mismatch: "Supplier rule mismatch", tendered_less_than_total: "Tendered short", ewt_expected: "EWT expected",
  payment_source_unknown: "Payment source unknown", duplicate_invoice_number: "Duplicate number", personal_purchase: "Personal",
  account_locked: "Locked account", receipt_incomplete: "Invalid receipt", needs_review: "Needs review",
};

const DUPLICATE = new Set(["possible_duplicate", "duplicate_invoice_number"]);

/** What the review queue shows for a document: its queue reasons, duplicates first ("Needs review" when none). */
function issues(doc: AADocument): string[] {
  const reasons = doc.review_reasons.filter((r) => !SOFT_REASONS.has(r));
  return reasons.length ? [...reasons].sort((a, b) => Number(DUPLICATE.has(b)) - Number(DUPLICATE.has(a))) : ["needs_review"];
}

function inCategory(doc: AADocument, category: string): boolean {
  if (category === "review") return doc.needs_review && !doc.reviewed && !doc.excluded;
  return doc.category === category;
}

export default function FileGrid({ folder, category, onCategory, onOpen, onEditCompany, onBulkResolved }: Props) {
  const [reasonFilter, setReasonFilter] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const inReview = category === "review";
  const all = category ? folder.documents.filter((d) => inCategory(d, category)) : [];
  const reasonCounts = new Map<string, number>();
  if (inReview) for (const d of all) for (const r of d.review_reasons) if (!SOFT_REASONS.has(r)) reasonCounts.set(r, (reasonCounts.get(r) ?? 0) + 1);
  const filter = inReview && reasonFilter && reasonCounts.has(reasonFilter) ? reasonFilter : null;
  const docs = filter ? all.filter((d) => d.review_reasons.includes(filter)) : all;
  const chosen = docs.filter((d) => picked.has(d.id));
  const toggle = (id: string) => setPicked((p) => {
    const next = new Set(p);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });

  async function resolve(action: "reviewed" | "exclude") {
    if (!filter || chosen.length === 0) return;
    setBusy(true);
    setMessage("");
    try {
      const out = await accountingApi.bulkResolve({ document_ids: chosen.map((d) => d.id), reason_code: filter, action, reason: why.trim() });
      setMessage(`${out.resolved.length} ${action === "reviewed" ? "marked reviewed" : "excluded"}${out.skipped.length ? `, ${out.skipped.length} skipped` : ""}.`);
      setPicked(new Set());
      setWhy("");
      onBulkResolved?.();
    } catch (e) {
      setMessage(apiErrorMessage(e, "Couldn't resolve the documents"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <button onClick={() => onCategory(null)} className="font-semibold text-[var(--text-primary)] hover:underline">
          {folder.company.registered_name} / {folder.label}
        </button>
        {category && <span className="text-[var(--text-secondary)]">/ {CATEGORY_LABELS[category]}</span>}
        <div className="ml-auto flex items-center gap-3">
          {category && (
            <button
              onClick={() => onCategory(null)}
              className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
            >
              <ArrowLeft size={13} />
              Back
            </button>
          )}
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
      ) : null}
      {inReview && reasonCounts.size > 0 && (
        <div className="mb-3 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-[var(--text-secondary)]">
              Resolve in bulk{" "}
              <Hint>Pick a reason to see only the documents flagged for it, tick them, then mark them reviewed or exclude them in one go. Each document&apos;s audit log keeps your reason.</Hint>
            </span>
            {[...reasonCounts.entries()].sort((a, b) => b[1] - a[1]).map(([r, n]) => (
              <button
                key={r}
                title={REASON_LABELS[r]}
                onClick={() => {
                  setReasonFilter(filter === r ? null : r);
                  setPicked(new Set());
                }}
                className={`rounded-full border px-2.5 py-0.5 ${filter === r ? "border-[var(--accent)] text-[var(--accent)]" : "border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}
              >
                {SHORT_REASON[r] ?? r} · {n}
              </button>
            ))}
          </div>
          {filter && (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <label className="inline-flex items-center gap-1 text-xs text-[var(--text-secondary)]">
                <input
                  type="checkbox"
                  checked={chosen.length === docs.length && docs.length > 0}
                  onChange={(e) => setPicked(new Set(e.target.checked ? docs.map((d) => d.id) : []))}
                />
                All {docs.length}
              </label>
              <input
                className="w-64 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1 text-sm text-[var(--text-primary)]"
                placeholder="Reason (kept in the audit log)"
                maxLength={500}
                value={why}
                onChange={(e) => setWhy(e.target.value)}
              />
              <button
                className="rounded-lg bg-[var(--accent)] px-3 py-1 font-medium text-white disabled:opacity-60"
                disabled={busy || chosen.length === 0 || why.trim().length < 3}
                onClick={() => resolve("reviewed")}
              >
                Mark {chosen.length} reviewed
              </button>
              <button
                className="rounded-lg border border-[var(--border)] px-3 py-1 font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60"
                disabled={busy || chosen.length === 0 || why.trim().length < 3}
                onClick={() => resolve("exclude")}
              >
                Exclude {chosen.length}
              </button>
            </div>
          )}
          {message && <p className="text-xs text-[var(--text-secondary)]">{message}</p>}
        </div>
      )}
      {category === null ? null : docs.length === 0 ? (
        <p className="py-10 text-center text-sm text-[var(--text-secondary)]">Nothing here.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--text-secondary)]">
                {filter && <th className="w-6 py-2" />}
                <th className="py-2 pr-3 font-medium">Date</th>
                <th className="py-2 pr-3 font-medium">Document</th>
                <th className="py-2 pr-3 font-medium">Counterparty</th>
                {inReview ? (
                  <th className="py-2 font-medium">Suspected issue</th>
                ) : (
                  <>
                    <th className="py-2 pr-3 text-right font-medium">Total</th>
                    <th className="py-2 pr-3 text-right font-medium">VAT</th>
                    <th className="py-2" />
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr
                  key={d.id}
                  onClick={() => onOpen(d)}
                  className="cursor-pointer border-t border-[var(--border)] text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
                >
                  {filter && (
                    <td className="py-2" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" aria-label={`Select ${d.doc_number || d.id}`} checked={picked.has(d.id)} onChange={() => toggle(d.id)} />
                    </td>
                  )}
                  <td className="py-2 pr-3 whitespace-nowrap">{d.doc_date ?? "—"}</td>
                  <td className="py-2 pr-3">
                    {d.document_title || CATEGORY_LABELS[d.category]}
                    {d.doc_number && <span className="text-[var(--text-secondary)]"> #{d.doc_number}</span>}
                  </td>
                  <td className="py-2 pr-3">{counterpartyName(d) || "—"}</td>
                  {inReview ? (
                    <td className="py-2">
                      <div className="flex flex-wrap gap-1">
                        {issues(d).map((r) => (
                          <button
                            key={r}
                            title={`${REASON_LABELS[r] ?? r} Click to see only these.`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setReasonFilter(filter === r ? null : r);
                              setPicked(new Set());
                              setMessage("");
                            }}
                            className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${DUPLICATE.has(r)
                              ? "bg-[var(--badge-red-bg)] text-[var(--badge-red-text)]"
                              : "border border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"}`}
                          >
                            {SHORT_REASON[r] ?? REASON_LABELS[r] ?? r}
                          </button>
                        ))}
                      </div>
                    </td>
                  ) : (
                  <>
                  <td className="py-2 pr-3 text-right tabular-nums">{formatPeso(d.gross_amount)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{formatPeso(d.vat_amount)}</td>
                  <td className="py-2 text-right">
                    {d.excluded ? (
                      <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-xs text-[var(--text-secondary)]">{d.review_reasons.includes("personal_purchase") ? "Excluded: personal" : "Excluded"}</span>
                    ) : d.needs_review && !d.reviewed && (d.review_reasons.includes("possible_duplicate") || d.review_reasons.includes("duplicate_invoice_number")) ? (
                      <span className="rounded-full bg-[var(--badge-red-bg)] px-2 py-0.5 text-xs font-medium text-[var(--badge-red-text)]">Duplicate?</span>
                    ) : d.needs_review && !d.reviewed ? (
                      <span className="rounded-full bg-[var(--badge-yellow-bg)] px-2 py-0.5 text-xs font-medium text-[var(--badge-yellow-text)]">Review</span>
                    ) : null}
                  </td>
                  </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
