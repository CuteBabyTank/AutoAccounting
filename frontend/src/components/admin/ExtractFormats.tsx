"use client";

import { useEffect, useState } from "react";
import { CaretDown, CaretRight } from "@phosphor-icons/react";
import { adminApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { Account, AdminExtractFormat } from "@/types";

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("en-PH", { dateStyle: "medium", timeStyle: "short" });
}

/** Every firm's Extract formats, read only: fields, check sentences and the generated reading prompt. */
export default function ExtractFormats({ firms }: { firms: Account[] }) {
  const [firmId, setFirmId] = useState("");
  const [rows, setRows] = useState<AdminExtractFormat[] | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setRows(null);
    setError("");
    adminApi
      .extractFormats(firmId || undefined)
      .then((r) => live && setRows(r))
      .catch((e) => live && setError(apiErrorMessage(e, "Couldn't load formats")));
    return () => {
      live = false;
    };
  }, [firmId]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-xs text-[var(--lp-muted)]">
          Firm
          <select value={firmId} onChange={(e) => setFirmId(e.target.value)} className="aa-field !h-8 !rounded-[9px] px-2 text-[13px]">
            <option value="">Every firm</option>
            {firms.map((f) => (
              <option key={f.id} value={f.id}>
                {f.organization_name || f.email}
              </option>
            ))}
          </select>
        </label>
        {rows && <span className="text-xs text-[var(--lp-muted)]">{rows.length} format{rows.length === 1 ? "" : "s"}, newest edit first</span>}
      </div>

      {error && <p className="px-1 py-3 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {!rows && !error && <p className="px-1 py-6 text-sm text-[var(--lp-muted)]">Loading formats…</p>}
      {rows && rows.length === 0 && <p className="px-1 py-6 text-sm text-[var(--lp-muted)]">No firm has saved a format yet.</p>}

      {rows && rows.length > 0 && (
        <ul className="aa-card divide-y divide-[var(--lp-border)] rounded-2xl">
          {rows.map((r) => {
            const isOpen = open === r.id;
            return (
              <li key={r.id}>
                <button
                  type="button"
                  aria-expanded={isOpen}
                  onClick={() => setOpen(isOpen ? null : r.id)}
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-[var(--lp-accent-soft)]"
                >
                  {isOpen ? <CaretDown size={14} /> : <CaretRight size={14} />}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-[var(--lp-text)]">
                      {r.name}
                      {r.deleted && <span className="ml-2 text-[11px] font-normal text-[var(--error)]">deleted</span>}
                    </span>
                    <span className="block truncate text-xs text-[var(--lp-muted)]">{r.firm}</span>
                  </span>
                  <span className="shrink-0 text-[11px] tabular-nums text-[var(--lp-faint)]">v{r.version}</span>
                  <span className="hidden shrink-0 text-xs text-[var(--lp-muted)] sm:block">
                    {[r.updated_by, when(r.updated_at)].filter(Boolean).join(" · ")}
                  </span>
                </button>
                {isOpen && (
                  <div className="space-y-4 px-4 pb-4 pt-1">
                    <section>
                      <p className="mb-1 text-[11px] font-medium text-[var(--lp-muted)]">Fields ({r.fields.length})</p>
                      <ul className="space-y-0.5 text-[13px] text-[var(--lp-text)]">
                        {r.fields.map((f) => (
                          <li key={f.key}>
                            {f.label} <span className="text-[var(--lp-faint)]">
                              {f.type}, {f.scope === "row" ? "line" : "header"}{f.required ? ", required" : ""}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </section>
                    <section>
                      <p className="mb-1 text-[11px] font-medium text-[var(--lp-muted)]">Checks ({r.checks.length})</p>
                      {r.checks.length === 0 ? (
                        <p className="text-[13px] text-[var(--lp-muted)]">None.</p>
                      ) : (
                        <ul className="space-y-0.5 text-[13px] text-[var(--lp-text)]">
                          {r.checks.map((c) => (
                            <li key={c.id}>
                              <span className="text-[var(--lp-faint)]">{c.level}</span> {c.sentence}
                            </li>
                          ))}
                        </ul>
                      )}
                    </section>
                    <section>
                      <p className="mb-1 text-[11px] font-medium text-[var(--lp-muted)]">Reading prompt</p>
                      <pre
                        tabIndex={0}
                        aria-label={`Reading prompt for ${r.name}`}
                        className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-[var(--lp-border)] p-3 font-mono text-xs text-[var(--lp-text)]"
                      >
                        {r.prompt}
                      </pre>
                    </section>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
