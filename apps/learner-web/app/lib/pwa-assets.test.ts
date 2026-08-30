import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const serviceWorker = readFileSync(
  new URL("../../public/sw.js", import.meta.url),
  "utf8",
);

describe("learner PWA cache boundary", () => {
  it("provides an offline navigation fallback without caching learner API data", () => {
    expect(serviceWorker).toContain('const OFFLINE_URL = "/offline"');
    expect(serviceWorker).toContain('url.pathname.startsWith("/v1/")');
    expect(serviceWorker).toContain('request.mode === "navigate"');
    expect(serviceWorker).toContain(
      'url.pathname.startsWith("/_next/static/")',
    );
    expect(serviceWorker).not.toContain('caches.open("/v1');
  });
});
