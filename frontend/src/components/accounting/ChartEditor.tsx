"use client";

import { useEffect, useState } from "react";
import { Lock } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { Account } from "@/types/accounting";

const INPUT = "px-2 py-1 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)]";

export default function ChartEditor({ companyId, canManage }: { companyId: string; canManage: boolean }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState<{ parent: string; code: string; name: string } | null>(null);

  useEffect(() => {
    accountingApi.accounts(companyId).then(setAccounts).catch((e) => setError(apiErrorMessage(e, "Couldn't load the chart")));
  }, [companyId]);

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
      <table className="w-full text-sm">
        <tbody>
          {accounts.map((a) => (
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
              <td className="w-24 py-1 text-xs text-[var(--text-secondary)]">{a.type}{a.contra ? " (contra)" : ""}</td>
              <td className="w-40 py-1 text-right text-xs">
                {a.system_key ? (
                  <span className="inline-flex items-center gap-1 text-[var(--text-secondary)]"><Lock size={12} /> used by posting</span>
                ) : canManage ? (
                  <button className="text-[var(--accent)]" onClick={() => run(async () => replace(await accountingApi.updateAccount(a.id, { active: !a.active })))}>
                    {a.active ? "Deactivate" : "Activate"}
                  </button>
                ) : null}
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
        </div>
      )}
    </div>
  );
}
