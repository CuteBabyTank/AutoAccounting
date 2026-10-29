export type TaxpayerType = "individual" | "corporation" | "partnership";

export interface CompanyInput {
  registered_name: string;
  aliases: string[];
  /** Owner / officers: a purchase made out to one of them personally is excluded as personal. */
  owner_names: string[];
  tin: string;
  branch_code: string;
  rdo_code: string;
  address: string;
  zip_code: string;
  taxpayer_type: TaxpayerType;
  vat_status: "vat" | "non_vat";
  income_tax_option: "graduated" | "eight_percent";
  deduction_method: "itemized" | "osd";
  business_type: "trading" | "manufacturing" | "services";
  is_withholding_agent: boolean;
  is_top_withholding_agent: boolean;
  has_employees: boolean;
  has_compensation_income: boolean;
  fiscal_year_end_month: number;
  /** Year operations began (non-individuals): MCIT applies from the 4th taxable year after it. */
  operations_start_year: number | null;
  contact_number: string;
  email: string;
  /** 2550-Q item 13; "" until set. */
  taxpayer_classification: "" | "micro" | "small" | "medium" | "large";
  pinned: boolean;
  /** First day on the books (YYYY-MM-DD); null = books off. */
  books_start: string | null;
  books_kept: string[];
  books_signatory: string;
  books_signatory_title: string;
}

export interface Company extends CompanyInput {
  id: string;
  created_at: string;
  archived_at: string | null;
}

/** The caller's latest finished upload and where its documents are now (for "wrong company? move them"). */
export interface RecentUpload {
  id: string;
  created_at: string;
  files: { id: string; original_filename: string; documents: number; companies: CompanyBrief[] }[];
}

export interface UploadMoveResult {
  moved: number;
  refused: { document: string; reason: string }[];
  upload: RecentUpload | null;
}

export interface CompanyBrief {
  id: string;
  registered_name: string;
  tin: string;
}

export type UploadStatus =
  | "detecting"
  | "awaiting_confirmation"
  | "confirming"
  | "extracting"
  | "done"
  | "failed";

export interface AAUploadFile {
  id: string;
  original_filename: string;
  status: string;
  company_id: string | null;
  error_message: string | null;
}

export interface UploadGroup {
  key: string;
  company: CompanyBrief | null;
  level: "certain" | "likely" | "unknown" | "unreadable";
  detected_name: string;
  detected_tin: string;
  detected_address: string;
  file_ids: string[];
  file_names: string[];
}

export interface Upload {
  id: string;
  status: UploadStatus;
  total_files: number;
  processed_files: number;
  preselected_company_id: string | null;
  files: AAUploadFile[];
  groups: UploadGroup[];
  affected_periods: AffectedPeriod[];
}

export interface ConfirmAssignment {
  file_ids: string[];
  company_id?: string;
  skip?: boolean;
}

export interface TreeQuarter {
  year: number;
  quarter: number;
  label: string;
  document_count: number;
  review_count: number;
  latest_version: number | null;
  stale: boolean;
  filed: boolean;
}

export interface TreeAnnual {
  latest_version: number | null;
  stale: boolean;
  filed: boolean;
}

export interface TreeBankMonth {
  month_start: string;
  lines: number;
  open: number;
  reconciled: boolean;
}

export interface TreeBankAccount {
  account_code: string; // "" = a statement whose account isn't chosen yet
  name: string;
  last4: string;
  months: TreeBankMonth[];
}

export interface TreeYear {
  year: number;
  quarters: TreeQuarter[];
  annual: TreeAnnual;
  bank?: TreeBankAccount[];
}

export interface TreeCompany {
  id: string;
  registered_name: string;
  tin: string;
  pinned: boolean;
  fiscal_year_end_month: number;
  books_start: string | null;
  has_employees: boolean;
  years: TreeYear[];
  undated_count: number;
}

export type Category = "sales" | "purchases" | "expenses" | "payroll" | "2307" | "support" | "unsorted";

