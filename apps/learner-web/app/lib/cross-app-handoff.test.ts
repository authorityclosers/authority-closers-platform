import { webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import {
  createHandoffVerifier,
  handoffChallenge,
  handoffReturnPath,
  isHandoffReturnPath,
} from "./cross-app-handoff";

afterEach(() => vi.unstubAllGlobals());
it("matches the RFC 7636 S256 known vector", async () => {
  vi.stubGlobal("crypto", webcrypto);
  expect(
    await handoffChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
  ).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
});
it("generates a fresh 32-byte base64url verifier", () => {
  vi.stubGlobal("crypto", webcrypto);
  const first = createHandoffVerifier();
  expect(first).toMatch(/^[A-Za-z0-9_-]{43}$/);
  expect(Buffer.from(first, "base64url")).toHaveLength(32);
  expect(createHandoffVerifier()).not.toBe(first);
});
it.each([
  "https://x",
  "//x",
  "\\x",
  "/\\x",
  "/" + "a".repeat(599),
  "/a\nb",
  "/a\x7fb",
  "/a\x85b",
  null,
])("rejects unsafe return %s", (value) => {
  expect(isHandoffReturnPath(value)).toBe(false);
  expect(handoffReturnPath(value)).toBe("/home");
});
it.each(["/home", "/learning?tab=mine#lesson", "/" + "\u{10400}".repeat(511)])(
  "keeps exact safe return %s",
  (value) => {
    expect(handoffReturnPath(value)).toBe(value);
  },
);
