// Field boxes: self-host Tesseract.js's worker, WASM core and English data in public/ocr/ (lib/page-words.ts).
// The CSP allows scripts only from this site, so nothing is loaded from a CDN. Runs before dev and build.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "ocr");
const nm = join(root, "node_modules");
const files = [
  ["tesseract.js/dist/worker.min.js", "worker.min.js"],
  ["tesseract.js-core/tesseract-core-simd-lstm.wasm.js", "tesseract-core-simd-lstm.wasm.js"],
  ["tesseract.js-core/tesseract-core-lstm.wasm.js", "tesseract-core-lstm.wasm.js"],
  ["@tesseract.js-data/eng/4.0.0_best_int/eng.traineddata.gz", "eng.traineddata.gz"],
];
mkdirSync(out, { recursive: true });
for (const [from, to] of files) {
  const src = join(nm, from);
  if (!existsSync(src)) {
    console.error(`copy-ocr: missing ${from}; run npm install`);
    process.exit(1);
  }
  copyFileSync(src, join(out, to));
}
console.log(`copy-ocr: ${files.length} files in public/ocr`);
