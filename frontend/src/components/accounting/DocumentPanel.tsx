"use client";

import { useEffect, useState } from "react";
import { X } from "@phosphor-icons/react";
import AssetSection from "@/components/accounting/AssetSection";
import DuplicateCompare from "@/components/accounting/DuplicateCompare";
import { accountingApi } from "@/lib/accounting-api";
import { ACCOUNTS, ACCOUNT_LABELS, CATEGORY_LABELS, EWT_ATC_OPTIONS, REASON_LABELS, apiErrorMessage, formatPeso } from "@/lib/accounting-format";
import type { AADocument, Account, DocumentPatch, DuplicatePair, PaymentLinks } from "@/types/accounting";

const AMOUNTS = [
  ["gross_amount", "Total"],
  ["vatable_amount", "VATable"],
  ["vat_amount", "VAT"],
  ["exempt_amount", "VAT-exempt"],
  ["zero_rated_amount", "Zero-rated"],
  ["withholding_amount", "Tax withheld"],
] as const;
const AMOUNT_KEYS = new Set<string>(AMOUNTS.map(([k]) => k));
const CATEGORIES = ["sales", "purchases", "expenses", "payroll", "2307", "support", "unsorted"] as const;
const INPUT = "w-full px-2.5 py-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const LABEL = "block text-[11px] font-medium text-[var(--text-secondary)] mb-1";
const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";

type Draft = Record<string, string>;

function toDraft(doc: AADocument): Draft {
  return {
    doc_date: doc.doc_date ?? "",
    doc_number: doc.doc_number,
    category: doc.category,
    account: doc.account,
    seller_name: doc.seller_name,
    seller_tin: doc.seller_tin,
    buyer_name: doc.buyer_name,
    buyer_tin: doc.buyer_tin,
    gross_amount: doc.gross_amount,
    vatable_amount: doc.vatable_amount,
    vat_amount: doc.vat_amount,
    exempt_amount: doc.exempt_amount,
    zero_rated_amount: doc.zero_rated_amount,
    withholding_amount: doc.withholding_amount,
    ewt_atc: doc.ewt_atc,
    paid_on: doc.paid_on ?? "",
    paid_via: doc.paid_via,
    payment_ref: doc.payment_ref,
    gl_account_code: doc.gl_account_code,
  };
}

const ATC_SOURCE: Record<string, string> = {
  supplier: " (this supplier's ATC in the databank)",
  account: " (the databank default for this expense type)",
};

interface Props {
  doc: AADocument;
  onClose: () => void;
  onChanged: (doc: AADocument) => void;
  onDeleted: (id: string) => void;
}

/** The account a document account posts to (as the books do) and its active sub-accounts, plus the current pick. */
function bookableAccounts(accounts: Account[], docAccount: string, current: string): Account[] {
  const key = (k: string) => accounts.find((a) => a.system_key === k)?.code;
  const mapped = docAccount === "capital_goods" ? key("ppe") : (key(`doc:${docAccount}`) ?? key("doc:other"));
  return accounts.filter(
    (a) => (a.active && mapped !== undefined && (a.code === mapped || a.parent_code === mapped)) || (current !== "" && a.code === current),
  );
}

