import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { HowItWorks } from "./ad-platforms";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("tab=stages"),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

it("says, per platform, what leaves Sales X-Ray and why it helps", () => {
  act(() => root.render(<HowItWorks />));
  const text = host.textContent ?? "";
  expect(host.querySelector("details")?.open).toBe(false);
  expect(text).toContain("What your ads receive, and why it helps");
  for (const name of [
    "Meta",
    "Google Ads",
    "LinkedIn",
    "TikTok",
    "Microsoft Ads",
  ]) {
    expect(text).toContain(name);
  }
  expect(text).toContain(
    "Names, notes, calls and what was said never leave Sales X-Ray",
  );
  expect(text).toContain("Only stages you confirmed are sent");
});

it("never mentions a price or cost", () => {
  act(() => root.render(<HowItWorks />));
  const text = (host.textContent ?? "").toLowerCase();
  for (const word of [
    "₹",
    "$",
    "price",
    "cost",
    "spend",
    "credit",
    "per lead",
  ]) {
    expect(text).not.toContain(word);
  }
});
