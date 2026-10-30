import { buildCustomRoute } from "next/dist/lib/build-custom-route";
import { afterEach, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

// Whether a header rule applies to a path, by the expression Next itself builds from it.
function matches(source: string, path: string): boolean {
  const { regex } = buildCustomRoute("header", { source, headers: [] });
  return new RegExp(regex).test(path);
}

it("lets no cache keep a page: private, no-store on all but build files and the website line", async () => {
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "0");
  vi.resetModules();
  const { default: config } = await import("./next.config");
  const rules = (await config.headers?.()) ?? [];
  const pages = rules.find(
    (rule) => rule.source === "/:path((?!_next/static/|sx\\.js/?$).*)",
  );
  expect(pages?.headers).toContainEqual({
    key: "Cache-Control",
    value: "private, no-store",
  });
  for (const path of [
    "/",
    "/leads",
    "/settings/team",
    "/sx.js.map",
    "/sx.jsx",
    "/a/sx.js",
    "/favicon.ico",
  ])
    expect(matches(pages?.source ?? "", path), path).toBe(true);
  for (const path of ["/_next/static/chunks/a.js", "/sx.js", "/sx.js/"])
    expect(matches(pages?.source ?? "", path), path).toBe(false);
  expect(rules.every((rule) => !rule.source.startsWith("/_next/static"))).toBe(
    true,
  );
});

it("lets browsers and Cloudflare keep the website line a few minutes, and nothing else", async () => {
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "0");
  vi.resetModules();
  const { default: config, SCRIPT_CACHE } = await import("./next.config");
  expect(SCRIPT_CACHE).toBe(
    "public, max-age=300, stale-while-revalidate=86400, stale-if-error=86400",
  );
  const rules = (await config.headers?.()) ?? [];
  const script = rules.filter((rule) =>
    rule.headers.some((header) => header.value === SCRIPT_CACHE),
  );
  expect(script.map((rule) => rule.source)).toEqual(["/sx.js"]);
  expect(script[0]?.headers).toEqual([
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Cache-Control", value: SCRIPT_CACHE },
  ]);
  // Exactly one rule sets the line's Cache-Control, so no header is sent twice.
  for (const path of ["/sx.js", "/sx.js/"]) {
    const setting = rules.filter(
      (rule) =>
        matches(rule.source, path) &&
        rule.headers.some((header) => header.key === "Cache-Control"),
    );
    expect(
      setting.map((rule) => rule.source),
      path,
    ).toEqual(["/sx.js"]);
  }
});

it("rewrites only the required canonical auth and profile endpoints", async () => {
  vi.stubEnv("AC_CONVERSATION_API_ORIGIN", "https://api.example.test");
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "0");
  vi.stubEnv("AC_SALES_XRAY_REVIEW", "0");
  vi.resetModules();
  const { default: config } = await import("./next.config");
  const rules = await config.rewrites?.();
  if (!Array.isArray(rules)) throw new Error("Expected exact rewrite list");
  const bySource = new Map(
    rules.map((rule) => [rule.source, rule.destination]),
  );
  for (const path of [
    "/v1/auth/email-code/config",
    "/v1/auth/email-code/request",
    "/v1/auth/email-code/verify",
    "/v1/auth/password/login",
    "/v1/auth/google/start",
    "/v1/auth/google/callback",
    "/v1/auth/google/completion",
    "/v1/me/workspaces",
    "/v1/me/sales-xray-workspaces",
    "/v1/me/sales-xray-profile",
    "/v1/me/sales-xray-profile/write-eligibility",
  ])
    expect(bySource.get(path)).toBe(`https://api.example.test${path}`);
  expect(bySource.has("/v1/auth/:path*")).toBe(false);
  expect(bySource.has("/v1/me/:path*")).toBe(false);
});

it("does not expose canonical rewrites to the local read-only review build", async () => {
  vi.stubEnv("AC_CONVERSATION_API_ORIGIN", "https://api.example.test");
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "0");
  vi.stubEnv("AC_SALES_XRAY_REVIEW", "1");
  vi.stubEnv("NODE_ENV", "development");
  vi.resetModules();
  const { default: config } = await import("./next.config");
  expect(await config.rewrites?.()).toEqual([]);
  expect(config.turbopack?.resolveAlias?.["./processing-review-port"]).toMatch(
    /processing-review-port\.dev\.ts$/,
  );
});

it("keeps the Turbopack review alias out of production and ordinary development", async () => {
  for (const [environment, review] of [
    ["production", "1"],
    ["development", "0"],
  ]) {
    vi.stubEnv("NODE_ENV", environment);
    vi.stubEnv("AC_SALES_XRAY_REVIEW", review);
    vi.resetModules();
    const { default: config } = await import("./next.config");
    expect(config.turbopack?.resolveAlias).toBeUndefined();
  }
});

it("hands the build's release, and nothing else, to the page", async () => {
  vi.stubEnv("AC_RELEASE_ID", "0f3c2a9b1d4e5f60718293a4b5c6d7e8f9012345");
  vi.resetModules();
  const { default: config } = await import("./next.config");
  expect(config.env).toEqual({
    NEXT_PUBLIC_AC_RELEASE_ID: "0f3c2a9b1d4e5f60718293a4b5c6d7e8f9012345",
  });
  vi.stubEnv("AC_RELEASE_ID", undefined);
  vi.resetModules();
  const { default: local } = await import("./next.config");
  expect(local.env).toEqual({ NEXT_PUBLIC_AC_RELEASE_ID: "" });
});

it("builds the speed check's fixture pages only when asked", async () => {
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "0");
  vi.stubEnv("AC_SALES_XRAY_PERF_FIXTURES", "");
  vi.resetModules();
  const { default: ordinary, pageExtensions } = await import("./next.config");
  expect(ordinary.pageExtensions).not.toContain("perf.tsx");
  expect(pageExtensions(true)).toEqual(["tsx", "ts", "jsx", "js"]);
  vi.stubEnv("AC_SALES_XRAY_PERF_FIXTURES", "1");
  vi.resetModules();
  const { default: speed } = await import("./next.config");
  expect(speed.pageExtensions).toEqual([
    "tsx",
    "ts",
    "jsx",
    "js",
    "discovery.ts",
    "perf.tsx",
  ]);
});

it("allows extra dev origins only when explicitly configured", async () => {
  vi.stubEnv("AC_SALES_XRAY_DEV_ALLOWED_ORIGINS", "");
  vi.resetModules();
  const { default: unset } = await import("./next.config");
  expect(unset.allowedDevOrigins).toBeUndefined();
  vi.stubEnv(
    "AC_SALES_XRAY_DEV_ALLOWED_ORIGINS",
    " salesxray-dev.example.test , ,other.example.test",
  );
  vi.resetModules();
  const { default: configured } = await import("./next.config");
  expect(configured.allowedDevOrigins).toEqual([
    "salesxray-dev.example.test",
    "other.example.test",
  ]);
});
