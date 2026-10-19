"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, X } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, formatAmount } from "@/lib/accounting-format";
import { BTN, Chip, shortDate } from "@/components/work/ui";
import type { PostingLine, Postings, ReportSource } from "@/types/accounting";

/** What the drawer shows: the postings behind a report cell, or one entry's source. */
export type DrillTarget =
  | { mode: "postings"; label: string; codes: string[]; start: string | null; end: string }
  | { mode: "entry"; label: string; entryId: string };

interface Props {
  companyId: string;
  target: DrillTarget;
  onClose: () => void;
  onOpenDocument: (id: string, page?: number) => void;
}

const SOURCE_LABEL: Record<string, string> = {
  document: "Document",
  bank_line: "Bank line",
  journal_entry: "Journal entry",
  asset: "Depreciation",
  tax: "Tax return",
  system: "Books engine",
};

/** Drill-down: report amount → the postings behind it → the source document page, journal entry or bank line. */
export default function ReportDrill({ companyId, target, onClose, onOpenDocument }: Props) {
  const [postings, setPostings] = useState<Postings | null>(null);
  const [source, setSource] = useState<ReportSource | null>(null);
  const [line, setLine] = useState<PostingLine | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError("");
    setPostings(null);
    setSource(null);
    setLine(null);
    if (target.mode === "postings") {
      accountingApi
        .reportPostings(companyId, target.codes, target.start, target.end)
        .then((p) => !cancelled && setPostings(p))
        .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the postings")));
    } else {
      accountingApi
        .reportSource(companyId, target.entryId)
        .then((s) => !cancelled && setSource(s))
        .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't find the source")));
    }
    return () => {
      cancelled = true;
    };
  }, [companyId, target]);

  const openLine = (l: PostingLine) => {
    setLine(l);
    setSource(null);
    accountingApi
      .reportSource(companyId, l.entry_id)
      .then(setSource)
      .catch((e) => setError(apiErrorMessage(e, "Couldn't find the source")));
  };

  const span =
    target.mode === "postings"
      ? `${target.start ? shortDate(target.start) : "From the start of the books"} – ${shortDate(target.end)}`
      : "";

  return (
    <div className="fixed inset-y-0 right-0 z-30 flex w-full max-w-xl flex-col border-l border-[var(--border)] bg-[var(--bg-secondary)] shadow-xl">
      <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-3">
        {line && target.mode === "postings" && (
          <button aria-label="Back to the postings" className="p-1 text-[var(--text-secondary)]" onClick={() => { setLine(null); setSource(null); }}>
            <ArrowLeft size={16} />
          </button>
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-[var(--text-primary)]">{target.label}</p>
          {span && <p className="text-xs text-[var(--text-secondary)]">{span}</p>}
        </div>
        <button aria-label="Close" className="p-1 text-[var(--text-secondary)]" onClick={onClose}>
          <X size={16} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 text-sm">
        {error && <p className="mb-2 text-[var(--alert-error-text)]">{error}</p>}
        {target.mode === "postings" && !line && postings && (
          <>
            <p className="mb-2 text-xs text-[var(--text-secondary)]">
              {postings.count} posting{postings.count === 1 ? "" : "s"} · net {formatAmount(postings.total)} (debit − credit)
              {postings.truncated && ` · showing the first ${postings.lines.length}; narrow the dates to see the rest`}
            </p>
            <ul className="divide-y divide-[var(--border)] rounded-lg border border-[var(--border)] bg-[var(--bg-primary)]">
              {postings.lines.map((l, i) => (
                <li key={`${l.entry_id}-${i}`}>
                  <button className="flex w-full flex-wrap items-baseline gap-x-2 px-3 py-2 text-left hover:bg-[var(--bg-hover)]" onClick={() => openLine(l)}>
                    <span className="w-24 text-xs text-[var(--text-secondary)]">{shortDate(l.date)}</span>
                    <span className="min-w-0 flex-1 truncate text-[var(--text-primary)]">{l.particulars || l.reference}</span>
                    <span className="tabular-nums text-[var(--text-primary)]">
                      {Number(l.debit) ? `Dr ${formatAmount(l.debit)}` : `Cr ${formatAmount(l.credit)}`}
                    </span>
                    <span className="w-full text-xs text-[var(--text-secondary)]">
                      {l.code} {l.name} · {l.book} {l.reference}{l.party && ` · ${l.party}`} · {SOURCE_LABEL[l.ref.kind]}
                    </span>
                  </button>
                </li>
              ))}
              {postings.lines.length === 0 && <li className="px-3 py-4 text-[var(--text-secondary)]">No postings in this window.</li>}
            </ul>
          </>
        )}
        {(line || target.mode === "entry") && (
          <SourceView source={source} line={line} onOpenDocument={onOpenDocument} />
        )}
      </div>
    </div>
  );
}

function SourceView({ source, line, onOpenDocument }: {
  source: ReportSource | null;
  line: PostingLine | null;
  onOpenDocument: (id: string, page?: number) => void;
}) {
  if (!source) return <p className="text-[var(--text-secondary)]">Finding the source…</p>;
  const doc = source.document;
  return (
    <div className="space-y-3">
      {line && (
        <p className="text-[var(--text-primary)]">
          {shortDate(line.date)} · {line.book} {line.reference} · {line.particulars}
        </p>
      )}
      <div><Chip tone="blue">{SOURCE_LABEL[source.kind]}</Chip></div>
      {source.bank_line && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-3">
          <p className="font-medium text-[var(--text-primary)]">
            Statement line {source.bank_line.line_no} · {shortDate(source.bank_line.date)} · {formatAmount(source.bank_line.amount)}
          </p>
          <p className="text-xs text-[var(--text-secondary)]">
            {source.bank_line.narration}
            {source.bank_line.check_no && ` · check ${source.bank_line.check_no}`} · account {source.bank_line.account_code}
          </p>
        </div>
      )}
      {source.journal_entry && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-3">
          <p className="font-medium text-[var(--text-primary)]">
            {source.journal_entry.kind === "opening" ? "Opening balances" : "Journal entry"} · {source.journal_entry.book} ·{" "}
            {shortDate(source.journal_entry.entry_date)} {source.journal_entry.reference}
            {source.journal_entry.is_adjusting && <span className="ml-2"><Chip tone="blue">Adjusting</Chip></span>}
            {source.journal_entry.deleted && <span className="ml-2"><Chip tone="red">Deleted</Chip></span>}
          </p>
          <p className="mb-2 text-xs text-[var(--text-secondary)]">{source.journal_entry.particulars}</p>
          <table className="w-full text-xs">
            <tbody>
              {source.journal_entry.lines.map((l, i) => (
                <tr key={i}>
                  <td className="py-0.5 text-[var(--text-primary)]">{l.account_code}</td>
                  <td className="py-0.5 text-[var(--text-secondary)]">{l.party_name}</td>
                  <td className="py-0.5 text-right tabular-nums">{Number(l.debit) ? formatAmount(String(l.debit)) : ""}</td>
                  <td className="py-0.5 text-right tabular-nums">{Number(l.credit) ? formatAmount(String(l.credit)) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-[var(--text-secondary)]">Typed entries have no scanned page; edit them under Books.</p>
        </div>
      )}
      {source.asset && (
        <p className="text-[var(--text-primary)]">
          {source.asset.description} · cost {formatAmount(source.asset.cost)} · in service {shortDate(source.asset.in_service)}
        </p>
      )}
      {(source.kind === "tax" || source.kind === "system") && (
        <p className="text-[var(--text-secondary)]">
          {source.kind === "tax"
            ? "Posted from the quarter's returns (accrual) or a filed return's payment. Open the quarter to see the version."
            : "Posted by the books engine (inventory count, contributions or a correction of a closed month)."}
        </p>
      )}
      {doc && (
        <div>
          <button className={BTN} onClick={() => onOpenDocument(doc.document_id, doc.page)}>
            Open {source.kind === "bank_line" ? "the statement" : "the document"}, page {doc.page}
            {doc.doc_number && ` · ${doc.doc_number}`}
          </button>
        </div>
      )}
      {doc === null && <p className="text-[var(--text-secondary)]">The source document was deleted.</p>}
    </div>
  );
}
