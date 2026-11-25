/** Field boxes: find where a field's value is printed on a page (pure).
 *
 *  The words come from the PDF's own text layer or from OCR in the browser (`page-words.ts`); the reader's hint
 *  (`field_hints` on a document, `hints` on an Extract record) only says roughly where it read the value. A box is
 *  returned only when it is certain: never the hint itself, never a guess between two equal values, never a lone
 *  amount without a hint (a "120.00" printed once may still be another line). No box is better than a wrong box. */

/** [x0, y0, x1, y1] as fractions of the untrimmed page. */
export type Rect = [number, number, number, number];
/** A word with its box: [x0, y0, x1, y1, text]. */
export type Word = [number, number, number, number, string];
export type Hint = { page: number; box: Rect } | { computed: true };
export type FieldKind = "money" | "number" | "date" | "tin" | "docno" | "text";

const MAX_RUN = 6;        // words one value may span
const PAD = 0.01;
const HINT_GROW = 0.25;   // the hint box grows by this share of its size on every side
const MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
  "november", "december"];

const alnum = (s: string) => s.normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
const digits = (s: string) => s.replace(/\D/g, "");

function amount(s: string): string | null {
  const t = s.normalize("NFKC").replace(/₱|php|p(?=\d)|\s/gi, "");
  const m = /^(-)?\(?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\)?(-)?$/.exec(t);
  if (!m) return null;
  const n = Number(`${m[2].replace(/,/g, "")}${m[3] ?? ""}`);
  if (!Number.isFinite(n)) return null;
  const negative = !!m[1] || !!m[4] || (t.startsWith("(") && t.endsWith(")"));
  return (negative ? -n : n).toFixed(2);
}

function dateForms(iso: string): Set<string> {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso.trim());
  if (!m) return new Set();
  const [y, mm, dd] = [m[1], m[2], m[3]];
  const mon = MONTHS[Number(mm) - 1];
  if (!mon) return new Set();
  const d = String(Number(dd));
  const mo = String(Number(mm));
  const yy = y.slice(2);
  const out = new Set<string>();
  for (const day of new Set([d, dd])) {
    for (const month of new Set([mo, mm])) {
      out.add(`${month}${day}${y}`).add(`${day}${month}${y}`).add(`${month}${day}${yy}`).add(`${day}${month}${yy}`);
    }
    for (const name of [mon, mon.slice(0, 3), mon.slice(0, 4)]) {
      out.add(`${name}${day}${y}`).add(`${day}${name}${y}`).add(`${y}${name}${day}`);
    }
  }
  out.add(`${y}${mm}${dd}`);
  return out;
}

/** Whether a run of words reads as the value. */
function matcher(value: string, kind: FieldKind): ((text: string) => boolean) | null {
  if (kind === "money" || kind === "number") {
    const want = amount(value);
    return want === null ? null : (t) => amount(t) === want;
  }
  if (kind === "date") {
    const forms = dateForms(value);
    return forms.size ? (t) => forms.has(alnum(t)) : null;
  }
  if (kind === "tin") {
    const want = digits(value);
    if (want.length < 9) return null;
    return (t) => /^[\d\s.\-/]+$/.test(t.trim()) && digits(t).length <= 14 && digits(t).startsWith(want);
  }
  const want = alnum(value);
  return want ? (t) => alnum(t) === want : null;
}

const sameLine = (a: Word, b: Word) => {
  const h = Math.max(a[3] - a[1], b[3] - b[1]);
  return Math.abs((a[1] + a[3]) / 2 - (b[1] + b[3]) / 2) <= h / 2 && b[0] >= a[0];
};

const union = (ws: Word[]): Rect =>
  [Math.min(...ws.map((x) => x[0])), Math.min(...ws.map((x) => x[1])), Math.max(...ws.map((x) => x[2])),
    Math.max(...ws.map((x) => x[3]))];

