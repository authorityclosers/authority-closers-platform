const CACHE_PREFIX = "ac-learner-shell-";
const CACHE_NAME = `${CACHE_PREFIX}v0.1.2`;
const OFFLINE_URL = "/offline";
const SHELL_ASSETS = [
  OFFLINE_URL,
  "/icon.svg",
  "/brand/closers-academy-v0.1/icon-192.png",
  "/brand/closers-academy-v0.1/icon-512.png",
  "/brand/closers-academy-v0.1/icon-180.png",
  "/manifest.webmanifest",
  "/theme-init.js",
];

function isSameOrigin(url) {
  return url.origin === self.location.origin;
}

function isProtectedApiPath(pathname) {
  return pathname === "/v1" || pathname.startsWith("/v1/");
}

function isCacheableResponse(response, expectedUrl) {
  if (!response || !response.ok || response.type !== "basic") return false;
  if (response.redirected || response.headers.has("set-cookie")) return false;

  const responseUrl = new URL(
    response.url || expectedUrl.href,
    self.location.origin,
  );
  return (
    isSameOrigin(responseUrl) && responseUrl.pathname === expectedUrl.pathname
  );
}

async function cacheShellAsset(cache, asset) {
  const expectedUrl = new URL(asset, self.location.origin);
  const request = new Request(expectedUrl, {
    cache: "reload",
    credentials: "omit",
  });
  const response = await fetch(request);
  if (!isCacheableResponse(response, expectedUrl)) {
    throw new Error(
      `Unsafe learner shell response for ${expectedUrl.pathname}`,
    );
  }
  await cache.put(request, response);
}

async function refreshStaticAsset(cache, request, cached) {
  try {
    const networkRequest = new Request(request, {
      cache: "no-cache",
      credentials: "omit",
    });
    const response = await fetch(networkRequest);
    const expectedUrl = new URL(request.url);
    if (!isCacheableResponse(response, expectedUrl)) {
      return cached || Response.error();
    }
    try {
      await cache.put(request, response.clone());
    } catch {
      // A cache write failure must not turn a successful network response
      // into a failed learner navigation.
    }
    return response;
  } catch {
    return cached || Response.error();
  }
}

function serveStaticAsset(cache, request, cached) {
  const refreshed = refreshStaticAsset(cache, request, cached);
  // Keep the already-downloaded immutable asset responsive while the browser
  // revalidates it in the background. The refresh promise handles its own
  // failure so a storage/network error cannot become an unhandled rejection.
  return cached || refreshed;
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) =>
        Promise.all(SHELL_ASSETS.map((asset) => cacheShellAsset(cache, asset))),
      ),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (!isSameOrigin(url) || isProtectedApiPath(url.pathname)) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(async () => {
        try {
          const cache = await caches.open(CACHE_NAME);
          const cached = await cache.match(OFFLINE_URL);
          return cached || Response.error();
        } catch {
          return Response.error();
        }
      }),
    );
    return;
  }

  if (
    url.pathname.startsWith("/_next/static/") ||
    (SHELL_ASSETS.includes(url.pathname) &&
      url.pathname.startsWith("/brand/")) ||
    url.pathname === "/icon.svg" ||
    url.pathname === "/theme-init.js"
  ) {
    event.respondWith(
      caches
        .open(CACHE_NAME)
        .then((cache) =>
          cache
            .match(request)
            .then((cached) => serveStaticAsset(cache, request, cached)),
        )
        .catch(() =>
          fetch(
            new Request(request, {
              credentials: "omit",
            }),
          ),
        ),
    );
  }
});
