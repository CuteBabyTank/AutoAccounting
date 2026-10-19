"use client";

import { useCallback, useEffect, useState } from "react";
import Hint from "@/components/guide/Hint";
import ImportHistory from "@/components/accounting/ImportHistory";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, formatPeso, saveBlob } from "@/lib/accounting-format";
import { BTN, BTN_PRIMARY, Chip, INPUT } from "@/components/work/ui";
import type { Account, ImportKind, ImportOptions, ImportPreview, ImportResult, OpeningItems } from "@/types/accounting";

interface Props {
  companyId: string;
  companyName: string;
  onChanged: () => void;
}

const TABS: { kind: ImportKind; label: string; blurb: string }[] = [
  { kind: "opening-tb", label: "Opening balances", blurb: "A trial balance as of the day before the books start: account, debit, credit." },
  { kind: "open-items", label: "Open items", blurb: "Customer invoices and supplier bills still unpaid when the books start." },
  { kind: "journal-entries", label: "Journal entries", blurb: "Journals with several lines each, grouped by journal number (or date + reference)." },
];
const LABEL = "block text-[11px] font-medium text-[var(--text-secondary)] mb-1";
const TH = "px-2 py-1.5 text-left text-[11px] font-medium text-[var(--text-secondary)]";
const TD = "px-2 py-1.5 align-top";
const NUM = "px-2 py-1.5 text-right tabular-nums align-top";
const HOW: Record<string, { label: string; tone: "green" | "blue" | "yellow" | "red" }> = {
  code: { label: "Code", tone: "green" },
  conflict: { label: "Code, but the name differs", tone: "yellow" },
  name: { label: "Name", tone: "green" },
  fuzzy: { label: "Closest name", tone: "yellow" },
  none: { label: "No match", tone: "red" },
};
const PROBLEM: Record<string, string> = {
  unmapped: "Pick an account",
  not_in_chart: "Not in the chart",
  inactive: "Inactive",
  locked: "Locked",
  unconfirmed: "Confirm",
};
const day = (iso: string | null) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" }) : "");

