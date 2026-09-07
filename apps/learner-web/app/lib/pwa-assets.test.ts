import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import manifest from "../manifest";

const serviceWorker = readFileSync(
  new URL("../../public/sw.js", import.meta.url),
  "utf8",
);
const themeInitializer = readFileSync(
  new URL("../../public/theme-init.js", import.meta.url),
  "utf8",
);
const registration = readFileSync(
  new URL("../components/pwa-register.tsx", import.meta.url),
  "utf8",
);
const layout = readFileSync(new URL("../layout.tsx", import.meta.url), "utf8");

function pngDimensions(path: string) {
  const bytes = readFileSync(new URL(path, import.meta.url));
  expect([...bytes.subarray(0, 8)]).toEqual([
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
  ]);
  return {
    width: bytes.readUInt32BE(16),
    height: bytes.readUInt32BE(20),
  };
}

describe("learner PWA cache boundary", () => {
  it("provides an offline navigation fallback without caching learner API data", () => {
    expect(serviceWorker).toContain('const OFFLINE_URL = "/offline"');
    expect(serviceWorker).toContain(
      'pathname === "/v1" || pathname.startsWith("/v1/")',
    );
    expect(serviceWorker).toContain('request.mode === "navigate"');
    expect(serviceWorker).toContain(
      'url.pathname.startsWith("/_next/static/")',
    );
    expect(serviceWorker).toContain('"/theme-init.js"');
    expect(serviceWorker).toContain("cache.match(OFFLINE_URL)");
    expect(serviceWorker).toContain('credentials: "omit"');
    expect(serviceWorker).toContain('response.type !== "basic"');
    expect(serviceWorker).not.toContain("cache.addAll");
    expect(serviceWorker).not.toContain('caches.open("/v1');
    expect(serviceWorker).not.toContain('"/home"');
    expect(serviceWorker).not.toContain('"/progress"');
    expect(serviceWorker).not.toContain('"/learn"');
  });

  it("waits for a safe lifecycle boundary instead of reloading over dirty work", () => {
    expect(serviceWorker).toContain(
      "const CACHE_NAME = `${CACHE_PREFIX}v0.1.2`",
    );
    expect(serviceWorker).toContain('cache: "reload"');
    expect(serviceWorker).toContain('cache: "no-cache"');
    expect(serviceWorker).not.toContain("self.skipWaiting");
    expect(serviceWorker).not.toContain("location.reload");
    expect(registration).toContain('updateViaCache: "none"');
    expect(registration).not.toContain("location.reload");
  });

  it("ships Chromium-sized and iOS Home Screen icons with stable metadata", () => {
    const metadata = manifest();

    expect(metadata.display).toBe("standalone");
    expect(metadata.display_override).toEqual(["standalone"]);
    expect(metadata.orientation).toBe("any");
    expect(metadata.lang).toBe("en");
    expect(metadata.dir).toBe("ltr");
    expect(metadata.prefer_related_applications).toBe(false);
    expect(metadata.icons).toEqual([
      expect.objectContaining({
        src: "/brand/closers-academy-v0.1/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      }),
      expect.objectContaining({
        src: "/brand/closers-academy-v0.1/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      }),
    ]);
    expect(
      pngDimensions("../../public/brand/closers-academy-v0.1/icon-192.png"),
    ).toEqual({
      width: 192,
      height: 192,
    });
    expect(
      pngDimensions("../../public/brand/closers-academy-v0.1/icon-512.png"),
    ).toEqual({
      width: 512,
      height: 512,
    });
    expect(
      pngDimensions("../../public/brand/closers-academy-v0.1/icon-180.png"),
    ).toEqual({
      width: 180,
      height: 180,
    });
    expect(layout).toContain('manifest: "/manifest.webmanifest"');
    expect(layout).toContain(
      '<meta name="apple-mobile-web-app-capable" content="yes" />',
    );
    expect(layout).toContain('url: "/brand/closers-academy-v0.1/icon-180.png"');
    expect(layout).toContain("capable: true");
    expect(layout).toContain('statusBarStyle: "default"');
    expect(layout).toContain('viewportFit: "cover"');
  });

  it("keeps the pre-paint theme initializer in the offline shell boundary", () => {
    expect(serviceWorker).toContain('"/theme-init.js"');
    expect(themeInitializer).toContain("root.dataset.theme = effective");
    expect(themeInitializer).toContain("root.dataset.themePreference =");
    expect(themeInitializer).toContain(
      "themeStorageReadFailed && bootstrapThemePreference",
    );
    expect(themeInitializer).toContain("root.style.colorScheme = effective");
  });
});
