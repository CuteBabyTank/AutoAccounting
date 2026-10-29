"use client";

import { useCallback, useEffect, useState } from "react";
import BankRules from "@/components/accounting/BankRules";
import AmountInput from "@/components/AmountInput";
import Hint from "@/components/guide/Hint";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, formatPeso } from "@/lib/accounting-format";
import { useFilePreview } from "@/components/accounting/PdfPreview";
import type { Account, BankAccountInfo, BankLine, BankMonth, ReconcileResult } from "@/types/accounting";

interface Props {
  companyId: string;
  account: string; // "" = statements nobody has assigned to an account yet
  month: string; // YYYY-MM
  canManage: boolean;
  onChanged: () => void;
}

const BTN = "rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50";
const PRIMARY = "rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60";
const INPUT = "rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const CHIP = "rounded-full px-2 py-0.5 text-[11px] font-medium";

const STATUS: Record<BankLine["match_status"], { label: string; tone: string }> = {
  matched: { label: "Matched", tone: "bg-[var(--badge-blue-bg)] text-[var(--badge-blue-text)]" },
  confirmed: { label: "Confirmed", tone: "bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]" },
  suggested: { label: "Suggested", tone: "bg-[var(--badge-yellow-bg)] text-[var(--badge-yellow-text)]" },
  ambiguous: { label: "Pick a match", tone: "bg-[var(--badge-yellow-bg)] text-[var(--badge-yellow-text)]" },
  unmatched: { label: "Unmatched", tone: "bg-[var(--badge-yellow-bg)] text-[var(--badge-yellow-text)]" },
  excluded: { label: "Excluded", tone: "bg-[var(--bg-hover)] text-[var(--text-secondary)]" },
};
const STRENGTH: Record<string, string> = {
  strong: "narration names it",
  partial: "part payment",
  weak: "amount and date only",
  conflict: "narration names someone else",
};

const day = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" });
const monthName = (ym: string) => new Date(`${ym}-01T00:00:00`).toLocaleDateString("en-PH", { month: "long", year: "numeric" });
const signed = (value: string) => (Number(value) < 0 ? `(${formatPeso(-Number(value))})` : formatPeso(value));