export interface AADocument {
  id: string;
  company_id: string;
  file_id: string;
  page_start: number;
  page_end: number;
  document_title: string;
  doc_type: string;
  category: Category;
  account: string;
  client_role: "seller" | "buyer";
  doc_number: string;
  doc_date: string | null;
  period_year: number | null;
  period_quarter: number | null;
  period_month: number | null;
  period_locked: boolean;
  seller_name: string;
  seller_tin: string;
  /** Branch code as printed after the TIN ("000"), "" when none. */
  seller_branch: string;
  seller_address: string;
  seller_vat_registered: boolean | null;
  buyer_name: string;
  buyer_tin: string;
  buyer_branch: string;
  buyer_address: string;
  gross_amount: string;
  vatable_amount: string;
  vat_amount: string;
  exempt_amount: string;
  zero_rated_amount: string;
  withholding_amount: string;
  ewt_atc: string;
  ewt_atc_effective: string;
  ewt_atc_source: "document" | "supplier" | "account" | "";
  ewt_atc_suggestion: string;
  ewt_atc_suggestion_company: string;
  ewt_atc_best: string; // the decision tree's pick (an ATC or NONE), first in the picker
  ewt_atc_best_reason: string;
  rule_applied_to?: number; // after a category/account correction: the supplier's other unreviewed documents changed
  vat_treatment: string;
  input_vat_valid: boolean | null;
  confidence: number;
  needs_review: boolean;
  review_reasons: string[];
  /** Details per reason, e.g. review_notes.ewt_expected = { atc, rate, base, amount }. */
  review_notes?: Record<string, Record<string, string>>;
  reviewed: boolean;
  excluded: boolean;
  paid_on: string | null;
  paid_via: "" | "cash" | "bank" | "ewallet";
  payment_ref: string;
  settles_document_id: string | null;
  settles_source: "" | "auto" | "user";
  gl_account_code: string;
  created_at: string;
}

/** Two documents that look like the same paper filed twice; ``duplicate`` was filed later. */
export interface DuplicatePair {
  original: AADocument;
  duplicate: AADocument;
  reason: "same_number" | "same_details" | "number_reused";
  original_file: string;
  duplicate_file: string;
}

export interface Folder {
  company: CompanyBrief;
  year: number | null;
  quarter: number | null;
  label: string;
  counts: Record<string, number>;
  documents: AADocument[];
}

/** A quarter folder, a year's Annual return (quarter 0), or a company's Undated folder (year and quarter null). */
export interface FolderRef {
  companyId: string;
  year: number | null;
  quarter: number | null;
  view?: "books" | "atc" | "employees" | "audit" | "bank" | "customers" | "suppliers" | "overview" | "reports" | "reclassify" | "import";
  /** view "bank": the bank account code ("" = unassigned statements) and month (YYYY-MM). */
  bankAccount?: string;
  month?: string;
}

export type DocumentPatch = Record<string, string | number | boolean | null>;

export interface PayrollMonth {
  mwe_basic: string;
  mwe_premium: string;
  thirteenth_month: string;
  de_minimis: string;
  contributions: string;
  employer_contributions: string;
  other_non_taxable: string;
  not_subject: string;
  adjustment: string;
  amended_paid: string;
  no_payroll: boolean;
}

export interface PeriodInputs {
  ending_inventory: string | null;
  opening_inventory: string | null;
  opening_excess_input_vat: string;
  vat_withheld: string;
  advance_vat: string;
  uncollected_output_vat: string;
  recovered_output_vat: string;
  unpaid_input_vat: string;
  settled_input_vat: string;
  percentage_tax_withheld: string;
  non_operating_income: string;
  prior_year_excess_credits: string;
  prior_taxable_income: string | null;
  prior_tax_paid: string | null;
  prior_cwt: string | null;
  prior_gross_income: string | null;
  amended_paid_business_tax: string;
  amended_paid_income_tax: string;
  cit_rate: 20 | 25;
  mcit_applies: boolean;
  ewt_remitted_m1: string | null;
  ewt_remitted_m2: string | null;
  ewt_over_remittance: string;
  amended_paid_withholding: string;
  payroll: PayrollMonth[];
}

export interface OutputBrief {
  id: string;
  version: number;
  created_at: string;
  review_open: number;
  changes: number;
  amended: boolean;
}

