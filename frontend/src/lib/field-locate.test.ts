import { describe, expect, it } from "vitest";
import { boxInShown, locate, type Word } from "./field-locate";

// A receipt line: "Total ₱1,234.50" around y = 0.50, "Date Nov 3, 2026" around y = 0.10.
const w = (x0: number, y0: number, x1: number, y1: number, t: string): Word => [x0, y0, x1, y1, t];
const total = w(0.6, 0.5, 0.75, 0.52, "₱1,234.50");
const words: Word[] = [
  w(0.1, 0.1, 0.16, 0.12, "Date"), w(0.2, 0.1, 0.24, 0.12, "Nov"), w(0.25, 0.1, 0.27, 0.12, "3,"), w(0.28, 0.1, 0.34, 0.12, "2026"),
  w(0.1, 0.2, 0.2, 0.22, "Juan"), w(0.21, 0.2, 0.28, 0.22, "Dela"), w(0.29, 0.2, 0.36, 0.22, "Cruz"), w(0.37, 0.2, 0.5, 0.22, "Hardware"),
  w(0.1, 0.3, 0.3, 0.32, "123-456-789-000"), w(0.1, 0.4, 0.18, 0.42, "Cash"),
  w(0.1, 0.5, 0.2, 0.52, "Total"), total,
];
const hintAt = (r: number[]) => ({ page: 1, box: r as [number, number, number, number] });
const pad = (r: number[]) => [r[0] - 0.01, r[1] - 0.01, r[2] + 0.01, r[3] + 0.01];

describe("locate", () => {
  it("finds an amount inside its hint, padded", () => {
    const got = locate("1234.50", "money", words, hintAt([0.58, 0.48, 0.8, 0.54]), 1)!;
    got.forEach((v, i) => expect(v).toBeCloseTo(pad(total.slice(0, 4) as number[])[i], 6));
  });
  it("never trusts an amount without a hint", () => {
    expect(locate("1234.50", "money", words, undefined, 1)).toBeNull();
  });
  it("needs the hint to pick exactly one of two equal amounts", () => {
    const sub = w(0.6, 0.45, 0.75, 0.47, "1,234.50");
    const two = [...words, sub];
    expect(locate("1234.50", "money", two, hintAt([0.58, 0.49, 0.8, 0.54]), 1)![1]).toBeCloseTo(0.49, 6);
    expect(locate("1234.50", "money", two, undefined, 1)).toBeNull();
    expect(locate("1234.50", "money", two, hintAt([0.5, 0.4, 0.9, 0.6]), 1)).toBeNull();
  });
  it("refuses a single match outside the hint", () => {
    expect(locate("1234.50", "money", words, hintAt([0.1, 0.8, 0.3, 0.9]), 1)).toBeNull();
  });
  it("matches written dates", () => {
    expect(locate("2026-11-03", "date", words, undefined, 1)).not.toBeNull();
    expect(locate("2026-11-03", "date", [w(0.1, 0.1, 0.2, 0.12, "11/03/2026")], undefined, 1)).not.toBeNull();
    expect(locate("2026-11-04", "date", words, undefined, 1)).toBeNull();
  });
  it("matches a TIN by its digits, branch code included", () => {
    expect(locate("123456789", "tin", words, undefined, 1)).not.toBeNull();
  });
  it("takes several-word text without a hint, never one word", () => {
    const got = locate("Juan Dela Cruz Hardware", "text", words, undefined, 1)!;
    expect(got[0]).toBeCloseTo(0.09, 6);
    expect(got[2]).toBeCloseTo(0.51, 6);
    expect(locate("Cash", "text", words, undefined, 1)).toBeNull();
    expect(locate("Cash", "text", words, hintAt([0.05, 0.38, 0.25, 0.45]), 1)).not.toBeNull();
  });
  it("skips computed fields, other pages and edited values", () => {
    expect(locate("1234.50", "money", words, { computed: true }, 1)).toBeNull();
    expect(locate("1234.50", "money", words, { page: 2, box: [0.58, 0.48, 0.8, 0.54] }, 1)).toBeNull();
    expect(locate("999.00", "money", words, hintAt([0.58, 0.48, 0.8, 0.54]), 1)).toBeNull();
    expect(locate("", "text", words, undefined, 1)).toBeNull();
  });
});

describe("boxInShown", () => {
  it("maps into the trimmed image", () => {
    const got = boxInShown([0.5, 0.5, 0.6, 0.6], [0.1, 0.1, 0.9, 0.9], 1, 1)!;
    [0.5, 0.5, 0.625, 0.625].forEach((v, i) => expect(got[i]).toBeCloseTo(v, 6));
  });
  it("draws nothing when the image isn't the crop it claims", () => {
    expect(boxInShown([0.5, 0.5, 0.6, 0.6], [0.1, 0.1, 0.9, 0.9], 1.05, 1)).toBeNull();
    expect(boxInShown([0.5, 0.5, 0.6, 0.6], null, 1, 1)).toBeNull();
    expect(boxInShown([0.0, 0.0, 0.05, 0.05], [0.1, 0.1, 0.9, 0.9], 1, 1)).toBeNull();
  });
});
