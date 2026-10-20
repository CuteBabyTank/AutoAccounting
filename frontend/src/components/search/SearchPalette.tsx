"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { usePathname, useRouter } from "next/navigation";
import { MagnifyingGlass, Spinner, X } from "@phosphor-icons/react";
import { SearchRow } from "@/components/search/SearchResults";
import { searchApi } from "@/lib/search-api";
import { TYPE_LABELS, openResult } from "@/lib/search-nav";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { SearchItem, SearchResponse } from "@/types/search";

const DEBOUNCE_MS = 250;

interface Props {
  /** "rail": a sidebar row (label fades in with the rail); "bar": the mobile top bar icon. */
  variant: "rail" | "bar";
  fadeStyle?: CSSProperties;
}

/** True while the person is typing somewhere: "/" then types a slash instead of opening search. */
function typingIn(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

/** Global search in the app shell: "/" or Cmd/Ctrl-K, type-ahead grouped by type, arrow keys + Enter. */
export default function SearchPalette({ variant, fadeStyle }: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [review, setReview] = useState(false);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [active, setActive] = useState(0);
  const router = useRouter();
  const pathname = usePathname();
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);

  // Both palettes are mounted (rail at md+, mobile bar below); only the one for this screen width owns the shortcut.
  useEffect(() => {
    const wide = window.matchMedia("(min-width: 768px)");
    const onKey = (e: KeyboardEvent) => {
      if (wide.matches !== (variant === "rail")) return;
      const k = e.key.toLowerCase();
      if ((e.metaKey || e.ctrlKey) && k === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey && !typingIn(e.target)) {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [variant]);

  useEffect(() => {
    if (open) setTimeout(() => input.current?.focus(), 0);
  }, [open]);

  // Debounced type-ahead; a newer keystroke aborts the older request so stale results never land.
  useEffect(() => {
    if (!open) return;
    const q = text.trim();
    if (!review && q.length < 2) {
      setData(null);
      setLoading(false);
      return;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      setError("");
      searchApi
        .search({ q, review, limit: 5 }, ctrl.signal)
        .then((r) => {
          setData(r);
          setActive(0);
        })
        .catch((e) => {
          if (!ctrl.signal.aborted) setError(apiErrorMessage(e, "Search failed"));
        })
        .finally(() => !ctrl.signal.aborted && setLoading(false));
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [text, review, open]);

  const flat = useMemo(() => (data?.groups ?? []).flatMap((g) => g.items), [data]);

  const close = useCallback(() => setOpen(false), []);

  const go = useCallback(
    (item: SearchItem) => {
      setOpen(false);
      openResult(item, pathname, (href) => router.push(href));
    },
    [pathname, router],
  );

  const seeAll = useCallback(() => {
    setOpen(false);
    const p = new URLSearchParams();
    if (text.trim()) p.set("q", text.trim());
    if (review) p.set("review", "1");
    router.push(`/accounting/search${p.toString() ? `?${p}` : ""}`);
  }, [text, review, router]);

  useEffect(() => {
    list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => (flat.length ? (i + 1) % flat.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (flat.length ? (i - 1 + flat.length) % flat.length : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (flat[active]) go(flat[active]);
      else seeAll();
    }
  }

  const button =
    variant === "rail" ? (
      <button
        onClick={() => setOpen(true)}
        data-tour="search"
        aria-label="Search (press / or Ctrl K)"
        title="Search (/ or Ctrl K)"
        className="aa-item nav-press flex items-center gap-3 w-full h-10 px-3 rounded-xl text-sm whitespace-nowrap overflow-hidden text-[var(--text-sidebar-muted)] hover:text-[var(--text-sidebar)]"
      >
        <MagnifyingGlass size={20} weight="light" className="shrink-0" />
        <span style={fadeStyle} className="aa-fade flex flex-1 items-center justify-between">
          Search
          <kbd className="rounded border border-[var(--border-sidebar)] px-1.5 text-[10px] text-[var(--text-sidebar-muted)]">/</kbd>
        </span>
      </button>
    ) : (
      <button
        onClick={() => setOpen(true)}
        data-tour="search"
        aria-label="Search"
        className="nav-press ml-auto flex items-center justify-center w-11 h-11 rounded-lg text-[var(--text-sidebar)] hover:bg-[var(--bg-sidebar-hover)]"
      >
        <MagnifyingGlass size={22} />
      </button>
    );

  let index = -1;
  return (
    <>
      {button}
      {open &&
        createPortal(
          <div className="lp-skin fixed inset-0 z-[60] bg-black/30" onClick={close}>
            <div
              role="dialog"
              aria-label="Search"
              onClick={(e) => e.stopPropagation()}
              onKeyDown={onKeyDown}
              className="modal-enter fixed inset-x-3 top-16 mx-auto flex max-h-[75vh] max-w-2xl flex-col rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] shadow-xl md:top-24"
            >
              <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-3">
                <MagnifyingGlass size={18} className="shrink-0 text-[var(--text-secondary)]" />
                <input
                  ref={input}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  maxLength={200}
                  role="combobox"
                  aria-expanded={flat.length > 0}
                  aria-controls="aa-search-results"
                  aria-activedescendant={flat[active] ? `aa-search-${active}` : undefined}
                  placeholder="Number, supplier, TIN, ₱ amount, date, review reason…"
                  className="min-w-0 flex-1 bg-transparent text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none"
                />
                {loading && <Spinner size={16} className="animate-spin text-[var(--text-secondary)]" />}
                <button onClick={close} aria-label="Close search" className="rounded p-1 hover:bg-[var(--bg-hover)]">
                  <X size={16} />
                </button>
              </div>
              <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-2">
                <button
                  onClick={() => setReview((r) => !r)}
                  aria-pressed={review}
                  className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${review ? "border-[var(--accent)] bg-[var(--accent-subtle)] text-[var(--text-primary)]" : "border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"}`}
                >
                  Review queue
                </button>
                <span className="text-xs text-[var(--text-secondary)]">
                  {review ? "Documents still needing review" : "Everything in your firm"}
                </span>
              </div>
              <div className="overflow-y-auto py-1">
                {error ? (
                  <p className="px-4 py-6 text-sm text-[var(--alert-error-text)]">{error}</p>
                ) : !review && text.trim().length < 2 ? (
                  <p className="px-4 py-6 text-sm text-[var(--text-secondary)]">
                    Type at least two characters. Try a document number, a supplier, a TIN, ₱1,500 or Oct 15, 2026.
                  </p>
                ) : data && data.groups.length === 0 && !loading ? (
                  <p className="px-4 py-6 text-sm text-[var(--text-secondary)]">No matches.</p>
                ) : (
                  <ul id="aa-search-results" ref={list} role="listbox" aria-label="Search results">
                    {(data?.groups ?? []).map((g) => (
                      <li key={g.type} role="presentation">
                        <p className="px-4 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
                          {TYPE_LABELS[g.type]}
                        </p>
                        <ul role="presentation" className="px-1">
                          {g.items.map((item) => {
                            index += 1;
                            const i = index;
                            return (
                              <li key={`${item.type}-${item.id}`} id={`aa-search-${i}`} data-index={i} role="option" aria-selected={i === active}>
                                <button className="w-full" onMouseMove={() => setActive(i)} onClick={() => go(item)}>
                                  <SearchRow item={item} active={i === active} />
                                </button>
                              </li>
                            );
                          })}
                        </ul>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="flex items-center gap-3 border-t border-[var(--border)] px-4 py-2 text-xs text-[var(--text-secondary)]">
                <span className="hidden sm:inline">↑↓ to move · Enter to open · Esc to close</span>
                <button onClick={seeAll} className="ml-auto font-medium text-[var(--accent)] hover:underline">
                  See all results and filters
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
