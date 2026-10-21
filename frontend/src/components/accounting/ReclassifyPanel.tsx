"use client";

import { useEffect, useState } from "react";
import Hint from "@/components/guide/Hint";
import AtcPicker from "@/components/accounting/AtcPicker";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, formatAmount } from "@/lib/accounting-format";
import { PRESETS, presetRange, type PresetKey } from "@/lib/report-periods";
import { BTN, BTN_PRIMARY, Chip, INPUT } from "@/components/work/ui";
import type { Account, ReclassifyList, ReclassifyPreview } from "@/types/accounting";

interface Props {
  companyId: string;
  companyName: string;
  fiscalYearEndMonth: number;
  onOpenDocument: (id: string) => void;
  onChanged: () => void;
}

const LABEL = "block text-[11px] font-medium text-[var(--text-secondary)] mb-1";

/** Company → Reclassify: move the postings behind an account (documents, typed journal entries) in bulk. */
export default function ReclassifyPanel({ companyId, companyName, fiscalYearEndMonth, onOpenDocument, onChanged }: Props) {
  const initial = presetRange("this_quarter", new Date(), fiscalYearEndMonth);
  const [preset, setPreset] = useState<PresetKey>("this_quarter");
  const [start, setStart] = useState(initial.start);
  const [end, setEnd] = useState(initial.end);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [account, setAccount] = useState("");
  const [atc, setAtc] = useState("");
  const [list, setList] = useState<ReclassifyList | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [toAccount, setToAccount] = useState("");
  const [toAtc, setToAtc] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<ReclassifyPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  useEffect(() => {
    accountingApi.accounts(companyId).then(setAccounts).catch((e) => setError(apiErrorMessage(e, "Couldn't load the chart")));
  }, [companyId]);

  const name = (code: string) => accounts.find((a) => a.code === code)?.name ?? "";
  const targets = accounts.filter((a) => a.active && !a.locked && a.code !== account);
  const movable = (list?.candidates ?? []).filter((c) => c.movable);
  const body = () => ({ start, end, account, atc, keys: [...picked], to_account: toAccount, to_atc: toAtc, reason });

  async function load() {
    if (!account) return;
    setBusy(true);
    setError("");
    setDone("");
    setPreview(null);
    try {
      setList(await accountingApi.reclassifyCandidates(companyId, { start, end, account, atc }));
      setPicked(new Set());
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't list the postings"));
    } finally {
      setBusy(false);
    }
  }

  async function run(apply: boolean) {
    setBusy(true);
    setError("");
    try {
      if (apply) {
        const out = await accountingApi.reclassify(companyId, body());
        setDone(`Moved ${out.moved ?? out.count} item(s)${out.corrections ? `; ${out.corrections} in closed months post as correcting entries` : ""}.`);
        setPreview(null);
        setReason("");
        onChanged();
        setList(await accountingApi.reclassifyCandidates(companyId, { start, end, account, atc }));
        setPicked(new Set());
      } else {
        setPreview(await accountingApi.reclassifyPreview(companyId, body()));
      }
    } catch (e) {
      setError(apiErrorMessage(e, apply ? "Couldn't reclassify" : "Couldn't preview the move"));
    } finally {
      setBusy(false);
    }
  }

  const toggle = (key: string) => {
    setPreview(null);
    setPicked((p) => {
      const next = new Set(p);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <div className="mb-6">
      <h2 className="mb-3 text-base font-semibold text-[var(--text-primary)]">
        Reclassify · {companyName}{" "}
        <Hint align="right">
          Move what was posted to one account (and optionally one ATC) to another, in bulk. It changes the documents&apos; account or ATC and
          typed journal entries, then the books recompute. Items in closed months post as correcting entries on the first open day; the
          closed pages stay as printed. Every moved item is in the audit log with your reason.
        </Hint>
      </h2>

      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div>
          <label className={LABEL}>Period</label>
          <select
            className={INPUT}
            value={preset}
            onChange={(e) => {
              const key = e.target.value as PresetKey;
              setPreset(key);
              if (key !== "custom") {
                const r = presetRange(key, new Date(), fiscalYearEndMonth);
                setStart(r.start);
                setEnd(r.end);
              }
            }}
          >
            {PRESETS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL}>From</label>
          <input type="date" className={INPUT} value={start} onChange={(e) => { setPreset("custom"); setStart(e.target.value); }} />
        </div>
        <div>
          <label className={LABEL}>To</label>
          <input type="date" className={INPUT} value={end} onChange={(e) => { setPreset("custom"); setEnd(e.target.value); }} />
        </div>
        <div>
          <label className={LABEL}>Account</label>
          <select className={`${INPUT} max-w-64`} value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="">Choose an account</option>
            {accounts.map((a) => <option key={a.code} value={a.code}>{a.code} {a.name}{a.active ? "" : " (inactive)"}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL}>ATC (optional)</label>
          <AtcPicker className={`${INPUT} max-w-52`} value={atc} blank="Any" onChange={setAtc} />
        </div>
        <button className={BTN_PRIMARY} disabled={!account || busy} onClick={load}>Show postings</button>
      </div>

      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {done && <p className="mb-2 text-sm text-[var(--text-secondary)]">{done}</p>}

      {list && (list.candidates.length === 0 ? (
        <p className="py-6 text-sm text-[var(--text-secondary)]">Nothing posted to {list.account} {list.account_name} in this period.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--text-secondary)]">
                <th className="w-6 py-2">
                  <input
                    type="checkbox"
                    aria-label="Select every movable item"
                    checked={movable.length > 0 && movable.every((c) => picked.has(c.key))}
                    onChange={(e) => { setPreview(null); setPicked(new Set(e.target.checked ? movable.map((c) => c.key) : [])); }}
                  />
                </th>
                <th className="py-2 pr-3 font-medium">Date</th>
                <th className="py-2 pr-3 font-medium">Source</th>
                <th className="py-2 pr-3 font-medium">Party</th>
                <th className="py-2 pr-3 font-medium">ATC</th>
                <th className="py-2 pr-3 text-right font-medium">Amount</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {list.candidates.map((c) => (
                <tr key={c.entry_id} className={`border-t border-[var(--border)] ${c.movable ? "text-[var(--text-primary)]" : "text-[var(--text-secondary)]"}`}>
                  <td className="py-1.5">
                    {c.movable && <input type="checkbox" aria-label={`Select ${c.reference || c.key}`} checked={picked.has(c.key)} onChange={() => toggle(c.key)} />}
                  </td>
                  <td className="py-1.5 pr-3 whitespace-nowrap">{c.date}</td>
                  <td className="py-1.5 pr-3">
                    {c.kind === "document" ? (
                      <button className="text-[var(--accent)] hover:underline" onClick={() => onOpenDocument(c.source_id)}>
                        {c.book} {c.reference || "document"}
                      </button>
                    ) : (
                      <span>{c.book} {c.reference || c.particulars}</span>
                    )}
                    {c.kind === "journal_entry" && <span className="ml-1 text-xs">(journal entry)</span>}
                  </td>
                  <td className="py-1.5 pr-3">{c.party || "—"}</td>
                  <td className="py-1.5 pr-3 text-xs">{c.atc || "—"}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{formatAmount(c.amount)}</td>
                  <td className="py-1.5 text-right text-xs">
                    {c.closed && <Chip tone="blue" title="This month is closed: a move posts as a correcting entry">Closed month</Chip>}
                    {!c.movable && <span className="ml-1" title={c.why_not}>{c.why_not}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      {list && movable.length > 0 && (
        <div className="mt-3 flex flex-wrap items-end gap-3 rounded-lg border border-[var(--border)] p-3">
          <div>
            <label className={LABEL}>Move {picked.size} to account</label>
            <select className={`${INPUT} max-w-64`} value={toAccount} onChange={(e) => { setPreview(null); setToAccount(e.target.value); }}>
              <option value="">Keep the account</option>
              {targets.map((a) => <option key={a.code} value={a.code}>{a.code} {a.name}</option>)}
            </select>
            {toAccount && <p className="mt-1 text-[11px] text-[var(--text-secondary)]">{accounts.find((a) => a.code === toAccount)?.placement}</p>}
          </div>
          <div>
            <label className={LABEL}>and / or ATC (documents)</label>
            <AtcPicker
              className={`${INPUT} max-w-52`}
              value={toAtc}
              blank="Keep the ATC"
              onChange={(v) => { setPreview(null); setToAtc(v); }}
            />
          </div>
          <button className={BTN} disabled={busy || picked.size === 0 || (!toAccount && !toAtc)} onClick={() => run(false)}>Preview</button>
        </div>
      )}

      {preview && (
        <div className="mt-3 rounded-lg border border-[var(--accent)] p-3 text-sm">
          <p className="mb-2 text-[var(--text-primary)]">
            {preview.count} item(s), ₱{formatAmount(preview.total)}
            {preview.to_account && <> → {preview.to_account} {preview.to_name || name(preview.to_account)}</>}
            {preview.corrections > 0 && <> · {preview.corrections} in closed months post as correcting entries</>}
            {preview.skipped.length > 0 && <> · {preview.skipped.length} can&apos;t move and are left out</>}
          </p>
          <ul className="mb-3 max-h-56 overflow-y-auto text-xs text-[var(--text-secondary)]">
            {preview.items.map((i) => (
              <li key={i.key}>
                {i.date} {i.reference} {i.party}: ₱{formatAmount(i.amount)} {i.from} → {i.to}
                {i.from_atc !== i.to_atc && <> · ATC {i.from_atc || "none"} → {i.to_atc}</>}
                {i.closed && <> · posts on {i.posts_on}</>}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            <input className={`${INPUT} w-72`} placeholder="Reason (kept in the audit log)" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className={BTN_PRIMARY} disabled={busy || reason.trim().length < 3} onClick={() => run(true)}>Reclassify {preview.count}</button>
            <button className={BTN} onClick={() => setPreview(null)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