export interface Period {
  company: CompanyBrief;
  year: number;
  quarter: number;
  label: string;
  inputs: PeriodInputs;
  filed_at: string | null;
  filed_forms: Record<string, FiledForm>;
  document_count: number;
  open_reviews: number;
  latest_version: number | null;
  stale: boolean;
  books_stale: boolean;
  forms_expected: string[];
  due_dates: Record<string, string>;
  outputs: OutputBrief[];
}

export interface FiledForm {
  output_id: string;
  version: number;
  filed_at: string;
  paid_on?: string | null;
}

export type Scope = "M1" | "M2" | "M3" | "Q";

export interface PrepareForm {
  form: string;
  title: string;
  guide: string;
  source: string | null;
  due: string | null;
  filed: FiledForm | null;
  amended: boolean;
  missing: string[];
}

export interface Prepare {
  scope: Scope;
  label: string;
  note: string | null;
  forms: PrepareForm[];
  stale: boolean;
  version: number;
  latest_version: number;
}

export interface OutputItem {
  key: string;
  label: string;
  value: string;
  changed: boolean;
  before: string | null;
  /** The books' figure, when this one was edited by hand. */
  engine?: string | null;
}

/** One editable field of a form or certificate in the PDF preview. */
export interface PdfField {
  key: string;
  label: string;
  value: string;
  kind: "amount" | "text";
}

/** A certificate (2307, 2316) in the preview: its id and editable fields. */
export interface Certificate {
  id: string;
  label: string;
  fields: PdfField[];
}

/** One cell of a workbook preview: displayed text and style. */
export interface WorkbookCell {
  v: string;
  fill?: string;
  bold?: boolean;
  num?: boolean;
  strike?: boolean;
}

export interface WorkbookSheet {
  name: string;
  rows: WorkbookCell[][];
  truncated: boolean;
}

/** Edits per certificate id → field key → value. */
export type CertificateEdits = Record<string, Record<string, string>>;

export interface OutputForm {
  form: string;
  title: string;
  items: OutputItem[];
  pdf: boolean;
  payable_item: string | null;
}

export interface Output {
  id: string;
  company_id: string;
  year: number;
  quarter: number;
  label: string;
  version: number;
  parent_version: number | null;
  created_at: string;
  review_open: number;
  amended: boolean;
  changes: number;
  warnings: string[];
  forms: OutputForm[];
  ledgers: Record<string, number>;
}

export interface AffectedPeriod {
  company_id: string;
  company_name: string;
  year: number;
  quarter: number;
  label: string;
  latest_version: number;
  filed: boolean;
  new_documents: number;
}

export interface OpeningRow {
  year: number;
  amount: string;
  used: string;
}

export interface AnnualInputs {
  ending_inventory: string | null;
  non_operating_income: string | null;
  prior_year_excess_credits: string | null;
  q1_paid: string | null;
  q2_paid: string | null;
  q3_paid: string | null;
  amended_paid_income_tax: string;
  cit_20_percent: boolean;
  refund_overpayment: boolean;
  current_assets: string | null;
  ppe_net: string | null;
  other_noncurrent_assets: string | null;
  current_liabilities: string | null;
  noncurrent_liabilities: string | null;
  equity: string | null;
  book_net_income: string | null;
  nondeductible_expenses: string;
  nontaxable_income: string;
  other_reconciling: string;
  pre_books_sales: string;
  pre_books_cost_of_sales: string;
  pre_books_deductions: string;
  pre_books_cwt: string;
  compensation_income: string;
  compensation_nontaxable: string;
  compensation_tax_withheld: string;
  opening_nolco: OpeningRow[];
  opening_excess_mcit: OpeningRow[];
}

export interface AnnualPeriod {
  company: CompanyBrief;
  year: number;
  label: string;
  form: string;
  inputs: AnnualInputs;
  filed_at: string | null;
  document_count: number;
  open_reviews: number;
  latest_version: number | null;
  stale: boolean;
  forms_expected: string[];
  due_dates: Record<string, string>;
  outputs: OutputBrief[];
  carry_source: "previous_year" | "opening";
  previous_year_version: number | null;
  pre_books_quarters: number[];
  has_compensation_income: boolean;
}

