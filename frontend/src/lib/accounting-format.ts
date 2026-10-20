import type { AxiosError } from "axios";
import type { AADocument } from "@/types/accounting";

export const CATEGORY_LABELS: Record<string, string> = {
  sales: "Sales",
  purchases: "Purchases",
  expenses: "Expenses",
  payroll: "Payroll",
  "2307": "2307s",
  support: "Supporting papers",
  unsorted: "Unsorted",
  review: "Review queue",
};

export const ACCOUNT_LABELS: Record<string, string> = {
  sales: "Sales",
  purchases: "Purchases (goods for resale)",
  raw_materials: "Raw materials",
  importation: "Importation",
  capital_goods: "Capital goods",
  salaries: "Salaries and wages",
  rent: "Rent",
  utilities: "Utilities",
  professional_fees: "Professional fees",
  office_supplies: "Office supplies",
  representation: "Representation / entertainment",
  transportation: "Transportation",
  repairs: "Repairs and maintenance",
  taxes_licenses: "Taxes and licenses",
  "2307_received": "2307 received",
  "2307_issued": "2307 issued",
  other: "Other",
};

export const ACCOUNTS = Object.keys(ACCOUNT_LABELS);

export const REASON_LABELS: Record<string, string> = {
  low_confidence: "Low extraction confidence. Check the amounts and date.",
  missing_date: "No readable date, so it can't be filed in a quarter.",
  missing_amount: "No total amount was found.",
  unsorted: "Couldn't tell what kind of document this is.",
  not_addressed_to_client: "Not addressed to the company's name or TIN, so no input VAT.",
  seller_not_vat_registered: "Seller isn't shown as VAT-registered, so no input VAT.",
  not_an_invoice: "Not an invoice. Receipts don't support input VAT.",
  vat_math_mismatch: "VAT isn't 12% of the VATable amount. Input VAT is claimed at 12% and the excess goes to VAT difference - for review.",
  amounts_dont_add_up: "VATable, VAT, exempt and zero-rated amounts don't add up to the total. Check them against the page.",
  possible_duplicate: "Possible duplicate of a document already filed.",
  other_company_tin: "Shows another company's TIN from your databank.",
  nothing_extracted: "Nothing could be read from these pages.",
  possible_payment: "Looks like a payment receipt for one of several invoices. Choose the invoice it pays.",
  supplier_rule_mismatch: "This supplier's remembered account doesn't fit this document (goods vs services), so it wasn't applied. Check the account.",
  tendered_less_than_total: "Cash tendered is less than the total (negative change). The total is posted. Ask whether there was another payment or the receipt was altered.",
  ewt_expected: "The company withholds tax, but this bill for professional fees or rent shows no EWT.",
  payment_source_unknown: "Marked paid or released, but nothing shows where the money came from. Ask the client.",
  payment_unverified: "On credit terms and no payment is linked yet.",
  duplicate_invoice_number: "This supplier used the same invoice number on another document with a different date.",
  account_locked: "Its account is locked in the chart of accounts. Choose another account, or unlock the account if this posting is right.",
  receipt_incomplete: "May not be a valid BIR invoice or receipt, so the expense could be disallowed. Ask the supplier for a proper invoice, or type in what's printed if it was misread.",
  personal_purchase: "Made out to the owner personally, so it was excluded from the books. If the company paid for it, record it as drawings.",
};

/** Reasons shown as a note only: they never put a document in the review queue or block a month close. */
export const SOFT_REASONS = new Set(["payment_unverified"]);

