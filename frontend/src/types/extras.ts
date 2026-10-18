// Workstream 10 extras: recurring entries, write-offs, cash forecast, checklist templates.
import type { JournalEntry, JournalLine } from "@/types/accounting";

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
