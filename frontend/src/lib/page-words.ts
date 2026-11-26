/** Field boxes: the words printed on a page, with their positions as fractions of the untrimmed page.
 *
 *  Only for a page someone opens. A PDF with a text layer gets its words from the server (a millisecond read, no
 *  rendering); a photo or scan is read here, in the person's browser, with Tesseract.js in a Web Worker (files
 *  self-hosted in /ocr/, copied by scripts/copy-ocr.mjs). One OCR job at a time per tab, only while the tab is
 *  visible. Results are kept in memory and in IndexedDB per person; both are cleared on sign-out
 *  (`clearPageWords`, called from personal-storage.ts; keep public/app.js in step). */
import type { Rect, Word } from "@/lib/field-locate";

export interface PageLayout {
  /** The part of the page the trimmed image shows; null = don't place boxes on this page. */
  crop: Rect | null;
  /** The untrimmed page's width / height. */
  aspect: number;
  words: Word[];
  text_layer: boolean;
}

export interface PageWords {
  crop: Rect | null;
  aspect: number;
  words: Word[];
}

export interface WordsRequest {
  src: "accounting" | "extract";
  fileId: string;
  page: number;
  userId: string;
  /** The shown (trimmed) image, and its natural size in pixels. */
  imageUrl: string;
  width: number;
  height: number;
  signal: AbortSignal;
}

interface Store {
  get(key: string): Promise<PageWords | undefined>;
  put(key: string, value: PageWords): Promise<void>;
  /** Drop every page kept for anyone but this person (a shared browser whose last user closed the tab). */
  purgeOthers?(userId: string): Promise<void>;
}

interface Deps {
  layoutFetch: (src: WordsRequest["src"], fileId: string, page: number) => Promise<PageLayout>;
  /** OCR of the shown image: words as fractions of that image. */
  ocr: (imageUrl: string, width: number, height: number) => Promise<Word[]>;
  store: Store | null;
  /** Pages kept in memory (oldest dropped first). */
  memoryCap?: number;
}

/** Bump when how words are read changes (OCR scale, data, cut-off), so pages cached the old way are read again. */
const WORDS_VERSION = 2;

/** Browser-store keys to drop when `userId` reads pages: anyone else's, and this person's from an older version. */
export function keysToPurge(keys: string[], userId: string): string[] {
  const mine = `v${WORDS_VERSION}:${userId}:`;
  return keys.filter((k) => !k.startsWith(mine));
}

const abortError = () => Object.assign(new Error("Aborted"), { name: "AbortError" });

function untilVisible(signal: AbortSignal): Promise<void> {
  if (typeof document === "undefined" || document.visibilityState === "visible") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const done = () => {
      document.removeEventListener("visibilitychange", check);
      signal.removeEventListener("abort", stop);
    };
    const check = () => { if (document.visibilityState === "visible") { done(); resolve(); } };
    const stop = () => { done(); reject(abortError()); };
    document.addEventListener("visibilitychange", check);
    signal.addEventListener("abort", stop);
  });
}

