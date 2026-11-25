import { describe, expect, it } from "vitest";
import { recordTargets } from "./extract-targets";
import type { ExtractRecord, ExtractSnapshot } from "@/types/extract";

const snapshot = {
  key: "invoice", name: "Invoice", checks: [], detect_hint: "",
  fields: [
    { key: "total_amount", label: "Total", type: "money", scope: "header" },
    { key: "receipt_number", label: "No.", type: "code", scope: "header" },
    { key: "paid", label: "Paid", type: "boolean", scope: "header" },
    { key: "vat_rate", label: "VAT %", type: "percent", scope: "header" },
    { key: "amount", label: "Amount", type: "money", scope: "row" },
  ],
} as unknown as ExtractSnapshot;

const record = {
  id: "r", file_id: "f", position: 0, page_start: 1, page_end: 1, confidence: 90, edited: [], bad_cells: [], flags: [],
  values: { header: { total_amount: "250.00", receipt_number: "A-1", paid: "true", vat_rate: "12" },
    rows: [{ amount: "10.00" }, { amount: "20.00" }, { amount: "30.00" }, { amount: "40.00" }] },
  hints: { header: { total_amount: { page: 1, box: [0.7, 0.9, 0.8, 0.93] } },
    rows: [{}, {}, {}, { amount: { page: 1, box: [0.7, 0.4, 0.8, 0.42] } }] },
} as unknown as ExtractRecord;

describe("recordTargets", () => {
  const targets = recordTargets(record, snapshot);
  const by = Object.fromEntries(targets.map((t) => [t.key, t]));
  it("keys cells like the flags do and carries their hints", () => {
    expect(by["h:total_amount"]).toMatchObject({ value: "250.00", kind: "money", hint: { page: 1 } });
    expect(by["3:amount"]).toMatchObject({ value: "40.00", kind: "money", hint: { page: 1 } });
    expect(by["0:amount"].hint).toBeUndefined();
  });
  it("maps field types to how they are matched, and skips yes/no fields", () => {
    expect(by["h:receipt_number"].kind).toBe("docno");
    expect(by["h:vat_rate"].kind).toBe("number");
    expect(by["h:paid"]).toBeUndefined();
  });
  it("copes with a record saved before hints existed", () => {
    const old = { ...record, hints: undefined } as unknown as ExtractRecord;
    expect(recordTargets(old, snapshot).every((t) => t.hint === undefined)).toBe(true);
  });
});
