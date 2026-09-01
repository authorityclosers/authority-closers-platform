import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const serviceWorker = readFileSync(
  new URL("../../public/sw.js", import.meta.url),
  "utf8",
);
const themeInitializer = readFileSync(
  new URL("../../public/theme-init.js", import.meta.url),
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
    expect(serviceWorker).toContain('"/theme-init.js"');
    expect(serviceWorker).not.toContain('caches.open("/v1');
  });

  it("keeps the pre-paint theme initializer in the offline shell boundary", () => {
    expect(serviceWorker).toContain('"/theme-init.js"');
    expect(themeInitializer).toContain("root.dataset.theme = effective");
    expect(themeInitializer).toContain(
      "root.dataset.themePreference = preference",
    );
    expect(themeInitializer).toContain("root.style.colorScheme = effective");
  });
});
