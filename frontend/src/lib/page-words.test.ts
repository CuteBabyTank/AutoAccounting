import { describe, expect, it, vi } from "vitest";
import { createPageWords, type PageLayout } from "./page-words";
import type { Word } from "./field-locate";

const base = { src: "accounting" as const, fileId: "f1", page: 1, userId: "u1", imageUrl: "blob:x", width: 100, height: 200 };

function setup(layout: PageLayout, ocrWords: Word[] = []) {
  const layoutFetch = vi.fn(async () => layout);
  const ocr = vi.fn(async () => ocrWords);
  return { layoutFetch, ocr, pw: createPageWords({ layoutFetch, ocr, store: null }) };
}

describe("wordsFor", () => {
  it("uses the PDF's text layer without OCR", async () => {
    const words: Word[] = [[0.1, 0.1, 0.2, 0.12, "Total"]];
    const { ocr, pw } = setup({ crop: [0, 0, 1, 1], aspect: 0.5, words, text_layer: true });
    const got = await pw.wordsFor({ ...base, signal: new AbortController().signal });
    expect(got.words).toEqual(words);
    expect(ocr).not.toHaveBeenCalled();
  });

  it("caches per person, file and page", async () => {
    const { layoutFetch, pw } = setup({ crop: [0, 0, 1, 1], aspect: 0.5, words: [[0, 0, 1, 1, "x"]], text_layer: true });
    await pw.wordsFor({ ...base, signal: new AbortController().signal });
    await pw.wordsFor({ ...base, signal: new AbortController().signal });
    expect(layoutFetch).toHaveBeenCalledTimes(1);
    await pw.wordsFor({ ...base, userId: "u2", signal: new AbortController().signal });
    expect(layoutFetch).toHaveBeenCalledTimes(2);
  });

  it("maps OCR words from the trimmed image back to the page", async () => {
    const { pw } = setup({ crop: [0.2, 0.2, 0.6, 0.6], aspect: 1, words: [], text_layer: false }, [[0, 0, 0.5, 0.5, "1,234.50"]]);
    const got = await pw.wordsFor({ ...base, width: 100, height: 100, signal: new AbortController().signal });
    got.words[0].slice(0, 4).forEach((v, i) => expect(v).toBeCloseTo([0.2, 0.2, 0.4, 0.4][i], 6));
    expect(got.words[0][4]).toBe("1,234.50");
  });

  it("an aborted request rejects and leaves nothing cached", async () => {
    const { ocr, pw } = setup({ crop: [0, 0, 1, 1], aspect: 0.5, words: [], text_layer: false }, [[0, 0, 1, 1, "x"]]);
    const ctl = new AbortController();
    ctl.abort();
    await expect(pw.wordsFor({ ...base, signal: ctl.signal })).rejects.toMatchObject({ name: "AbortError" });
    await pw.wordsFor({ ...base, signal: new AbortController().signal });
    expect(ocr).toHaveBeenCalledTimes(1);
  });

  it("a photo the server won't place gets no OCR at all", async () => {
    const { ocr, pw } = setup({ crop: null, aspect: 1, words: [], text_layer: false });
    const got = await pw.wordsFor({ ...base, signal: new AbortController().signal });
    expect(got.crop).toBeNull();
    expect(got.words).toEqual([]);
    expect(ocr).not.toHaveBeenCalled();
  });
});

describe("sign-out", () => {
  it("drops a page that finishes after clear: nothing is kept for the next person", async () => {
    let release: (l: PageLayout) => void = () => undefined;
    const layoutFetch = vi.fn(() => new Promise<PageLayout>((r) => { release = r; }));
    const put = vi.fn(async () => undefined);
    const pw = createPageWords({ layoutFetch, ocr: vi.fn(async () => []), store: { get: async () => undefined, put } });
    const pending = pw.wordsFor({ ...base, signal: new AbortController().signal });
    await new Promise((r) => setTimeout(r, 0));   // the layout request is out
    pw.clear();
    release({ crop: [0, 0, 1, 1], aspect: 1, words: [[0, 0, 1, 1, "x"]], text_layer: true });
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(put).not.toHaveBeenCalled();
  });
});

describe("the image must be the page the layout describes", () => {
  it("refuses to OCR (and caches nothing) when the image's shape doesn't match the crop", async () => {
    const put = vi.fn(async () => undefined);
    const ocr = vi.fn(async () => [[0, 0, 1, 1, "x"]] as Word[]);
    const layout: PageLayout = { crop: [0, 0, 1, 1], aspect: 0.77, words: [], text_layer: false };
    const pw = createPageWords({ layoutFetch: async () => layout, ocr, store: { get: async () => undefined, put } });
    const got = await pw.wordsFor({ ...base, width: 100, height: 100, signal: new AbortController().signal });  // square image
    expect(got.words).toEqual([]);
    expect(ocr).not.toHaveBeenCalled();
    expect(put).not.toHaveBeenCalled();
  });
  it("a different image size is a different cache entry", async () => {
    const ocr = vi.fn(async () => [[0, 0, 1, 1, "x"]] as Word[]);
    const pw = createPageWords({ layoutFetch: async () => ({ crop: [0, 0, 1, 1], aspect: 0.5, words: [], text_layer: false }), ocr, store: null });
    await pw.wordsFor({ ...base, width: 100, height: 200, signal: new AbortController().signal });
    await pw.wordsFor({ ...base, width: 200, height: 400, signal: new AbortController().signal });
    expect(ocr).toHaveBeenCalledTimes(2);
  });
  it("keeps a PDF's own text out of browser storage", async () => {
    const put = vi.fn(async () => undefined);
    const pw = createPageWords({ layoutFetch: async () => ({ crop: [0, 0, 1, 1], aspect: 0.5, words: [[0, 0, 1, 1, "x"]], text_layer: true }),
      ocr: vi.fn(async () => []), store: { get: async () => undefined, put } });
    await pw.wordsFor({ ...base, signal: new AbortController().signal });
    expect(put).not.toHaveBeenCalled();
  });
});
