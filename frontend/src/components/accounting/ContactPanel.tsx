"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, FilePdf, FileZip } from "@phosphor-icons/react";
import Hint from "@/components/guide/Hint";
import { accountingApi } from "@/lib/accounting-api";
import { EWT_ATC_OPTIONS, apiErrorMessage, formatPeso, saveBlob } from "@/lib/accounting-format";
import type { Account, ContactDetail, ContactPatch, ContactRow } from "@/types/accounting";

interface Props {
  companyId: string;
  contactId: string;
  asOf: string;
  canManage: boolean;
  onBack: () => void;
  onOpenContact: (id: string) => void;
  onOpenDocument: (id: string) => void;
}

const BTN = "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50";
const PRIMARY = "rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60";
const INPUT = "w-full rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] disabled:opacity-60";
const LABEL = "mb-1 block text-xs text-[var(--text-secondary)]";
const CHIP = "rounded-full px-2 py-0.5 text-[11px] font-medium";
const H3 = "mb-2 mt-5 text-sm font-semibold text-[var(--text-primary)]";
const TH = "py-1.5 pr-3 font-medium";
const TD = "py-1.5 pr-3";
const NUM = "py-1.5 pr-3 text-right tabular-nums";

const day = (iso: string | null) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" }) : "No date";
const KIND: Record<string, string> = { ar: "Sale", ap: "Bill", "2307": "2307 received", receipt: "Receipt", other: "Other" };
const SOURCE: Record<string, string> = { receipt: "Receipt", paid_on: "Marked paid", bank: "Bank line" };

