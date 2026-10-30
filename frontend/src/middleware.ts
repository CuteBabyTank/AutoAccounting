import { NextRequest, NextResponse } from "next/server";

// Per-request nonce CSP: a fresh nonce per request allow-lists inline scripts
// (Next.js bootstrap, next-themes) instead of 'unsafe-inline', so injected
// inline scripts are blocked. Google Sign-In loads via `src` from the host
// allow-list below. Smoke-test Google sign-in after any change here.

const API_FALLBACK = "http://localhost:8000";

function apiOrigin(): string {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? API_FALLBACK;
  try {
    return new URL(apiUrl).origin;
  } catch {
    return apiUrl;
  }
}

// Shared with Cloudflare, which adds it as X-AA-Origin. When set, a request without it never came through
// Cloudflare (someone calling the run.app URL directly) and is refused. Read at runtime, never shipped to the browser.
function fromEdge(request: NextRequest): boolean {
  const secret = process.env.ORIGIN_SECRET ?? "";
  if (!secret) return true;
  const sent = request.headers.get("x-aa-origin") ?? "";
  if (sent.length !== secret.length) return false;
  let diff = 0;
  for (let i = 0; i < secret.length; i++) diff |= sent.charCodeAt(i) ^ secret.charCodeAt(i);
  return diff === 0;
}

export function middleware(request: NextRequest) {
  if (!fromEdge(request)) return new NextResponse("Forbidden", { status: 403 });
  // Prefetches still pass the origin check above, but don't need a nonce.
  if (request.headers.has("next-router-prefetch") || request.headers.get("purpose") === "prefetch") {
    return NextResponse.next();
  }

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");

  const csp = [
    "default-src 'self'",
    // 'unsafe-eval' only in dev: React Refresh evaluates modules as strings.
    `script-src 'self' 'nonce-${nonce}'${process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : ""} https://accounts.google.com/gsi/client`,
    "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style https://fonts.googleapis.com",
    // blob: lets the PDF preview show a generated file in an iframe.
    "frame-src 'self' blob: https://accounts.google.com/",
    // blob: covers document previews and generated PDFs opened from object URLs.
    "img-src 'self' data: blob: https://lh3.googleusercontent.com https://*.googleusercontent.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    `connect-src 'self' blob: https://accounts.google.com/ ${apiOrigin()}`,
    "worker-src 'self' blob:",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  // Next.js reads the nonce from this request-scoped CSP header and applies it
  // to the framework's own inline bootstrap scripts automatically.
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    {
      // Everything but static assets (prefetches return early, without a nonce).
      source: "/((?!_next/static|_next/image|favicon.ico).*)",
    },
  ],
};