/** One bank account's statement lines for a month: what each line pays, confirm / reject / re-match, reconcile. */
export default function BankPanel({ companyId, account, month, canManage, onChanged }: Props) {
  const [data, setData] = useState<BankMonth | null>(null);
  const [accounts, setAccounts] = useState<BankAccountInfo[]>([]);
  const [chart, setChart] = useState<Account[]>([]);
  const [showRules, setShowRules] = useState(false);
  const file = useFilePreview();
  const [openLine, setOpenLine] = useState("");
  const [postTo, setPostTo] = useState("");
  const [partial, setPartial] = useState("");
  const [assignTo, setAssignTo] = useState("");
  const [result, setResult] = useState<ReconcileResult | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [m, overview] = await Promise.all([
      accountingApi.bankMonth(companyId, account, month),
      accountingApi.bankOverview(companyId),
    ]);
    setData(m);
    setAccounts(overview.accounts);
  }, [companyId, account, month]);

  useEffect(() => {
    let cancelled = false;
    setError("");
    setResult(null);
    Promise.all([accountingApi.bankMonth(companyId, account, month), accountingApi.bankOverview(companyId), accountingApi.accounts(companyId)])
      .then(([m, overview, all]) => {
        if (cancelled) return;
        setData(m);
        setAccounts(overview.accounts);
        setChart(all.filter((a) => a.active && !a.locked));
      })
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the bank lines")));
    return () => {
      cancelled = true;
    };
  }, [companyId, account, month]);

  async function run(label: string, action: () => Promise<BankMonth | void>) {
    setBusy(label);
    setError("");
    try {
      const next = await action();
      if (next) setData(next);
      else await load();
      setOpenLine("");
      setPostTo("");
      setPartial("");
      setResult(null);
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "That didn't work"));
    } finally {
      setBusy("");
    }
  }

  async function reconcile() {
    if (!data?.account) return;
    setBusy("reconcile");
    setError("");
    try {
      const r = await accountingApi.reconcileBank(companyId, data.account.code, `${month}-01`);
      setResult(r);
      if (r.ok) {
        await load();
        onChanged();
      }
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't reconcile"));
    } finally {
      setBusy("");
    }
  }

  if (!data) return error ? <p className="mb-3 text-sm text-[var(--alert-error-text)]">{error}</p> : null;
  const info = data.account;
  const open = data.lines.filter((l) => ["unmatched", "ambiguous", "suggested"].includes(l.match_status)).length;
  const postable = chart.filter((a) => a.code !== account);
  const title = info ? `${info.code} ${info.name}${info.bank_account_no ? ` ····${info.bank_account_no.slice(-4)}` : ""}` : "Account not set";

  return (
    <section className="mb-6">
      <h2 className="mb-1 flex items-center gap-1.5 text-base font-semibold text-[var(--text-primary)]">
        Bank · {title} · {monthName(month)}
        <Hint align="right">
          The bank statement&apos;s lines for the month. Each line is matched to what it pays or collects by the exact
          amount, the date and the payee or document number in the narration; amount alone never links. Matched lines
          post the payment to this bank account in the books (in place of a document&apos;s paid-on date). Confirm or
          reject each match, pick one when several fit, or post a line to an account (bank charges, interest,
          transfers). Reconcile when every line is settled: the book balance must equal the statement&apos;s.
        </Hint>
      </h2>
      {data.statements.map((s) => (
        <p key={s.id} className="text-xs text-[var(--text-secondary)]">
          {s.bank_name || "Statement"} {s.account_number} · {s.period_start ? day(s.period_start) : "?"} – {s.period_end ? day(s.period_end) : "?"}
          {s.opening_balance !== null && ` · opening ${formatPeso(s.opening_balance)}`}
          {s.closing_balance !== null && ` · closing ${formatPeso(s.closing_balance)}`}
          {" · "}
          {s.ties ? (
            <span className="text-[var(--badge-green-text)]">balances tie</span>
          ) : (
            <span className="text-[var(--alert-warning-text)]">
              running balance breaks at {s.tie_breaks.map((n) => (n === 0 ? "the closing balance" : `line ${n}`)).join(", ")} (check for a misread amount)
            </span>
          )}
        </p>
      ))}
      {data.opening_balance !== null && (
        <p className="mt-1 text-sm text-[var(--text-primary)]">
          Statement: {formatPeso(data.opening_balance)} at the start of the month → {formatPeso(data.closing_balance ?? "0")} at the end
        </p>
      )}
      {error && <p className="mt-2 text-sm text-[var(--alert-error-text)]">{error}</p>}

      {!account && data.statements.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)] p-3 text-sm text-[var(--alert-warning-text)]">
          <span>Which bank account is this statement ({data.statements[0].account_number || "no number read"})? Its lines don&apos;t post until you choose.</span>
          <select className={INPUT} value={assignTo} onChange={(e) => setAssignTo(e.target.value)} aria-label="Bank account">
            <option value="">Choose…</option>
            {chart.filter((a) => a.type === "asset").map((a) => (
              <option key={a.code} value={a.code}>{a.code} {a.name}</option>
            ))}
          </select>
          <button className={BTN} disabled={!assignTo || Boolean(busy)}
            onClick={() => run("assign", async () => {
              for (const s of data.statements) await accountingApi.setStatementAccount(s.id, assignTo);
            })}>
            Save
          </button>
        </div>
      )}

      {info?.opening_missing && (
        <p className="mt-3 rounded-lg border border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)] p-3 text-sm text-[var(--alert-warning-text)]">
          Opening balance missing: the first statement opens at {formatPeso(info.opening_missing.statement)} on {day(info.opening_missing.date)}, but
          the books show {formatPeso(info.opening_missing.books)} for this account. Enter the opening balances under Books → Opening balances
          (or the earlier months&apos; statements) so cash isn&apos;t understated.
        </p>
      )}

      {info && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button className={PRIMARY} disabled={Boolean(busy)} onClick={reconcile}>
            {busy === "reconcile" ? "Reconciling…" : data.reconciliation ? "Reconcile again" : "Reconcile"}
          </button>
          <button className={BTN} disabled={Boolean(busy)} onClick={() => run("rematch", async () => { await accountingApi.rematchBank(companyId); })}>
            {busy === "rematch" ? "Matching…" : "Re-match"}
          </button>
          <span className="text-xs text-[var(--text-secondary)]">
            {info.reconciled_through ? `Reconciled through ${day(info.reconciled_through)}` : "Not reconciled yet"}
            {open > 0 && ` · ${open} line${open === 1 ? "" : "s"} to settle`}
          </span>
          {data.reconciliation && (
            <button className={BTN} onClick={() => {
              const id = data.reconciliation!.id;
              file.open(`Bank reconciliation · ${account} ${month}`, () => accountingApi.reconciliationFile(id),
                `Bank reconciliation ${account} ${month}.pdf`);
            }}>Reconciliation report</button>
          )}
          {file.node}
          <button className={`${BTN} ml-auto`} onClick={() => setShowRules((show) => !show)}>
            {showRules ? "Hide bank rules" : "Bank rules"}
          </button>
        </div>
      )}

      {result && (
        <div className={`mt-3 rounded-lg border p-3 text-sm ${result.ok ? "border-[var(--alert-success-border)] bg-[var(--alert-success-bg)] text-[var(--alert-success-text)]" : "border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)] text-[var(--alert-warning-text)]"}`}>
          <p className="font-medium">{result.ok ? `Reconciled: books ${formatPeso(result.book_balance ?? "0")} = statement.` : result.problem}</p>
          {result.statement_balance !== null && (
            <p className="mt-1 text-xs">
              Statement {formatPeso(result.statement_balance)} · uncleared {signed(result.outstanding ?? "0")} · books {formatPeso(result.book_balance ?? "0")} · difference {signed(result.difference ?? "0")}
            </p>
          )}
          {result.uncleared.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-xs">
              {result.uncleared.map((u) => <li key={u.id}>{day(u.date)} · {u.label} · {signed(u.amount)}</li>)}
            </ul>
          )}
        </div>
      )}

      {showRules && <BankRules companyId={companyId} accounts={chart} canManage={canManage} onChanged={async () => { await load(); setResult(null); onChanged(); }} />}

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="text-left text-xs text-[var(--text-secondary)]">
              <th className="py-1 pr-3 font-medium">Date</th>
              <th className="py-1 pr-3 font-medium">Narration</th>
              <th className="py-1 pr-3 text-right font-medium">Amount</th>
              <th className="py-1 pr-3 font-medium">Match</th>
              <th className="py-1 font-medium" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]">
            {data.lines.map((l) => {
              const status = STATUS[l.match_status];
              const expanded = openLine === l.id;
              const decided = l.match_status === "confirmed" || l.match_status === "excluded";
              return (
                <tr key={l.id} className="align-top">
                  <td className="whitespace-nowrap py-2 pr-3 text-[var(--text-secondary)]">{day(l.line_date)}</td>
                  <td className="py-2 pr-3 text-[var(--text-primary)]">
                    {l.narration}
                    {l.check_no && <span className="ml-1 text-xs text-[var(--text-secondary)]">check {l.check_no}</span>}
                  </td>
                  <td className={`whitespace-nowrap py-2 pr-3 text-right tabular-nums ${Number(l.amount) > 0 ? "text-[var(--badge-green-text)]" : "text-[var(--text-primary)]"}`}>
                    {signed(l.amount)}
                  </td>
                  <td className="py-2 pr-3">
                    <span className={`${CHIP} ${status.tone}`}>{status.label}</span>
                    {l.match_label && (
                      <span className="ml-1.5 text-xs text-[var(--text-primary)]">
                        {l.match_kind === "posting" ? `→ ${l.match_label}` : l.match_label}
                        {l.match_amount && Number(l.match_amount) < Math.abs(Number(l.amount)) - 0.005 && ` (part: ${formatPeso(l.match_amount)})`}
                      </span>
                    )}
                    {l.match_status !== "matched" && l.match_status !== "confirmed" && l.candidates.length > 0 && !expanded && (
                      <span className="ml-1.5 text-xs text-[var(--text-secondary)]">
                        {l.candidates.length} possible: {l.candidates.map((c) => c.label).join("; ")}
                      </span>
                    )}
                    {expanded && (
                      <div className="mt-2 space-y-1.5 rounded-lg border border-[var(--border)] p-2 text-xs">
                        {l.candidates.map((c) => (
                          <div key={`${c.kind}:${c.ref}`} className="flex flex-wrap items-center gap-2">
                            <span className="text-[var(--text-primary)]">{c.label}</span>
                            <span className="text-[var(--text-secondary)]">{day(c.date)} · {formatPeso(c.amount)} · {STRENGTH[c.strength] ?? c.strength}</span>
                            <button className={BTN} disabled={Boolean(busy)}
                              onClick={() => run("link", () => accountingApi.confirmBankLine(l.id, { kind: c.kind, ref: c.ref, ...(partial ? { amount: partial } : {}) }))}>
                              Link
                            </button>
                          </div>
                        ))}
                        {l.candidates.length > 0 && (
                          <label className="flex items-center gap-2 text-[var(--text-secondary)]">
                            Part payment only?
                            <AmountInput className={`${INPUT} w-28`} placeholder={formatPeso(Math.abs(Number(l.amount)))} value={partial}
                              onValueChange={(v) => setPartial(v.replace(/[^\d.]/g, ""))} />
                          </label>
                        )}
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[var(--text-secondary)]">Or post to</span>
                          <select className={INPUT} value={postTo} onChange={(e) => setPostTo(e.target.value)} aria-label="Post to account">
                            <option value="">Choose an account…</option>
                            {postable.map((a) => <option key={a.code} value={a.code}>{a.code} {a.name}</option>)}
                          </select>
                          <button className={BTN} disabled={!postTo || Boolean(busy)}
                            onClick={() => run("post", () => accountingApi.confirmBankLine(l.id, { kind: "posting", account_code: postTo }))}>
                            Post
                          </button>
                        </div>
                      </div>
                    )}
                  </td>
                  <td className="whitespace-nowrap py-2">
                    {account && (
                      <div className="flex flex-wrap justify-end gap-1">
                        {(l.match_status === "matched" || l.match_status === "suggested") && (
                          <button className={BTN} disabled={Boolean(busy)} onClick={() => run("confirm", () => accountingApi.confirmBankLine(l.id))}>Confirm</button>
                        )}
                        {(l.match_status === "matched" || l.match_status === "suggested" || l.match_status === "confirmed") && (
                          <button className={BTN} disabled={Boolean(busy)} onClick={() => run("reject", () => accountingApi.rejectBankLine(l.id))}>
                            {l.match_status === "confirmed" ? "Undo" : "Reject"}
                          </button>
                        )}
                        {!decided && (
                          <button className={BTN} onClick={() => { setOpenLine(expanded ? "" : l.id); setPostTo(""); setPartial(""); }}>
                            {expanded ? "Close" : "Re-match"}
                          </button>
                        )}
                        {!decided && (
                          <button className={BTN} disabled={Boolean(busy)} onClick={() => run("exclude", () => accountingApi.excludeBankLine(l.id))}>Exclude</button>
                        )}
                        {l.match_status === "excluded" && (
                          <button className={BTN} disabled={Boolean(busy)} onClick={() => run("include", () => accountingApi.rejectBankLine(l.id))}>Include again</button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {data.lines.length === 0 && <p className="py-6 text-center text-sm text-[var(--text-secondary)]">No statement lines this month.</p>}
      </div>
      {accounts.length > 1 && (
        <p className="mt-3 text-xs text-[var(--text-secondary)]">
          Bank accounts: {accounts.map((a) => `${a.code} ${a.name}${a.bank_account_no ? ` ····${a.bank_account_no.slice(-4)}` : ""}`).join(" · ")}.
          Statements are matched to an account by the last 4 digits of its number (set in the chart of accounts).
        </p>
      )}
    </section>
  );
}