/** One customer or supplier: details, open items, 2307s to receive / issue, payments and documents. */
export default function ContactPanel({ companyId, contactId, asOf, canManage, onBack, onOpenContact, onOpenDocument }: Props) {
  const [data, setData] = useState<ContactDetail | null>(null);
  const [form, setForm] = useState<ContactPatch>({});
  const [reason, setReason] = useState("");
  const [chart, setChart] = useState<Account[]>([]);
  const [others, setOthers] = useState<ContactRow[]>([]);
  const [mergeInto, setMergeInto] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([accountingApi.contact(contactId, asOf), accountingApi.accounts(companyId)])
      .then(([c, accounts]) => {
        if (cancelled) return;
        setData(c);
        setChart(accounts.filter((a) => a.active && !a.locked));
      })
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load this contact")));
    Promise.all([accountingApi.contacts(companyId, "customer", asOf), accountingApi.contacts(companyId, "supplier", asOf)])
      .then(([c, s]) => {
        if (cancelled) return;
        const seen = new Map<string, ContactRow>();
        [...c.contacts, ...s.contacts].forEach((r) => r.id !== contactId && seen.set(r.id, r));
        setOthers([...seen.values()].sort((a, b) => a.registered_name.localeCompare(b.registered_name)));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [companyId, contactId, asOf]);

  async function run(label: string, call: () => Promise<ContactDetail | void>, done = "") {
    setBusy(label);
    setError("");
    setSaved("");
    try {
      const next = await call();
      if (next) setData(next);
      else setData(await accountingApi.contact(contactId, asOf));
      if (done) setSaved(done);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save"));
    } finally {
      setBusy("");
    }
  }

  if (!data) {
    return (
      <div className="mb-6">
        <button className={BTN} onClick={onBack}><ArrowLeft size={14} /> Back</button>
        {error ? <p className="mt-3 text-sm text-[var(--alert-error-text)]">{error}</p> : <p className="mt-3 text-sm text-[var(--text-secondary)]">Loading…</p>}
      </div>
    );
  }

  const value = <K extends keyof ContactPatch>(k: K, fallback: ContactPatch[K]) => (k in form ? form[k] : fallback);
  const set = (patch: ContactPatch) => setForm((f) => ({ ...f, ...patch }));
  const dirty = Object.keys(form).length > 0;
  const isCustomer = data.role !== "supplier";
  const isSupplier = data.role !== "customer";

  return (
    <div className="mb-6">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <button className={BTN} onClick={onBack}><ArrowLeft size={14} /> Back</button>
        <h2 className="text-base font-semibold text-[var(--text-primary)]">
          {data.registered_name}{" "}
          <Hint align="right">
            Everything with this {isCustomer && isSupplier ? "customer and supplier" : isCustomer ? "customer" : "supplier"}: what is
            still open as of {day(data.as_of)}, the 2307s to receive or issue, payments seen and the documents they came from.
          </Hint>
        </h2>
        {data.tin && <span className="text-xs text-[var(--text-secondary)]">TIN {data.tin}</span>}
        {data.merged_into_id && (
          <button className={`${CHIP} bg-[var(--badge-yellow-bg)] text-[var(--badge-yellow-text)]`} onClick={() => onOpenContact(data.merged_into_id!)}>
            Merged into another contact: open it
          </button>
        )}
        <div className="ml-auto flex gap-2">
          {isCustomer && (
            <button
              className={BTN}
              disabled={busy !== ""}
              onClick={() =>
                run("statement", async () => saveBlob(await accountingApi.customerStatement(contactId, asOf), `${data.registered_name} statement ${asOf}.pdf`))
              }
            >
              <FilePdf size={14} /> Customer statement
            </button>
          )}
        </div>
      </div>
      {data.aliases.length > 0 && (
        <p className="mb-2 text-xs text-[var(--text-secondary)]">Also seen as: {data.aliases.join(" · ")}</p>
      )}
      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {saved && <p className="mb-2 text-sm text-[var(--alert-success-text)]">{saved}</p>}

      <div className="mb-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {isCustomer && <Tile label="Receivable" value={formatPeso(data.receivable)} />}
        {isSupplier && <Tile label="Payable" value={formatPeso(data.payable)} />}
        <Tile label="Overdue" value={formatPeso(data.open_items.filter((i) => i.days_past_due > 0).reduce((n, i) => n + Number(i.open), 0))} />
        {isCustomer && (
          <Tile label="2307s to receive" value={formatPeso(data.cwt_2307s.filter((c) => c.status === "pending").reduce((n, c) => n + Number(c.amount), 0))} />
        )}
      </div>

      <h3 className={H3}>Open items</h3>
      {data.open_items.length === 0 ? (
        <p className="text-sm text-[var(--text-secondary)]">Nothing open as of {day(data.as_of)}.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--text-secondary)]">
                <th className={TH}>Document</th><th className={TH}>Date</th><th className={TH}>Due</th>
                <th className={`${TH} text-right`}>Total</th><th className={`${TH} text-right`}>Withheld</th>
                <th className={`${TH} text-right`}>Paid</th><th className={`${TH} text-right`}>Open</th><th className={TH} />
              </tr>
            </thead>
            <tbody>
              {data.open_items.map((i) => (
                <tr key={i.document_id} className="border-t border-[var(--border)] text-[var(--text-primary)]">
                  <td className={TD}>
                    {i.opening ? (
                      <span className="font-medium" title="Imported as open at the books start (Import → Open items); no document behind it">
                        {KIND[i.kind]} {i.doc_number || "(no number)"}{" "}
                        <span className="rounded-full bg-[var(--bg-hover)] px-2 py-0.5 text-[11px] text-[var(--text-secondary)]">Opening balance</span>
                      </span>
                    ) : (
                      <button className="font-medium text-[var(--accent)] hover:underline" onClick={() => onOpenDocument(i.document_id)}>
                        {KIND[i.kind]} {i.doc_number || "(no number)"}
                      </button>
                    )}
                  </td>
                  <td className={TD}>{day(i.doc_date)}</td>
                  <td className={TD}>{day(i.due)}</td>
                  <td className={NUM}>{formatPeso(i.total)}</td>
                  <td className={NUM}>{Number(i.withheld) ? formatPeso(i.withheld) : ""}</td>
                  <td className={NUM}>{Number(i.paid) ? formatPeso(i.paid) : ""}</td>
                  <td className={`${NUM} font-semibold`}>{formatPeso(i.open)}</td>
                  <td className="py-1.5 whitespace-nowrap">
                    {i.days_past_due > 0 ? (
                      <span className={`${CHIP} bg-[var(--badge-yellow-bg)] text-[var(--badge-yellow-text)]`}>{i.days_past_due} days overdue</span>
                    ) : (
                      <span className={`${CHIP} bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]`}>Current</span>
                    )}
                    {i.payment_unverified && (
                      <span className={`${CHIP} ml-1 bg-[var(--bg-hover)] text-[var(--text-secondary)]`} title="On credit terms, and no receipt or bank line pays it yet">
                        Unverified
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.cwt_2307s.length > 0 && (
        <>
          <h3 className={H3}>
            2307s to receive{" "}
            <Hint align="right">
              The customer withheld tax on these sales and owes the company a BIR 2307 for it. Uploading the 2307 marks it
              received for that quarter; you can also mark it yourself or link the uploaded certificate.
            </Hint>
          </h3>
          <table className="w-full text-sm">
            <tbody>
              {data.cwt_2307s.map((c) => (
                <tr key={c.document_id} className="border-t border-[var(--border)] text-[var(--text-primary)]">
                  <td className={TD}>Sale {c.doc_number} · {day(c.doc_date)}</td>
                  <td className={TD}>{c.year && c.quarter ? `FY ${c.year} Q${c.quarter}` : ""}</td>
                  <td className={NUM}>{formatPeso(c.amount)}</td>
                  <td className={TD}>
                    {c.status === "received" ? (
                      <span className={`${CHIP} bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]`}>
                        Received{c.certificate_label ? ` · ${c.certificate_label}` : ""}{c.source === "user" ? " (marked)" : ""}
                      </span>
                    ) : (
                      <span className={`${CHIP} bg-[var(--badge-yellow-bg)] text-[var(--badge-yellow-text)]`}>Waiting for the 2307</span>
                    )}
                  </td>
                  <td className="py-1.5 text-right whitespace-nowrap">
                    {c.status === "pending" && data.certificates.length > 0 && (
                      <select
                        className={`${INPUT} mr-1 inline-block w-auto py-1 text-xs`}
                        value=""
                        disabled={busy !== ""}
                        aria-label="Link an uploaded 2307"
                        onChange={(e) => e.target.value && run("cwt", () => accountingApi.markCwt2307(c.document_id, "received", e.target.value).then(() => undefined))}
                      >
                        <option value="">Link a 2307…</option>
                        {data.certificates.map((x) => (
                          <option key={x.id} value={x.id}>{x.label}</option>
                        ))}
                      </select>
                    )}
                    <button
                      className={BTN}
                      disabled={busy !== ""}
                      onClick={() => run("cwt", () => accountingApi.markCwt2307(c.document_id, c.status === "pending" ? "received" : "pending").then(() => undefined))}
                    >
                      {c.status === "pending" ? "Mark received" : "Mark not received"}
                    </button>
                    {c.source === "user" && (
                      <button className={`${BTN} ml-1`} disabled={busy !== ""} onClick={() => run("cwt", () => accountingApi.markCwt2307(c.document_id, "auto").then(() => undefined))}>
                        Undo mark
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {data.outgoing_2307s.length > 0 && (
        <>
          <h3 className={H3}>
            2307s to issue{" "}
            <Hint align="right">The company withheld tax from these bills and must give the supplier a 2307 for each quarter. The ZIP comes from that quarter&apos;s latest version.</Hint>
          </h3>
          <table className="w-full text-sm">
            <tbody>
              {data.outgoing_2307s.map((o) => (
                <tr key={o.document_id} className="border-t border-[var(--border)] text-[var(--text-primary)]">
                  <td className={TD}>Bill {o.doc_number} · {day(o.doc_date)}</td>
                  <td className={TD}>{o.atc}</td>
                  <td className={TD}>FY {o.year} Q{o.quarter}</td>
                  <td className={NUM}>{formatPeso(o.amount)}</td>
                  <td className="py-1.5 text-right">
                    {o.output_id ? (
                      <button
                        className={BTN}
                        disabled={busy !== ""}
                        onClick={() =>
                          run("2307s", async () => saveBlob(await accountingApi.outgoing2307s(o.output_id!), `FY ${o.year} Q${o.quarter} 2307s.zip`))
                        }
                      >
                        <FileZip size={14} /> 2307s
                      </button>
                    ) : (
                      <span className="text-xs text-[var(--text-secondary)]">Generate Q{o.quarter} to issue it</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h3 className={H3}>Payments</h3>
      {data.payments.length === 0 ? (
        <p className="text-sm text-[var(--text-secondary)]">No payments seen yet.</p>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {data.payments.map((p, n) => (
              <tr key={`${p.document_id}-${n}`} className="border-t border-[var(--border)] text-[var(--text-primary)]">
                <td className={TD}>{day(p.on)}</td>
                <td className={TD}>{p.doc_number || "(no number)"}</td>
                <td className={TD}>{SOURCE[p.source] ?? p.source}{p.ref ? ` · ${p.ref}` : ""}</td>
                <td className={NUM}>{formatPeso(p.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3 className={H3}>Documents</h3>
      <table className="w-full text-sm">
        <tbody>
          {data.documents.map((d) => (
            <tr key={d.id} className="border-t border-[var(--border)] text-[var(--text-primary)]">
              <td className={TD}>
                <button className="text-[var(--accent)] hover:underline" onClick={() => onOpenDocument(d.id)}>
                  {KIND[d.kind]} {d.doc_number || "(no number)"}
                </button>
              </td>
              <td className={TD}>{day(d.doc_date)}</td>
              <td className={TD}>{d.period_year && d.period_quarter ? `${d.period_year} Q${d.period_quarter}` : ""}</td>
              <td className={NUM}>{formatPeso(d.total)}</td>
              <td className={NUM}>{d.open !== null ? `${formatPeso(d.open)} open` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 className={H3}>Details</h3>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label>
          <span className={LABEL}>Registered name</span>
          <input className={INPUT} value={value("registered_name", data.registered_name) ?? ""} onChange={(e) => set({ registered_name: e.target.value })} />
        </label>
        <label>
          <span className={LABEL}>Kind</span>
          <select className={INPUT} value={value("role", data.role)} onChange={(e) => set({ role: e.target.value as ContactPatch["role"] })}>
            <option value="customer">Customer</option>
            <option value="supplier">Supplier</option>
            <option value="both">Customer and supplier</option>
          </select>
        </label>
        <label>
          <span className={LABEL}>VAT status</span>
          <select className={INPUT} value={value("vat_status", data.vat_status)} onChange={(e) => set({ vat_status: e.target.value as ContactPatch["vat_status"] })}>
            <option value="">Not known</option>
            <option value="vat">VAT registered</option>
            <option value="non_vat">Non-VAT</option>
          </select>
        </label>
        <label className="md:col-span-2">
          <span className={LABEL}>Address</span>
          <input className={INPUT} value={value("address", data.address) ?? ""} onChange={(e) => set({ address: e.target.value })} />
        </label>
        <label>
          <span className={LABEL}>Payment terms (days)</span>
          <input
            className={INPUT}
            type="number"
            min={0}
            placeholder="Due on the document date"
            value={value("payment_terms_days", data.payment_terms_days) ?? ""}
            onChange={(e) => set({ payment_terms_days: e.target.value === "" ? null : Number(e.target.value) })}
          />
        </label>
        {isSupplier && (
          <>
            <label>
              <span className={LABEL}>Default account</span>
              <select className={INPUT} disabled={!data.tin} value={value("default_account", data.default_account)} onChange={(e) => set({ default_account: e.target.value })}>
                <option value="">From the document</option>
                {chart.map((a) => (
                  <option key={a.code} value={a.code}>{a.code} {a.name}</option>
                ))}
              </select>
            </label>
            <label>
              <span className={LABEL}>Default ATC</span>
              <select className={INPUT} disabled={!data.tin} value={value("default_atc", data.default_atc)} onChange={(e) => set({ default_atc: e.target.value })}>
                <option value="">Suggested by AutoAccounting</option>
                {EWT_ATC_OPTIONS.filter((o) => o.value).map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>
          </>
        )}
        <label className={isSupplier ? "" : "md:col-span-1"}>
          <span className={LABEL}>Why (for the audit log)</span>
          <input className={INPUT} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Optional" />
        </label>
      </div>
      {isSupplier && !data.tin && <p className="mt-1 text-xs text-[var(--text-secondary)]">A default account or ATC needs the supplier&apos;s TIN.</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          className={PRIMARY}
          disabled={!dirty || busy !== ""}
          onClick={() =>
            run("save", async () => {
              const next = await accountingApi.updateContact(contactId, { ...form, reason }, asOf);
              setForm({});
              setReason("");
              return next;
            }, "Saved. Fields you set here are kept when new documents come in.")
          }
        >
          Save details
        </button>
        {dirty && <button className={BTN} onClick={() => setForm({})}>Discard</button>}
      </div>

      {canManage && !data.merged_into_id && others.length > 0 && (
        <>
          <h3 className={H3}>
            Merge{" "}
            <Hint align="right">
              Use this when the same party shows up twice (a name without a TIN, or a mistyped TIN). Its documents then count
              for the contact you pick, and its name is kept as an alias. The merge is recorded in the audit log.
            </Hint>
          </h3>
          <div className="flex flex-wrap items-end gap-2">
            <label className="min-w-[240px] flex-1">
              <span className={LABEL}>Merge {data.registered_name} into</span>
              <select className={INPUT} value={mergeInto} onChange={(e) => setMergeInto(e.target.value)}>
                <option value="">Pick a contact…</option>
                {others.map((o) => (
                  <option key={o.id} value={o.id}>{o.registered_name}{o.tin ? ` · ${o.tin}` : ""}</option>
                ))}
              </select>
            </label>
            <button
              className={BTN}
              disabled={!mergeInto || busy !== ""}
              onClick={() =>
                run("merge", async () => {
                  const target = await accountingApi.mergeContact(contactId, mergeInto, reason, asOf);
                  onOpenContact(target.id);
                  return target;
                })
              }
            >
              Merge
            </button>
          </div>
        </>
      )}
      {data.merged_from.length > 0 && (
        <p className="mt-2 text-xs text-[var(--text-secondary)]">Merged in: {data.merged_from.join(" · ")}</p>
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