export interface Asset {
  id: string;
  document_id: string | null; // null: an opening asset carried in at the books' start
  doc_number: string;
  doc_date: string | null;
  description: string;
  cost: string;
  in_service: string;
  useful_life_months: number;
  end_date: string | null;
  active: boolean;
  this_year: string;
  accumulated: string;
  net_book_value: string;
}

export type AssetPatch = Partial<Pick<Asset, "description" | "cost" | "in_service" | "useful_life_months" | "end_date">>;

export interface OpeningAssetInput {
  description: string;
  cost: string;
  useful_life_months: number;
}

export interface Account {
  id: string;
  code: string;
  name: string;
  type: "asset" | "liability" | "equity" | "income" | "cost" | "expense";
  contra: boolean;
  parent_code: string | null;
  system_key: string | null;
  active: boolean;
  /** Locked: no new postings by people or extraction (existing ones stay). */
  locked?: boolean;
  bank_account_no?: string;
  /** Where it lands, e.g. "Profit and loss · Operating expenses". */
  placement?: string;
}

export interface JournalLine {
  account_code: string;
  debit: string;
  credit: string;
  party_name: string;
  party_tin: string;
}

export interface JournalEntryInput {
  kind: "opening" | "manual";
  book: "GJ" | "CRJ" | "CDJ";
  entry_date: string;
  reference: string;
  particulars: string;
  lines: JournalLine[];
  /** An adjusting entry: listed in the Adjusted TB and the Adjusting Journal Entries report. */
  is_adjusting?: boolean;
}

export interface BookMonth {
  start: string;
  end: string;
  status: "closed" | "open" | "before_books";
  pages: Record<string, [number, number]>;
  books: string[];
  closed_at: string | null;
}

export interface BooksYear {
  fiscal_year: number;
  months: BookMonth[];
  bound: boolean;
  bound_books: string[];
  bind_by: string;
}

export interface JournalEntry extends JournalEntryInput {
  id: string;
  created_at: string;
  /** A bulk write-off: delete it to reopen the invoices; it can't be edited. */
  is_writeoff?: boolean;
  /** Posted from a recurring template. */
  recurring?: boolean;
}

export interface DocRef {
  id: string;
  doc_number: string;
  doc_date: string | null;
  counterparty: string;
  gross_amount: string;
}

export interface PaymentLinks {
  linked_invoice: DocRef | null;
  candidates: DocRef[];
  paid_by: DocRef[];
}

export interface AtcSupplier {
  tin: string;
  name: string;
  documents: number;
  ewt_atc: string;
  suggestion: string;
  suggestion_company: string;
  automatic: string; // ATC(s) the returns use for its documents with no supplier ATC, e.g. "WC120 / WC158"
  hint: string; // the decision tree's ATC (or NONE) to adopt, "" when it agrees
  hint_reason: string;
  best: string; // the decision tree's pick (an ATC or NONE), first in the picker
  best_reason: string;
}

export interface AtcCode {
  code: string;
  nature: string;
  rate: string; // fraction, e.g. "0.05"
}

export interface AtcDatabank {
  defaults: { account: string; ewt_atc: string; suggestion: string }[];
  suppliers: AtcSupplier[];
}

export type EmployeeData = Record<string, string | boolean>;

export interface Employee {
  id: string;
  data: EmployeeData;
  schedule: 1 | 2;
  gross: string;
  taxable: string;
  tax_due: string;
  withheld: string;
  december: string;
  refund: string;
  substituted: boolean;
}

export interface EmployeesYear {
  year: number;
  employees: Employee[];
  warnings: string[];
  checks: { key: string; check: string; alphalist: string; returns: string; difference: string }[];
  remittances: { key: string; month: string; remitted_on: string; withheld: string; adjustment: string; penalties: string; total: string; source: string }[];
  fields: Record<string, string>;
  due: string;
}

export interface PayrollPreview {
  headers: string[];
  sample: string[][];
  rows: number;
  mapping: Record<string, string>;
  fields: Record<string, string>;
}

export interface PayrollImport extends EmployeesYear {
  imported: number;
  errors: string[];
}

