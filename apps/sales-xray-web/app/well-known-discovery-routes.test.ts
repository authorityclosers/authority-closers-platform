import { existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { pageExtensions } from "../next.config";

// The discovery handlers must reach every real build (staging and production serve
// /.well-known from this app) and stay out of the static preview, which cannot hold them.
const ROUTES = [
  "oauth-authorization-server/route.discovery.ts",
  "openid-configuration/route.discovery.ts",
  "oauth-protected-resource/[[...resource]]/route.discovery.ts",
];

describe("/.well-known discovery routes", () => {
  it("exist as route.discovery.ts handlers", () => {
    for (const route of ROUTES)
      expect(
        existsSync(path.join(__dirname, ".well-known", route)),
        route,
      ).toBe(true);
  });

  it("are routes in a normal build and left out of the static preview", () => {
    expect(pageExtensions(false)).toContain("discovery.ts");
    expect(pageExtensions(true)).not.toContain("discovery.ts");
    expect(pageExtensions(true)).toEqual(["tsx", "ts", "jsx", "js"]);
  });
});
