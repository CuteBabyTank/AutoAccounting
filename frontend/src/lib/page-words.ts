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
}

interface Deps {
  layoutFetch: (src: WordsRequest["src"], fileId: string, page: number) => Promise<PageLayout>;
  /** OCR of the shown image: words as fractions of that image. */
  ocr: (imageUrl: string, width: number, height: number) => Promise<Word[]>;
  store: Store | null;
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
  let queue: Promise<unknown> = Promise.resolve();   // one OCR job at a time

  async function wordsFor(req: WordsRequest): Promise<PageWords> {
    const key = `${req.userId}:${req.src}:${req.fileId}:${req.page}`;
    if (req.signal.aborted) throw abortError();
    const hit = memory.get(key) ?? (await deps.store?.get(key).catch(() => undefined));
    if (hit) {
      memory.set(key, hit);
      return hit;
    }
    const layout = await deps.layoutFetch(req.src, req.fileId, req.page);
    if (req.signal.aborted) throw abortError();
    let result: PageWords;
    if (!layout.crop) {
      result = { crop: null, aspect: layout.aspect, words: [] };
    } else if (layout.text_layer) {
      result = { crop: layout.crop, aspect: layout.aspect, words: layout.words };
    } else {
      const crop = layout.crop;
      const job = queue.then(async () => {
        await untilVisible(req.signal);
        if (req.signal.aborted) throw abortError();
        return deps.ocr(req.imageUrl, req.width, req.height);
      });
      queue = job.catch(() => undefined);
      const shown = await job;
      if (req.signal.aborted) throw abortError();
      const [cx0, cy0, cx1, cy1] = crop;
      const cw = cx1 - cx0;
      const ch = cy1 - cy0;
      result = {
        crop, aspect: layout.aspect,
        words: shown.map(([x0, y0, x1, y1, t]) => [cx0 + x0 * cw, cy0 + y0 * ch, cx0 + x1 * cw, cy0 + y1 * ch, t]),
      };
    }
    memory.set(key, result);
    void deps.store?.put(key, result).catch(() => undefined);
    return result;
  }

  return { wordsFor, clear: () => memory.clear() };
}

// ---- The browser's instance: API layout routes, Tesseract.js, IndexedDB ----

const DB = "aa-page-words";
const KEEP_MS = 7 * 24 * 3600 * 1000;
const MAX_BYTES = 20 * 1024 * 1024;
const MIN_CONFIDENCE = 60;   // OCR words it isn't sure of are left out (no box beats a wrong box)

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

function browserStore(): Store | null {
  if (typeof indexedDB === "undefined") return null;
  let ready: Promise<IDBDatabase> | null = null;
  const db = () => {
    ready ??= idb().then(async (d) => {
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
    async put(key, value) {
      const size = JSON.stringify(value).length;
      await request((await db()).transaction("pages", "readwrite").objectStore("pages")
        .put({ key, at: Date.now(), size, value } satisfies Row));
    },
  };
}

type TesseractWorker = Awaited<ReturnType<typeof import("tesseract.js")["createWorker"]>>;
let worker: Promise<TesseractWorker> | null = null;

async function tesseractOcr(imageUrl: string, width: number, height: number): Promise<Word[]> {
  worker ??= import("tesseract.js").then(({ createWorker }) => createWorker("eng", 1, {
    workerPath: "/ocr/worker.min.js", corePath: "/ocr/", langPath: "/ocr/", workerBlobURL: false, gzip: true,
  }));
  const { data } = await (await worker).recognize(imageUrl, {}, { blocks: true, text: false });
  const out: Word[] = [];
  for (const block of data.blocks ?? []) {
    for (const para of block.paragraphs) {
      for (const line of para.lines) {
        for (const w of line.words) {
          if (w.confidence < MIN_CONFIDENCE || !w.text.trim()) continue;
          const b = w.bbox;
          out.push([b.x0 / width, b.y0 / height, b.x1 / width, b.y1 / height, w.text]);
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
  instance?.clear();
  instance = null;
  const w = worker;
  worker = null;
  void w?.then((x) => x.terminate()).catch(() => undefined);
  try {
    indexedDB.deleteDatabase(DB);
  } catch {
    // storage blocked: nothing was kept either
  }
}