/** Places on the page that read as the value: runs of words on one line, overlapping runs counted once. */
function places(words: Word[], test: (text: string) => boolean): Rect[] {
  const runs: [number, number][] = [];
  for (let i = 0; i < words.length; i++) {
    let text = "";
    for (let j = i; j < Math.min(words.length, i + MAX_RUN); j++) {
      if (j > i && !sameLine(words[j - 1], words[j])) break;
      text = j > i ? `${text} ${words[j][4]}` : words[j][4];
      if (test(text)) runs.push([i, j + 1]);
    }
  }
  // A run that contains another is the same place read with a neighbour ("₱" + "1,234.50"): keep the shorter.
  const kept = runs.filter(([a, b]) => !runs.some(([c, d]) => (c !== a || d !== b) && a <= c && d <= b));
  kept.sort((x, y) => x[0] - y[0]);
  const merged: [number, number][] = [];
  for (const r of kept) {
    const last = merged[merged.length - 1];
    if (last && r[0] < last[1]) last[1] = Math.max(last[1], r[1]);
    else merged.push([r[0], r[1]]);
  }
  return merged.map(([a, b]) => union(words.slice(a, b)));
}

function inside(r: Rect, hint: Rect): boolean {
  const gx = (hint[2] - hint[0]) * HINT_GROW;
  const gy = (hint[3] - hint[1]) * HINT_GROW;
  const cx = (r[0] + r[2]) / 2;
  const cy = (r[1] + r[3]) / 2;
  return cx >= hint[0] - gx && cx <= hint[2] + gx && cy >= hint[1] - gy && cy <= hint[3] + gy;
}

const padded = (r: Rect): Rect =>
  [Math.max(0, r[0] - PAD), Math.max(0, r[1] - PAD), Math.min(1, r[2] + PAD), Math.min(1, r[3] + PAD)];

/** Values distinctive enough to trust one match on the page without the reader's hint. */
function distinctive(value: string, kind: FieldKind): boolean {
  if (kind === "tin" || kind === "docno" || kind === "date") return true;
  return kind === "text" && value.trim().split(/\s+/).filter((p) => alnum(p)).length >= 2;
}

/** The box of `value` on page `page` (untrimmed fractions, padded), or null when it can't be placed for certain. */
export function locate(value: string, kind: FieldKind, words: Word[], hint: Hint | undefined, page: number): Rect | null {
  if (!value.trim() || (hint && "computed" in hint)) return null;
  if (hint && hint.page !== page) return null;
  const test = matcher(value, kind);
  if (!test) return null;
  const found = places(words, test);
  if (hint) {
    const near = found.filter((r) => inside(r, hint.box));
    return near.length === 1 ? padded(near[0]) : null;
  }
  return found.length === 1 && distinctive(value, kind) ? padded(found[0]) : null;
}

/** A box (untrimmed fractions) in the shown, trimmed image's fractions; null when the image isn't the crop the
 *  layout describes (aspect off by > 2%) or the box falls outside it. */
export function boxInShown(box: Rect, crop: Rect | null, shownAspect: number, pageAspect: number): Rect | null {
  if (!crop) return null;
  const cw = crop[2] - crop[0];
  const ch = crop[3] - crop[1];
  if (cw <= 0 || ch <= 0 || !(shownAspect > 0) || !(pageAspect > 0)) return null;
  if (Math.abs(shownAspect / (pageAspect * (cw / ch)) - 1) > 0.02) return null;
  const sx = 0.02 * cw;
  const sy = 0.02 * ch;
  if (box[0] < crop[0] - sx || box[1] < crop[1] - sy || box[2] > crop[2] + sx || box[3] > crop[3] + sy) return null;
  const clamp = (v: number) => Math.min(1, Math.max(0, v));
  return [clamp((box[0] - crop[0]) / cw), clamp((box[1] - crop[1]) / ch), clamp((box[2] - crop[0]) / cw),
    clamp((box[3] - crop[1]) / ch)];
}
