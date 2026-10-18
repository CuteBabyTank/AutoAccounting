// Workstream 10 extras: recurring entries, write-offs, cash forecast, checklist templates.
import type { JournalEntry, JournalLine, OpenItemRow } from "@/types/accounting";
import type { Task } from "@/types/work";

export type Frequency = "monthly" | "quarterly";

export interface RecurringInput {
  name: string;
  book: "GJ" | "CRJ" | "CDJ";
  reference: string;
  particulars: string;
  lines: JournalLine[];
  is_adjusting: boolean;
  frequency: Frequency;
  next_date: string;
  end_date: string | null;
  active: boolean;
}

export interface RecurringEntry extends RecurringInput {
  id: string;
  day_of_month: number;
  /** Occurrences due by today: posted only when someone presses "Post due entries". */
  due: string[];
  amount: string;
}

export interface RecurringPosted {
  posted: JournalEntry[];
  template: RecurringEntry;
}

export interface WriteOffCandidates {
  as_of: string;
  items: OpenItemRow[];
  total: string;
  last_closed: string | null;
  books_start: string | null;
}

export interface WriteOffResult {
  entry: JournalEntry;
  count: number;
  total: string;
}

export interface CashWeek {
  start: string;
  end: string;
  inflow: string;
  outflow: string;
  net: string;
  closing: string | null;
}

export interface CashForecast {
  as_of: string;
  opening: string | null;
  closing: string | null;
  weeks: CashWeek[];
  overdue_in: string;
  overdue_out: string;
  later_in: string;
  later_out: string;
  note: string;
}

/** Customer statement: what is open on the date, balance forward with the period's activity, or the activity only. */
export type StatementType = "open_item" | "balance_forward" | "transaction";

export type Cadence = "monthly" | "quarterly" | "annual";

export interface ChecklistItem {
  title: string;
  notes: string;
  /** Due this many days after the period end (negative = before). */
  offset_days: number;
  priority: "low" | "normal" | "high";
}

export interface ChecklistTemplate {
  /** A uuid, or builtin:<key> for the two built-in checklists. */
  id: string;
  name: string;
  cadence: Cadence;
  items: ChecklistItem[];
  builtin: boolean;
}

export interface ChecklistInput {
  name: string;
  cadence: Cadence;
  items: ChecklistItem[];
}

export interface ChecklistApplied {
  created: Task[];
  skipped: number;
}
