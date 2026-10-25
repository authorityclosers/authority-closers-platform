import { afterEach, expect, it, vi } from "vitest";

import { agreedTerms, forgetTerms, rememberTerms } from "./consent-memory";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

it("remembers the exact policy agreed to, per workspace", () => {
  rememberTerms("workspace-a", "policy-1");
  expect(agreedTerms("workspace-a")).toBe("policy-1");
  expect(agreedTerms("workspace-b")).toBeNull();
  expect(agreedTerms(null)).toBeNull();
});

it("forgets an agreement that is unticked", () => {
  rememberTerms("workspace-a", "policy-1");
  rememberTerms("workspace-b", "policy-1");
  forgetTerms("workspace-a");
  expect(agreedTerms("workspace-a")).toBeNull();
  expect(agreedTerms("workspace-b")).toBe("policy-1");
});

it("asks again when storage is blocked or holds something else", () => {
  window.localStorage.setItem("sales-xray:upload-terms", "[1,2]");
  expect(agreedTerms("workspace-a")).toBeNull();
  vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
    throw new DOMException("blocked", "SecurityError");
  });
  expect(() => rememberTerms("workspace-a", "policy-1")).not.toThrow();
  expect(agreedTerms("workspace-a")).toBeNull();
});
