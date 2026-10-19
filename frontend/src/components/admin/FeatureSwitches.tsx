"use client";

import { useMemo } from "react";
import type { Account, AdminFeatures } from "@/types";

interface Props {
  data: AdminFeatures | null;
  firms: Account[];
  /** "" = every firm (the global switches); otherwise one firm's id. */
  scope: string;
  onScope: (firmId: string) => void;
  busy: string | null;
  onGlobal: (key: string, enabled: boolean) => void;
  onFirm: (firmId: string, key: string, enabled: boolean | null) => void;
  onAllOn: () => void;
}

function Switch({ on, disabled, label, onClick }: { on: boolean; disabled: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
        on ? "bg-[var(--lp-accent)]" : "bg-[var(--error)]"
      }`}
    >
      <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${on ? "translate-x-[18px]" : "translate-x-0.5"}`} />
    </button>
  );
}

const SEG = "px-1.5 h-6 text-[11px] font-medium first:rounded-l-md last:rounded-r-md border border-[var(--lp-border)] -ml-px first:ml-0 disabled:opacity-50";

/** Maintenance switches: off hides a feature from firms (and the server refuses it) while the admin keeps it. */
export default function FeatureSwitches({ data, firms, scope, onScope, busy, onGlobal, onFirm, onAllOn }: Props) {
  const groups = useMemo(() => {
    const out: { name: string; items: AdminFeatures["features"] }[] = [];
    for (const f of data?.features ?? []) {
      const g = out.find((x) => x.name === f.group);
      if (g) g.items.push(f);
      else out.push({ name: f.group, items: [f] });
    }
    return out;
  }, [data]);

  if (!data) return <p className="px-1 py-6 text-sm text-[var(--lp-muted)]">Loading switches…</p>;

  const firmOverrides = scope ? data.overrides[scope] ?? {} : {};
  const globalOff = data.features.filter((f) => !f.enabled).length;
  const pinned = Object.values(data.overrides).reduce((n, o) => n + Object.keys(o).length, 0);
  const firmName = (id: string) => {
    const f = firms.find((x) => x.id === id);
    return f?.organization_name || f?.email || "A firm";
  };
  const firmsPinning = (key: string) => Object.entries(data.overrides).filter(([, o]) => key in o);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-xs text-[var(--lp-muted)]">
          Applies to
          <select value={scope} onChange={(e) => onScope(e.target.value)} className="aa-field !h-8 !rounded-[9px] px-2 text-[13px]">
            <option value="">Every firm</option>
            {firms.map((f) => (
              <option key={f.id} value={f.id}>
                {f.organization_name || f.email}
                {data.overrides[f.id] ? ` (${Object.keys(data.overrides[f.id]).length} pinned)` : ""}
              </option>
            ))}
          </select>
        </label>
        <span className="text-xs text-[var(--lp-muted)]">
          {globalOff === 0 && pinned === 0
            ? "Everything is on."
            : [globalOff && `${globalOff} off for every firm`, pinned && `${pinned} pinned per firm`].filter(Boolean).join(" · ")}
        </span>
        {(globalOff > 0 || pinned > 0) && (
          <button className="aa-ghost ml-auto !text-[var(--lp-accent)]" disabled={!!busy} onClick={onAllOn}>
            Turn everything back on
          </button>
        )}
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {groups.map((g) => (
          <div key={g.name} className="aa-card rounded-xl p-1.5">
            <p className="px-2 pb-1 pt-1 text-[11px] font-medium text-[var(--lp-muted)]">{g.name}</p>
            <ul>
              {g.items.map((f) => {
                const pin = firmOverrides[f.key];
                const effective = scope ? pin ?? f.enabled : f.enabled;
                const pinners = firmsPinning(f.key);
                const saving = busy === f.key;
                return (
                  <li key={f.key} className="flex h-9 items-center gap-2 rounded-lg px-2 hover:bg-[var(--lp-accent-soft)]">
                    <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--lp-text)]" title={f.description}>
                      {f.label}
                    </span>
                    {!scope && pinners.length > 0 && (
                      <span
                        className="shrink-0 text-[11px] text-[var(--lp-faint)]"
                        title={pinners.map(([id, o]) => `${firmName(id)}: ${o[f.key] ? "on" : "off"}`).join("\n")}
                      >
                        {pinners.length} firm{pinners.length === 1 ? "" : "s"} pinned
                      </span>
                    )}
                    {scope ? (
                      <span className="flex shrink-0" role="group" aria-label={`${f.label} for ${firmName(scope)}`}>
                        {([["Default", null], ["On", true], ["Off", false]] as const).map(([label, value]) => {
                          const active = (pin ?? null) === value;
                          return (
                            <button
                              key={label}
                              type="button"
                              disabled={saving || !!busy}
                              aria-pressed={active}
                              title={value === null ? `Follow the global switch (${f.enabled ? "on" : "off"})` : undefined}
                              onClick={() => !active && onFirm(scope, f.key, value)}
                              className={`${SEG} ${
                                active
                                  ? value === false
                                    ? "bg-[var(--error)] text-white"
                                    : "bg-[var(--lp-accent)] text-white"
                                  : "text-[var(--lp-muted)] hover:text-[var(--lp-text)]"
                              }`}
                            >
                              {value === null ? (f.enabled ? "Default" : "Default (off)") : label}
                            </button>
                          );
                        })}
                      </span>
                    ) : (
                      <Switch
                        on={effective}
                        disabled={saving || !!busy}
                        label={`${f.label}: ${effective ? "on" : "off"}`}
                        onClick={() => onGlobal(f.key, !f.enabled)}
                      />
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
      <p className="mt-2 px-1 text-[11px] text-[var(--lp-faint)]">
        Off hides it from firm owners, managers and employees and the server refuses it. You still see everything.
        A firm&apos;s pin wins over the global switch.
      </p>
    </div>
  );
}
