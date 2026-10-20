"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowRight, X } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/accounting-api";
import { CATEGORY_LABELS, apiErrorMessage } from "@/lib/accounting-format";
import type { AADocument, Company, DocumentPatch } from "@/types/accounting";

const FOLDERS = ["sales", "purchases", "expenses", "payroll", "2307", "support", "unsorted"] as const;
const AUTO = "auto";
const INPUT = "w-full px-2.5 py-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const LABEL = "block text-[11px] font-medium text-[var(--text-secondary)] mb-1";

interface Props {
  doc: AADocument;
  onClose: () => void;
  /** The document after the move, and a one-line summary of where it went. */
  onMoved: (doc: AADocument, summary: string) => void;
}

/** Where a document goes: company, folder and quarter in one place. Another company re-sorts it for that company
 *  (its side of the invoice can flip), so the folder defaults to "Sort automatically" there. */
export default function MoveDocumentDialog({ doc, onClose, onMoved }: Props) {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [companyId, setCompanyId] = useState(doc.company_id);
  const otherCompany = companyId !== doc.company_id;
  const [folder, setFolder] = useState<string>(doc.category);
  const [byDate, setByDate] = useState(!doc.period_locked);
  const [year, setYear] = useState(String(doc.period_year ?? new Date().getFullYear()));
  const [quarter, setQuarter] = useState(String(doc.period_quarter ?? 1));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    accountingApi
      .listCompanies()
      .then(setCompanies)
      .catch((e) => setError(apiErrorMessage(e, "Couldn't load the companies")));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const pickCompany = (id: string) => {
    setCompanyId(id);
    setFolder(id === doc.company_id ? doc.category : AUTO);
    setByDate(id === doc.company_id ? !doc.period_locked : true);
    setError("");
  };

  const yearNum = Number(year);
  const yearOk = Number.isInteger(yearNum) && yearNum >= 2000 && yearNum <= 2100;
  /** The folder / quarter changes, as a document update (applied after the company move, if any). */
  const patch = useMemo<DocumentPatch>(() => {
    const p: DocumentPatch = {};
    if (folder !== AUTO && folder !== doc.category) p.category = folder;
    if (byDate) {
      if (doc.period_locked && !otherCompany) Object.assign(p, { period_year: null, period_quarter: null });
    } else if (otherCompany || !doc.period_locked || yearNum !== doc.period_year || Number(quarter) !== doc.period_quarter) {
      Object.assign(p, { period_year: yearNum, period_quarter: Number(quarter) });
    }
    return p;
  }, [folder, byDate, otherCompany, yearNum, quarter, doc]);
  const changes = otherCompany || Object.keys(patch).length > 0;

  const companyName = (id: string) => companies?.find((c) => c.id === id)?.registered_name ?? "";
  const docName = `${doc.document_title || CATEGORY_LABELS[doc.category]}${doc.doc_number ? ` #${doc.doc_number}` : ""}`;

  async function move() {
    if (!changes || busy || (!byDate && !yearOk)) return;
    setBusy(true);
    setError("");
    let moved: AADocument | null = null;
    try {
      moved = otherCompany ? await accountingApi.moveDocumentToCompany(doc.id, companyId) : doc;
      // A company move re-sorts the folder against the new company's view, so compare with the moved document.
      const after: DocumentPatch = { ...patch };
      if (otherCompany && after.category === moved.category) delete after.category;
      if (Object.keys(after).length > 0) moved = await accountingApi.updateDocument(moved.id, after);
      const where = [
        otherCompany ? companyName(companyId) : "",
        moved.period_year != null ? `${moved.period_year} · Q${moved.period_quarter}` : "No quarter yet",
        CATEGORY_LABELS[moved.category],
      ].filter(Boolean);
      onMoved(moved, `Moved to ${where.join(" / ")}.`);
      onClose();
    } catch (e) {
      // The company move can land while the folder / quarter step after it fails: say so, keep what moved.
      if (moved && moved !== doc && moved.company_id !== doc.company_id) {
        onMoved(moved, `Moved to ${companyName(companyId)}, but the folder or quarter wasn't changed: ${apiErrorMessage(e, "try again")}`);
        onClose();
      } else {
        setError(apiErrorMessage(e, "Couldn't move the document"));
      }
    } finally {
      setBusy(false);
    }
  }

  return createPortal(
    <div
      className="lp-skin overlay-enter fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => e.target === e.currentTarget && !busy && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="move-doc-title"
        className="modal-enter w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-6 shadow-xl"
      >
        <div className="mb-1 flex items-center justify-between">
          <h3 id="move-doc-title" className="text-lg font-semibold text-[var(--text-primary)]">Move document</h3>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
            className="-mr-1.5 rounded-lg p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-primary)]"
          >
            <X size={18} />
          </button>
        </div>
        <p className="mb-4 truncate text-sm text-[var(--text-secondary)]">{docName}</p>

        <div className="space-y-3">
          <div>
            <label className={LABEL} htmlFor="move-company">Company</label>
            <select
              id="move-company"
              className={INPUT}
              value={companyId}
              disabled={busy || companies === null}
              onChange={(e) => pickCompany(e.target.value)}
            >
              {companies === null && <option value={doc.company_id}>Loading…</option>}
              {companies?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.registered_name}{c.id === doc.company_id ? " (current)" : ""}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className={LABEL} htmlFor="move-folder">Folder</label>
            <select id="move-folder" className={INPUT} value={folder} disabled={busy} onChange={(e) => setFolder(e.target.value)}>
              {otherCompany && <option value={AUTO}>Sort automatically for this company</option>}
              {FOLDERS.map((f) => (
                <option key={f} value={f}>
                  {CATEGORY_LABELS[f]}{!otherCompany && f === doc.category ? " (current)" : ""}
                </option>
              ))}
            </select>
            {otherCompany && folder === AUTO && (
              <p className="mt-1 text-[11px] text-[var(--text-secondary)]">
                Picks the side and folder from this company&apos;s view: a sale here can be a purchase there.
              </p>
            )}
          </div>

          <div>
            <span className={LABEL}>Quarter</span>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-[var(--text-primary)]">
              <label className="inline-flex items-center gap-1.5">
                <input type="radio" name="move-period" checked={byDate} disabled={busy} onChange={() => setByDate(true)} />
                From the document date{doc.doc_date ? ` (${doc.doc_date})` : ""}
              </label>
              <label className="inline-flex items-center gap-1.5">
                <input type="radio" name="move-period" checked={!byDate} disabled={busy} onChange={() => setByDate(false)} />
                Choose a quarter
              </label>
            </div>
            {!byDate && (
              <div className="mt-2 flex items-center gap-2">
                <input
                  type="number"
                  min={2000}
                  max={2100}
                  aria-label="Fiscal year"
                  className={`${INPUT} w-24`}
                  value={year}
                  disabled={busy}
                  onChange={(e) => setYear(e.target.value)}
                />
                <select aria-label="Quarter" className={`${INPUT} w-20`} value={quarter} disabled={busy} onChange={(e) => setQuarter(e.target.value)}>
                  {[1, 2, 3, 4].map((q) => (
                    <option key={q} value={q}>Q{q}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>

        {error && <p role="alert" className="mt-4 text-sm text-[var(--alert-error-text)]">{error}</p>}

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-primary)]"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={move}
            disabled={busy || !changes || (!byDate && !yearOk)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60"
          >
            {busy ? "Moving…" : "Move"}
            {!busy && <ArrowRight size={14} weight="bold" />}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
