import { expect, it } from "vitest";

import { phoneTabFor, shellActiveFor } from "./phone-nav";

it("lights the phone tab from the address before the page settles", () => {
  // The old root loader said "analyse" on every route while loading.
  expect(phoneTabFor("/dashboard", "analyse")).toBe("dashboard");
  expect(phoneTabFor("/prospects", "analyse")).toBe("prospects");
  expect(phoneTabFor("/prospects/8f3c", "analyse")).toBe("prospects");
  expect(phoneTabFor("/coaching", "analyse")).toBe("coaching");
  expect(phoneTabFor(null, "coaching")).toBe("coaching");
  expect(phoneTabFor("/organisation", "analyse")).toBe("more");
  expect(phoneTabFor("/account", undefined)).toBe("more");
  expect(phoneTabFor("/plans", undefined)).toBe("more");
  expect(phoneTabFor("/analysis/new", "dashboard")).toBe("new");
});

it("keeps a call's report under Calls", () => {
  expect(
    phoneTabFor(
      "/analysis/calls/0b6e7c52-3f0e-4a8e-9a55-2d4f1c9e8b10",
      "analyse",
    ),
  ).toBe("calls");
  expect(phoneTabFor("/analysis/calls", undefined)).toBe("calls");
  expect(phoneTabFor("/calls", undefined)).toBe("calls");
});

it("falls back to the page's own section where the address is shared", () => {
  expect(phoneTabFor("/", "analyse")).toBe("new");
  expect(phoneTabFor("/sales-xray", "calls")).toBe("calls");
  expect(phoneTabFor(null, "organisation")).toBe("more");
  expect(phoneTabFor("/", undefined)).toBeNull();
  // A path that merely starts with a section name is not that section.
  expect(phoneTabFor("/dashboards", undefined)).toBeNull();
});

it("lights the desktop rail icon from the address too", () => {
  // Coaching's page leaves the shell at its New analysis default.
  expect(shellActiveFor("/coaching", "analyse")).toBe("coaching");
  expect(shellActiveFor("/organisation", "analyse")).toBe("organisation");
  expect(shellActiveFor("/account", "analyse")).toBe("account");
  expect(shellActiveFor("/analysis/calls/0b6e", "analyse")).toBe("calls");
  expect(shellActiveFor("/analysis/new", "dashboard")).toBe("analyse");
  expect(shellActiveFor("/", "dashboard")).toBe("dashboard");
  expect(shellActiveFor(null, "prospects")).toBe("prospects");
});
