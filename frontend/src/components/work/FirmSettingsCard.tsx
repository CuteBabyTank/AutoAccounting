"use client";

import { useEffect, useState } from "react";
import Hint from "@/components/guide/Hint";
import { firmSettings, workApi } from "@/lib/work-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { FirmSettings } from "@/types/work";
import { INPUT } from "@/components/work/ui";

/** Team page: firm-wide work settings. Everyone sees them; managers can change automatic assignment. */
export default function FirmSettingsCard() {
  const [settings, setSettings] = useState<FirmSettings | null>(null);
  const [days, setDays] = useState("7");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    firmSettings(true)
      .then((s) => {
        setSettings(s);
        setDays(String(s.deadline_days));
        setName(s.organization_name);
      })
      .catch((e) => setError(apiErrorMessage(e, "Couldn't load the firm settings")));
  }, []);

  async function save(next: Partial<Pick<FirmSettings, "organization_name" | "approve_before_close" | "deadline_days" | "auto_assign" | "assistant_writes">>) {
    setBusy(true);
    setError("");
    try {
      const s = await workApi.saveSettings(next);
      setSettings(s);
      setDays(String(s.deadline_days));
      setName(s.organization_name);
      firmSettings(true).catch(() => undefined);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save the firm settings"));
    } finally {
      setBusy(false);
    }
  }

  if (!settings) return error ? <p className="mb-6 text-sm text-[var(--alert-error-text)]">{error}</p> : null;
  const locked = !settings.can_edit || busy;
  return (
    <div data-tour="work-settings" className="mb-6 rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
      <h2 className="mb-3 text-sm font-semibold text-[var(--text-primary)]">Work settings</h2>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm text-[var(--text-primary)]">
        <label htmlFor="firm-name">Firm name</label><input id="firm-name" className={INPUT} maxLength={255} disabled={locked} value={name} onChange={(e) => setName(e.target.value)} />
        {settings.can_edit && <button disabled={busy || name.trim() === settings.organization_name} className="text-[var(--accent)] disabled:opacity-50" onClick={() => save({ organization_name: name.trim() })}>Save firm name</button>}
      </div>
      <label className="mb-3 flex items-start gap-2 text-sm text-[var(--text-primary)]">
        <input type="checkbox" className="mt-0.5" disabled={!settings.can_auto_assign || busy} checked={settings.auto_assign}
          onChange={(e) => save({ auto_assign: e.target.checked })} />
        <span>Automatically assign work
          <Hint align="right">New unassigned tasks go to their client&apos;s handler, or the available firm member with the fewest open items. Managers can also assign unassigned work from the Work board.</Hint>
        </span>
      </label>
      <label className="flex items-start gap-2 text-sm text-[var(--text-primary)]">
        <input
          type="checkbox"
          className="mt-0.5"
          disabled={locked}
          checked={settings.approve_before_close}
          onChange={(e) => save({ approve_before_close: e.target.checked, deadline_days: settings.deadline_days })}
        />
        <span>
          Managers approve filing
          <Hint align="right">
            When on, only managers and the firm owner can mark a return filed (or undo it), on the quarter, the annual
            return or the work board. Closing a month of the books is already limited to them.
          </Hint>
        </span>
      </label>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-[var(--text-primary)]">
        <label htmlFor="deadline-days">Remind about deadlines</label>
        <input
          id="deadline-days"
          type="number"
          min={1}
          max={60}
          disabled={locked}
          className={`${INPUT} w-20`}
          value={days}
          onChange={(e) => setDays(e.target.value)}
          onBlur={() => {
            const n = Math.round(Number(days));
            if (n >= 1 && n <= 60 && n !== settings.deadline_days) save({ approve_before_close: settings.approve_before_close, deadline_days: n });
            else setDays(String(settings.deadline_days));
          }}
        />
        <span className="text-[var(--text-secondary)]">days before they&apos;re due</span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-[var(--text-primary)]">
        <label htmlFor="assistant-writes">Casper can make changes for</label>
        <select
          id="assistant-writes"
          className={INPUT}
          disabled={locked}
          value={settings.assistant_writes ?? "managers"}
          onChange={(e) => save({ assistant_writes: e.target.value as FirmSettings["assistant_writes"] })}
        >
          <option value="off">Nobody (read-only)</option>
          <option value="managers">Managers and the owner</option>
          <option value="everyone">Everyone at the firm</option>
        </select>
        <Hint align="right">
          With write mode on, Casper can set up and update tasks, assign filings, fix a document&apos;s account or
          period, and delete a task or document. Each change waits for the person&apos;s confirm, is in the audit log, and
          can be undone or restored for 7 days. It can never touch companies, people, settings, filing or closing.
        </Hint>
      </div>
      {!settings.can_edit && <p className="mt-2 text-xs text-[var(--text-secondary)]">Only the firm owner can change filing approval, deadline reminders and Casper&apos;s changes.</p>}
      {error && <p className="mt-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
    </div>
  );
}
