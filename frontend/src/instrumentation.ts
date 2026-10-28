// Next.js calls register() exactly once per server instance at startup. On
// Cloud Run that fires the moment a frontend instance boots (i.e. a user is
// present), so we use it to warm the backend: the backend runs with
// min-instances=0 to avoid 24/7 cost, and this one-shot ping to the
// unauthenticated /api/health lets it cold-start in parallel with page load
// instead of blocking the user's first real API call.
//
// Deliberately fire-and-forget with a hard timeout: a slow or failed warm-up
// must never delay or crash frontend boot. There is intentionally no ongoing
// heartbeat: Cloud Run throttles CPU between requests unless CPU-always is on,
// so a setInterval would be unreliable and cost more. The boot ping plus the
// app's own session traffic keeps the backend warm while a user is active.
export function register() {
  // Guard to the Node.js runtime only; the edge runtime also calls register().
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  // Fire-and-forget: do NOT await. Next.js awaits register(), so awaiting the
  // fetch here would stall frontend boot by up to the timeout whenever the
  // backend is cold, which is the common case now that it scales to zero. We
  // kick the ping off in the background and return immediately; `void` marks
  // the floating promise as intentional. warmBackend() never rejects.
  void warmBackend();
}

async function warmBackend(): Promise<void> {
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const url = `${base}/api/health`;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);

  try {
    const res = await fetch(url, { signal: controller.signal });
    console.log(`[warmup] backend ping ${url} -> ${res.status}`);
  } catch (err) {
    // Swallow it: warm-up is best-effort and non-fatal.
    const reason = err instanceof Error ? err.message : String(err);
    console.warn(`[warmup] backend ping ${url} failed: ${reason}`);
  } finally {
    clearTimeout(timeout);
  }
}