export function createPageWords(deps: Deps) {
  const memory = new Map<string, PageWords>();
  const cap = deps.memoryCap ?? 60;
  const remember = (key: string, value: PageWords) => {
    memory.delete(key);
    memory.set(key, value);
    while (memory.size > cap) memory.delete(memory.keys().next().value as string);
  };
  let queue: Promise<unknown> = Promise.resolve();   // one OCR job at a time
  let generation = 0;   // bumped on sign-out: anything still in flight is dropped, never kept
  let owner: string | null = null;   // the person whose pages the store was last checked for

  async function wordsFor(req: WordsRequest): Promise<PageWords> {
    if (owner !== req.userId) {
      owner = req.userId;
      await deps.store?.purgeOthers?.(req.userId).catch(() => undefined);
    }
    // The image size is part of the key: words are only good for the exact image they were read from.
    const key = `v${WORDS_VERSION}:${req.userId}:${req.src}:${req.fileId}:${req.page}:${req.width}x${req.height}`;
    const gen = generation;
    const stale = () => req.signal.aborted || gen !== generation;
    if (stale()) throw abortError();
    const hit = memory.get(key) ?? (await deps.store?.get(key).catch(() => undefined));
    if (stale()) throw abortError();
    if (hit) {
      remember(key, hit);
      return hit;
    }
    const layout = await deps.layoutFetch(req.src, req.fileId, req.page);
    if (stale()) throw abortError();
    let result: PageWords;
    const crop = layout.crop;
    const shapeOk = !!crop && req.width > 0 && req.height > 0 && layout.aspect > 0 &&
      Math.abs((req.width / req.height) / (layout.aspect * ((crop[2] - crop[0]) / (crop[3] - crop[1]))) - 1) <= 0.02;
    if (!crop || !shapeOk) {
      // Not the image this layout describes (a stale cached image, a render fallback): no words, nothing kept.
      return { crop: null, aspect: layout.aspect, words: [] };
    } else if (layout.text_layer) {
      // The PDF's own text: cheap to fetch again, so it stays in memory only, never in browser storage.
      result = { crop, aspect: layout.aspect, words: layout.words };
      remember(key, result);
      return result;
    } else {
      const job = queue.then(async () => {
        await untilVisible(req.signal);
        if (stale()) throw abortError();
        return deps.ocr(req.imageUrl, req.width, req.height);
      });
      queue = job.catch(() => undefined);
      const shown = await job;
      if (gen !== generation) throw abortError();   // signed out meanwhile: keep nothing
      const [cx0, cy0, cx1, cy1] = crop;
      const cw = cx1 - cx0;
      const ch = cy1 - cy0;
      result = {
        crop, aspect: layout.aspect,
        words: shown.map(([x0, y0, x1, y1, t]) => [cx0 + x0 * cw, cy0 + y0 * ch, cx0 + x1 * cw, cy0 + y1 * ch, t]),
      };
      // Kept even when the page was left meanwhile (OCR can't be interrupted): reopening it needs no second read.
      remember(key, result);
      void deps.store?.put(key, result).catch(() => undefined);
      if (req.signal.aborted) throw abortError();
    }
    return result;
  }

  return {
    wordsFor,
    clear: () => {
      generation += 1;
      memory.clear();
      owner = null;
    },
  };
}

// ---- The browser's instance: API layout routes, Tesseract.js, IndexedDB ----

const DB = "aa-page-words";
const KEEP_MS = 7 * 24 * 3600 * 1000;
const MAX_BYTES = 20 * 1024 * 1024;
const MIN_CONFIDENCE = 60;
const OCR_SIDE = 3000;
const OCR_MAX_SCALE = 2.5;   // OCR words it isn't sure of are left out (no box beats a wrong box)

function idb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(DB, 1);
    open.onupgradeneeded = () => open.result.createObjectStore("pages", { keyPath: "key" });
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  });
}

