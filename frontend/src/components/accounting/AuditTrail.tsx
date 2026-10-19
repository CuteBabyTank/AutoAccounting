"use client";

import { ACCOUNT_LABELS, CATEGORY_LABELS, REASON_LABELS } from "@/lib/accounting-format";
import type { AuditEvent } from "@/types/accounting";

export const ENTITY_LABELS: Record<string, string> = {
  document: "Document",
  company: "Company",
  account: "Chart account",
  journal_entry: "Journal entry",
  books_month: "Books",
  period: "Return inputs and filing",
  output: "Return version",
  asset: "Asset",
  employee: "Employee",
  atc: "ATC databank",
  upload: "Upload",
  bank_statement: "Bank statement",
  bank_line: "Bank line",
  bank_rule: "Bank rule",
  bank_reconciliation: "Bank reconciliation",
  contact: "Customer / supplier",
  work_item: "Work board",
  task: "Task",
  firm_settings: "Firm settings",
  coa_template: "Chart template",
  opening_item: "Opening open item",
  recurring_entry: "Recurring entry",
  checklist_template: "Checklist template",
  import_batch: "Import",
};

const ACTION_LABELS: Record<string, string> = {
  create: "Created",
  reclassify: "Reclassified",
  update: "Edited",
  delete: "Deleted",
  mark_reviewed: "Marked reviewed",
  unmark_reviewed: "Marked not reviewed",
  exclude: "Excluded from computation",
  include: "Included again",
  move: "Moved to another quarter",
  not_duplicate: "Kept both (not a duplicate)",
  supplier_rule: "Moved by a correction to the same supplier",
  confirm: "Files confirmed for this company",
  close: "Month closed",
  match_confirmed: "Bank match confirmed",
  match_rejected: "Bank match rejected",
  reconcile: "Reconciled",
  reopen: "Month reopened",
  merge: "Merged into another contact",
  merge_in: "Another contact merged in",
  cwt_2307: "2307 to receive marked",
  bind: "Year bound",
  inputs: "Inputs saved",
  filed: "Marked filed",
  unfiled: "Marked not filed",
  form_filed: "Form marked filed",
  form_unfiled: "Form marked not filed",
  generate: "Version generated",
  edit: "Edited by hand",
  import: "Imported from a sheet",
  undo_import: "Import undone",
  supplier: "Supplier ATC set",
  use_suggestions: "Suggested ATCs adopted",
  account: "Default ATC set",
  board_filed: "Marked filed on the work board",
  board_unfiled: "Work board filing cleared",
  task_done: "Task done",
  task_reopened: "Task reopened",
  pack_notes: "Management pack notes saved",
  pack_generated: "Management pack generated",
  writeoff: "Written off",
  written_off: "Written off",
  post_due: "Due entries posted",
  apply: "Checklist applied",
};

const FIELD_LABELS: Record<string, string> = {
  is_adjusting: "Adjusting entry",
  frequency: "Repeats",
  next_date: "Next date",
  day_of_month: "Day of month",
  cadence: "Cadence",
  locked: "Locked",
  coa_template: "Chart template",
  assignee_id: "Assigned to",
  status_override: "Board status",
  filed_on: "Filed on",
  approve_before_close: "Managers approve filing",
  paid_account: "Paid through",
  items: "Items",
  receivables: "Receivables",
  payables: "Payables",
  deadline_days: "Deadline reminder (days)",
  title: "Title",
  due_date: "Due date",
  priority: "Priority",
  doc_date: "Document date",
  doc_number: "Document no.",
  category: "Folder",
  account: "Account",
  seller_name: "Seller",
  seller_tin: "Seller TIN",
  buyer_name: "Buyer",
  buyer_tin: "Buyer TIN",
  gross_amount: "Total",
  vatable_amount: "VATable",
  vat_amount: "VAT",
  exempt_amount: "VAT-exempt",
  zero_rated_amount: "Zero-rated",
  withholding_amount: "Tax withheld",
  vat_treatment: "VAT treatment",
  ewt_atc: "ATC",
  paid_on: "Paid on",
  paid_via: "Paid via",
  payment_ref: "Check / ref no.",
  gl_account_code: "Book to account",
  settles_document_id: "Receipt pays",
  period_year: "Year",
  period_quarter: "Quarter",
  period_month: "Month",
  period_locked: "Moved by hand",
  overridden_reasons: "Flags accepted",
  registered_name: "Registered name",
  books_start: "Books start",
  entry_date: "Entry date",
  lines: "Lines",
  useful_life_months: "Useful life (months)",
  in_service: "In service",
  end_date: "End date",
};