/** Company → Import: opening balances, open items at books start and journal entries from a spreadsheet. */
export default function ImportPanel({ companyId, companyName, onChanged }: Props) {
  const [kind, setKind] = useState<ImportKind>("opening-tb");
  const [file, setFile] = useState<File | null>(null);
  const [opts, setOpts] = useState<ImportOptions>({});
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [items, setItems] = useState<OpeningItems | null>(null);
  const [pay, setPay] = useState<Record<string, { on: string; via: string; account: string }>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [imported, setImported] = useState(0);

  useEffect(() => {
    accountingApi.accounts(companyId).then(setAccounts).catch((e) => setError(apiErrorMessage(e, "Couldn't load the chart")));
  }, [companyId]);

  const loadItems = useCallback(() => {
    accountingApi.openingItems(companyId).then(setItems).catch((e) => setError(apiErrorMessage(e, "Couldn't load the open items")));
  }, [companyId]);
  useEffect(() => {
    if (kind === "open-items") loadItems();
  }, [kind, loadItems]);

  async function run(next: ImportOptions, chosen: File | null = file) {
    if (!chosen) return;
    setOpts(next);
    setBusy(true);
    setError("");
    try {
      setPreview(await accountingApi.importPreview(companyId, kind, chosen, next));
    } catch (e) {
      setPreview(null);
      setError(apiErrorMessage(e, "Couldn't read the file"));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!file || !preview?.ready) return;
    setBusy(true);
    setError("");
    try {
      const out = await accountingApi.importConfirm(companyId, kind, file, opts);
      setResult(out);
      setPreview(null);
      setFile(null);
      setOpts({});
      setImported((n) => n + 1);
      onChanged();
      if (kind === "open-items") loadItems();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't import"));
    } finally {
      setBusy(false);
    }
  }

  function switchTab(next: ImportKind) {
    setKind(next);
    setFile(null);
    setPreview(null);
    setResult(null);
    setOpts({});
    setError("");
  }

  async function template(format: "csv" | "xlsx") {
    try {
      saveBlob(await accountingApi.importTemplate(kind, format), `${kind}-template.${format}`);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't download the template"));
    }
  }

  const usable = accounts.filter((a) => a.active && !a.locked);
  const name = (code: string | null) => accounts.find((a) => a.code === code)?.name ?? "";
  const accountOptions = (current: string | null) => (
    <>
      <option value="">Choose an account</option>
      {usable.map((a) => <option key={a.code} value={a.code}>{a.code} {a.name}</option>)}
      {current && !usable.some((a) => a.code === current) && <option value={current}>{current} {name(current)} (can&apos;t post)</option>}
    </>
  );
  const moneyKey = (code: string) => {
    const a = accounts.find((x) => x.code === code);
    const parent = accounts.find((x) => x.code === a?.parent_code);
    return ["cash", "bank", "ewallet"].find((k) => a?.system_key === k || parent?.system_key === k) ?? "";
  };
  const moneyAccounts = usable.filter((a) => moneyKey(a.code));
  const equityFirst = [...usable].sort((a, b) => Number(b.type === "equity") - Number(a.type === "equity") || a.code.localeCompare(b.code));
  const tab = TABS.find((t) => t.kind === kind)!;
  const columns = preview?.columns ?? {};
  const ambiguous = !!preview && preview.date_formats.length > 1;

  return (
    <div className="mb-6">
      <h2 className="mb-3 text-base font-semibold text-[var(--text-primary)]">
        Import · {companyName}{" "}
        <Hint align="right">
          Bring a client&apos;s starting position and bulk journals in from Excel or CSV. Upload, check how the columns and accounts were read
          (code first, then the account name, then the closest name, which you confirm; fix any row), then confirm. Negative amounts are fine (a negative debit is
          a credit), and the date format is detected from the values: you&apos;re asked only when it could be read two ways. Nothing posts until it
          balances. Every import is in the audit log and listed under Recent imports, where an owner or manager can undo a whole import in
          one step (the opening balances go back to what they were). An undo is refused while the import sits in a closed month, a filed quarter
          or a bank reconciliation, or after later work used it (a confirmed bank match, a payment, a write-off, an edit).
        </Hint>
      </h2>

      <div className="mb-3 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button key={t.kind} className={t.kind === kind ? BTN_PRIMARY : BTN} onClick={() => switchTab(t.kind)}>{t.label}</button>
        ))}
      </div>
      <p className="mb-3 text-sm text-[var(--text-secondary)]">
        {tab.blurb} Template:{" "}
        <button className="text-[var(--accent)] hover:underline" onClick={() => template("xlsx")}>Excel</button> ·{" "}
        <button className="text-[var(--accent)] hover:underline" onClick={() => template("csv")}>CSV</button>
      </p>

      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div>
          <label className={LABEL}>File (.xlsx or .csv, up to 5 MB)</label>
          <input
            type="file"
            accept=".xlsx,.xlsm,.csv,.txt"
            className="text-sm text-[var(--text-primary)]"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              setResult(null);
              setPreview(null);
              if (f) run({}, f);
              e.target.value = "";
            }}
          />
        </div>
        {file && <span className="text-sm text-[var(--text-secondary)]">{file.name}</span>}
        {busy && <span className="text-sm text-[var(--text-secondary)]">Reading…</span>}
      </div>

      {error && <p className="mb-3 text-sm text-[var(--badge-red-text)]">{error}</p>}
      {result && (
        <p className="mb-3 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)]">
          {kind === "opening-tb"
            ? `Opening balances ${result.updated ? "replaced" : "saved"}.`
            : `Imported ${result.created} ${kind === "open-items" ? "open item(s)" : "journal entr(ies)"}${result.skipped ? `; ${result.skipped} already there were skipped` : ""}.`}
          {result.warnings.map((w) => <span key={w} className="mt-1 block text-[var(--badge-yellow-text)]">{w}</span>)}
        </p>
      )}

      {preview && (
        <div className="space-y-4">
          <section>
            <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">Columns ({preview.row_count} rows read)</h3>
            <div className="flex flex-wrap gap-3">
              {Object.entries(preview.fields).map(([field, label]) => (
                <div key={field}>
                  <label className={LABEL}>{label}</label>
                  <select
                    className={`${INPUT} max-w-48`}
                    value={columns[field] ?? ""}
                    onChange={(e) => {
                      const next = { ...columns };
                      if (e.target.value) next[field] = e.target.value;
                      else delete next[field];
                      run({ ...opts, columns: next });
                    }}
                  >
                    <option value="">—</option>
                    {preview.headers.filter(Boolean).map((h) => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>
              ))}
              {(preview.date_formats.length > 0 || preview.date_format) && (
                <div>
                  <label className={LABEL}>Date format{ambiguous ? " (could be read two ways)" : ""}</label>
                  <select
                    className={`${INPUT} ${ambiguous && !opts.date_format ? "border-[var(--badge-yellow-text)]" : ""}`}
                    value={opts.date_format ?? (ambiguous ? "" : preview.date_format ?? "")}
                    onChange={(e) => run({ ...opts, date_format: e.target.value || null })}
                  >
                    {ambiguous && <option value="">Choose…</option>}
                    {preview.date_formats.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </select>
                </div>
              )}
              {kind === "open-items" && !columns.kind && (
                <div>
                  <label className={LABEL}>The sheet lists</label>
                  <select className={INPUT} value={opts.default_kind ?? ""} onChange={(e) => run({ ...opts, default_kind: (e.target.value || null) as ImportOptions["default_kind"] })}>
                    <option value="">Choose…</option>
                    <option value="ar">Receivables (customer invoices)</option>
                    <option value="ap">Payables (supplier bills)</option>
                  </select>
                </div>
              )}
            </div>
          </section>

          {preview.accounts.length > 0 && (
            <section>
              <h3 className="mb-2 flex flex-wrap items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
                Accounts
                {preview.accounts.some((a) => a.problem === "unconfirmed") && (
                  <button
                    className={BTN}
                    disabled={busy}
                    onClick={() => run({
                      ...opts,
                      accounts: {
                        ...(opts.accounts ?? {}),
                        ...Object.fromEntries(preview.accounts.filter((a) => a.problem === "unconfirmed" && a.chosen).map((a) => [a.key, a.chosen as string])),
                      },
                    })}
                  >
                    Use every match shown
                  </button>
                )}
              </h3>
              <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
                <table className="w-full text-sm">
                  <thead>
                    <tr><th className={TH}>In the file</th><th className={TH}>Matched by</th><th className={TH}>Chart account</th><th className={`${TH} text-right`}>Rows</th></tr>
                  </thead>
                  <tbody>
                    {preview.accounts.map((a) => (
                      <tr key={a.key} className="border-t border-[var(--border)] text-[var(--text-primary)]">
                        <td className={TD}>{[a.code_in, a.name_in].filter(Boolean).join(" ") || "(blank)"}</td>
                        <td className={TD}>
                          {opts.accounts?.[a.key] ? <Chip tone="blue">Your choice</Chip> : <Chip tone={HOW[a.how].tone}>{HOW[a.how].label}</Chip>}{" "}
                          {a.problem && <Chip tone="red">{PROBLEM[a.problem]}</Chip>}
                        </td>
                        <td className={TD}>
                          <select
                            className={`${INPUT} max-w-72`}
                            value={a.chosen ?? ""}
                            onChange={(e) => run({ ...opts, accounts: { ...(opts.accounts ?? {}), [a.key]: e.target.value } })}
                          >
                            {accountOptions(a.chosen)}
                          </select>
                          {a.problem === "unconfirmed" && a.chosen && (
                            <button
                              className={`${BTN} ml-2`}
                              disabled={busy}
                              onClick={() => run({ ...opts, accounts: { ...(opts.accounts ?? {}), [a.key]: a.chosen as string } })}
                            >
                              Use it
                            </button>
                          )}
                          {a.how === "conflict" && !opts.accounts?.[a.key] && (
                            <span className="mt-1 block text-[11px] text-[var(--text-secondary)]">
                              By code: {a.match_code} {name(a.match_code)}
                              {a.alternatives.length > 0 && <> · by name: {a.alternatives.map((c) => `${c} ${name(c)}`).join(", ")}</>}
                            </span>
                          )}
                          {a.how === "none" && a.alternatives.length > 0 && !a.chosen && (
                            <span className="ml-2 text-[11px] text-[var(--text-secondary)]">Closest: {a.alternatives.map((c) => `${c} ${name(c)}`).join(", ")}</span>
                          )}
                        </td>
                        <td className={NUM}>{a.rows}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {kind === "opening-tb" && (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">
                Opening entry on {day(preview.books_start)}{preview.as_of ? ` (trial balance as of ${day(preview.as_of)})` : ""}
              </h3>
              <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
                <table className="w-full text-sm">
                  <thead><tr><th className={TH}>Account</th><th className={`${TH} text-right`}>Debit</th><th className={`${TH} text-right`}>Credit</th></tr></thead>
                  <tbody>
                    {preview.tb_lines.map((l) => (
                      <tr key={l.account_code} className="border-t border-[var(--border)] text-[var(--text-primary)]">
                        <td className={TD}>{l.account_code} {l.account_name}</td>
                        <td className={NUM}>{Number(l.debit) ? formatPeso(l.debit) : ""}</td>
                        <td className={NUM}>{Number(l.credit) ? formatPeso(l.credit) : ""}</td>
                      </tr>
                    ))}
                    <tr className="border-t border-[var(--border)] font-semibold text-[var(--text-primary)]">
                      <td className={TD}>Total</td><td className={NUM}>{formatPeso(preview.debit)}</td><td className={NUM}>{formatPeso(preview.credit)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              {Number(preview.raw_difference) !== 0 && (
                <div className="mt-2 flex flex-wrap items-end gap-3 text-sm">
                  <span className={Number(preview.difference) ? "text-[var(--badge-red-text)]" : "text-[var(--text-secondary)]"}>
                    Debits and credits differ by {formatPeso(Math.abs(Number(preview.raw_difference)))}.{" "}
                    {Number(preview.difference) ? "Fix the sheet, or post the difference to an account you choose:" : "The difference posts to:"}
                  </span>
                  <select className={`${INPUT} max-w-72`} value={opts.difference_account ?? ""} onChange={(e) => run({ ...opts, difference_account: e.target.value || null })}>
                    <option value="">Don&apos;t post it (fix the sheet)</option>
                    {equityFirst.map((a) => <option key={a.code} value={a.code}>{a.code} {a.name}</option>)}
                  </select>
                </div>
              )}
            </section>
          )}

          {kind === "open-items" && (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">
                {preview.item_count} item(s){preview.skipped ? ` · ${preview.skipped} already in the books` : ""} · receivables {formatPeso(preview.totals.ar ?? "0")} · payables {formatPeso(preview.totals.ap ?? "0")}
              </h3>
              <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
                <table className="w-full text-sm">
                  <thead><tr><th className={TH}>Row</th><th className={TH}>Type</th><th className={TH}>Customer / supplier</th><th className={TH}>No.</th><th className={TH}>Date</th><th className={TH}>Due / terms</th><th className={`${TH} text-right`}>Open</th></tr></thead>
                  <tbody>
                    {preview.items.map((i) => (
                      <tr key={i.row} className="border-t border-[var(--border)] text-[var(--text-primary)]">
                        <td className={TD}>{i.row}</td><td className={TD}>{i.kind === "ar" ? "A/R" : "A/P"}</td>
                        <td className={TD}>{i.contact_name}{i.contact_tin && <span className="block text-[11px] text-[var(--text-secondary)]">{i.contact_tin}</span>}</td>
                        <td className={TD}>{i.doc_number}</td><td className={TD}>{day(i.doc_date)}</td>
                        <td className={TD}>{i.due_date ? day(i.due_date) : i.terms_days ? `${i.terms_days} days` : ""}</td>
                        <td className={NUM}>{formatPeso(i.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {kind === "journal-entries" && preview.entries.length > 0 && (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">{preview.entries.length} journal entr{preview.entries.length === 1 ? "y" : "ies"}</h3>
              <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
                <table className="w-full text-sm">
                  <thead><tr><th className={TH}>Row</th><th className={TH}>Date</th><th className={TH}>Reference · particulars</th><th className={`${TH} text-right`}>Lines</th><th className={`${TH} text-right`}>Debit</th><th className={`${TH} text-right`}>Credit</th><th className={TH}></th></tr></thead>
                  <tbody>
                    {preview.entries.map((e) => (
                      <tr key={e.row} className="border-t border-[var(--border)] text-[var(--text-primary)]">
                        <td className={TD}>{e.row}</td>
                        <td className={TD}>
                          {day(e.entry_date)}
                          {e.posts_on && e.posts_on !== e.entry_date && <span className="block text-[11px] text-[var(--badge-yellow-text)]">Closed month: posts as a correction on {day(e.posts_on)}</span>}
                        </td>
                        <td className={TD}>{[e.reference, e.particulars].filter(Boolean).join(" · ")} {e.is_adjusting && <Chip tone="blue">Adjusting</Chip>}</td>
                        <td className={NUM}>{e.lines}</td><td className={NUM}>{formatPeso(e.debit)}</td><td className={NUM}>{formatPeso(e.credit)}</td>
                        <td className={TD}>{e.errors.map((m) => <span key={m} className="block text-[11px] text-[var(--badge-red-text)]">{m}</span>)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {(preview.errors.length > 0 || preview.warnings.length > 0) && (
            <section className="space-y-1 text-sm">
              {preview.errors.map((e) => (
                <p key={`${e.row}:${e.message}`} className="text-[var(--badge-red-text)]">{e.row ? `Row ${e.row}: ` : ""}{e.message}</p>
              ))}
              {preview.warnings.map((w) => <p key={w} className="text-[var(--badge-yellow-text)]">{w}</p>)}
            </section>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <button className={BTN_PRIMARY} disabled={busy || !preview.ready} onClick={confirm}>
              {kind === "opening-tb" ? (preview.has_opening ? "Replace the opening balances" : "Save the opening balances") : kind === "open-items" ? `Import ${preview.item_count} open item(s)` : `Post ${preview.entries.length} journal entr${preview.entries.length === 1 ? "y" : "ies"}`}
            </button>
            {!preview.ready && <span className="text-sm text-[var(--text-secondary)]">Fix what&apos;s shown in red first.</span>}
            {kind === "opening-tb" && preview.has_opening && <span className="text-sm text-[var(--text-secondary)]">The company already has opening balances; this replaces their lines.</span>}
          </div>
        </div>
      )}

      {kind === "open-items" && items && items.items.length > 0 && (
        <section className="mt-6">
          <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">
            Open items at books start · receivables {formatPeso(items.totals.ar ?? "0")} · payables {formatPeso(items.totals.ap ?? "0")}
          </h3>
          {items.warnings.map((w) => <p key={w} className="mb-2 text-sm text-[var(--badge-yellow-text)]">{w}</p>)}
          <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
            <table className="w-full text-sm">
              <thead><tr><th className={TH}>Type</th><th className={TH}>Customer / supplier</th><th className={TH}>No.</th><th className={TH}>Date</th><th className={`${TH} text-right`}>Amount</th><th className={`${TH} text-right`}>Open</th><th className={TH}>Paid outside the bank feed</th><th className={TH}></th></tr></thead>
              <tbody>
                {items.items.map((i) => {
                  const p = pay[i.id] ?? { on: i.paid_on ?? "", via: i.paid_via || "cash", account: i.paid_account };
                  const set = (patch: Partial<typeof p>) => setPay((all) => ({ ...all, [i.id]: { ...p, ...patch } }));
                  const act = (fn: () => Promise<unknown>) => {
                    setBusy(true);
                    setError("");
                    fn().then(() => { loadItems(); onChanged(); }).catch((e) => setError(apiErrorMessage(e, "Couldn't save"))).finally(() => setBusy(false));
                  };
                  return (
                    <tr key={i.id} className="border-t border-[var(--border)] text-[var(--text-primary)]">
                      <td className={TD}>{i.kind === "ar" ? "A/R" : "A/P"}</td>
                      <td className={TD}>{i.contact_name}</td><td className={TD}>{i.doc_number}</td><td className={TD}>{day(i.doc_date)}</td>
                      <td className={NUM}>{formatPeso(i.amount)}</td><td className={`${NUM} font-semibold`}>{formatPeso(i.open)}</td>
                      <td className={TD}>
                        <div className="flex flex-wrap items-center gap-1">
                          <input type="date" className={INPUT} value={p.on} min={items.books_start ?? undefined} onChange={(e) => set({ on: e.target.value })} />
                          <select className={INPUT} value={p.account} onChange={(e) => set({ account: e.target.value })}>
                            <option value="">Cash on hand</option>
                            {moneyAccounts.map((a) => <option key={a.code} value={a.code}>{a.code} {a.name}</option>)}
                          </select>
                          <button className={BTN} disabled={busy} onClick={() => act(() => accountingApi.payOpeningItem(i.id, p.on ? { paid_on: p.on, paid_via: p.account ? moneyKey(p.account) : "cash", paid_account: p.account } : { paid_on: null }))}>
                            {p.on ? "Save" : i.paid_on ? "Clear" : "Save"}
                          </button>
                        </div>
                      </td>
                      <td className={TD}>
                        <button className={BTN} disabled={busy} onClick={() => window.confirm(`Delete ${i.doc_number || "this item"} of ${i.contact_name}?`) && act(() => accountingApi.deleteOpeningItem(i.id))}>Delete</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <ImportHistory
        companyId={companyId}
        version={imported}
        onUndone={(undone) => {
          setResult(null);
          onChanged();
          if (undone === "open-items" && kind === "open-items") loadItems();
        }}
      />
    </div>
  );
}
