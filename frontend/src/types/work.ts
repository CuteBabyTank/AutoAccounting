// Work board, client health, tasks, firm settings and notifications (routers/accounting_work.py, accounting_tasks.py).

export type BoardStatus = "no_docs" | "docs_in" | "needs_review" | "generated" | "filed";

export interface Person {
  id: string;
  name: string;
  email: string;
  role: string;
}

export interface FirmSettings {
  approve_before_close: boolean;
  deadline_days: number;
  can_edit: boolean;
  can_file: boolean;
}

export interface WorkCard {
  key: string;
  company_id: string;
  company_name: string;
  form: string;
  form_label: string;
  year: number;
  quarter: number;
  period_label: string;
  due_date: string;
  status: BoardStatus;
  auto_status: BoardStatus;
  status_override: string;
  overdue: boolean;
  days_left: number;
  filed_on: string | null;
  filed_source: "return" | "board" | null;
  assignee_id: string | null;
  assignee_name: string;
  documents: number;
  open_reviews: number;
}

export interface CompanySummary {
  company_id: string;
  company_name: string;
  open_reviews: number;
  unmatched_bank_lines: number;
  unreconciled_months: number;
  months_not_closed: number;
  books_on: boolean;
  open_tasks: number;
  overdue_filings: number;
}

export interface Board {
  start: string;
  end: string;
  today: string;
  cards: WorkCard[];
  companies: CompanySummary[];
  people: Person[];
}

export interface BoardFilters {
  start?: string;
  end?: string;
  company_id?: string;
  status?: string;
  assignee?: string;
}

export interface WorkItemInput {
  company_id: string;
  year: number;
  quarter: number;
  form: string;
  assignee_id?: string | null;
  status_override?: "" | Exclude<BoardStatus, "filed">;
  filed_on?: string | null;
}

export interface HealthBankAccount {
  code: string;
  name: string;
  reconciled_through: string | null;
  unreconciled_months: string[];
  unmatched_lines: number;
}

export interface HealthBalance {
  code: string;
  name: string;
  type: string;
  balance: string;
}

export interface CompanyHealth {
  company_id: string;
  company_name: string;
  as_of: string;
  reviews_by_reason: Record<string, number>;
  open_reviews: number;
  bank_accounts: HealthBankAccount[];
  unassigned_statements: number;
  unmatched_bank_lines: number;
  cwt_pending_count: number;
  cwt_pending_amount: string;
  months_not_closed: string[];
  books_on: boolean;
  ar_over_90_count: number;
  ar_over_90_amount: string;
  ap_over_90_count: number;
  ap_over_90_amount: string;
  negative_balances: HealthBalance[];
  review_balances: HealthBalance[];
  writeoff_recoveries?: { document_id: string; doc_number: string; contact_name: string; amount: string; opening: boolean }[];
  issues: number;
  notes: string[];
}

export type TaskStatus = "open" | "in_progress" | "done";
export type TaskPriority = "low" | "normal" | "high";

export interface Task {
  id: string;
  title: string;
  notes: string;
  due_date: string | null;
  assignee_id: string | null;
  assignee_name: string;
  status: TaskStatus;
  priority: TaskPriority;
  company_id: string | null;
  company_name: string;
  document_id: string | null;
  document_label: string;
  period_year: number | null;
  period_quarter: number | null;
  created_by: string | null;
  created_by_name: string;
  created_at: string;
  completed_at: string | null;
  overdue: boolean;
}

export interface TaskInput {
  title: string;
  notes: string;
  due_date: string | null;
  assignee_id: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  company_id: string | null;
  document_id?: string | null;
  period_year: number | null;
  period_quarter: number | null;
}

export interface TaskFilters {
  company_id?: string;
  document_id?: string;
  assignee?: string;
  status?: "open" | "done" | "all";
}

export interface AppNotification {
  key: string;
  kind: "deadline" | "review" | "bank" | "cwt" | "task_assigned" | "task_due";
  title: string;
  detail: string;
  company_id: string | null;
  due_date: string | null;
  severity: "high" | "normal";
  read: boolean;
}

export interface Notifications {
  items: AppNotification[];
  unread: number;
}
