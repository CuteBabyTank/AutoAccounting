"use client";

import { Bank, Buildings, CheckSquare, FileText, Notebook, UserCircle } from "@phosphor-icons/react";
import { formatAmount } from "@/lib/accounting-format";
import type { SearchItem, SearchType } from "@/types/search";

export const TYPE_ICONS: Record<SearchType, typeof FileText> = {
  document: FileText,
  contact: UserCircle,
  bank_line: Bank,
  journal_entry: Notebook,
  task: CheckSquare,
  company: Buildings,
};

const MATCH_LABELS: Record<string, string> = {
  number: "Number",
  name: "Name",
  tin: "TIN",
  amount: "Amount",
  date: "Date",
  reason: "Review reason",
  narration: "Narration",
  reference: "Reference",
  memo: "Memo",
  title: "Title",
};

const CHIP = "rounded-full px-1.5 text-[10px] font-semibold";

function shortDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" });
}

/** One result line: icon, title, context, chips, date and amount. Shared by the palette and the results page. */
export function SearchRow({ item, active }: { item: SearchItem; active?: boolean }) {
  const Icon = TYPE_ICONS[item.type];
  return (
    <span className={`flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left ${active ? "bg-[var(--accent-subtle)]" : ""}`}>
      <Icon size={18} weight="light" className="mt-0.5 shrink-0 text-[var(--text-secondary)]" />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium text-[var(--text-primary)]">{item.title}</span>
          {item.needs_review && (
            <span className={`${CHIP} bg-[var(--alert-warning-bg)] text-[var(--alert-warning-text)]`}>Needs review</span>
          )}
          {item.excluded && <span className={`${CHIP} bg-[var(--bg-hover)] text-[var(--text-secondary)]`}>Excluded</span>}
        </span>
        <span className="block truncate text-xs text-[var(--text-secondary)]">
          {item.subtitle}
          {item.matched.length > 0 && (
            <span> · matched {item.matched.map((m) => MATCH_LABELS[m] ?? m).join(", ").toLowerCase()}</span>
          )}
        </span>
      </span>
      <span className="shrink-0 text-right text-xs text-[var(--text-secondary)]">
        {item.amount !== null && <span className="block font-medium tabular-nums text-[var(--text-primary)]">₱{formatAmount(item.amount)}</span>}
        <span className="block">{shortDate(item.date)}</span>
      </span>
    </span>
  );
}
