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

export interface TreeYear {
  year: number;
  quarters: TreeQuarter[];
  annual: TreeAnnual;
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
  seller_address: string;
  seller_vat_registered: boolean | null;
  buyer_name: string;
  buyer_tin: string;
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
  view?: "books" | "atc" | "employees";
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
}

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

export type AssetPatch = Partial<Pick<Asset, "description" | "in_service" | "useful_life_months" | "end_date">>;

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
}

export interface AtcDatabank {
  defaults: { account: string; ewt_atc: string }[];
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
