"use client";

import { useState } from "react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { ContactCreate } from "@/types/accounting";

const INPUT = "w-full rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1.5 text-sm text-[var(--text-primary)]";

export default function ContactForm({ companyId, role, onSaved, onClose }: {
  companyId: string; role: "customer" | "supplier"; onSaved: (id: string) => void; onClose: () => void;
}) {
  const [form, setForm] = useState<ContactCreate>({ registered_name: "", tin: "", role, address: "", vat_status: "", payment_terms_days: null });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return <form className="my-3 rounded-lg border border-[var(--border)] p-3" onSubmit={async (e) => {
    e.preventDefault(); setBusy(true); setError("");
    try { onSaved((await accountingApi.createContact(companyId, form)).id); }
    catch (e) { setError(apiErrorMessage(e, "Couldn't add the contact")); }
    finally { setBusy(false); }
  }}>
    <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">Add contact</h3>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="text-xs text-[var(--text-secondary)]">Registered name<input className={INPUT} required maxLength={255} value={form.registered_name} onChange={(e) => setForm({ ...form, registered_name: e.target.value })} /></label>
      <label className="text-xs text-[var(--text-secondary)]">TIN (optional)<input className={INPUT} placeholder="123-456-789" maxLength={11} value={form.tin} onChange={(e) => setForm({ ...form, tin: e.target.value })} /></label>
      <label className="text-xs text-[var(--text-secondary)]">Role<select className={INPUT} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as ContactCreate["role"] })}><option value="customer">Customer</option><option value="supplier">Supplier</option><option value="both">Customer and supplier</option></select></label>
      <label className="text-xs text-[var(--text-secondary)]">Payment terms (days)<input className={INPUT} type="number" min={0} max={3650} value={form.payment_terms_days ?? ""} onChange={(e) => setForm({ ...form, payment_terms_days: e.target.value === "" ? null : Number(e.target.value) })} /></label>
      <label className="text-xs text-[var(--text-secondary)]">Address<input className={INPUT} maxLength={500} value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></label>
      <label className="text-xs text-[var(--text-secondary)]">Tax registration<select className={INPUT} value={form.vat_status} onChange={(e) => setForm({ ...form, vat_status: e.target.value as ContactCreate["vat_status"] })}><option value="">Not set</option><option value="vat">VAT</option><option value="non_vat">Non-VAT</option></select></label>
    </div>
    {error && <p role="alert" className="mt-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
    <div className="mt-3 flex gap-3"><button type="submit" disabled={busy || !form.registered_name.trim()} className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm text-white disabled:opacity-50">Save contact</button><button type="button" disabled={busy} onClick={onClose} className="text-sm text-[var(--text-primary)]">Cancel</button></div>
  </form>;
}