const humanize = (key: string) => FIELD_LABELS[key] ?? (key.charAt(0).toUpperCase() + key.slice(1)).replace(/_/g, " ");

function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (key === "category" && typeof value === "string") return CATEGORY_LABELS[value] ?? value;
  if (key === "account" && typeof value === "string") return ACCOUNT_LABELS[value] ?? value;
  if (Array.isArray(value)) {
    if (key === "overridden_reasons") return value.map((r) => REASON_LABELS[String(r)] ?? String(r)).join(", ") || "—";
    if (key === "lines") {
      return value
        .map((l) => {
          const line = l as Record<string, string>;
          const debit = Number(line.debit ?? 0);
          return `${line.account_code} ${debit ? `Dr ${line.debit}` : `Cr ${line.credit}`}`;
        })
        .join(" · ");
    }
    if (value.some((v) => v !== null && typeof v === "object")) return `${value.length} row${value.length === 1 ? "" : "s"}`;
    return value.map(String).join(", ") || "—";
  }
  if (typeof value === "object") {
    const o = value as Record<string, unknown>;
    if ("version" in o) return `v${o.version}${o.filed_on ? ` · filed ${o.filed_on}` : ""}`;
    const text = JSON.stringify(value);
    return text.length > 80 ? `${Object.keys(o).length} fields` : text;
  }
  return String(value);
}

export const actionLabel = (a: string) => ACTION_LABELS[a] ?? humanize(a);
export const formatWhen = (iso: string) =>
  new Date(iso).toLocaleString("en-PH", { dateStyle: "medium", timeStyle: "short" });

interface Props {
  events: AuditEvent[];
  /** Company log: name what each event is about. The document History tab leaves it out. */
  showEntity?: boolean;
}

/** A list of audit events, newest first, each with who, when, why and the fields that changed. */
export default function AuditTrail({ events, showEntity = false }: Props) {
  return (
    <ol className="space-y-2">
      {events.map((e) => {
        const keys = Array.from(new Set([...Object.keys(e.before), ...Object.keys(e.after)]));
        return (
          <li key={e.id} className="rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-3 text-sm">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-semibold text-[var(--text-primary)]">{actionLabel(e.action)}</span>
              {showEntity && (
                <span className="text-[var(--text-secondary)]">
                  {ENTITY_LABELS[e.entity] ?? e.entity}
                  {e.label && ` · ${e.label}`}
                </span>
              )}
              <span className="ml-auto text-xs text-[var(--text-secondary)]">
                {e.user_name} · {formatWhen(e.at)}
              </span>
            </div>
            {e.reason && <p className="mt-1 text-[var(--text-primary)]">“{e.reason}”</p>}
            {keys.length > 0 && (
              <table className="mt-2 w-full table-fixed text-xs">
                <tbody>
                  {keys.map((k) => (
                    <tr key={k} className="align-top">
                      <td className="w-36 py-0.5 pr-2 text-[var(--text-secondary)]">{humanize(k)}</td>
                      <td className="break-words py-0.5 text-[var(--text-secondary)] line-through decoration-[var(--border)] [overflow-wrap:anywhere]">
                        {e.action === "create" ? "" : formatValue(k, e.before[k])}
                      </td>
                      <td className="break-words py-0.5 pl-2 font-medium text-[var(--text-primary)] [overflow-wrap:anywhere]">
                        {e.action === "delete" ? "" : formatValue(k, e.after[k])}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </li>
        );
      })}
    </ol>
  );
}
