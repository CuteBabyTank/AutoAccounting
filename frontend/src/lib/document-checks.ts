/** Live checks on a document's edit form: which fields are blank (orange) or don't add up (red), mirroring the
 *  backend's review rules (`classify._vat_math_mismatch`, `_amounts_dont_add_up`, `review_rules.receipt_problems`)
 *  so a box is coloured for the same reason the document was queued. Pure; no React. */

export type CheckLevel = "error" | "warn";
export interface FieldCheck {
  level: CheckLevel;
  message: string;
}
export type FieldChecks = Partial<Record<string, FieldCheck>>;

/** What the checks need beyond the draft: the stored document's fixed facts. */
export interface CheckContext {
  client_role: "seller" | "buyer";
  doc_type: string;
  /** Today in YYYY-MM-DD (passed in so the checks stay pure). */
  today: string;
}

const VAT_RATE = 0.12;
const TOLERANCE = 1; // ₱1, as the backend's _VAT_TOLERANCE
const BILLS = new Set(["purchases", "expenses"]);
const TRANSACTIONS = new Set(["sales", "purchases", "expenses"]);
const RECEIPT_KINDS = new Set(["invoice", "receipt"]);
// Same words as review_rules._GOVERNMENT: government ORs need only a serial number.
const GOVERNMENT =
  /\b(GOVERNMENT|GOV'?T|CITY OF|MUNICIPALITY|MUNICIPAL|PROVINCE OF|PROVINCIAL|BARANGAY|BUREAU|DEPARTMENT OF|TREASURER|REPUBLIC OF THE PHILIPPINES|SOCIAL SECURITY SYSTEM|SSS|PHILHEALTH|PAG-?IBIG|HDMF|LAND TRANSPORTATION|LTO|LTFRB|BIR)\b/;

const peso = (n: number) => n.toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const blank = (v: string | undefined) => !(v ?? "").trim();

/** A typed amount: 0 when blank, NaN when it isn't a number. */
function amount(v: string | undefined): number {
  const s = (v ?? "").replace(/,/g, "").trim();
  return s === "" ? 0 : /^-?\d+(\.\d*)?$|^-?\.\d+$/.test(s) ? Number(s) : NaN;
}

function tinProblem(v: string): string | null {
  const s = v.trim();
  if (!s) return null;
  if (/[^\d\s-]/.test(s)) return "A TIN has digits only";
  const n = s.replace(/\D/g, "").length;
  if (n < 9) return "A TIN has 9 digits (plus a 3–5 digit branch code)";
  if (n > 14) return "Too many digits for a TIN and branch code";
  if (n > 9 && n < 12) return "The branch code after the TIN has 3–5 digits";
  return null;
}

export function checkDocument(d: Record<string, string>, ctx: CheckContext): FieldChecks {
  const out: FieldChecks = {};
  const set = (key: string, level: CheckLevel, message: string) => {
    // A red finding beats an orange one on the same box.
    if (!out[key] || (out[key]!.level === "warn" && level === "error")) out[key] = { level, message };
  };
  const category = d.category ?? "";
  const transaction = TRANSACTIONS.has(category);
  const bill = BILLS.has(category) && ctx.client_role === "buyer";

  // Amounts: numbers, not negative, withholding within the total.
  const keys = ["gross_amount", "vatable_amount", "vat_amount", "exempt_amount", "zero_rated_amount", "withholding_amount"];
  const a: Record<string, number> = {};
  for (const k of keys) {
    a[k] = amount(d[k]);
    if (Number.isNaN(a[k])) set(k, "error", "Not a number");
    else if (a[k] < 0) set(k, "error", "Can't be negative");
  }
  const ok = (...ks: string[]) => ks.every((k) => !Number.isNaN(a[k]));
  const gross = a.gross_amount;

  if (transaction && ok("gross_amount") && gross === 0) set("gross_amount", "warn", "Total is blank");

  // VAT = 12% of the VATable base (derived from the total when only the VAT is printed).
  if (ok("gross_amount", "vatable_amount", "vat_amount", "exempt_amount", "zero_rated_amount")) {
    const derived = gross - a.vat_amount - a.exempt_amount - a.zero_rated_amount;
    const vatable = a.vatable_amount > 0 || a.vat_amount <= 0 ? a.vatable_amount : Math.max(derived, 0);
    if (a.vat_amount > 0 && Math.abs(vatable * VAT_RATE - a.vat_amount) > TOLERANCE) {
      set("vat_amount", "error", `12% of ₱${peso(vatable)} is ₱${peso(vatable * VAT_RATE)}`);
    }
    if (a.vatable_amount > 0 && a.vat_amount === 0 && transaction) {
      set("vat_amount", "warn", `VAT is blank; 12% would be ₱${peso(a.vatable_amount * VAT_RATE)}`);
    }
    // The parts should add up to the total (imports build their total differently).
    const parts = vatable + a.vat_amount + a.exempt_amount + a.zero_rated_amount;
    if (ctx.doc_type !== "import" && parts > 0 && gross !== 0 && Math.abs(parts - gross) > TOLERANCE) {
      set("gross_amount", "error", `VATable + VAT + exempt + zero-rated = ₱${peso(parts)}`);
    }
  }
  if (ok("gross_amount", "withholding_amount") && a.withholding_amount > 0 && gross > 0 && a.withholding_amount >= gross) {
    set("withholding_amount", "error", "More than the total");
  }

  // Dates.
  if (transaction && blank(d.doc_date)) set("doc_date", "warn", "Date is blank");
  else if (d.doc_date && d.doc_date > ctx.today) set("doc_date", "error", "Date is in the future");
  if (d.paid_on && d.doc_date && d.paid_on < d.doc_date) set("paid_on", "warn", "Before the document date");
  if (d.paid_on && d.paid_on > ctx.today) set("paid_on", "error", "Date is in the future");
  if (d.paid_via && blank(d.paid_on)) set("paid_on", "warn", "Payment date is blank");

  // TINs.
  for (const k of ["seller_tin", "buyer_tin"]) {
    const p = tinProblem(d[k] ?? "");
    if (p) set(k, "error", p);
  }

  // A supplier's invoice / receipt must show who issued it (RR 7-2024); a sale must show the client's TIN.
  if (bill && RECEIPT_KINDS.has(ctx.doc_type)) {
    const gov = GOVERNMENT.test((d.seller_name ?? "").toUpperCase());
    if (blank(d.doc_number)) set("doc_number", "warn", "Serial number is blank");
    if (!gov) {
      if (blank(d.seller_name)) set("seller_name", "warn", "Seller is blank");
      if (blank(d.seller_tin)) set("seller_tin", "warn", "Seller TIN is blank");
      if (blank(d.seller_address)) set("seller_address", "warn", "Seller address is blank");
    }
  } else if (bill) {
    if (blank(d.seller_name)) set("seller_name", "warn", "Seller is blank");
  }
  if (category === "sales" && ctx.client_role === "seller") {
    if (blank(d.doc_number)) set("doc_number", "warn", "Invoice number is blank");
    if (blank(d.buyer_name)) set("buyer_name", "warn", "Buyer is blank");
  }
  return out;
}
