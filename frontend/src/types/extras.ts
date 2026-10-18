// Workstream 10 extras: recurring entries, write-offs, cash forecast, checklist templates.
import type { JournalEntry, JournalLine, OpenItemRow } from "@/types/accounting";

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
