// Field boxes on the Extract record panel: the cells the scan can outline (lib/field-locate.ts), keyed like the
// flags (`cellId`), with the reader's hint for each (`record.hints`, absent on records read before hints).
import { cellId } from "@/lib/extract-flags";
import type { FieldKind, FieldTarget } from "@/lib/field-locate";
import type { ExtractFieldType, ExtractRecord, ExtractSnapshot } from "@/types/extract";

const KINDS: Partial<Record<ExtractFieldType, FieldKind>> = {
  money: "money", number: "number", percent: "number", date: "date", tin: "tin", code: "docno", text: "text",
};

/** `typing`: cells being edited and not saved yet (by cell id); their typed text wins over the saved value. */
export function recordTargets(record: ExtractRecord, snapshot: ExtractSnapshot,
  typing: Record<string, string> = {}): FieldTarget[] {
  const out: FieldTarget[] = [];
  const add = (key: string, row: number | null, type: ExtractFieldType, value: unknown, hint: unknown) => {
    const kind = KINDS[type];
    if (!kind) return;   // yes / no fields aren't printed as a value to point at
    const id = cellId(key, row);
    const text = id in typing ? typing[id] : value == null ? "" : String(value);
    out.push({ key: id, kind, value: text,
      ...(hint && typeof hint === "object" ? { hint: hint as FieldTarget["hint"] } : {}) });
  };
  for (const f of snapshot.fields) {
    if (f.scope === "header") add(f.key, null, f.type, record.values.header?.[f.key], record.hints?.header?.[f.key]);
  }
  const rowFields = snapshot.fields.filter((f) => f.scope === "row");
  (record.values.rows ?? []).forEach((row, i) => {
    for (const f of rowFields) add(f.key, i, f.type, row?.[f.key], record.hints?.rows?.[i]?.[f.key]);
  });
  return out;
}
