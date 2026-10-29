import { afterEach, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

it("lets no cache keep a page: private, no-store on all but build files", async () => {
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "0");
  vi.resetModules();
  const { default: config } = await import("./next.config");
  const rules = (await config.headers?.()) ?? [];
  const pages = rules.find(
    (rule) => rule.source === "/:path((?!_next/static/).*)",
  );
  expect(pages?.headers).toContainEqual({
    key: "Cache-Control",
    value: "private, no-store",
  });
  expect(rules.every((rule) => !rule.source.startsWith("/_next/static"))).toBe(
    true,
  );
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
