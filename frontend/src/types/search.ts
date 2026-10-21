// Global search (GET /api/accounting/search).
export type SearchType = "document" | "contact" | "bank_line" | "journal_entry" | "task" | "company";

export interface SearchItem {
  type: SearchType;
  id: string;
  company_id: string | null;
  company_name: string;
  title: string;
  subtitle: string;
  date: string | null;
  amount: string | null;
  /** What matched: number, name, tin, amount, date, reason, narration, reference, memo, title. */
  matched: string[];
  score: number;
  // document
  document_id?: string;
  page?: number;
  period_year?: number | null;
  period_quarter?: number | null;
  review_reasons?: string[];
  needs_review?: boolean;
  excluded?: boolean;
  // contact
  role?: "customer" | "supplier" | "both";
  tin?: string;
  // bank line
  account_code?: string;
  month?: string;
  fiscal_year?: number;
  statement_document_id?: string | null;
  match_status?: string;
  // journal entry
  reference?: string;
  // task
  status?: string;
}

export interface SearchGroup {
  type: SearchType;
  items: SearchItem[];
  more: boolean;
}

export interface SearchResponse {
  query: string;
  too_short: boolean;
  groups: SearchGroup[];
}

export interface SearchParams {
  q: string;
  types?: string;
  company_id?: string;
  date_from?: string;
  date_to?: string;
  review?: boolean;
  limit?: number;
}
