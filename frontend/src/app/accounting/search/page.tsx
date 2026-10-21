"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { MagnifyingGlass, Spinner } from "@phosphor-icons/react";
import Hint from "@/components/guide/Hint";
import { SearchRow } from "@/components/search/SearchResults";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import { searchApi } from "@/lib/search-api";
import { TYPE_LABELS, openResult } from "@/lib/search-nav";
import { safeId } from "@/lib/work-api";
import type { Company } from "@/types/accounting";
import type { SearchResponse, SearchType } from "@/types/search";

const TYPES = Object.keys(TYPE_LABELS) as SearchType[];
const ISO = /^\d{4}-\d{2}-\d{2}$/;
const INPUT =
  "rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const CHIP = "rounded-full border px-2.5 py-1 text-xs font-medium";

/** Full search results with filters: type, company, date range and the review queue. */
export default function SearchPage() {
  const router = useRouter();
  const pathname = usePathname();
  const [text, setText] = useState("");
  const [type, setType] = useState<SearchType | "">("");
  const [company, setCompany] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [review, setReview] = useState(false);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    setText((p.get("q") ?? "").slice(0, 200));
    setReview(p.get("review") === "1");
    const t = p.get("type");
    if (t && (TYPES as string[]).includes(t)) setType(t as SearchType);
    setCompany(safeId(p.get("company")) ?? "");
    setReady(true);
    accountingApi.listCompanies().then(setCompanies).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!ready) return;
    const q = text.trim();
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (review) p.set("review", "1");
    if (type) p.set("type", type);
    if (company) p.set("company", company);
    window.history.replaceState(null, "", `/accounting/search${p.toString() ? `?${p}` : ""}`);
    if (!review && q.length < 2) {
      setData(null);
      return;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      setError("");
      searchApi
        .search(
          {
            q,
            review,
            limit: 25,
            types: type || undefined,
            company_id: company || undefined,
            date_from: ISO.test(from) ? from : undefined,
            date_to: ISO.test(to) ? to : undefined,
          },
          ctrl.signal,
        )
        .then(setData)
        .catch((e) => !ctrl.signal.aborted && setError(apiErrorMessage(e, "Search failed")))
        .finally(() => !ctrl.signal.aborted && setLoading(false));
    }, 250);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [ready, text, type, company, from, to, review]);

  const dated = Boolean(from || to);

  return (
    <div className="lp relative min-h-screen">
      <div className="p-4 sm:p-8 page-enter">
        <div className="mb-6 flex items-center gap-2">
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Search</h1>
          <Hint align="right">
            Searches every client of your firm: document numbers, supplier and customer names, TINs in any format,
            amounts (1500, 1,500.00 or ₱1,500), dates (10/15/2026, Oct 15, 2026 or Oct 2026) and review reasons
            (&quot;duplicate&quot;, &quot;EWT expected&quot;). Press / or Ctrl K anywhere to search without leaving the page.
          </Hint>
        </div>

        <div className="mb-4 rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
          <label className="relative block">
            <span className="sr-only">Search</span>
            <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
            <input
              autoFocus
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={200}
              placeholder="Number, supplier, TIN, ₱ amount, date, review reason…"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] py-2 pl-9 pr-3 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
            />
          </label>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              onClick={() => setReview((r) => !r)}
              aria-pressed={review}
              className={`${CHIP} ${review ? "border-[var(--accent)] bg-[var(--accent-subtle)] text-[var(--text-primary)]" : "border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"}`}
            >
              Review queue
            </button>
            <span className="mx-1 h-4 w-px bg-[var(--border)]" aria-hidden="true" />
            {(["", ...TYPES] as (SearchType | "")[]).map((t) => (
              <button
                key={t || "all"}
                onClick={() => setType(t)}
                aria-pressed={type === t}
                disabled={review && t !== "" && t !== "document"}
                className={`${CHIP} disabled:opacity-40 ${type === t ? "border-[var(--accent)] bg-[var(--accent-subtle)] text-[var(--text-primary)]" : "border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"}`}
              >
                {t ? TYPE_LABELS[t] : "All"}
              </button>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-end gap-3 text-xs text-[var(--text-secondary)]">
            <label className="flex flex-col gap-1">
              Company
              <select value={company} onChange={(e) => setCompany(e.target.value)} className={`${INPUT} max-w-[16rem]`}>
                <option value="">All companies</option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.registered_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              From
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={INPUT} />
            </label>
            <label className="flex flex-col gap-1">
              To
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className={INPUT} />
            </label>
            {(dated || company || type || review) && (
              <button
                onClick={() => {
                  setFrom("");
                  setTo("");
                  setCompany("");
                  setType("");
                  setReview(false);
                }}
                className="pb-2 font-medium text-[var(--accent)] hover:underline"
              >
                Clear filters
              </button>
            )}
          </div>
          {dated && !review && (
            <p className="mt-2 text-xs text-[var(--text-secondary)]">
              With dates set, customers, suppliers and companies are hidden (they have no date).
            </p>
          )}
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-[var(--alert-error-border)] bg-[var(--alert-error-bg)] px-4 py-2 text-sm text-[var(--alert-error-text)]">
            {error}
          </div>
        )}

        <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-2">
          {loading && !data ? (
            <p className="flex items-center gap-2 px-3 py-6 text-sm text-[var(--text-secondary)]">
              <Spinner size={16} className="animate-spin" /> Searching…
            </p>
          ) : !review && text.trim().length < 2 ? (
            <p className="px-3 py-6 text-sm text-[var(--text-secondary)]">
              Type at least two characters, or turn on Review queue to see every document still needing review.
            </p>
          ) : data && data.groups.length === 0 ? (
            <p className="px-3 py-6 text-sm text-[var(--text-secondary)]">No matches.</p>
          ) : (
            (data?.groups ?? []).map((g) => (
              <div key={g.type} className="mb-2">
                <p className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
                  {TYPE_LABELS[g.type]}
                </p>
                <ul>
                  {g.items.map((item) => (
                    <li key={`${item.type}-${item.id}`}>
                      <button
                        className="w-full rounded-lg hover:bg-[var(--bg-hover)]"
                        onClick={() => openResult(item, pathname, (href) => router.push(href))}
                      >
                        <SearchRow item={item} />
                      </button>
                    </li>
                  ))}
                </ul>
                {g.more && (
                  <p className="px-3 py-1 text-xs text-[var(--text-secondary)]">
                    More {TYPE_LABELS[g.type].toLowerCase()} match. Narrow the search or add a filter.
                  </p>
                )}
              </div>
            ))
          )}
        </section>
      </div>
    </div>
  );
}
