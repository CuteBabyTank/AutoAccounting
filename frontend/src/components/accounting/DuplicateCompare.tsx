"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Trash, X } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/accounting-api";
import { CATEGORY_LABELS, apiErrorMessage, counterpartyName, formatPeso, formatTin } from "@/lib/accounting-format";
import type { AADocument, DuplicatePair } from "@/types/accounting";
import PageViewer from "@/components/accounting/PageViewer";

const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50";

const REASONS: Record<DuplicatePair["reason"], string> = {
  same_number: "Same counterparty and document number.",
  same_details: "Same counterparty, date and total. The number is different or missing, so it may have been misread.",
  number_reused: "Same supplier and invoice number, but a different date. A supplier shouldn't reuse an invoice number.",
};

type Side = "original" | "duplicate";

interface Props {
  pairs: DuplicatePair[];
  onClose: () => void;
  /** A copy was deleted or a pair kept; the folder should reload. */
  onResolved: (deletedId: string | null) => void;
}

function useFirstPages(doc: AADocument): string[] {
  const [images, setImages] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    const urls: string[] = [];
    setImages([]);
    const last = Math.min(doc.page_end, doc.page_start + 9);
    (async () => {
      for (let p = doc.page_start; p <= last; p++) {
        try {
          const blob = await accountingApi.pageImage(doc.file_id, p);
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          urls.push(url);
          setImages((prev) => [...prev, url]);
        } catch {
          // Previews are best-effort; the fields still compare.
        }
      }
    })();
    return () => {
      cancelled = true;
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [doc.file_id, doc.page_start, doc.page_end]);
  return images;
}

const ROWS: [string, (d: AADocument) => string][] = [
  ["Document no.", (d) => d.doc_number || "None"],
  ["Date", (d) => d.doc_date ?? "None"],
  ["Counterparty", (d) => counterpartyName(d) || "None"],
  ["TIN", (d) => {
    const tin = d.client_role === "seller" ? d.buyer_tin : d.seller_tin;
    return tin ? formatTin(tin) : "None";
  }],
  ["Total", (d) => formatPeso(d.gross_amount)],
  ["VAT", (d) => formatPeso(d.vat_amount)],
  ["Folder", (d) => CATEGORY_LABELS[d.category] ?? d.category],
  ["Quarter", (d) => (d.period_year ? `${d.period_year} Q${d.period_quarter}` : "Undated")],
];

