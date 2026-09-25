import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

import Page from "./page";
import { FullShellPreview } from "./full-shell-preview";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  window.history.replaceState(null, "", "/review-fixture/shell");
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  // The shell's profile menu makes one read-only profile request; it has no
  // server here and must stay usable when that read fails.
  fetchMock = vi.fn(() => Promise.reject(new Error("offline fixture")));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it("is not routable outside local development", () => {
  vi.stubEnv("NODE_ENV", "production");
  expect(() => Page()).toThrow("NEXT_NOT_FOUND");
  vi.stubEnv("NODE_ENV", "test");
  expect(() => Page()).toThrow("NEXT_NOT_FOUND");
});

it("mounts the actual shell, report header, sections and dock with fictional data only", async () => {
  await act(async () => root.render(<FullShellPreview />));
  await act(async () => Promise.resolve());

  // Real shell owners: rail navigation, top bar and mobile navigation.
  expect(container.querySelector("[data-lightbox-shell]")).not.toBeNull();
  expect(container.querySelector('nav[aria-label="Workspace"]')).not.toBeNull();
  expect(
    container.querySelector('nav[aria-label="Mobile Sales Xray navigation"]'),
  ).not.toBeNull();
  // Real report header with overflow actions and collapsed provenance.
  const report = container.querySelector('[aria-label="Sales call report"]');
  expect(report?.getAttribute("data-lx-surface")).toBe("light");
  expect(report?.querySelector("h1")?.textContent).toBe("Sales call report");
  expect(
    report?.querySelector('summary[aria-label="More report actions"]'),
  ).not.toBeNull();
  expect(report?.textContent).toContain("59:58");
  // Real report sections and the one call dock.
  expect(container.querySelectorAll("[data-report-mode-section]")).toHaveLength(
    6,
  );
  expect(
    container.querySelector('[aria-label="Call audio player"] audio'),
  ).not.toBeNull();
  // Clearly fictional and inert: nothing is sent anywhere but the profile read.
  expect(container.textContent).toContain(
    "Development fixture · fictional data",
  );
  expect(container.querySelector("audio")?.getAttribute("src")).toBeNull();
  const requested = fetchMock.mock.calls.map(([url]) => String(url));
  // Only the rail and mobile profile menus' read-only profile GETs.
  expect(requested.length).toBeGreaterThan(0);
  expect(new Set(requested)).toEqual(new Set(["/v1/me/sales-xray-profile"]));
  expect(
    fetchMock.mock.calls.every(
      ([, init]) => !init || !init.method || init.method === "GET",
    ),
  ).toBe(true);

  const another = [...container.querySelectorAll("button")].find(
    (button) => button.textContent?.trim() === "Analyse another call",
  )!;
  await act(async () => another.click());
  expect(
    container.querySelector('[aria-label="Fixture action status"]')
      ?.textContent,
  ).toContain("Nothing was sent");
});
