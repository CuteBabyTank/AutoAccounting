"use client";

import { useEffect, useState } from "react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { CoaTemplate } from "@/types/accounting";
import { confirmDialog } from "@/components/ui/Dialogs";

const INPUT = "w-full rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1.5 text-sm text-[var(--text-primary)]";

export default function CoaTemplateEditor({ template, companyId, onSaved, onClose }: {
  template: CoaTemplate; companyId: string; onSaved: (template: CoaTemplate) => void; onClose: () => void;
}) {
  const [name, setName] = useState(template.name);
  const [description, setDescription] = useState(template.description);
  const [refresh, setRefresh] = useState(false);
  const [rows, setRows] = useState<Awaited<ReturnType<typeof accountingApi.coaTemplateAccounts>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    accountingApi.coaTemplateAccounts(template.id).then((r) => !cancelled && setRows(r)).catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load template accounts")));
    return () => { cancelled = true; };
  }, [template.id]);
  return <form className="mt-3 space-y-2 rounded-lg border border-[var(--border)] p-3" onSubmit={async (e) => {
    e.preventDefault();
    if (template.builtin) return;
    if (refresh && !(await confirmDialog({
      title: `Replace the accounts in "${template.name}"?`,
      message: "They'll be replaced with this company's current chart. Existing companies keep their chart.",
      confirmLabel: "Replace",
    }))) return;
    setBusy(true); setError("");
    try { onSaved(await accountingApi.updateCoaTemplate(template.id, { name: name.trim(), description, ...(refresh ? { source_company_id: companyId } : {}) })); }
    catch (e) { setError(apiErrorMessage(e, "Couldn't update the chart template")); }
    finally { setBusy(false); }
  }}>
    <label className="block text-xs text-[var(--text-secondary)]">Template name<input className={INPUT} value={name} readOnly={template.builtin} required maxLength={80} onChange={(e) => setName(e.target.value)} /></label>
    <label className="block text-xs text-[var(--text-secondary)]">Description<input className={INPUT} value={description} readOnly={template.builtin} maxLength={300} onChange={(e) => setDescription(e.target.value)} /></label>
    {template.builtin ? <p className="text-xs text-[var(--text-secondary)]">Built-in templates are read-only. Save a company&apos;s chart as a firm template to customize it.</p> : <label className="flex items-center gap-2 text-sm text-[var(--text-primary)]"><input type="checkbox" checked={refresh} onChange={(e) => setRefresh(e.target.checked)} />Replace template accounts with this company&apos;s current chart</label>}
    {error && <p role="alert" className="text-sm text-[var(--alert-error-text)]">{error}</p>}
    <div className="flex gap-3 text-sm">{!template.builtin && <button disabled={busy || !name.trim()} className="text-[var(--accent)] disabled:opacity-50">Save template changes</button>}<button type="button" disabled={busy} onClick={onClose}>{template.builtin ? "Close" : "Cancel"}</button></div>
    <div className="max-h-64 overflow-auto text-xs text-[var(--text-secondary)]">{rows === null ? (error ? "Template accounts unavailable. Close and reopen to retry." : "Loading template accounts…") : rows.length === 0 ? "This template has no accounts." : <table className="w-full"><thead><tr><th className="text-left">Code</th><th className="text-left">Account</th><th className="text-left">Report placement</th></tr></thead><tbody>{rows.map((r) => <tr key={r.code}><td>{r.code}</td><td>{r.name}{!r.active && " (inactive)"}</td><td>{r.placement}</td></tr>)}</tbody></table>}</div>
  </form>;
}
