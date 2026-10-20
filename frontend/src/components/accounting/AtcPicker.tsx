"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { CaretDown, Check, MagnifyingGlass } from "@phosphor-icons/react";
import Portal from "@/components/Portal";
import { accountingApi } from "@/lib/accounting-api";
import { COMMON_ATCS } from "@/lib/accounting-format";
import type { AtcCode } from "@/types/accounting";

let cached: Promise<AtcCode[]> | null = null;

function loadCodes(): Promise<AtcCode[]> {
  cached ??= accountingApi.atcCodes().catch((e) => {
    cached = null; // try again next time a picker mounts
    throw e;
  });
  return cached;
}

function percent(rate: string): string {
  return `${Number((Number(rate) * 100).toFixed(2))}%`;
}

function codeLabel(c: AtcCode): string {
  const payee = c.code.startsWith("WC") ? "corporate" : "individual";
  return `${c.code} ${c.nature}, ${payee} (${percent(c.rate)})`;
}

interface Option {
  value: string;
  label: string;
  group: string; // "" = top of the list, no heading
}

interface Props {
  value: string;
  onChange: (value: string) => void;
  /** Label of the "" choice ("Suggested (WC100)", "Any", …). */
  blank: string;
  disabled?: boolean;
  /** Classes for the closed box (the panel's usual input style). */
  className: string;
  ariaLabel?: string;
}

const MENU_WIDTH = 560;
const MENU_HEIGHT = 380; // search box + ten rows

/** ATC dropdown with a search box: the blank choice, "No withholding", the common ATCs, then every other one the
 * backend knows, about ten rows at a time. A saved code that isn't listed still shows. */
export default function AtcPicker({ value, onChange, blank, disabled, className, ariaLabel = "ATC" }: Props) {
  const [codes, setCodes] = useState<AtcCode[]>([]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [pos, setPos] = useState<{ left: number; top: number; width: number; up: boolean } | null>(null);
  const boxRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    let cancelled = false;
    loadCodes().then((c) => !cancelled && setCodes(c)).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const options = useMemo<Option[]>(() => {
    const common = new Set(COMMON_ATCS.map((o) => o.value));
    const out: Option[] = [
      { value: "", label: blank, group: "" },
      { value: "NONE", label: "No withholding", group: "" },
      ...COMMON_ATCS.map((o) => ({ ...o, group: "Common" })),
      ...codes.filter((c) => !common.has(c.code)).map((c) => ({ value: c.code, label: codeLabel(c), group: "All other ATCs" })),
    ];
    if (value && !out.some((o) => o.value === value)) out.push({ value, label: value, group: "" });
    return out;
  }, [codes, blank, value]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    const words = q.split(/\s+/);
    return options.filter((o) => o.value && words.every((w) => o.label.toLowerCase().includes(w)));
  }, [options, query]);

  const selected = options.find((o) => o.value === value) ?? options[0];

  function place() {
    const r = boxRef.current?.getBoundingClientRect();
    if (!r) return;
    const width = Math.min(Math.max(r.width, MENU_WIDTH), window.innerWidth - 16);
    const left = Math.min(Math.max(8, r.left), window.innerWidth - width - 8);
    const up = window.innerHeight - r.bottom < MENU_HEIGHT && r.top > window.innerHeight - r.bottom;
    setPos({ left, width, up, top: up ? r.top - 4 : r.bottom + 4 });
  }

  function openMenu() {
    if (disabled) return;
    place();
    setQuery("");
    setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen(true);
  }

  function choose(v: string) {
    setOpen(false);
    boxRef.current?.focus();
    if (v !== value) onChange(v);
  }

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!menuRef.current?.contains(t) && !boxRef.current?.contains(t)) setOpen(false);
    };
    const onMove = (e: Event) => {
      if (!menuRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onMove, true);
    window.addEventListener("resize", onMove);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
    };
  }, [open]);

  useLayoutEffect(() => {
    if (!open) return;
    listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [open, active, shown]);

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => Math.min(Math.max(i + step, 0), shown.length - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (shown[active]) choose(shown[active].value);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      boxRef.current?.focus();
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <>
      <button
        ref={boxRef}
        type="button"
        disabled={disabled}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : openMenu())}
        onKeyDown={(e) => {
          if (!open && (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            openMenu();
          }
        }}
        className={`${className} flex items-center gap-2 text-left`}
      >
        <span className="min-w-0 flex-1 truncate">{selected.label}</span>
        <CaretDown size={12} className="shrink-0 text-[var(--text-secondary)]" />
      </button>
      {open && pos && (
        <Portal>
          <div
            ref={menuRef}
            onKeyDown={onKey}
            style={{ left: pos.left, width: pos.width, ...(pos.up ? { bottom: window.innerHeight - pos.top } : { top: pos.top }) }}
            className="fixed z-[80] overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] shadow-xl"
          >
            <label className="relative block border-b border-[var(--border)]">
              <span className="sr-only">Search ATCs</span>
              <MagnifyingGlass size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
              <input
                autoFocus
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setActive(0);
                }}
                placeholder="Search code or description"
                className="w-full bg-transparent py-2 pl-8 pr-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none"
              />
            </label>
            <ul ref={listRef} role="listbox" aria-label={ariaLabel} className="max-h-80 overflow-y-auto py-1">
              {shown.map((o, i) => (
                <li key={o.value || "blank"}>
                  {o.group && o.group !== shown[i - 1]?.group && (
                    <div className="px-3 pb-0.5 pt-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-tertiary)]">{o.group}</div>
                  )}
                  <button
                    type="button"
                    role="option"
                    data-index={i}
                    aria-selected={o.value === value}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => choose(o.value)}
                    className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm leading-snug text-[var(--text-primary)] ${i === active ? "bg-[var(--bg-hover)]" : ""}`}
                  >
                    <span className="min-w-0 flex-1">{o.label}</span>
                    {o.value === value && <Check size={14} weight="bold" className="shrink-0 text-[var(--accent)]" />}
                  </button>
                </li>
              ))}
              {shown.length === 0 && (
                <li className="px-3 py-6 text-center text-sm text-[var(--text-secondary)]">No ATC matches &ldquo;{query}&rdquo;.</li>
              )}
            </ul>
          </div>
        </Portal>
      )}
    </>
  );
}
