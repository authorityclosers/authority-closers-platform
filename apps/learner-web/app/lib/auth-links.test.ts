import { describe, expect, it } from "vitest";

import { googleAuthStartUrl } from "./auth-links";

describe("Google authorization links", () => {
  it("builds an exact API-owned authenticate transaction without callback secrets", () => {
    const result = googleAuthStartUrl("authenticate");
    const url = new URL(result, "https://app.authorityclosers.com");

    expect(url.origin).toBe("https://app.authorityclosers.com");
    expect(url.pathname).toBe("/v1/auth/google/start");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      action: "authenticate",
      surface: "learner",
      return_path: "/home",
    });
    expect(result).not.toMatch(/state|nonce|verifier|secret|token/i);
  });

  it("uses a distinct server-owned registration intent", () => {
    expect(
      new URL(
        googleAuthStartUrl("register"),
        "https://app.authorityclosers.com",
      ).searchParams.get("action"),
    ).toBe("register");
  });

  it("is always same-origin and cannot be redirected by environment configuration", () => {
    expect(googleAuthStartUrl("authenticate")).toMatch(
      /^\/v1\/auth\/google\/start\?/,
    );
    expect(googleAuthStartUrl("authenticate")).not.toContain("http");
  });
});
