"use client";

import { useCallback, useEffect, useState } from "react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { Account, BankRule, BankRuleInput } from "@/types/accounting";
import { confirmDialog } from "@/components/ui/Dialogs";

const INPUT = "rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1 text-sm text-[var(--text-primary)]";
const BTN = "rounded-lg border border-[var(--border)] px-2 py-1 text-xs text-[var(--text-primary)] disabled:opacity-50";
const blank = (): BankRuleInput => ({ pattern: "", direction: "any", kind: "payee", account_code: "", payee_name: "", payee_tin: "" });

export default function BankRules({ companyId, accounts, canManage, onChanged }: {
  companyId: string; accounts: Account[]; canManage: boolean; onChanged: () => Promise<void>;
}) {
  const [rules, setRules] = useState<BankRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<{ id?: string; body: BankRuleInput } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => setRules(await accountingApi.bankRules(companyId)), [companyId]);
  useEffect(() => { load().catch((e) => setError(apiErrorMessage(e, "Couldn't load bank rules"))).finally(() => setLoading(false)); }, [load]);
  async function run(action: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await action(); setEditing(null); await load(); await onChanged(); }
    catch (e) { setError(apiErrorMessage(e, "Couldn't save bank rules")); }
    finally { setBusy(false); }
  }
  const set = (patch: Partial<BankRuleInput>) => setEditing((old) => old && ({ ...old, body: { ...old.body, ...patch } }));
  return <div className="mt-3 rounded-lg border border-[var(--border)] p-3 text-sm">
    <div className="mb-2 flex items-center gap-3"><h3 className="font-medium text-[var(--text-primary)]">Bank rules</h3>{canManage && <button className={BTN} disabled={busy} onClick={() => setEditing({ body: blank() })}>Add rule</button>}</div>
    <p className="mb-2 text-xs text-[var(--text-secondary)]">Narration rules can identify a payee or suggest an account. Changes rematch affected open lines. Filed returns, closed books and reconciled history are protected.</p>
    {error && <p role="alert" className="my-2 text-[var(--alert-error-text)]">{error}</p>}
    {loading ? <p>Loading…</p> : !error && !rules.length && <p className="text-[var(--text-secondary)]">No rules yet. Add one or confirm a bank match to teach one.</p>}
    <ul className="space-y-2">{rules.map((r) => <li key={r.id} className="flex flex-wrap items-center gap-2 text-[var(--text-primary)]">
      <span>&ldquo;{r.pattern}&rdquo; ({r.direction}) → {r.kind === "payee" ? r.payee_name || r.payee_tin : r.account_code}</span>
      <span className="text-xs text-[var(--text-secondary)]">used {r.hits}×</span>
      {canManage && <><button className={BTN} disabled={busy} onClick={() => setEditing({ id: r.id, body: { pattern: r.pattern, direction: r.direction, kind: r.kind, account_code: r.account_code, payee_name: r.payee_name, payee_tin: r.payee_tin } })}>Edit</button><button className={BTN} disabled={busy} onClick={async () => { if (await confirmDialog({ title: `Delete the rule "${r.pattern}"?`, message: "Affected open lines will be matched again; finalized and reconciled history is protected.", confirmLabel: "Delete", danger: true })) run(() => accountingApi.deleteBankRule(r.id)); }}>Delete</button></>}
    </li>)}</ul>
    {editing && <form className="mt-3 grid gap-2 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); run(() => editing.id ? accountingApi.updateBankRule(editing.id, editing.body) : accountingApi.createBankRule(companyId, editing.body)); }}>
      <label className="flex flex-col text-xs text-[var(--text-secondary)]">Narration contains<input className={INPUT} minLength={2} maxLength={80} required value={editing.body.pattern} onChange={(e) => set({ pattern: e.target.value })} /></label>
      <label className="flex flex-col text-xs text-[var(--text-secondary)]">Direction<select className={INPUT} value={editing.body.direction} onChange={(e) => set({ direction: e.target.value as BankRuleInput["direction"] })}><option value="any">Any</option><option value="in">Money in</option><option value="out">Money out</option></select></label>
      <label className="flex flex-col text-xs text-[var(--text-secondary)]">Action<select className={INPUT} value={editing.body.kind} onChange={(e) => set({ kind: e.target.value as BankRuleInput["kind"] })}><option value="payee">Identify payee</option><option value="posting">Suggest account</option></select></label>
      {editing.body.kind === "posting" ? <label className="flex flex-col text-xs text-[var(--text-secondary)]">Account<select className={INPUT} required value={editing.body.account_code} onChange={(e) => set({ account_code: e.target.value })}><option value="">Choose account</option>{accounts.filter((a) => a.active && !a.locked).map((a) => <option key={a.id} value={a.code}>{a.code} {a.name}</option>)}</select></label> : <>
        <label className="flex flex-col text-xs text-[var(--text-secondary)]">Payee name<input className={INPUT} maxLength={255} value={editing.body.payee_name} onChange={(e) => set({ payee_name: e.target.value })} /></label>
        <label className="flex flex-col text-xs text-[var(--text-secondary)]">Payee TIN (optional)<input className={INPUT} maxLength={11} value={editing.body.payee_tin} onChange={(e) => set({ payee_tin: e.target.value })} /></label>
      </>}
      <div className="flex gap-2 sm:col-span-2"><button className={BTN} disabled={busy || editing.body.pattern.trim().length < 2}>Save rule</button><button className={BTN} type="button" disabled={busy} onClick={() => setEditing(null)}>Cancel</button></div>
    </form>}
  </div>;
}
