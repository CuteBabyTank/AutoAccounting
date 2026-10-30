"use client";

import { useEffect, useMemo, useState } from "react";
import { FilePdf, FileXls, MagnifyingGlass } from "@phosphor-icons/react";
import Hint from "@/components/guide/Hint";
import ContactPanel from "@/components/accounting/ContactPanel";
import ContactForm from "@/components/accounting/ContactForm";
import WriteOffPanel from "@/components/accounting/WriteOffPanel";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, formatPeso } from "@/lib/accounting-format";
import { useFilePreview } from "@/components/accounting/PdfPreview";
import { useWorkbookPreview } from "@/components/accounting/WorkbookPreview";
import type { Aging, AgingBucket, ContactList } from "@/types/accounting";
import { confirmDialog } from "@/components/ui/Dialogs";

interface Props {
  companyId: string;
  companyName: string;
  role: "customer" | "supplier";
  canManage: boolean;
  onOpenDocument: (id: string) => void;
  /** Open this contact's page first (a search result or deep link). */
  initialContactId?: string | null;
}

const BTN = "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";
const INPUT = "rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const CHIP = "rounded-full px-2 py-0.5 text-[11px] font-medium";
export const BUCKETS: { key: AgingBucket; label: string }[] = [
  { key: "current", label: "Current" },
  { key: "1-30", label: "1–30" },
  { key: "31-60", label: "31–60" },
  { key: "61-90", label: "61–90" },
  { key: "90+", label: "90+" },
];

