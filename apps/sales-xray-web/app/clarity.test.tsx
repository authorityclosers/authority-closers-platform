import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import { ClarityGate, resetClarityForTest, startClarity } from "./clarity";
import { telemetry } from "./telemetry";

const tags = () =>
  [
    ...document.querySelectorAll<HTMLScriptElement>(
      'script[src^="https://www.clarity.ms/"]',
    ),
  ].map((script) => script.getAttribute("src"));

afterEach(() => {
  resetClarityForTest();
  for (const script of document.querySelectorAll(
    'script[src^="https://www.clarity.ms/"]',
  ))
    script.remove();
  delete (window as { clarity?: unknown }).clarity;
  vi.restoreAllMocks();
});

it("loads nothing until telemetry's server answer allows it, then the project's tag", async () => {
  let listener: ((project: string) => void) | undefined;
  vi.spyOn(telemetry, "whenReplay").mockImplementation((next) => {
    listener = next;
    return () => {
      listener = undefined;
    };
  });
  const root = createRoot(document.createElement("div"));
  await act(async () => root.render(<ClarityGate />));
  // Signed out, usage analytics off, or no project here: no request to Clarity at all.
  expect(tags()).toEqual([]);
  act(() => listener?.("z4fyjboxqs"));
  expect(tags()).toEqual(["https://www.clarity.ms/tag/z4fyjboxqs"]);
  await act(async () => root.unmount());
  expect(listener).toBeUndefined();
});

it("adds the tag once a page, denies advertising storage, and never names anyone", () => {
  startClarity("<script>");
  startClarity("https://example.com/x.js");
  expect(tags()).toEqual([]);
  startClarity("z4fyjboxqs");
  startClarity("z4fyjboxqs");
  expect(tags()).toEqual(["https://www.clarity.ms/tag/z4fyjboxqs"]);
  const queued = (window as { clarity?: { q?: unknown[][] } }).clarity?.q;
  expect(queued).toEqual([
    ["consentv2", { ad_Storage: "denied", analytics_Storage: "granted" }],
  ]);
  expect(JSON.stringify(queued)).not.toMatch(/identify|"set"/);
});