export interface AlphalistStatus {
  company_id: string;
  company: string;
  employees: number;
  issues: number;
  status: "no_payroll" | "needs_review" | "ready";
}

/** One change a person made (audit log). ``before``/``after`` hold only the fields that changed. */
export interface AuditEvent {
  id: string;
  at: string;
  company_id: string | null;
  user_id: string | null;
  user_name: string;
  entity: string;
  entity_id: string;
  label: string;
  action: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  reason: string;
}

export interface AuditPage {
  events: AuditEvent[];
  total: number;
  users: { id: string; name: string }[];
}

export interface AuditFilters {
  company_id?: string;
  user_id?: string;
  start?: string;
  end?: string;
  entity?: string;
  entity_id?: string;
  limit?: number;
  offset?: number;
}

// --- Bank statements ----------------------------------------------------------------------------------------------

export type BankMatchStatus = "unmatched" | "ambiguous" | "suggested" | "matched" | "confirmed" | "excluded";

export interface BankCandidate {
  kind: "document" | "tax" | "journal";
  ref: string;
  label: string;
  amount: string;
  date: string;
  strength: "strong" | "weak" | "conflict" | "partial";
}

export interface BankLine {
  id: string;
  statement_id: string;
  account_code: string;
  line_no: number;
  line_date: string;
  amount: string; // signed: + money in
  balance: string | null;
  narration: string;
  check_no: string;
  match_status: BankMatchStatus;
  match_kind: "" | "document" | "posting" | "tax" | "journal";
  matched_ref: string;
  match_label: string;
  match_amount: string | null;
  posting: { kind?: string; key?: string; account?: string; label?: string };
  candidates: BankCandidate[];
  review_reason: "" | "bank_match_ambiguous" | "bank_line_unmatched";
  matched_at: string | null;
}

export interface BankStatement {
  id: string;
  document_id: string;
  account_code: string;
  account_number: string;
  bank_name: string;
  period_start: string | null;
  period_end: string | null;
  opening_balance: string | null;
  closing_balance: string | null;
  ties: boolean;
  tie_breaks: number[];
}

export interface BankReconciliation {
  id: string;
  account_code: string;
  month_start: string;
  month_end: string;
  statement_balance: string;
  book_balance: string;
  uncleared: { id: string; date: string; amount: string; label: string }[];
  reconciled_at: string;
}

export interface BankAccountInfo {
  code: string;
  name: string;
  bank_account_no: string;
  reconciled_through: string | null;
  opening_missing: { date: string; statement: string; books: string } | null;
}

export interface BankOverview {
  accounts: BankAccountInfo[];
  unassigned: BankStatement[];
  rules: number;
}

export interface BankMonth {
  account: BankAccountInfo | null;
  month_start: string;
  statements: BankStatement[];
  lines: BankLine[];
  reconciliation: BankReconciliation | null;
  opening_balance: string | null;
  closing_balance: string | null;
}

export interface BankConfirm {
  kind?: "document" | "posting" | "tax" | "journal";
  ref?: string;
  account_code?: string;
  amount?: string;
}

export interface ReconcileResult {
  ok: boolean;
  problem: string;
  statement_balance: string | null;
  book_balance: string | null;
  outstanding: string | null;
  difference: string | null;
  uncleared: { id: string; date: string; amount: string; label: string }[];
  open_lines: number;
  reconciliation: BankReconciliation | null;
}

export interface BankRule {
  id: string;
  pattern: string;
  direction: "in" | "out" | "any";
  kind: "payee" | "posting";
  account_code: string;
  payee_name: string;
  payee_tin: string;
  hits: number;
}

export type BankRuleInput = Omit<BankRule, "id" | "hits">;

// Customers / suppliers: contacts master, open items, aging, 2307s
export type AgingBucket = "current" | "1-30" | "31-60" | "61-90" | "90+";

export interface ContactRow {
  archived_at: string | null;
  id: string;
  key: string;
  role: "customer" | "supplier" | "both";
  tin: string;
  registered_name: string;
  aliases: string[];
  open_balance: string;
  overdue: string;
  open_count: number;
  cwt_pending: string;
  unverified: number;
  last_date: string | null;
  payment_terms_days?: number | null;
  /** Supplier list: the supplier's default chart account ("" = none). */
  default_account?: string;
}

