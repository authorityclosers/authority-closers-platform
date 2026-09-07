import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

beforeEach(() => {
  vi.resetModules();
  vi.stubEnv("AC_DEV_AUTH_BRIDGE_ENABLED", "true");
  vi.stubEnv("NEXT_TRACE_SPAN_THRESHOLD_MS", "9007199254740991");
  vi.stubEnv("NODE_DEBUG", "");
  vi.stubEnv("AC_DEV_AUTH_BRIDGE_ORIGIN", "http://learner.localhost:3100");
  vi.stubEnv(
    "AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN",
    "https://staging.authorityclosers.com",
  );
});
afterEach(() => vi.unstubAllEnvs());

describe("opt-in media bridge logging boundary", () => {
  it.each(["http", "HTTPS", "http,https", "*", "h*", "fs,https"])(
    "refuses unsafe native diagnostic mask %s on direct bridge startup",
    async (mask) => {
      vi.stubEnv("NODE_ENV", "development");
      vi.stubEnv("NODE_DEBUG", mask);
      await expect(import("../../next.config")).rejects.toThrow(
        "native HTTP diagnostics",
      );
    },
  );
  it("does not change ordinary development diagnostic policy", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("AC_DEV_AUTH_BRIDGE_ENABLED", "false");
    vi.stubEnv("NODE_DEBUG", "https");
    const { default: config } = await import("../../next.config");
    expect(config.logging).toBeUndefined();
  });
  it("disables framework URL logs only after validated development activation", async () => {
    vi.stubEnv("NODE_ENV", "development");
    const { default: config } = await import("../../next.config");
    expect(config.logging).toBe(false);
  });
  it("preserves normal production logging even when dev variables are present", async () => {
    vi.stubEnv("NODE_ENV", "production");
    const { default: config } = await import("../../next.config");
    expect(config.logging).toBeUndefined();
  });
  it("leaves ordinary non-bridge development logging unchanged", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("AC_DEV_AUTH_BRIDGE_ENABLED", "false");
    const { default: config } = await import("../../next.config");
    expect(config.logging).toBeUndefined();
  });
  it("fails invalid opted-in configuration instead of silently bypassing it", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv(
      "AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN",
      "https://app.authorityclosers.com",
    );
    await expect(import("../../next.config")).rejects.toThrow(
      "exact staging learner origin",
    );
  });
  it.each([undefined, "-1", "0", "9007199254740990", "9007199254740991 "])(
    "refuses bridge startup without the exact pre-bootstrap trace threshold (%s)",
    async (threshold) => {
      vi.stubEnv("NODE_ENV", "development");
      vi.stubEnv("NEXT_TRACE_SPAN_THRESHOLD_MS", threshold);
      await expect(import("../../next.config")).rejects.toThrow(
        "trace-private launcher",
      );
    },
  );
  it("does not require trace suppression for production", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_TRACE_SPAN_THRESHOLD_MS", undefined);
    const { default: config } = await import("../../next.config");
    expect(config.logging).toBeUndefined();
  });
  it("fails closed when the installed Next version has not been revalidated", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.doMock("next/package.json", () => ({
      default: { version: "16.2.12-unvalidated-fixture" },
    }));
    try {
      await expect(import("../../next.config")).rejects.toThrow(
        "validated Next version",
      );
    } finally {
      vi.doUnmock("next/package.json");
    }
  });
});
