// Tags the static site's CSS / JS links with a hash of their contents (styles.css?v=1a2b3c4d), so a browser that
// kept an old copy (Cloudflare lets browsers keep them 4 hours) fetches the new one as soon as a deploy changes it.
// The HTML pages themselves are never kept, so the new tag is always seen. Runs before every `npm run build`.
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const dir = join(import.meta.dirname, "..", "public");
const assets = ["styles.css", "app.js"];
const hash = (f) => createHash("sha256").update(readFileSync(join(dir, f))).digest("hex").slice(0, 10);
const versions = Object.fromEntries(assets.map((f) => [f, hash(f)]));

for (const page of ["index.html", "privacy.html", "terms.html"]) {
  const path = join(dir, page);
  const before = readFileSync(path, "utf8");
  let after = before;
  for (const f of assets) {
    const name = f.replace(".", "\\.");
    after = after.replace(new RegExp(`((?:href|src)="/?)${name}(\\?v=[0-9a-f]+)?"`, "g"), `$1${f}?v=${versions[f]}"`);
  }
  if (after !== before) {
    writeFileSync(path, after);
    console.log(`version-assets: ${page} updated`);
  }
}
