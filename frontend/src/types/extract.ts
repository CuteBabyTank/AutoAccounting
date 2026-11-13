// Extract tab shapes, mirroring backend routers/accounting_extract.py (formats.out / draft_out, _file_out,
// _record_out, list_runs, get_run).

export type ExtractFieldType = "text" | "number" | "money" | "date" | "tin" | "percent" | "code" | "boolean";
export type ExtractScope = "header" | "row";
export type ExtractLevel = "red" | "yellow";
export type ExtractCheckKind =
  | "required" | "sum" | "percent_of" | "rows_sum" | "row_product" | "date_order" | "same_quarter"
  | "not_future" | "format" | "one_of" | "range" | "not_more_than" | "differs";

export interface ExtractField {
  key: string;
  label: string;
  type: ExtractFieldType;
  scope: ExtractScope;
  required: boolean;
  description: string;
}

/** A catalogue check with its plain sentence; the params present depend on `kind` (backend spec._kind_params). */
export interface ExtractCheck {
  id: string;
  kind: ExtractCheckKind;
  level: ExtractLevel;
  sentence: string;
  field?: string;
  target?: string;
  base?: string;
  terms?: { field: string; sign: 1 | -1 }[];
  scope?: ExtractScope;
  rates?: number[];
  inclusive?: boolean;
  row_field?: string;
  a?: string;
  b?: string;
  first?: string;
  last?: string;
  pattern?: "tin" | "atc" | "zip";
  values?: string[];
  min?: string | null;
  max?: string | null;
  limit_field?: string;
}

/** A format the firm can use: a built-in (key = built-in key) or a firm row (key = its id). `edited` marks the
 *  firm's copy of a built-in. */
export interface ExtractFormat {
  key: string;
  name: string;
  description: string;
  builtin: boolean;
  edited: boolean;
  fields: ExtractField[];
  checks: ExtractCheck[];
  detect_hint: string;
  version: number;
}

/** What a run kept of a format (GET /runs/{id} `snapshots`). */
export interface ExtractSnapshot {
  key: string;
  name: string;
  fields: ExtractField[];
  checks: ExtractCheck[];
  detect_hint: string;
}

export interface ExtractDraftField extends ExtractField {
  value: string;
  picked: boolean;
}

export interface ExtractDraft {
  id: string;
  name: string;
  detect_hint: string;
  fields: ExtractDraftField[];
  checks: ExtractCheck[];
  asks_left: number;
  page_count: number;
}

export interface ExtractMissingResult {
  added: ExtractDraftField[];
  not_found: string[];
  asks_left: number;
  checks: ExtractCheck[];
}

export interface ExtractFormatInput {
  draft_id?: string | null;
  name: string;
  description: string;
  picks: { key: string; label: string; required: boolean }[];
  check_ids: string[];
}

export interface ExtractCell {
  key: string;
  row: number | null;
}

export interface ExtractFlag {
  check_id: string;
  level: ExtractLevel;
  message: string;
  cells: ExtractCell[];
}

export interface ExtractValues {
  header: Record<string, string | null>;
  rows: Record<string, string | null>[];
}

export interface ExtractRecord {
  id: string;
  file_id: string;
  position: number;
  page_start: number;
  page_end: number;
  confidence: number | null;
  values: ExtractValues;
  edited: ExtractCell[];
  bad_cells: ExtractCell[];
  flags: ExtractFlag[];
}

export interface ExtractRecordPage {
  format_key: string | null;
  total: number;
  offset: number;
  records: ExtractRecord[];
}

export type ExtractFileStatus = "queued" | "detecting" | "reading" | "choose" | "done" | "error";
export type ExtractRunStatus = "reading" | "done" | "failed";

export interface ExtractFile {
  id: string;
  name: string;
  file_type: string;
  page_count: number;
  status: ExtractFileStatus;
  format_key: string | null;
  detect_confidence: number | null;
  error: string;
  interrupts: number;
}

export interface ExtractFormatCount {
  format_key: string;
  name: string;
  records: number;
  red: number;
  yellow: number;
}

export interface ExtractRun {
  id: string;
  format_key: string;
  format_name: string;
  status: ExtractRunStatus;
  created_at: string;
  created_by: string | null;
  created_by_name: string;
  can_delete: boolean;
  snapshots: Record<string, ExtractSnapshot>;
  files: ExtractFile[];
  formats: ExtractFormatCount[];
}

/** A row of "Past extracts" (GET /runs). */
export interface ExtractRunSummary {
  id: string;
  format_key: string;
  format_name: string;
  status: ExtractRunStatus;
  created_at: string;
  created_by: string | null;
  created_by_name: string;
  file_count: number;
  record_count: number;
  red_count: number;
  yellow_count: number;
}

export interface ExtractEdit {
  key: string;
  row: number | null;
  value: string;
}
