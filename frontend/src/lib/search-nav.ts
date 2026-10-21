// Where a search result opens, and the deep-link params the Documents page reads (?company=&view=&doc=…).
import { safeId } from "@/lib/work-api";
import type { FolderRef } from "@/types/accounting";
import type { SearchItem, SearchType } from "@/types/search";

/** The Documents page listens for this (detail = a query string) to open a target without a reload. */
export const OPEN_TARGET_EVENT = "aa:open-target";

export const TYPE_LABELS: Record<SearchType, string> = {
  document: "Documents",
  contact: "Customers and suppliers",
  bank_line: "Bank lines",
  journal_entry: "Journal entries",
  task: "Tasks",
  company: "Companies",
};

const VIEWS = new Set<NonNullable<FolderRef["view"]>>([
  "books", "atc", "employees", "audit", "bank", "customers", "suppliers", "overview", "reports", "reclassify", "import",
]);

export interface Target {
  ref: FolderRef | null;
  docId: string | null;
  contactId: string | null;
}

function intIn(value: string | null, re: RegExp, lo: number, hi: number): number | null {
  if (!value || !re.test(value)) return null;
  const n = Number(value);
  return n >= lo && n <= hi ? n : null;
}

/** Read a deep link. Ids must be UUIDs, the view one we know, account codes / months in their shapes; anything
 *  else is dropped (the panels then load through the firm-scoped API). */
export function parseTarget(params: URLSearchParams): Target {
  const companyId = safeId(params.get("company"));
  const docId = safeId(params.get("doc"));
  const contactId = safeId(params.get("contact"));
  if (!companyId) return { ref: null, docId, contactId: null };
  const year = intIn(params.get("year"), /^\d{4}$/, 1990, 2100);
  const quarter = intIn(params.get("quarter"), /^\d$/, 0, 4);
  const rawView = params.get("view") ?? "";
  const view = VIEWS.has(rawView as NonNullable<FolderRef["view"]>) ? (rawView as FolderRef["view"]) : undefined;
  if (view === "bank") {
    const account = params.get("account") ?? "";
    const month = params.get("month") ?? "";
    if (year !== null && /^[A-Za-z0-9-]{0,10}$/.test(account) && /^\d{4}-(0[1-9]|1[0-2])$/.test(month)) {
      return { ref: { companyId, year, quarter: null, view, bankAccount: account, month }, docId, contactId: null };
    }
    return { ref: { companyId, year: null, quarter: null, view: "overview" }, docId, contactId: null };
  }
  if (view === "books" || view === "employees") {
    return year !== null
      ? { ref: { companyId, year, quarter: null, view }, docId, contactId: null }
      : { ref: { companyId, year: null, quarter: null, view: "overview" }, docId, contactId: null };
  }
  if (view) {
    const keepContact = view === "customers" || view === "suppliers" ? contactId : null;
    return { ref: { companyId, year: null, quarter: null, view }, docId, contactId: keepContact };
  }
  if (year !== null && quarter !== null) return { ref: { companyId, year, quarter }, docId, contactId: null };
  return { ref: { companyId, year: null, quarter: null, view: "overview" }, docId, contactId: null };
}

function query(values: Record<string, string | number | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(values)) if (v !== null && v !== undefined && v !== "") p.set(k, String(v));
  return p.toString();
}

/** The query string on /accounting that opens a result (tasks and companies-less tasks go elsewhere: see targetHref). */
export function targetQuery(item: SearchItem): string {
  const company = safeId(item.company_id);
  if (!company) return "";
  switch (item.type) {
    case "document":
      return query({
        company,
        year: item.period_year ?? null,
        quarter: item.period_year && item.period_quarter ? item.period_quarter : null,
        doc: safeId(item.document_id),
      });
    case "contact":
      return query({ company, view: item.role === "customer" ? "customers" : "suppliers", contact: safeId(item.id) });
    case "bank_line":
      return query({ company, view: "bank", year: item.fiscal_year, account: item.account_code ?? "", month: item.month });
    case "journal_entry":
      return query({ company, view: "books", year: item.fiscal_year });
    default:
      return query({ company, view: "overview" });
  }
}

export function targetHref(item: SearchItem): string {
  if (item.type === "task") {
    const company = safeId(item.company_id);
    return `/accounting/work?${query({ tab: "tasks", company })}`;
  }
  const q = targetQuery(item);
  return q ? `/accounting?${q}` : "/accounting";
}

/** Open a result: on the Documents page without a reload, elsewhere by navigating. */
export function openResult(item: SearchItem, pathname: string, push: (href: string) => void): void {
  const href = targetHref(item);
  if (pathname === "/accounting" && href.startsWith("/accounting?")) {
    window.history.replaceState(null, "", href);
    window.dispatchEvent(new CustomEvent(OPEN_TARGET_EVENT, { detail: href.slice("/accounting?".length) }));
  } else {
    push(href);
  }
}