export default function DocumentPanel({ doc, onClose, onChanged, onDeleted }: Props) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(doc));
  const [images, setImages] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => setNotice(""), [doc.id]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [moveYear, setMoveYear] = useState(String(doc.period_year ?? new Date().getFullYear()));
  const [moveQuarter, setMoveQuarter] = useState(String(doc.period_quarter ?? 1));

  const [accounts, setAccounts] = useState<Account[]>([]);
  const [links, setLinks] = useState<PaymentLinks | null>(null);
  const [dupPairs, setDupPairs] = useState<DuplicatePair[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setAccounts([]);
    accountingApi
      .accounts(doc.company_id)
      .then((a) => {
        if (!cancelled) setAccounts(a);
      })
      .catch(() => {
        if (!cancelled) setAccounts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [doc.company_id]);

  useEffect(() => {
    let cancelled = false;
    setLinks(null);
    accountingApi
      .documentPayments(doc.id)
      .then((l) => {
        if (!cancelled) setLinks(l);
      })
      .catch(() => {
        if (!cancelled) setLinks(null);
      });
    return () => {
      cancelled = true;
    };
  }, [doc.id, doc.settles_document_id, doc.gross_amount, doc.doc_date]);

  useEffect(() => {
    setDraft(toDraft(doc));
    setConfirmDelete(false);
  }, [doc]);

  useEffect(() => {
    let cancelled = false;
    const urls: string[] = [];
    setImages([]);
    const last = Math.min(doc.page_end, doc.page_start + 4);
    (async () => {
      for (let p = doc.page_start; p <= last; p++) {
        try {
          const blob = await accountingApi.pageImage(doc.file_id, p);
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          urls.push(url);
          setImages((prev) => [...prev, url]);
        } catch {
          // Page previews are best-effort; the fields still load.
        }
      }
    })();
    return () => {
      cancelled = true;
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [doc.file_id, doc.page_start, doc.page_end]);

  async function save(extra: DocumentPatch = {}, { onlyExtra = false }: { onlyExtra?: boolean } = {}) {
    const initial = toDraft(doc);
    const patch: DocumentPatch = { ...extra };
    for (const [key, value] of onlyExtra ? [] : Object.entries(draft)) {
      if (value === initial[key]) continue;
      if (key === "doc_date" || key === "paid_on") patch[key] = value || null;
      else if (AMOUNT_KEYS.has(key)) patch[key] = value.trim() || "0";
      else patch[key] = value;
    }
    if (Object.keys(patch).length === 0) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await accountingApi.updateDocument(doc.id, patch);
      const others = updated.rule_applied_to ?? 0;
      if (others > 0) {
        setNotice(`Also moved ${others} other unreviewed document${others === 1 ? "" : "s"} from this supplier to the same folder and account.`);
      }
      onChanged(updated);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save the document"));
    } finally {
      setBusy(false);
    }
  }

  async function adoptSuggestedAtc() {
    setBusy(true);
    setError("");
    try {
      await accountingApi.setSupplierAtc(doc.company_id, doc.seller_tin, doc.ewt_atc_suggestion, doc.seller_name);
      onChanged(await accountingApi.getDocument(doc.id));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save the supplier's ATC"));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setBusy(true);
    try {
      await accountingApi.deleteDocument(doc.id);
      onDeleted(doc.id);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't delete the document"));
      setBusy(false);
    }
  }

  const field = (key: string, label: string, type = "text") => (
    <div>
      <label className={LABEL}>{label}</label>
      <input
        type={type}
        className={INPUT}
        value={draft[key] ?? ""}
        onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
      />
    </div>
  );

  const openReasons = doc.needs_review && !doc.reviewed ? doc.review_reasons : [];

  async function compareDuplicates() {
    setError("");
    try {
      const pairs = (await accountingApi.duplicates(doc.company_id))
        .filter((p) => p.original.id === doc.id || p.duplicate.id === doc.id);
      if (pairs.length) setDupPairs(pairs);
      else setError("The other copy is gone, so this is no longer a duplicate. Mark it reviewed.");
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't load the possible duplicates"));
    }
  }

  function duplicateResolved(deletedId: string | null) {
    if (deletedId === doc.id) {
      onDeleted(doc.id);
      return;
    }
    accountingApi.getDocument(doc.id).then(onChanged).catch(() => undefined);
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose}>
      <aside
        onClick={(e) => e.stopPropagation()}
        className="h-full w-full max-w-xl overflow-y-auto border-l border-[var(--border)] bg-[var(--bg-secondary)] p-5"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-[var(--text-primary)]">
              {doc.document_title || CATEGORY_LABELS[doc.category]} {doc.doc_number && `#${doc.doc_number}`}
            </h2>
            <p className="text-xs text-[var(--text-secondary)]">
              {doc.period_year
                ? `Filed in ${doc.period_year} Q${doc.period_quarter}${doc.period_locked ? " (moved by hand)" : ""}`
                : "Undated"}
              {" · "}pages {doc.page_start}–{doc.page_end} · confidence {Math.round(doc.confidence)}%
            </p>
          </div>
          <button onClick={onClose} className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        {dupPairs && (
          <DuplicateCompare pairs={dupPairs} onClose={() => setDupPairs(null)} onResolved={duplicateResolved} />
        )}

        {openReasons.length > 0 && (
          <ul className="mb-4 space-y-1 rounded-lg border border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)] p-3 text-sm text-[var(--alert-warning-text)]">
            {openReasons.map((r) => (
              <li key={r}>
                • {REASON_LABELS[r] ?? r}
                {r === "possible_duplicate" && (
                  <button className="ml-2 font-semibold underline" disabled={busy} onClick={compareDuplicates}>
                    Compare side by side
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

        <div className="mb-4 space-y-2">
          {images.map((src, i) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={src} src={src} alt={`Page ${doc.page_start + i}`} className="w-full rounded-lg border border-[var(--border)]" />
          ))}
          {images.length === 0 && <div className="h-40 animate-pulse rounded-lg bg-[var(--bg-primary)]" />}
        </div>

        <div className="grid grid-cols-2 gap-3">
          {field("doc_date", "Document date", "date")}
          {field("doc_number", "Document no.")}
          <div>
            <label className={LABEL}>Folder</label>
            <select className={INPUT} value={draft.category} onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value }))}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={LABEL}>Account</label>
            <select className={INPUT} value={draft.account} onChange={(e) => setDraft((d) => ({ ...d, account: e.target.value }))}>
              {ACCOUNTS.map((a) => (
                <option key={a} value={a}>{ACCOUNT_LABELS[a]}</option>
              ))}
            </select>
          </div>
          {(draft.category === "purchases" || draft.category === "expenses") && (
            <div className="col-span-2">
              <label className={LABEL}>Expanded withholding (ATC)</label>
              <select className={INPUT} value={draft.ewt_atc} onChange={(e) => setDraft((d) => ({ ...d, ewt_atc: e.target.value }))}>
                {EWT_ATC_OPTIONS.map((o) => (
                  <option key={o.value || "auto"} value={o.value}>{o.label}</option>
                ))}
                {draft.ewt_atc && !EWT_ATC_OPTIONS.some((o) => o.value === draft.ewt_atc) && (
                  <option value={draft.ewt_atc}>{draft.ewt_atc}</option>
                )}
              </select>
              {draft.ewt_atc === doc.ewt_atc && !doc.ewt_atc && (
                <span className="mt-0.5 block text-[11px] text-[var(--text-primary)]">
                  {doc.ewt_atc_effective ? `Currently using ${doc.ewt_atc_effective}` : "Currently no withholding"}
                  {ATC_SOURCE[doc.ewt_atc_source] ?? ""}
                </span>
              )}
              {draft.ewt_atc === doc.ewt_atc && doc.ewt_atc_suggestion && (
                <span className="mt-0.5 flex items-center gap-2 text-[11px] text-[var(--text-primary)]">
                  {doc.ewt_atc_suggestion} is set for this supplier in {doc.ewt_atc_suggestion_company}.
                  <button className="font-semibold text-[var(--accent)]" disabled={busy} onClick={adoptSuggestedAtc}>
                    Use it here
                  </button>
                </span>
              )}
              <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">
                Saved to this company&apos;s ATC databank for the supplier, so their other documents use it too.
              </span>
            </div>
          )}
          {field("seller_name", "Seller")}
          {field("seller_tin", "Seller TIN")}
          {field("buyer_name", "Buyer")}
          {field("buyer_tin", "Buyer TIN")}
          {AMOUNTS.map(([key, label]) => (
            <div key={key}>{field(key, label)}</div>
          ))}
        </div>

        {["sales", "purchases", "expenses", "payroll"].includes(draft.category) && !doc.settles_document_id && (
          <div className="mt-4 rounded-lg border border-[var(--border)] p-3">
            <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">Payment (books)</p>
            {links && links.paid_by.length > 0 ? (
              <ul className="space-y-1 text-sm text-[var(--text-primary)]">
                {links.paid_by.map((r) => (
                  <li key={r.id}>Paid by receipt {r.doc_number || "(no number)"} · {r.doc_date ?? "undated"} · {formatPeso(r.gross_amount)}</li>
                ))}
              </ul>
            ) : (
              <div className="grid grid-cols-3 gap-3">
                {field("paid_on", "Paid on", "date")}
                <div>
                  <label className={LABEL}>Paid via</label>
                  <select className={INPUT} value={draft.paid_via} onChange={(e) => setDraft((d) => ({ ...d, paid_via: e.target.value }))}>
                    <option value="">—</option>
                    <option value="cash">Cash</option>
                    <option value="bank">Bank / check</option>
                    <option value="ewallet">E-wallet</option>
                  </select>
                </div>
                {field("payment_ref", "Check / ref no.")}
              </div>
            )}
            {(draft.category === "purchases" || draft.category === "expenses") && accounts.length > 0 && (
              <div className="mt-3">
                <label className={LABEL}>Book to account</label>
                <select className={INPUT} value={draft.gl_account_code} onChange={(e) => setDraft((d) => ({ ...d, gl_account_code: e.target.value }))}>
                  <option value="">Default for “{ACCOUNT_LABELS[draft.account] ?? draft.account}”</option>
                  {bookableAccounts(accounts, draft.account, draft.gl_account_code).map((a) => (
                    <option key={a.id} value={a.code}>{a.code} {a.name}</option>
                  ))}
                </select>
                <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">Remembered for this supplier.</span>
              </div>
            )}
          </div>
        )}

        {links && (doc.settles_document_id || links.candidates.length > 0 || doc.doc_type === "receipt") && (
          <div className="mt-4 rounded-lg border border-[var(--border)] p-3">
            <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">This receipt pays</p>
            <select
              className={INPUT}
              disabled={busy}
              value={doc.settles_document_id ?? ""}
              onChange={(e) => save({ settles_document_id: e.target.value || null }, { onlyExtra: true })}
            >
              <option value="">Nothing: it is a sale or expense of its own</option>
              {[...(links.linked_invoice ? [links.linked_invoice] : []), ...links.candidates.filter((c) => c.id !== links.linked_invoice?.id)].map((c) => (
                <option key={c.id} value={c.id}>
                  {c.doc_number || "(no number)"} · {c.doc_date ?? "undated"} · {c.counterparty} · {formatPeso(c.gross_amount)}
                </option>
              ))}
            </select>
            <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">
              {doc.settles_source === "auto" ? "Linked automatically. " : ""}A linked receipt only records the payment; the invoice is the sale or expense.
            </span>
          </div>
        )}

        {doc.account === "capital_goods" && doc.client_role === "buyer" && (
          <AssetSection doc={doc} onChanged={() => onChanged(doc)} />
        )}

        <div className="mt-4 rounded-lg border border-[var(--border)] p-3">
          <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">Move to another quarter</p>
          <div className="flex flex-wrap items-center gap-2">
            <input type="number" min={2000} max={2100} className={`${INPUT} w-24`} value={moveYear} onChange={(e) => setMoveYear(e.target.value)} />
            <select className={`${INPUT} w-20`} value={moveQuarter} onChange={(e) => setMoveQuarter(e.target.value)}>
              {[1, 2, 3, 4].map((q) => (
                <option key={q} value={q}>Q{q}</option>
              ))}
            </select>
            <button className={BTN} disabled={busy} onClick={() => save({ period_year: Number(moveYear), period_quarter: Number(moveQuarter) })}>
              Move
            </button>
            {doc.period_locked && (
              <button className={BTN} disabled={busy} onClick={() => save({ period_year: null, period_quarter: null })}>
                Use document date
              </button>
            )}
          </div>
        </div>

        {error && <p className="mt-3 text-sm text-[var(--alert-error-text)]">{error}</p>}
        {notice && <p className="mt-3 text-sm text-[var(--text-secondary)]">{notice}</p>}

        <div className="mt-5 flex flex-wrap gap-2">
          <button
            className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60"
            disabled={busy}
            onClick={() => save()}
          >
            Save
          </button>
          {doc.needs_review && !doc.reviewed && (
            <button className={BTN} disabled={busy} onClick={() => save({ reviewed: true })}>
              Mark reviewed
            </button>
          )}
          <button className={BTN} disabled={busy} onClick={() => save({ excluded: !doc.excluded })}>
            {doc.excluded ? "Include again" : "Exclude from computation"}
          </button>
          <button
            className="ml-auto rounded-lg border border-[var(--alert-error-border)] px-3 py-1.5 text-sm font-medium text-[var(--alert-error-text)] hover:bg-[var(--alert-error-bg)] disabled:opacity-60"
            disabled={busy}
            onClick={remove}
          >
            {confirmDelete ? "Click again to delete" : "Delete"}
          </button>
        </div>
      </aside>
    </div>
  );
}