function Copy({ doc, other, file, label, selected, onSelect }: {
  doc: AADocument; other: AADocument; file: string; label: string; selected: boolean; onSelect: () => void;
}) {
  const images = useFirstPages(doc);
  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={`relative flex min-w-0 cursor-pointer flex-col rounded-xl border-2 p-3 text-left transition-[border-color,box-shadow] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
        selected ? "border-red-500 shadow-[0_0_0_4px_rgba(239,68,68,0.25)]" : "border-[var(--border)] hover:border-[var(--accent)]"
      }`}
    >
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-semibold text-[var(--text-primary)]">{label}</span>
        {selected ? (
          <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-[var(--badge-red-bg)] px-2 py-0.5 text-xs font-semibold text-[var(--badge-red-text)]">
            <Trash size={12} weight="bold" /> Will be deleted
          </span>
        ) : (
          <span className="ml-auto text-xs text-[var(--text-secondary)]">Click to delete this copy</span>
        )}
      </div>
      <p className="mb-2 truncate text-xs text-[var(--text-secondary)]" title={file}>
        {file || "Uploaded file"} · page{doc.page_end > doc.page_start ? `s ${doc.page_start}–${doc.page_end}` : ` ${doc.page_start}`}
      </p>
      {/* Zooming and panning the page must not pick this copy for deletion. */}
      <div
        className={`mb-3 ${selected ? "opacity-70" : ""}`}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <PageViewer images={images} firstPage={doc.page_start} className="h-[42vh]" />
      </div>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
        {ROWS.map(([name, value]) => {
          const differs = value(doc) !== value(other);
          return (
            <div key={name} className="contents">
              <dt className="text-[var(--text-secondary)]">{name}</dt>
              <dd className={`truncate tabular-nums ${differs ? "rounded bg-[var(--badge-yellow-bg)] px-1 font-medium text-[var(--badge-yellow-text)]" : "text-[var(--text-primary)]"}`}>
                {value(doc)}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

/** Side by side: is this the same paper twice? Pick the copy to delete, or keep both. */
export default function DuplicateCompare({ pairs: initial, onClose, onResolved }: Props) {
  const [pairs, setPairs] = useState(initial);
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<Side | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [keepReason, setKeepReason] = useState("");

  const pair = pairs[Math.min(index, pairs.length - 1)];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!pair) return null;

  /** Move on with the pairs still open; close when none are left. */
  function advance(left: DuplicatePair[]) {
    setSelected(null);
    setBusy(false);
    if (!left.length) {
      onClose();
      return;
    }
    setPairs(left);
    setIndex((i) => Math.min(i, left.length - 1));
  }

  async function deleteSelected() {
    if (!selected) return;
    const doc = pair[selected];
    setBusy(true);
    setError("");
    try {
      await accountingApi.deleteDocument(doc.id);
      onResolved(doc.id);
      advance(pairs.filter((p) => p.original.id !== doc.id && p.duplicate.id !== doc.id));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't delete the copy"));
      setBusy(false);
    }
  }

  async function keepBoth() {
    setBusy(true);
    setError("");
    try {
      await accountingApi.notDuplicate(pair.duplicate.id, pair.original.id, keepReason.trim());
      setKeepReason("");
      onResolved(null);
      advance(pairs.filter((p) => p !== pair));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't keep both"));
      setBusy(false);
    }
  }

  const next = () => {
    setSelected(null);
    setError("");
    setIndex((i) => (i + 1) % pairs.length);
  };

  // Portalled to <body>: the folder area is animated with a transform, which would trap a fixed overlay inside it.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dup-title"
        onClick={(e) => e.stopPropagation()}
        className="max-h-[94vh] w-full max-w-5xl overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-5"
      >
        <div className="mb-1 flex items-center gap-3">
          <h2 id="dup-title" className="text-lg font-semibold text-[var(--text-primary)]">Is this a duplicate?</h2>
          {pairs.length > 1 && (
            <span className="text-sm text-[var(--text-secondary)]">{index + 1} of {pairs.length}</span>
          )}
          <button onClick={onClose} className="ml-auto rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <p className="mb-4 text-sm text-[var(--text-secondary)]">
          {REASONS[pair.reason]} Fields that differ are highlighted. To delete the other copy, click it so it gets a red
          border, then confirm below.
        </p>

        <div key={`${pair.original.id}-${pair.duplicate.id}`} className="grid gap-4 md:grid-cols-2">
          <Copy
            doc={pair.original} other={pair.duplicate} file={pair.original_file} label="Filed first"
            selected={selected === "original"} onSelect={() => setSelected(selected === "original" ? null : "original")}
          />
          <Copy
            doc={pair.duplicate} other={pair.original} file={pair.duplicate_file} label="Filed later"
            selected={selected === "duplicate"} onSelect={() => setSelected(selected === "duplicate" ? null : "duplicate")}
          />
        </div>

        {error && <p className="mt-4 text-sm text-[var(--alert-error-text)]">{error}</p>}

        <div className="mt-5 flex flex-wrap items-center gap-2">
          {pairs.length > 1 && <button className={BTN} disabled={busy} onClick={next}>Next pair</button>}
          <input
            aria-label="Why keep both (optional)"
            className="ml-auto w-56 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2.5 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
            maxLength={500}
            placeholder="Why keep both? (optional)"
            value={keepReason}
            onChange={(e) => setKeepReason(e.target.value)}
          />
          <button className={BTN} disabled={busy} onClick={keepBoth}>Not a duplicate, keep both</button>
          <button
            className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-40"
            disabled={busy || !selected}
            onClick={deleteSelected}
          >
            <Trash size={16} />
            {selected ? `Delete the ${selected === "original" ? "first" : "later"} copy` : "Select a copy to delete"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
