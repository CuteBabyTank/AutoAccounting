"use client";

import { useEffect, useMemo, useState } from "react";
import { MagnifyingGlass } from "@phosphor-icons/react";
import Hint from "@/components/guide/Hint";
import AtcPicker from "@/components/accounting/AtcPicker";
import { accountingApi } from "@/lib/accounting-api";
import { ACCOUNT_LABELS, apiErrorMessage } from "@/lib/accounting-format";
import type { AtcDatabank } from "@/types/accounting";

interface Props {
  companyId: string;
  companyName: string;
  onChanged: () => void;
}

const SELECT = "w-full rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] disabled:opacity-60";
const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";

function AtcSelect({ value, blank, disabled, onChange }: { value: string; blank: string; disabled: boolean; onChange: (v: string) => void }) {
  return <AtcPicker className={SELECT} value={value} blank={blank} disabled={disabled} onChange={onChange} />;
}

export default function AtcDatabankPanel({ companyId, companyName, onChanged }: Props) {
  const [data, setData] = useState<AtcDatabank | null>(null);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    accountingApi
      .atcDatabank(companyId)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the ATC databank")));
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  async function run(call: () => Promise<AtcDatabank>) {
    setBusy(true);
    setError("");
    try {
      setData(await call());
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save the ATC"));
    } finally {
      setBusy(false);
    }
  }

  const suppliers = useMemo(() => {
    const q = search.trim().toLowerCase();
    const digits = q.replace(/\D/g, "");
    return (data?.suppliers ?? []).filter(
      (s) => !q || s.name.toLowerCase().includes(q) || (digits.length > 0 && s.tin.includes(digits)),
    );
  }, [data, search]);
  const suggested = (data?.suppliers ?? []).filter((s) => s.suggestion && !s.ewt_atc).length;
  const hinted = (data?.suppliers ?? []).filter((s) => s.hint && !s.ewt_atc).length;

  return (
    <div className="mb-6">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">
          ATC databank · {companyName}{" "}
          <Hint align="right">
            An ATC (alphanumeric tax code) is the BIR code for a kind of payment, and it sets the withholding rate. It decides
            what goes on the 0619-E, the 1601-EQ and the 2307s you issue to suppliers.
          </Hint>
        </h2>
      </div>
      <p className="mb-4 text-xs text-[var(--text-secondary)]">
        Set each supplier&apos;s ATC once and every document from them uses it. A document&apos;s own ATC wins, then the
        supplier&apos;s, then the default for its expense type, then AutoAccounting&apos;s suggestion. Changes apply when you
        next generate a quarter.
      </p>
      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {!data ? (
        !error && <p className="text-sm text-[var(--text-secondary)]">Loading…</p>
      ) : (
        <>
          <section className="mb-6">
            <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">Defaults by expense type</h3>
            <div className="grid grid-cols-1 gap-x-4 gap-y-2 md:grid-cols-2">
              {data.defaults.map((d) => (
                <label key={d.account} className="grid grid-cols-[150px_1fr] items-center gap-2 text-sm text-[var(--text-primary)]">
                  <span className="truncate">{ACCOUNT_LABELS[d.account] ?? d.account}</span>
                  <AtcSelect
                    value={d.ewt_atc}
                    blank={d.suggestion ? `Suggested (${d.suggestion})` : "Suggested"}
                    disabled={busy}
                    onChange={(v) => run(() => accountingApi.setAccountAtc(companyId, d.account, v))}
                  />
                </label>
              ))}
            </div>
          </section>

          <section>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">Suppliers</h3>
              {suggested > 0 && (
                <button className={BTN} disabled={busy} onClick={() => run(() => accountingApi.useAtcSuggestions(companyId))}>
                  Use {suggested} suggestion{suggested === 1 ? "" : "s"} from other companies
                </button>
              )}
              {hinted > 0 && (
                <button className={BTN} disabled={busy} onClick={() => run(() => accountingApi.useAtcHints(companyId))}>
                  Use AutoAccounting&apos;s {hinted} suggestion{hinted === 1 ? "" : "s"}
                </button>
              )}
              <label className="relative ml-auto">
                <MagnifyingGlass size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search suppliers or TINs"
                  className="w-56 rounded-full border border-[var(--border)] bg-[var(--bg-primary)] py-1.5 pl-7 pr-3 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                />
              </label>
            </div>
            {data.suppliers.length === 0 ? (
              <p className="text-sm text-[var(--text-secondary)]">
                No suppliers yet. They appear here once this company has purchase or expense documents with a TIN.
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] text-[var(--text-secondary)]">
                    <th className="pb-1 font-medium">Supplier</th>
                    <th className="pb-1 font-medium">TIN</th>
                    <th className="pb-1 text-right font-medium">Docs</th>
                    <th className="w-[45%] pb-1 pl-3 font-medium">ATC</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {suppliers.map((s) => (
                    <tr key={s.tin}>
                      <td className="py-1.5 pr-2 text-[var(--text-primary)]">{s.name || "(no name)"}</td>
                      <td className="py-1.5 pr-2 tabular-nums text-[var(--text-secondary)]">
                        {s.tin.slice(0, 3)}-{s.tin.slice(3, 6)}-{s.tin.slice(6)}
                      </td>
                      <td className="py-1.5 text-right tabular-nums text-[var(--text-secondary)]">{s.documents}</td>
                      <td className="py-1.5 pl-3">
                        <AtcSelect
                          value={s.ewt_atc}
                          blank={s.automatic ? `Suggested (${s.automatic})` : "Suggested"}
                          disabled={busy}
                          onChange={(v) => run(() => accountingApi.setSupplierAtc(companyId, s.tin, v, s.name))}
                        />
                        {s.hint && (
                          <span className="mt-0.5 flex items-center gap-2 text-[11px] text-[var(--text-secondary)]">
                            <span className="min-w-0" title={s.hint_reason}>
                              AutoAccounting suggests {s.hint === "NONE" ? "no withholding" : s.hint}: {s.hint_reason}
                            </span>
                            <button
                              className="shrink-0 font-semibold text-[var(--accent)]"
                              disabled={busy}
                              onClick={() => run(() => accountingApi.setSupplierAtc(companyId, s.tin, s.hint, s.name))}
                            >
                              Use
                            </button>
                          </span>
                        )}
                        {s.suggestion && (
                          <span className="mt-0.5 flex items-center gap-2 text-[11px] text-[var(--text-secondary)]">
                            {s.suggestion} in {s.suggestion_company}
                            <button
                              className="font-semibold text-[var(--accent)]"
                              disabled={busy}
                              onClick={() => run(() => accountingApi.setSupplierAtc(companyId, s.tin, s.suggestion, s.name))}
                            >
                              Use
                            </button>
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}