/** The extra detail a reason carries (suggested ATC, recomputed VAT, cash tendered), or "". */
export function reasonDetail(reason: string, notes?: Record<string, Record<string, string>>): string {
  const n = notes?.[reason];
  if (!n) return "";
  if (reason === "ewt_expected") return `Suggested ${n.atc} at ${n.rate}% of ₱${formatPeso(n.base)}: ₱${formatPeso(n.amount)}.`;
  if (reason === "vat_math_mismatch")
    return `12% is ₱${formatPeso(n.expected)}; difference ₱${formatPeso(n.difference)}.${
      n.legacy === "filed" ? " Input VAT stays disallowed on this one: its quarter's return was filed before the VAT-difference rule." : ""
    }`;
  if (reason === "receipt_incomplete") {
    const r = n as unknown as { missing?: string[]; not_bir?: string };
    const parts = [r?.not_bir ? `${r.not_bir}, not an invoice.` : "", r?.missing?.length ? `No ${r.missing.join(", ")}.` : ""];
    return parts.filter(Boolean).join(" ");
  }
  if (reason === "tendered_less_than_total") return `Tendered ₱${formatPeso(n.tendered)} on a total of ₱${formatPeso(n.total)}.`;
  return "";
}

export const BOOK_LABELS: Record<string, string> = {
  SJ: "Sales Journal",
  PJ: "Purchase Journal",
  CRJ: "Cash Receipts Journal",
  CDJ: "Cash Disbursements Journal",
  GJ: "General Journal",
  GL: "General Ledger",
};

/** "010-234-567", or with the branch code as printed: ("010234567", "000") → "010-234-567-000". */
export function formatTin(tin: string, branch = ""): string {
  const d = (tin || "").replace(/\D/g, "");
  return d.length >= 9 ? `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6, 9)}${branch ? `-${branch}` : ""}` : d;
}

/** The branch code digits typed after the 9-digit TIN ("010-234-567-000" → "000"). */
export function tinBranch(text: string): string {
  const digits = text.replace(/\D/g, "");
  return digits.length > 9 ? digits.slice(9, 14) : "";
}

export function formatPeso(value: string | number): string {
  const n = Number(value);
  return Number.isFinite(n)
    ? n.toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "0.00";
}

export function counterpartyName(doc: AADocument): string {
  return doc.client_role === "seller" ? doc.buyer_name : doc.seller_name;
}

export function apiErrorMessage(e: unknown, fallback = "Something went wrong"): string {
  const detail = (e as AxiosError<{ detail?: unknown }>)?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg.replace(/^Value error, /, "");
  }
  return fallback;
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Money for display: thousands separators, negatives in parentheses like the BIR forms. */
export function formatAmount(value: string, whole = false): string {
  const n = Number(value);
  if (value === "" || !Number.isFinite(n)) return value;
  const digits = whole ? 0 : 2;
  const text = Math.abs(n).toLocaleString("en-PH", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return n < 0 ? `(${text})` : text;
}

/** Pastel yellow used for "changed since the previous version" everywhere. */
export const CHANGED_STYLE = { backgroundColor: "#FFF4B3", color: "#1F1F1F" } as const;

/** The ATCs most payments use, listed first in every ATC picker (`AtcPicker` adds the rest from the backend). */
export const COMMON_ATCS: { value: string; label: string }[] = [
  { value: "WI010", label: "WI010 Professional fees, individual ≤ ₱3M (5%)" },
  { value: "WI011", label: "WI011 Professional fees, individual > ₱3M or VAT-registered (10%)" },
  { value: "WC010", label: "WC010 Professional fees, corporate ≤ ₱720k (10%)" },
  { value: "WC011", label: "WC011 Professional fees, corporate > ₱720k (15%)" },
  { value: "WI100", label: "WI100 Rentals, individual (5%)" },
  { value: "WC100", label: "WC100 Rentals, corporate (5%)" },
  { value: "WI120", label: "WI120 Contractors, individual (2%)" },
  { value: "WC120", label: "WC120 Contractors, corporate (2%)" },
  { value: "WI158", label: "WI158 Goods from a Top Withholding Agent, individual (1%)" },
  { value: "WC158", label: "WC158 Goods from a Top Withholding Agent, corporate (1%)" },
  { value: "WI160", label: "WI160 Services from a Top Withholding Agent, individual (2%)" },
  { value: "WC160", label: "WC160 Services from a Top Withholding Agent, corporate (2%)" },
];
