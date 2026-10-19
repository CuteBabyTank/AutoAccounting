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

export function middleware(request: NextRequest) {
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
      // Run on document requests; skip static assets and prefetches so the
      // nonce isn't wasted on cacheable responses.
      source: "/((?!_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
