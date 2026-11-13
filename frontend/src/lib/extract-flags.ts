// Pure helpers for the Extract run screen: which flags sit on which cell, level precedence, display text.
import type { ExtractCell, ExtractFieldType, ExtractFlag, ExtractLevel, ExtractRecord } from "@/types/extract";

/** Records per table page (the server allows up to 200). */
export const PAGE_SIZE = 100;
/** The server's cap on one edited value (runner.MAX_EDIT_CHARS). */
export const MAX_VALUE_CHARS = 500;
/** The check id the server gives the low-confidence marker (no cells: it marks the whole record). */
export const CONFIDENCE_CHECK = "confidence";

/** A stable id for a cell: header cells have row null, table rows count from 0. */
export const cellId = (key: string, row: number | null): string => `${row === null ? "h" : row}:${key}`;
export const cellIdOf = (cell: ExtractCell): string => cellId(cell.key, cell.row);

/** Red beats yellow; null when there is nothing. */
export function worst(levels: Iterable<ExtractLevel>): ExtractLevel | null {
  let out: ExtractLevel | null = null;
  for (const level of levels) {
    if (level === "red") return "red";
    out = "yellow";
  }
  return out;
}

/** Each flagged cell's flags (a flag naming several cells appears under each). */
export function flagsByCell(record: ExtractRecord): Map<string, ExtractFlag[]> {
  const out = new Map<string, ExtractFlag[]>();
  for (const flag of record.flags) {
    for (const cell of flag.cells ?? []) {
      const id = cellIdOf(cell);
      const list = out.get(id);
      if (list) {
        if (!list.includes(flag)) list.push(flag);
      } else out.set(id, [flag]);
    }
  }
  return out;
}

/** Flags about the whole record (no cells), e.g. the low-confidence marker. */
export const recordWideFlags = (record: ExtractRecord): ExtractFlag[] => record.flags.filter((f) => !f.cells?.length);

export const lowConfidence = (record: ExtractRecord): boolean =>
  record.flags.some((f) => f.check_id === CONFIDENCE_CHECK);

/** The worst level among flags that touch any table-row cell (the "Lines" column). */
export const rowsLevel = (record: ExtractRecord): ExtractLevel | null =>
  worst(record.flags.filter((f) => f.cells?.some((c) => c.row !== null)).map((f) => f.level));

export const recordLevel = (record: ExtractRecord): ExtractLevel | null => worst(record.flags.map((f) => f.level));

export const editedCells = (record: ExtractRecord): Set<string> => new Set(record.edited.map(cellIdOf));

/** The first cell a flag points at, or null for a record-wide flag. */
export const firstCell = (flag: ExtractFlag): ExtractCell | null => flag.cells?.[0] ?? null;

const NUMERIC: ReadonlySet<ExtractFieldType> = new Set(["money", "number", "percent"]);
export const isNumeric = (type: ExtractFieldType): boolean => NUMERIC.has(type);

/** "1234567.5" -> "1,234,567.50" for money; other types as stored. Unparseable text is shown as it is. */
export function displayValue(value: string | null | undefined, type: ExtractFieldType): string {
  const text = value ?? "";
  if (!text) return "";
  if (type === "boolean") return text === "true" ? "Yes" : text === "false" ? "No" : text;
  if (type !== "money" && type !== "number") return type === "percent" && /^-?\d+(\.\d+)?$/.test(text) ? `${text}%` : text;
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!m) return text;
  const whole = m[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const frac = type === "money" ? `.${(m[3] ?? "").padEnd(2, "0")}` : m[3] ? `.${m[3]}` : "";
  return `${m[1]}${whole}${frac}`;
}

/** "1–100 of 734" (an empty page reads "0 of 0"). */
export function rangeLabel(offset: number, count: number, total: number): string {
  if (count === 0) return `0 of ${total}`;
  return `${offset + 1}–${offset + count} of ${total}`;
}

export const pagesLabel = (start: number, end: number): string => (end > start ? `${start}–${end}` : `${start}`);

export const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Theme classes per level (globals.css vars, light and dark). */
export const LEVEL_CELL: Record<ExtractLevel, string> = {
  red: "bg-[var(--badge-red-bg)] shadow-[inset_3px_0_0_var(--error)]",
  yellow: "bg-[var(--badge-yellow-bg)] shadow-[inset_3px_0_0_var(--warning)]",
};
export const LEVEL_TEXT: Record<ExtractLevel, string> = {
  red: "text-[var(--badge-red-text)]",
  yellow: "text-[var(--badge-yellow-text)]",
};
export const LEVEL_INPUT: Record<ExtractLevel, string> = {
  red: "!border-[var(--error)] bg-[var(--badge-red-bg)]",
  yellow: "!border-[var(--warning)] bg-[var(--badge-yellow-bg)]",
};
export const LEVEL_WORD: Record<ExtractLevel, string> = { red: "Wrong", yellow: "Check" };

/** A flag as a sentence; row checks name their line ("Line 3: Quantity x unit price = amount (…)"). */
export function flagSentence(flag: ExtractFlag): string {
  const row = flag.cells?.find((c) => c.row !== null)?.row;
  return row === undefined || row === null ? flag.message : `Line ${row + 1}: ${flag.message}`;
}