export interface ContactList {
  role: "customer" | "supplier";
  as_of: string;
  contacts: ContactRow[];
  total_open: string;
  total_overdue: string;
  total_cwt_pending: string;
}

export interface OpenItemRow {
  document_id: string;
  kind: "ar" | "ap";
  doc_number: string;
  doc_date: string;
  due: string;
  total: string;
  withheld: string;
  paid: string;
  open: string;
  days_past_due: number;
  bucket: AgingBucket;
  payment_unverified: boolean;
  contact_name: string;
  contact_tin: string;
  opening?: boolean;          // imported opening item: no document behind it
  recovered?: string;         // received after the item was written off (a recovery to post)
}

export interface ContactDocument {
  id: string;
  doc_number: string;
  doc_date: string | null;
  title: string;
  category: string;
  kind: "ar" | "ap" | "2307" | "receipt" | "other";
  total: string;
  withheld: string;
  period_year: number | null;
  period_quarter: number | null;
  open: string | null;
}

export interface ContactPayment {
  document_id: string;
  doc_number: string;
  on: string;
  amount: string;
  via: string;
  source: "receipt" | "paid_on" | "bank";
  ref: string;
}

export interface Cwt2307 {
  document_id: string;
  doc_number: string;
  doc_date: string;
  amount: string;
  year: number | null;
  quarter: number | null;
  status: "pending" | "received";
  certificate_id: string | null;
  certificate_label: string;
  source: "auto" | "user" | "";
}

export interface Outgoing2307 {
  document_id: string;
  doc_number: string;
  doc_date: string;
  atc: string;
  amount: string;
  year: number;
  quarter: number;
  output_id: string | null;
}

export interface ContactDetail {
  archived_at: string | null;
  id: string;
  key: string;
  role: "customer" | "supplier" | "both";
  tin: string;
  registered_name: string;
  aliases: string[];
  address: string;
  vat_status: "vat" | "non_vat" | "";
  payment_terms_days: number | null;
  default_account: string;
  default_atc: string;
  auto_atc: string; // what the returns use for its documents with no ATC set
  best_atc: string; // the decision tree's pick (an ATC or NONE), first in the picker
  best_atc_reason: string;
  manual: string[];
  merged_into_id: string | null;
  merged_from: string[];
  as_of: string;
  receivable: string;
  payable: string;
  documents: ContactDocument[];
  payments: ContactPayment[];
  open_items: OpenItemRow[];
  cwt_2307s: Cwt2307[];
  certificates: { id: string; label: string }[];
  outgoing_2307s: Outgoing2307[];
}

export interface ContactPatch {
  registered_name?: string;
  role?: "customer" | "supplier" | "both";
  address?: string;
  vat_status?: "vat" | "non_vat" | "";
  payment_terms_days?: number | null;
  default_account?: string;
  default_atc?: string;
  reason?: string;
}

export interface ContactCreate {
  registered_name: string;
  tin: string;
  role: "customer" | "supplier" | "both";
  address: string;
  vat_status: "vat" | "non_vat" | "";
  payment_terms_days: number | null;
}

export interface AgingRow {
  contact_id: string | null;
  name: string;
  tin: string;
  buckets: Record<AgingBucket, string>;
  total: string;
  count: number;
  unverified: number;
}

export interface Aging {
  kind: "ar" | "ap";
  as_of: string;
  rows: AgingRow[];
  totals: Record<AgingBucket | "total", string>;
  items: OpenItemRow[];
  /** Aging total → the books' control account: open items, CWT still in A/R, counter-paid, other, books. */
  tie?: { key: "aging" | "cwt" | "counter" | "other" | "books"; label: string; amount: string }[];
  tie_note?: string;
}

// --- Reports (live from the books) ---------------------------------------------------------------------------------

export type ReportKind = "pnl" | "balance-sheet" | "gl" | "transactions" | "adjusted-tb" | "adjusting" | "invalid";

