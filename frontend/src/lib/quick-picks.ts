// Phrases people type again and again (review reasons, task titles…): per viewer, kept in localStorage (best effort).
const PREFIX = "aa:quick:";
const MAX = 12;

export function loadPicks(kind: string): string[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(PREFIX + kind) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string").slice(0, MAX) : [];
  } catch {
    return [];
  }
}

function store(kind: string, picks: string[]) {
  try {
    window.localStorage.setItem(PREFIX + kind, JSON.stringify(picks.slice(0, MAX)));
  } catch {
    /* Picks still work for this visit. */
  }
}

/** Newest first; a phrase already saved (any case) moves to the front instead of doubling. */
export function savePick(kind: string, text: string): string[] {
  const value = text.trim();
  const rest = loadPicks(kind).filter((p) => p.toLowerCase() !== value.toLowerCase());
  const next = value ? [value, ...rest] : rest;
  store(kind, next);
  return next.slice(0, MAX);
}

export function removePick(kind: string, text: string): string[] {
  const next = loadPicks(kind).filter((p) => p !== text);
  store(kind, next);
  return next;
}

/** Built-in phrases per field; the person's own saved ones show first. */
export const PRESETS = {
  review: ["Checked against the original", "Client confirmed", "Verified with supplier", "Amounts match the receipt"],
  exclude: ["Owner's personal purchase", "Not a business expense", "Duplicate copy", "Belongs to another client"],
  bulk: ["Checked against the originals", "Client confirmed", "Known supplier, details OK"],
  close: ["Statement not yet received from client", "Reconciling items carried to next month", "Bank lines checked by hand"],
  reopen: ["Late document received", "Correcting a posting error", "Client sent adjustments"],
  reclassify: ["Wrong account picked at extraction", "Client clarified the expense", "Year-end cleanup"],
  task: [
    "Ask client for the bank statement",
    "Collect 2307s from customers",
    "Ask client for missing receipts",
    "Get payroll register for the month",
    "Send return to client for signing",
  ],
  particulars: ["Monthly depreciation", "Accrued expenses", "Prepaid expense amortization", "Bank charges", "Correction of prior entry"],
} as const;
