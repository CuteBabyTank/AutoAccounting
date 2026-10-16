"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Buildings, Check, MagnifyingGlass, X } from "@phosphor-icons/react";
import Portal from "@/components/Portal";
import type { Account } from "@/types";

interface Props {
  /** The account being assigned. */
  account: Account;
  role: "manager" | "employee";
  firms: Account[];
  busy: boolean;
  onConfirm: (firmId: string) => void;
  onClose: () => void;
}

/** Pick which firm a manager or employee joins: searchable, scrollable list instead of a numbered prompt. */
export default function FirmPicker({ account, role, firms, busy, onConfirm, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<string | null>(account.enterprise_id ?? null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    searchRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const sorted = useMemo(
    () => [...firms].sort((a, b) => (a.organization_name || a.email).localeCompare(b.organization_name || b.email)),
    [firms],
  );
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sorted;
    return sorted.filter((f) => [f.organization_name, f.email, f.nickname].some((v) => v?.toLowerCase().includes(q)));
  }, [sorted, query]);

  const roleName = role === "manager" ? "Manager" : "Employee";

  return (
    <Portal>
      <div
        className="lp-skin overlay-enter fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
        onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      >
        <div role="dialog" aria-modal="true" aria-labelledby="firm-picker-title" className="aa-card modal-enter flex max-h-[min(560px,calc(100dvh-2rem))] w-full max-w-md flex-col rounded-2xl">
          <div className="flex items-start gap-3 px-5 pt-5">
            <div className="min-w-0 flex-1">
              <h2 id="firm-picker-title" className="text-base font-semibold text-[var(--lp-text)]">Choose a firm</h2>
              <p className="mt-0.5 truncate text-sm text-[var(--lp-muted)]">
                {account.nickname || account.email} joins as {roleName}.
              </p>
            </div>
            <button onClick={onClose} aria-label="Close" className="-mr-1.5 rounded-lg p-1.5 text-[var(--lp-muted)] hover:bg-[var(--lp-bg-gray)] hover:text-[var(--lp-text)]">
              <X size={16} />
            </button>
          </div>

          <label className="relative mx-5 mt-4 block">
            <span className="sr-only">Search firms</span>
            <MagnifyingGlass size={16} weight="light" className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--lp-muted)]" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search firm name or owner email"
              className="aa-field w-full pl-9 pr-3"
            />
          </label>

          <ul role="listbox" aria-label="Firms" className="mx-3 mt-3 min-h-0 flex-1 overflow-y-auto pb-1">
            {shown.map((f) => {
              const selected = f.id === picked;
              return (
                <li key={f.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={selected}
                    onClick={() => setPicked(f.id)}
                    onDoubleClick={() => !busy && onConfirm(f.id)}
                    className={`flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left ${selected ? "bg-[var(--lp-accent-soft)]" : "hover:bg-[var(--lp-bg-gray)]"}`}
                  >
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[var(--lp-accent-soft)] text-[var(--lp-accent)]">
                      <Buildings size={18} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-[var(--lp-text)]">{f.organization_name || "Unnamed firm"}</span>
                      <span className="block truncate text-xs text-[var(--lp-muted)]">{f.email}</span>
                    </span>
                    {selected && <Check size={16} weight="bold" className="shrink-0 text-[var(--lp-accent)]" />}
                  </button>
                </li>
              );
            })}
            {shown.length === 0 && (
              <li className="px-3 py-8 text-center text-sm text-[var(--lp-muted)]">No firm matches &ldquo;{query}&rdquo;.</li>
            )}
          </ul>

          <div className="flex justify-end gap-2 border-t border-[var(--lp-border)] px-5 py-3.5">
            <button onClick={onClose} className="aa-ghost !h-10 !px-4 !text-sm">Cancel</button>
            <button disabled={!picked || busy} onClick={() => picked && onConfirm(picked)} className="aa-btn">
              Assign
            </button>
          </div>
        </div>
      </div>
    </Portal>
  );
}