export interface ReportParams {
  start?: string;
  end?: string;
  by?: "total" | "month" | "quarter";
  compare?: "none" | "period" | "year";
  nonzero?: boolean;
  thousands?: boolean;
  account?: string;
  party?: string;
}

export interface ReportColumn {
  key: string;
  label: string;
  start: string | null;
  end: string | null;
  kind: "amount" | "change" | "pct";
}

export interface ReportDrill {
  start: string | null;
  end: string;
}

export interface ReportGridRow {
  key: string;
  label: string;
  level: number;
  kind: "header" | "account" | "total";
  codes: string[];
  values: (string | null)[];
  drill: (ReportDrill | null)[];
}

export interface SourceRef {
  kind: "document" | "bank_line" | "journal_entry" | "asset" | "tax" | "system";
  id: string;
}

export interface PostingLine {
  entry_id: string;
  date: string;
  book: string;
  reference: string;
  party: string;
  particulars: string;
  debit: string;
  credit: string;
  balance?: string;
  code?: string;
  name?: string;
  ref: SourceRef;
}

export interface GlAccountDetail {
  code: string;
  name: string;
  type: string;
  opening: string;
  lines: PostingLine[];
  closing: string;
}

export interface TransactionRow {
  entry_id: string;
  date: string;
  book: string;
  source: string;
  reference: string;
  party: string;
  particulars: string;
  accounts: string[];
  account_names: string[];
  amount: string;
  ref: SourceRef;
}

export interface AdjustingRow {
  entry_id: string;
  date: string;
  book: string;
  reference: string;
  particulars: string;
  kind: string;
  amount: string;
  ref: SourceRef;
  lines: { code: string; name: string; debit: string; credit: string }[];
}

export interface InvalidRow {
  entry_id: string;
  date: string | null;
  reference: string;
  problem: string;
  label: string;
  detail: string;
  ref: SourceRef;
}

export interface Report {
  kind: ReportKind;
  title: string;
  subtitle: string;
  basis: string;
  company: string;
  columns?: ReportColumn[];
  /** Grid reports: ReportGridRow; transactions: TransactionRow; adjusting: AdjustingRow; invalid: InvalidRow. */
  rows?: unknown[];
  accounts?: GlAccountDetail[];
  balanced?: boolean;
  thousands?: boolean;
  engine_error?: string;
}

export interface Postings {
  lines: PostingLine[];
  count: number;
  total: string;
  truncated: boolean;
}

export interface ReportSource {
  kind: SourceRef["kind"];
  entry_id: string;
  document?: { document_id: string; page: number; title: string; doc_number: string; doc_date: string | null } | null;
  bank_line?: { date: string; narration: string; amount: string; check_no: string; account_code: string; line_no: number; page?: number | null };
  journal_entry?: {
    id: string; kind: string; book: string; entry_date: string; reference: string; particulars: string;
    lines: JournalLine[]; is_adjusting: boolean; deleted: boolean;
  };
  asset?: { description: string; cost: string; in_service: string };
}

export interface CompanyKpis {
  start: string;
  end: string;
  books_on: boolean;
  note: string;
  kpis: {
    net_sales: string; gross_profit: string; net_income: string; operating_expenses: string;
    gross_margin: string | null; net_margin: string | null; opex_ratio: string | null;
    current_assets: string; quick_assets: string; current_liabilities: string;
    current_ratio: string | null; quick_ratio: string | null;
  } | null;
  aging: Record<"ar" | "ap", { labels: Record<string, string>; buckets: string[]; totals: Record<string, string> }>;
}

export interface ManagementPack {
  year: number;
  quarter: number;
  period: string;
  notes: string;
  books_on: boolean;
  generated_at: string | null;
  generated_by: string;
  pdf: boolean;
  docx: boolean;
}

export interface CoaTemplate {
  /** A built-in key (trading, services, manufacturing, non_vat) or a firm template id. */
  id: string;
  name: string;
  description: string;
  builtin: boolean;
  accounts_count: number;
}

export interface ReclassifyCandidate {
  key: string;
  kind: "document" | "journal_entry" | "other";
  source_id: string;
  entry_id: string;
  date: string;
  book: string;
  reference: string;
  party: string;
  particulars: string;
  amount: string;
  atc: string;
  movable: boolean;
  why_not: string;
  closed: boolean;
  account: string;
}