function request<T>(r: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

interface Row { key: string; at: number; size: number; value: PageWords }

let storeGen = 0;   // bumped on sign-out: a write that was waiting for the database is dropped
let openDb: IDBDatabase | null = null;   // closed before the sign-out delete, which an open connection would block

function browserStore(): Store | null {
  if (typeof indexedDB === "undefined") return null;
  let ready: Promise<IDBDatabase> | null = null;
  const db = () => {
    ready ??= idb().then(async (d) => {
      openDb = d;
      d.onversionchange = () => d.close();   // a delete from another tab's sign-out goes through
      try {   // prune: old entries, then the oldest past the size cap
        const rows = (await request(d.transaction("pages").objectStore("pages").getAll())) as Row[];
        const now = Date.now();
        rows.sort((a, b) => b.at - a.at);
        let total = 0;
        const drop = rows.filter((r) => (total += r.size) > MAX_BYTES || now - r.at > KEEP_MS);
        if (drop.length) {
          const tx = d.transaction("pages", "readwrite");
          drop.forEach((r) => tx.objectStore("pages").delete(r.key));
        }
      } catch {
        // pruning is best effort
      }
      return d;
    });
    return ready;
  };
  return {
    async get(key) {
      const row = (await request((await db()).transaction("pages").objectStore("pages").get(key))) as Row | undefined;
      return row && Date.now() - row.at <= KEEP_MS ? row.value : undefined;
    },
    async purgeOthers(userId) {
      const d = await db();
      const keys = (await request(d.transaction("pages").objectStore("pages").getAllKeys())) as string[];
      const others = keysToPurge(keys, userId);
      if (!others.length) return;
      const tx = d.transaction("pages", "readwrite");
      others.forEach((k) => tx.objectStore("pages").delete(k));
    },
    async put(key, value) {
      const size = JSON.stringify(value).length;
      const gen = storeGen;
      const d = await db();
      if (gen !== storeGen) return;   // signed out while the database opened: keep nothing
      await request(d.transaction("pages", "readwrite").objectStore("pages")
        .put({ key, at: Date.now(), size, value } satisfies Row));
    },
  };
}

type TesseractWorker = Awaited<ReturnType<typeof import("tesseract.js")["createWorker"]>>;
let worker: Promise<TesseractWorker> | null = null;
let idle: ReturnType<typeof setTimeout> | undefined;
const IDLE_MS = 2 * 60 * 1000;   // the worker holds ~100 MB: shut it down when no page has been read for a while

function stopWorker(): void {
  clearTimeout(idle);
  const w = worker;
  worker = null;
  void w?.then((x) => x.terminate()).catch(() => undefined);
}

async function tesseractOcr(imageUrl: string, width: number, height: number): Promise<Word[]> {
  clearTimeout(idle);
  try {
    return await readPage(imageUrl, width, height);
  } finally {
    idle = setTimeout(stopWorker, IDLE_MS);
  }
}

async function readPage(imageUrl: string, width: number, height: number): Promise<Word[]> {
  worker ??= import("tesseract.js").then(({ createWorker }) => createWorker("eng", 1, {
    workerPath: "/ocr/worker.min.js", corePath: "/ocr/", langPath: "/ocr/", workerBlobURL: false, gzip: true,
  }));
  // Small print on a page-sized image is too small for OCR: read it enlarged (longest side about OCR_SIDE pixels).
  const scale = Math.min(OCR_MAX_SCALE, OCR_SIDE / Math.max(width, height));
  let input: string | Blob = imageUrl;
  if (scale > 1.2 && typeof OffscreenCanvas !== "undefined") {
    const bitmap = await createImageBitmap(await (await fetch(imageUrl)).blob());
    const canvas = new OffscreenCanvas(Math.round(width * scale), Math.round(height * scale));
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      input = await canvas.convertToBlob({ type: "image/png" });
    }
    bitmap.close();
  }
  const s = input === imageUrl ? 1 : scale;
  const { data } = await (await worker).recognize(input, {}, { blocks: true, text: false });
  const out: Word[] = [];
  for (const block of data.blocks ?? []) {
    for (const para of block.paragraphs) {
      for (const line of para.lines) {
        for (const w of line.words) {
          if (w.confidence < MIN_CONFIDENCE || !w.text.trim()) continue;
          const b = w.bbox;
          out.push([b.x0 / (width * s), b.y0 / (height * s), b.x1 / (width * s), b.y1 / (height * s), w.text]);
        }
      }
    }
  }
  return out;
}

let instance: ReturnType<typeof createPageWords> | null = null;

/** The words on a page for field boxes (see the top of this file). */
export async function wordsFor(req: WordsRequest): Promise<PageWords> {
  if (!instance) {
    const [{ accountingApi }, { extractApi }] = await Promise.all([import("@/lib/accounting-api"), import("@/lib/extract-api")]);
    instance = createPageWords({
      layoutFetch: (src, fileId, page) =>
        src === "extract" ? extractApi.pageLayout(fileId, page) : accountingApi.pageLayout(fileId, page),
      ocr: tesseractOcr,
      store: browserStore(),
    });
  }
  return instance.wordsFor(req);
}

/** Sign-out: forget every page's words (memory, IndexedDB) and stop the OCR worker. */
export function clearPageWords(): void {
  storeGen += 1;
  instance?.clear();
  instance = null;
  try {
    openDb?.close();
  } catch {
    // already closed
  }
  openDb = null;
  stopWorker();
  try {
    indexedDB.deleteDatabase(DB);
  } catch {
    // storage blocked: nothing was kept either
  }
}
