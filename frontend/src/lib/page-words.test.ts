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
    const { ocr, pw } = setup({ crop: [0, 0, 1, 1], aspect: 0.77, words, text_layer: true });
    const got = await pw.wordsFor({ ...base, signal: new AbortController().signal });
    expect(got.words).toEqual(words);
    expect(ocr).not.toHaveBeenCalled();
  });

  it("caches per person, file and page", async () => {
    const { layoutFetch, pw } = setup({ crop: [0, 0, 1, 1], aspect: 0.77, words: [[0, 0, 1, 1, "x"]], text_layer: true });
    await pw.wordsFor({ ...base, signal: new AbortController().signal });
    await pw.wordsFor({ ...base, signal: new AbortController().signal });
    expect(layoutFetch).toHaveBeenCalledTimes(1);
    await pw.wordsFor({ ...base, userId: "u2", signal: new AbortController().signal });
    expect(layoutFetch).toHaveBeenCalledTimes(2);
  });

  it("maps OCR words from the trimmed image back to the page", async () => {
    const { pw } = setup({ crop: [0.2, 0.2, 0.6, 0.6], aspect: 1, words: [], text_layer: false }, [[0, 0, 0.5, 0.5, "1,234.50"]]);
    const got = await pw.wordsFor({ ...base, signal: new AbortController().signal });
    got.words[0].slice(0, 4).forEach((v, i) => expect(v).toBeCloseTo([0.2, 0.2, 0.4, 0.4][i], 6));
    expect(got.words[0][4]).toBe("1,234.50");
  });

  it("an aborted request rejects and leaves nothing cached", async () => {
    const { ocr, pw } = setup({ crop: [0, 0, 1, 1], aspect: 1, words: [], text_layer: false }, [[0, 0, 1, 1, "x"]]);
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
