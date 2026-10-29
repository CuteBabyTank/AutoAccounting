"use client";

import { useEffect, useState } from "react";
import { Lock } from "@phosphor-icons/react";
import CoaTemplateEditor from "@/components/accounting/CoaTemplateEditor";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { Account, CoaTemplate } from "@/types/accounting";

const INPUT = "px-2 py-1 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)]";

export default function ChartEditor({ companyId, canManage }: { companyId: string; canManage: boolean }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState<{ parent: string; code: string; name: string } | null>(null);
  const [showInactive, setShowInactive] = useState(false);
  const [templates, setTemplates] = useState<CoaTemplate[]>([]);
  const [templateName, setTemplateName] = useState("");
  const [notice, setNotice] = useState("");
  const [editingTemplate, setEditingTemplate] = useState<CoaTemplate | null>(null);

  useEffect(() => {
    accountingApi.accounts(companyId).then(setAccounts).catch((e) => setError(apiErrorMessage(e, "Couldn't load the chart")));
    if (canManage) accountingApi.coaTemplates().then(setTemplates).catch((e) => setError(apiErrorMessage(e, "Couldn't load chart templates")));
  }, [companyId, canManage]);

  const inactiveCount = accounts.filter((a) => !a.active).length;
  const shown = accounts.filter((a) => showInactive || a.active);
  const parentOf = (code: string) => accounts.find((a) => a.code === code);

  const bankCode = accounts.find((a) => a.system_key === "bank")?.code;
  // Cash in bank and its sub-accounts carry the number printed on their statements (matched on the last 4 digits).
  const isBank = (a: Account) => a.system_key === "bank" || (bankCode !== undefined && a.parent_code === bankCode) || Boolean(a.bank_account_no);
  const replace = (a: Account) => setAccounts((all) => all.map((x) => (x.id === a.id ? a : x)));
  const run = async (fn: () => Promise<void>) => {
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save the account"));
    }
  };

  return (
    <div>
      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {notice && <p className="mb-2 text-sm text-[var(--text-secondary)]">{notice}</p>}
      <div className="mb-2 flex flex-wrap items-center gap-3 text-xs text-[var(--text-secondary)]">
        <span>Locked accounts take no new postings. Inactive ones are hidden from pickers but stay in the reports.</span>
        {inactiveCount > 0 && (
          <label className="ml-auto inline-flex items-center gap-1">
            <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
            Show inactive ({inactiveCount})
          </label>
        )}
      </div>
      <table className="w-full text-sm">
        <tbody>
          {shown.map((a) => (
            <tr key={a.id} className={`border-b border-[var(--border)] ${a.active ? "" : "opacity-50"}`}>
              <td className="w-20 py-1 font-mono text-xs" style={{ paddingLeft: a.parent_code ? 16 : 0 }}>{a.code}</td>
              <td className="py-1">
                {canManage ? (
                  <input
                    className={`${INPUT} w-full`}
                    defaultValue={a.name}
                    onBlur={(e) => {
                      const name = e.target.value.trim();
                      if (!name) {
                        e.target.value = a.name;
                        return;
                      }
                      if (name !== a.name) run(async () => replace(await accountingApi.updateAccount(a.id, { name })));
                    }}
                  />
                ) : (
                  a.name
                )}
              </td>
              <td className="w-24 py-1 text-xs text-[var(--text-secondary)]" title={a.placement}>
                {a.type}{a.contra ? " (contra)" : ""}
                {a.locked && (
                  <span className="ml-1 rounded-full bg-[var(--badge-yellow-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-yellow-text)]">Locked</span>
                )}
              </td>
              <td className="w-40 py-1">
                {isBank(a) && (canManage ? (
                  <input
                    className={`${INPUT} w-full text-xs`}
                    aria-label={`Bank account number for ${a.code}`}
                    placeholder="Bank account no."
                    maxLength={40}
                    defaultValue={a.bank_account_no ?? ""}
                    onBlur={(e) => {
                      const value = e.target.value.trim();
                      if (value !== (a.bank_account_no ?? "")) run(async () => replace(await accountingApi.updateAccount(a.id, { bank_account_no: value })));
                    }}
                  />
                ) : (
                  <span className="text-xs text-[var(--text-secondary)]">{a.bank_account_no}</span>
                ))}
              </td>
              <td className="w-40 py-1 text-right text-xs">
                {a.system_key ? (
                  <span className="inline-flex items-center gap-1 text-[var(--text-secondary)]"><Lock size={12} /> used by posting</span>
                ) : canManage ? (
                  <button className="text-[var(--accent)]" onClick={() => {
                    if (a.active && !window.confirm(`Deactivate ${a.code} ${a.name}? Existing reports are retained; new postings must use another account.`)) return;
                    run(async () => replace(await accountingApi.updateAccount(a.id, { active: !a.active })));
                  }}>
                    {a.active ? "Deactivate" : "Activate"}
                  </button>
                ) : null}
                {canManage && (!a.system_key || a.system_key.startsWith("doc:")) && a.active && (
                  <button
                    className="ml-3 text-[var(--accent)]"
                    title={a.locked ? "Allow new postings again" : "Block new postings to this account (existing ones stay)"}
                    onClick={() => run(async () => replace(await accountingApi.updateAccount(a.id, { locked: !a.locked })))}
                  >
                    {a.locked ? "Unlock" : "Lock"}
                  </button>
                )}
                {canManage && a.active && (
                  <button className="ml-3 text-[var(--accent)]" onClick={() => setAdding({ parent: a.code, code: "", name: "" })}>Sub-account</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {adding && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-[var(--text-secondary)]">Under {adding.parent}:</span>
          <input className={`${INPUT} w-24`} placeholder="Code" value={adding.code} onChange={(e) => setAdding({ ...adding, code: e.target.value.replace(/\D/g, "") })} />
          <input className={`${INPUT} w-64`} placeholder="Name" value={adding.name} onChange={(e) => setAdding({ ...adding, name: e.target.value })} />
          <button
            className="rounded-lg bg-[var(--accent)] px-3 py-1 font-medium text-white disabled:opacity-60"
            disabled={adding.code.length < 4 || !adding.name.trim()}
            onClick={() =>
              run(async () => {
                const created = await accountingApi.addAccount(companyId, { code: adding.code, name: adding.name, parent_code: adding.parent });
                setAccounts((all) => [...all, created].sort((x, y) => x.code.localeCompare(y.code)));
                setAdding(null);
              })
            }
          >
            Add
          </button>
          <button onClick={() => setAdding(null)}>Cancel</button>
          {parentOf(adding.parent)?.placement && (
            <span className="basis-full text-xs text-[var(--text-secondary)]">
              Lands on: <b className="text-[var(--text-primary)]">{parentOf(adding.parent)?.placement}</b>, under {adding.parent} {parentOf(adding.parent)?.name}
            </span>
          )}
        </div>
      )}
      {canManage && (
        <div className="mt-4 border-t border-[var(--border)] pt-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[var(--text-secondary)]">Save this chart as a firm template:</span>
            <input className={`${INPUT} w-56`} placeholder="Template name" maxLength={80} value={templateName} onChange={(e) => setTemplateName(e.target.value)} />
            <button
              className="rounded-lg border border-[var(--border)] px-3 py-1 font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60"
              disabled={!templateName.trim()}
              onClick={() =>
                run(async () => {
                  const saved = await accountingApi.saveCoaTemplate(companyId, templateName.trim());
                  setTemplates((all) => [...all, saved].sort((x, y) => x.name.localeCompare(y.name)));
                  setTemplateName("");
                  setNotice(`Saved "${saved.name}". Pick it when adding a company.`);
                })
              }
            >
              Save template
            </button>
          </div>
          {editingTemplate && <CoaTemplateEditor key={editingTemplate.id} template={editingTemplate} companyId={companyId} onClose={() => setEditingTemplate(null)} onSaved={(updated) => {
            setTemplates((all) => all.map((t) => t.id === updated.id ? updated : t).sort((a, b) => a.name.localeCompare(b.name)));
            setEditingTemplate(null); setNotice(`Updated "${updated.name}".`);
          }} />}
          {templates.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs text-[var(--text-secondary)]">
              {templates.map((t) => (
                <li key={t.id} className="flex items-center gap-2">
                  <span className="text-[var(--text-primary)]">{t.name}{t.builtin && " (built-in)"}</span> · {t.accounts_count} accounts
                  <button className="text-[var(--accent)]" onClick={() => setEditingTemplate(t)}>{t.builtin ? "View" : "View / edit"}</button>
                  {!t.builtin && <button
                    className="text-[var(--alert-error-text)]"
                    onClick={() => {
                      if (!window.confirm(`Delete the chart template "${t.name}"? Existing companies keep their chart.`)) return;
                      run(async () => {
                        await accountingApi.deleteCoaTemplate(t.id);
                        setTemplates((all) => all.filter((x) => x.id !== t.id));
                        if (editingTemplate?.id === t.id) setEditingTemplate(null);
                      });
                    }}
                  >
                    Delete
                  </button>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
