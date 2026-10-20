"use client";

import { useEffect, useState } from "react";
import Hint from "@/components/guide/Hint";
import { firmSettings, workApi } from "@/lib/work-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { FirmSettings } from "@/types/work";
import { INPUT } from "@/components/work/ui";

/** Team page: firm-wide work settings. Everyone sees them; only the firm owner changes them. */
export default function FirmSettingsCard() {
  const [settings, setSettings] = useState<FirmSettings | null>(null);
  const [days, setDays] = useState("7");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    firmSettings(true)
      .then((s) => {
        setSettings(s);
        setDays(String(s.deadline_days));
      })
      .catch((e) => setError(apiErrorMessage(e, "Couldn't load the firm settings")));
  }, []);

  async function save(next: { approve_before_close: boolean; deadline_days: number }) {
    setBusy(true);
    setError("");
    try {
      const s = await workApi.saveSettings(next);
      setSettings(s);
      setDays(String(s.deadline_days));
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
      {!settings.can_edit && <p className="mt-2 text-xs text-[var(--text-secondary)]">Only the firm owner can change these.</p>}
      {error && <p className="mt-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
    </div>
  );
}