export interface ReclassifyList {
  account: string;
  account_name: string;
  last_closed: string | null;
  candidates: ReclassifyCandidate[];
}

export interface ReclassifyInput {
  start: string;
  end: string;
  account: string;
  atc?: string;
  keys: string[];
  to_account?: string;
  to_atc?: string;
  reason?: string;
}

export interface ReclassifyPreview {
  items: { key: string; kind: string; date: string; reference: string; party: string; amount: string; from: string;
    to: string; from_atc: string; to_atc: string; closed: boolean; posts_on: string }[];
  count: number;
  corrections: number;
  total: string;
  to_account: string;
  to_name: string;
  skipped: string[];
  moved?: number;
}

export interface BulkResolveResult {
  resolved: string[];
  skipped: { id: string; why: string }[];
}

// --- spreadsheet imports (opening TB, opening open items, journal entries) ---
export type ImportKind = "opening-tb" | "open-items" | "journal-entries";

export interface ImportOptions {
  columns?: Record<string, string>;
  date_format?: string | null;
  accounts?: Record<string, string>;
  default_kind?: "ar" | "ap" | null;
  difference_account?: string | null;
}

export interface ImportAccountChoice {
  key: string;
  code_in: string;
  name_in: string;
  match_code: string | null;
  how: "code" | "conflict" | "name" | "fuzzy" | "none";
  score: number;
  alternatives: string[];
  chosen: string | null;
  problem: "" | "unmapped" | "not_in_chart" | "inactive" | "locked" | "unconfirmed";
  rows: number;
}

export interface ImportPreview {
  kind: ImportKind;
  filename: string;
  headers: string[];
  columns: Record<string, string>;
  fields: Record<string, string>;
  row_count: number;
  date_format: string | null;
  date_formats: { value: string; label: string }[];
  accounts: ImportAccountChoice[];
  errors: { row: number; message: string }[];
  warnings: string[];
  ready: boolean;
  tb_lines: { account_code: string; account_name: string; debit: string; credit: string }[];
  debit: string;
  credit: string;
  difference: string;
  raw_difference: string;
  as_of: string | null;
  has_opening: boolean;
  items: {
    row: number; kind: "ar" | "ap"; contact_name: string; contact_tin: string; doc_number: string; doc_date: string;
    due_date: string | null; terms_days: number | null; amount: string;
  }[];
  item_count: number;
  totals: Record<string, string>;
  control: Record<string, string>;
  skipped: number;
  entries: {
    row: number; entry_date: string | null; posts_on: string | null; reference: string; particulars: string;
    is_adjusting: boolean; debit: string; credit: string; lines: number; errors: string[];
  }[];
  last_closed: string | null;
  books_start: string | null;
}

export interface ImportResult {
  kind: ImportKind;
  batch_id: string | null;
  created: number;
  updated: number;
  skipped: number;
  warnings: string[];
}

export type ImportBatchStatus = "active" | "undone" | "replaced" | "emptied";

/** A confirmed import (Import page → Recent imports); undoing it removes what it wrote. */
export interface ImportBatch {
  id: string;
  kind: ImportKind;
  filename: string;
  row_count: number;
  created_by: string;
  created_at: string;
  undone_at: string | null;
  undone_by: string;
  status: ImportBatchStatus;
}

export interface ImportBatches {
  batches: ImportBatch[];
  can_undo: boolean;
}

export interface ImportUndo {
  batch: ImportBatch;
  removed: number;
  restored: boolean;
  warnings: string[];
}

export interface OpeningItem {
  id: string;
  kind: "ar" | "ap";
  contact_name: string;
  contact_tin: string;
  doc_number: string;
  doc_date: string;
  due_date: string | null;
  terms_days: number | null;
  amount: string;
  paid_on: string | null;
  paid_via: string;
  paid_account: string;
  open: string;
}

export interface OpeningItems {
  items: OpeningItem[];
  totals: Record<string, string>;
  control: Record<string, string>;
  warnings: string[];
  books_start: string | null;
}
