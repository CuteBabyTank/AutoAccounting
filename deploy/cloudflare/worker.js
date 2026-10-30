// Cloudflare Worker in front of both Cloud Run services (wrangler.toml routes the three hostnames here).
//
// Cloud Run picks the service by Host, and Cloudflare's Free plan can't rewrite Host (Origin Rules' host override is
// Enterprise-only), so the Worker fetches the run.app URL itself. That also means no certificate on our domain has to
// be issued or renewed by Google: Cloudflare holds the public one, run.app has Google's own.
//
// Every request gets the origin secret (X-AA-Origin), without which both services answer 403 once ORIGIN_SECRET is set
// on them, and the visitor's IP (X-AA-Client-IP), which the backend's rate limits key on (app/edge.py).

const ORIGINS = {
  "autoaccounting.ph": "aa-frontend-415242727441.asia-southeast1.run.app",
  "www.autoaccounting.ph": "aa-frontend-415242727441.asia-southeast1.run.app",
  "api.autoaccounting.ph": "aa-backend-415242727441.asia-southeast1.run.app",
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const publicHost = url.hostname;
    const origin = ORIGINS[publicHost];
    if (!origin || !env.ORIGIN_SECRET) return new Response("Not found", { status: 404 });

    url.protocol = "https:";
    url.hostname = origin;
    url.port = "";

    const headers = new Headers(request.headers);
    headers.set("x-aa-origin", env.ORIGIN_SECRET);
    headers.set("x-aa-client-ip", request.headers.get("cf-connecting-ip") ?? "");
    headers.set("x-forwarded-host", publicHost);

    const isApi = publicHost.startsWith("api.");
    const response = await fetch(url, {
      method: request.method,
      headers,
      body: request.body,
      redirect: "manual",
      // Firm data must never sit in Cloudflare's cache; the site's static assets may.
      cache: isApi ? "no-store" : undefined,
    });

    const out = new Response(response.body, response);
    // HTTPS only from here on, for every hostname (the backend sends this too; the frontend doesn't).
    out.headers.set("strict-transport-security", "max-age=31536000; includeSubDomains");
    // A redirect built from the run.app Host would send the browser around Cloudflare (and into the 403).
    const location = response.headers.get("location");
    if (location?.includes(origin)) out.headers.set("location", location.replaceAll(origin, publicHost));
    return out;
  },
};