export function todayIso(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

/** Company → Customers / Suppliers: who owes the company (A/R) or whom it owes (A/P), aged, with 2307s pending. */
export default function ContactsPanel({ companyId, companyName, role, canManage, onOpenDocument, initialContactId }: Props) {
  const [asOf, setAsOf] = useState(todayIso);
  const [list, setList] = useState<ContactList | null>(null);
  const [aging, setAging] = useState<Aging | null>(null);
  const [search, setSearch] = useState("");
  const [openOnly, setOpenOnly] = useState(true);
  const [contactId, setContactId] = useState<string | null>(initialContactId ?? null);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState("");
  const [writingOff, setWritingOff] = useState(false);
  const [adding, setAdding] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [busy, setBusy] = useState(false);
  const kind = role === "customer" ? "ar" : "ap";

  useEffect(() => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(asOf)) return;
    let cancelled = false;
    setError("");
    Promise.all([accountingApi.contacts(companyId, role, asOf), accountingApi.aging(companyId, kind, asOf)])
      .then(([l, a]) => {
        if (cancelled) return;
        setList(l);
        setAging(a);
      })
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the list")));
    return () => {
      cancelled = true;
    };
  }, [companyId, role, kind, asOf, refresh]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const digits = q.replace(/\D/g, "");
    return (list?.contacts ?? []).filter(
      (c) =>
        (!c.archived_at || showArchived || Number(c.open_balance) !== 0 || Number(c.cwt_pending) > 0) &&
        (!openOnly || Number(c.open_balance) !== 0 || Number(c.cwt_pending) > 0) &&
        (!q ||
          c.registered_name.toLowerCase().includes(q) ||
          c.aliases.some((a) => a.toLowerCase().includes(q)) ||
          (digits.length > 0 && c.tin.includes(digits))),
    );
  }, [list, search, openOnly, showArchived]);
  const agingById = useMemo(() => new Map((aging?.rows ?? []).map((r) => [r.contact_id, r])), [aging]);
  const file = useFilePreview();
  const sheet = useWorkbookPreview();

  if (contactId) {
    return (
      <ContactPanel
        key={contactId}
        companyId={companyId}
        contactId={contactId}
        asOf={asOf}
        canManage={canManage}
        onBack={() => {
          setContactId(null);
          setRefresh((n) => n + 1);
        }}
        onOpenContact={setContactId}
        onOpenDocument={onOpenDocument}
      />
    );
  }

  const title = role === "customer" ? "Customers" : "Suppliers";
  return (
    <div className="mb-6">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">
          {title} · {companyName}{" "}
          <Hint align="right">
            {role === "customer"
              ? "Everyone this company invoiced, with what they still owe as of the date you pick. A balance is net of the tax the customer withheld; that tax shows as a 2307 still to receive until the certificate comes in."
              : "Everyone who billed this company, with what it still owes as of the date you pick, net of the tax it withholds. Unverified means a bill on credit with no receipt or bank line paying it yet."}
          </Hint>
        </h2>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {canManage && <button className={BTN} onClick={() => setAdding(true)}>Add contact</button>}
          <label className="text-xs text-[var(--text-secondary)]" htmlFor="contacts-as-of">As of</label>
          <input id="contacts-as-of" type="date" className={INPUT} value={asOf} onChange={(e) => setAsOf(e.target.value)} />
          <button className={BTN} onClick={() =>
            sheet.open(`${title} aging · ${asOf}`, () => accountingApi.agingPreview(companyId, kind, asOf),
              () => accountingApi.agingFile(companyId, kind, asOf, "xlsx"), `${companyName} ${kind === "ar" ? "AR" : "AP"} aging ${asOf}.xlsx`)}>
            <FileXls size={16} /> Aging XLSX
          </button>
          <button className={BTN} onClick={() =>
            file.open(`${title} aging · ${asOf}`, () => accountingApi.agingFile(companyId, kind, asOf, "pdf"),
              `${companyName} ${kind === "ar" ? "AR" : "AP"} aging ${asOf}.pdf`)}>
            <FilePdf size={16} /> Aging PDF
          </button>
          {file.node}
          {sheet.node}
          {role === "customer" && canManage && !writingOff && (
            <button className={BTN} onClick={() => setWritingOff(true)}>Write off…</button>
          )}
        </div>
      </div>
      <p className="mb-3 text-xs text-[var(--text-secondary)]">
        Built from the documents: one entry per TIN, other spellings of the name kept as aliases. Payments come from linked
        receipts, paid-on dates and matched bank lines.
      </p>
      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {adding && <ContactForm companyId={companyId} role={role} onClose={() => setAdding(false)} onSaved={(id) => { setAdding(false); setOpenOnly(false); setContactId(id); setRefresh((n) => n + 1); }} />}
      {writingOff && (
        <WriteOffPanel
          companyId={companyId}
          asOf={asOf}
          onClose={() => setWritingOff(false)}
          onDone={() => {
            setWritingOff(false);
            setRefresh((n) => n + 1);
          }}
        />
      )}
      {!list || !aging ? (
        !error && <p className="text-sm text-[var(--text-secondary)]">Loading…</p>
      ) : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Tile label={role === "customer" ? "Receivable" : "Payable"} value={formatPeso(list.total_open)} />
            <Tile label="Overdue" value={formatPeso(list.total_overdue)} />
            {role === "customer" ? (
              <Tile label="2307s to receive" value={formatPeso(list.total_cwt_pending)} />
            ) : (
              <Tile label="Unverified bills" value={String(list.contacts.reduce((n, c) => n + c.unverified, 0))} />
            )}
            <Tile label="Over 90 days" value={formatPeso(aging.totals["90+"])} />
          </div>
          <div className="mb-2 flex flex-wrap items-center gap-3">
            <div className="relative">
              <MagnifyingGlass size={14} className="absolute left-2 top-2.5 text-[var(--text-secondary)]" />
              <input
                className={`${INPUT} pl-7`}
                placeholder="Name or TIN"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label={`Search ${title.toLowerCase()}`}
              />
            </div>
            <label className="flex items-center gap-1.5 text-sm text-[var(--text-primary)]">
              <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
              With a balance only
            </label>
            <label className="flex items-center gap-1.5 text-sm text-[var(--text-primary)]"><input type="checkbox" checked={showArchived} onChange={(e) => { setShowArchived(e.target.checked); if (e.target.checked) setOpenOnly(false); }} />Show archived contacts</label>
          </div>
          {rows.length === 0 ? (
            <p className="py-6 text-center text-sm text-[var(--text-secondary)]">
              {list.contacts.length === 0 ? `No ${title.toLowerCase()} yet. Add a contact or upload its documents.` : "Nothing matches. Turn off With a balance only to manage contacts without a balance."}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-[var(--text-secondary)]">
                    <th className="py-1.5 pr-3 font-medium">Name</th>
                    {BUCKETS.map((b) => (
                      <th key={b.key} className="py-1.5 pr-3 text-right font-medium">{b.label}</th>
                    ))}
                    <th className="py-1.5 pr-3 text-right font-medium">Open</th>
                    <th className="py-1.5 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c) => {
                    const a = agingById.get(c.id);
                    return (
                      <tr
                        key={c.id}
                        onClick={() => setContactId(c.id)}
                        className="cursor-pointer border-t border-[var(--border)] text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
                      >
                        <td className="py-1.5 pr-3">
                          <span className="font-medium">{c.registered_name}</span>
                          {c.archived_at && <span className="ml-2 text-xs text-[var(--text-secondary)]">Archived</span>}
                          {c.tin && <span className="ml-2 text-xs text-[var(--text-secondary)]">{c.tin}</span>}
                          {c.role === "both" && <span className="ml-2 text-xs text-[var(--text-secondary)]">customer and supplier</span>}
                          {(c.default_account || c.payment_terms_days != null) && (
                            <span className="block text-[11px] text-[var(--text-secondary)]" title="Supplier defaults: used for this supplier's new documents and due dates (edit on the contact page)">
                              {[c.default_account && `Default account ${c.default_account}`, c.payment_terms_days != null && (c.payment_terms_days ? `${c.payment_terms_days}-day terms` : "Due on receipt")].filter(Boolean).join(" · ")}
                            </span>
                          )}
                        </td>
                        {BUCKETS.map((b) => (
                          <td key={b.key} className="py-1.5 pr-3 text-right tabular-nums">
                            {a && Number(a.buckets[b.key]) !== 0 ? formatPeso(a.buckets[b.key]) : ""}
                          </td>
                        ))}
                        <td className="py-1.5 pr-3 text-right font-semibold tabular-nums">{formatPeso(c.open_balance)}</td>
                        <td className="py-1.5 whitespace-nowrap">
                          {canManage && <button className={BTN} disabled={busy} onClick={async (e) => {
                            e.stopPropagation();
                            if (!c.archived_at && !(await confirmDialog({
                              title: `Archive ${c.registered_name}?`,
                              message: "Its identity and tax records are retained. Open balances or pending 2307s must be settled first.",
                              confirmLabel: "Archive",
                              danger: true,
                            }))) return;
                            setBusy(true); setError("");
                            try {
                              if (c.archived_at) await accountingApi.restoreContact(c.id);
                              else await accountingApi.archiveContact(c.id);
                              setRefresh((n) => n + 1);
                            } catch (e) { setError(apiErrorMessage(e, "Couldn't change the contact's archive status")); }
                            finally { setBusy(false); }
                          }}>{c.archived_at ? "Restore" : "Archive"}</button>}
                          {Number(c.overdue) > 0 && (
                            <span className={`${CHIP} bg-[var(--badge-yellow-bg)] text-[var(--badge-yellow-text)]`}>Overdue</span>
                          )}
                          {Number(c.cwt_pending) > 0 && (
                            <span className={`${CHIP} ml-1 bg-[var(--badge-blue-bg)] text-[var(--badge-blue-text)]`}>
                              2307 {formatPeso(c.cwt_pending)}
                            </span>
                          )}
                          {c.unverified > 0 && (
                            <span className={`${CHIP} ml-1 bg-[var(--bg-hover)] text-[var(--text-secondary)]`}>{c.unverified} unverified</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {(aging.tie?.length ?? 0) > 0 && (
            <details className="mt-3 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2" open={aging.tie!.length > 2}>
              <summary className="cursor-pointer text-sm font-medium text-[var(--text-primary)]">
                Tie to the books{aging.tie!.length > 2 ? " · differences explained" : " · agrees"}
              </summary>
              <table className="mt-2 w-full text-sm">
                <tbody>
                  {aging.tie!.map((t) => (
                    <tr key={t.key} className={t.key === "books" ? "border-t border-[var(--border)]" : ""}>
                      <td className={`py-1 pr-3 ${t.key === "aging" || t.key === "books" ? "font-medium text-[var(--text-primary)]" : "pl-3 text-[var(--text-secondary)]"}`}>
                        {t.key !== "aging" && t.key !== "books" && "+ "}{t.label}
                      </td>
                      <td className="py-1 text-right tabular-nums text-[var(--text-primary)]">{formatPeso(t.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-1 text-xs text-[var(--text-secondary)]">
                The aging nets the customer&apos;s CWT and treats documents paid at the counter as paid; the books keep both in the control account until the 2307 or a payment is recorded.
              </p>
            </details>
          )}
          {aging.tie_note && <p className="mt-2 text-xs text-[var(--text-secondary)]">{aging.tie_note}</p>}
        </>
      )}
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2">
      <p className="text-xs text-[var(--text-secondary)]">{label}</p>
      <p className="text-base font-semibold tabular-nums text-[var(--text-primary)]">{value}</p>
    </div>
  );
}
