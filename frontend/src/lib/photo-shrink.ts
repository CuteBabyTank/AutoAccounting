// Shrinks JPEG photos in the browser before upload, matching the server's own pass
// (backend services/accounting/compress.py: long side <= 2400 px, JPEG quality 80, kept only when >= 5% smaller).
// The server still validates and compresses everything; this only makes uploads smaller and faster.
// PDFs and PNGs (often screenshots of text, which the server may keep as PNG) are sent as they are.

const MAX_SIDE = 2400;
const QUALITY = 0.8;
const MIN_SAVING = 0.05;

export type PreparedDrop = { files: File[]; originalHashes: string[] };

const isJpeg = (f: File) => f.type === "image/jpeg" || /\.jpe?g$/i.test(f.name);

async function sha256Hex(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function shrink(file: File): Promise<File | null> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  try {
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const w = Math.max(1, Math.round(bitmap.width * scale));
    const h = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, w, h);
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(bitmap, 0, 0, w, h);
    const blob = await new Promise<Blob | null>((ok) => canvas.toBlob(ok, "image/jpeg", QUALITY));
    canvas.width = canvas.height = 0; // free the backing store now (phones run out of canvas memory)
    if (!blob || blob.size > file.size * (1 - MIN_SAVING)) return null;
    return new File([blob], file.name, { type: "image/jpeg", lastModified: file.lastModified });
  } finally {
    bitmap.close();
  }
}

/** Smaller copies of the drop's JPEG photos, plus each shrunk photo's original SHA-256 ("" for files sent as they
 *  were) so the server still spots a photo dropped twice. Any failure just sends that file unchanged. */
export async function prepareDrop(files: File[], onProgress?: (done: number, total: number) => void): Promise<PreparedDrop> {
  const photos = files.filter(isJpeg).length;
  const canShrink = photos > 0 && typeof createImageBitmap === "function" && !!globalThis.crypto?.subtle;
  const out: File[] = [];
  const originalHashes: string[] = [];
  let done = 0;
  for (const file of files) {
    let kept = file;
    let hash = "";
    if (canShrink && isJpeg(file)) {
      try {
        const small = await shrink(file);
        if (small) {
          hash = await sha256Hex(file);
          kept = small;
        }
      } catch {
        // undecodable or out of memory: the server handles the original
      }
      onProgress?.(++done, photos);
    }
    out.push(kept);
    originalHashes.push(hash);
  }
  return { files: out, originalHashes };
}
