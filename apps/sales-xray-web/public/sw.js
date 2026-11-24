/*
 * Sales X-Ray's service worker (v1.96 device polish, lane P: "offline after the
 * first load shows Chrome's dino page"). Small on purpose; app/shell/shell-worker.tsx
 * registers it (never inside the phone apps) and holds the kill switch.
 *
 * What it does, and nothing else:
 * - A page (a navigation) always comes from the network. Only when the network
 *   fails does it answer with /offline.html, the in-app offline screen kept here.
 *   Pages are never stored: each carries one person's data.
 * - Build files (/_next/static/..., content-hashed and sent "immutable") are kept
 *   per release and served from here, as the browser's own cache would.
 * - Everything else (the API under /v1, sign-in, /__as, uploads, recordings,
 *   media, any other site) is never touched: the browser asks the network itself.
 *
 * The release is in the script's address (/sw.js?v=<release>): a new release is
 * a new worker, and on taking over it deletes the earlier releases' files.
 */
const RELEASE = new URL(self.location.href).searchParams.get("v") || "dev";
const PREFIX = "sx-shell-";
const CACHE = PREFIX + RELEASE;
const OFFLINE_PAGE = "/offline.html";
const MAX_WARM = 300;

/* Pages the worker must never answer, not even offline: sign-in and its handoffs. */
const NEVER_PAGES =
  /^\/(?:__as|v1|api|auth|login|logout|sign-?in|sign-?up|signup|oauth|\.well-known|sw-off)(?:[/?#]|$)/i;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) =>
        cache.add(new Request(OFFLINE_PAGE, { cache: "reload" })),
      )
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((name) => name.startsWith(PREFIX) && name !== CACHE)
          .map((name) => caches.delete(name)),
      );
      // The page's request starts while the worker wakes, so a page is never slower for it.
      if (self.registration.navigationPreload)
        await self.registration.navigationPreload.enable().catch(() => {});
      await self.clients.claim();
    })(),
  );
});

/** A build file the server says never changes: content-hashed, sent "immutable". */
function keepable(response) {
  return (
    response &&
    response.ok &&
    response.status === 200 &&
    response.type === "basic" &&
    /\bimmutable\b/i.test(response.headers.get("cache-control") || "")
  );
}

async function buildFile(request) {
  const cache = await caches.open(CACHE);
  const kept = await cache.match(request);
  if (kept) return kept;
  const response = await fetch(request);
  if (keepable(response)) cache.put(request, response.clone()).catch(() => {});
  return response;
}

async function page(event) {
  try {
    const preloaded = await event.preloadResponse;
    if (preloaded) return preloaded;
    return await fetch(event.request);
  } catch (error) {
    const offline = await caches.match(OFFLINE_PAGE, { cacheName: CACHE });
    if (offline) return offline;
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || request.headers.has("range")) return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === "navigate") {
    if (NEVER_PAGES.test(url.pathname)) return;
    event.respondWith(page(event));
    return;
  }
  if (url.pathname.startsWith("/_next/static/"))
    event.respondWith(buildFile(request));
});

/* The page hands over the build files it already loaded before the worker ran, so
   they are kept too ({type: "warm", urls}). Only this site's /_next/static files. */
self.addEventListener("message", (event) => {
  const data = event.data;
  if (!data || data.type !== "warm" || !Array.isArray(data.urls)) return;
  const urls = data.urls
    .filter((href) => typeof href === "string")
    .map((href) => {
      try {
        return new URL(href, self.location.origin);
      } catch {
        return null;
      }
    })
    .filter(
      (url) =>
        url &&
        url.origin === self.location.origin &&
        url.pathname.startsWith("/_next/static/"),
    )
    .slice(0, MAX_WARM);
  event.waitUntil(
    caches.open(CACHE).then((cache) =>
      Promise.all(
        urls.map(async (url) => {
          if (await cache.match(url.href)) return;
          const response = await fetch(url.href).catch(() => null);
          if (keepable(response))
            await cache.put(url.href, response).catch(() => {});
        }),
      ),
    ),
  );
});
