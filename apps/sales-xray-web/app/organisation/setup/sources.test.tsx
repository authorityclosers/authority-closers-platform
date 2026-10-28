import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { OrganisationSources } from "./sources";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("../../leads/app-connect", () => ({ useAppConnect: () => () => {} }));
vi.mock("./microphone", () => ({ MicrophoneAccess: () => null }));
vi.mock("../../notice-center", () => ({ notify: vi.fn() }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement, root: Root;
const calls: { path: string; body: Record<string, unknown> | null }[] = [];
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  calls.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ path, body });
      if (path.endsWith("/status"))
        return Response.json({
          configured: true,
          pages: [
            {
              pageId: "p1",
              name: "Sample One",
              account: { name: "Mira Fictional" },
              active: true,
              received: 2,
              forms: "all",
              formsOnPage: [
                { id: "old", name: "Cached form", status: "ACTIVE" },
              ],
            },
            {
              pageId: "p2",
              name: "Sample Two",
              account: { name: "Tali Example" },
              active: true,
              received: 1,
              forms: ["two"],
            },
          ],
        });
      if (path.endsWith("/p1/forms"))
        return Response.json([
          { id: "one", name: "New form", status: "ACTIVE" },
          { id: "archived", name: "Earlier campaign", status: "ARCHIVED" },
        ]);
      if (path.endsWith("/p2/forms"))
        return Response.json([
          { id: "two", name: "Course form", status: "ACTIVE" },
        ]);
      return Response.json({
        page: {
          pageId: "p1",
          backfill: { state: "done", seen: 5, created: 1, known: 4 },
        },
      });
    }),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
async function render() {
  await act(async () => {
    root.render(<OrganisationSources />);
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    for (let i = 0; i < 12; i++) await Promise.resolve();
  });
}
async function tap(text: string) {
  const button = [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  );
  expect(button).toBeDefined();
  await act(async () => {
    button!.click();
    for (let i = 0; i < 12; i++) await Promise.resolve();
  });
}
it("shows fresh forms across accounts, including archived forms, without saving on load", async () => {
  await render();
  expect(host.textContent).toContain("Mira Fictional");
  expect(host.textContent).toContain("Tali Example");
  expect(host.textContent).toContain("Earlier campaign");
  expect(host.textContent).not.toContain("Cached form");
  expect(calls.every((call) => call.body === null)).toBe(true);
  expect(host.textContent).toContain("existing duplicate checks");
});
it("keeps selection local until Save and sends history requests for all selected forms", async () => {
  await render();
  await tap("Fetch old leads");
  expect(
    calls
      .filter((call) => call.path.endsWith("/backfill"))
      .map((call) => call.body),
  ).toEqual([{ forms: ["one", "archived"] }, { forms: ["two"] }]);
  await tap("Earlier campaign");
  expect(calls.filter((call) => call.path.endsWith("/p1"))).toHaveLength(0);
  await tap("Save forms");
  expect(calls.find((call) => call.path.endsWith("/p1"))?.body).toEqual({
    forms: ["one"],
  });
});

// /settings/sources redirects to this hub: linking to it here would send people in a loop.
it("keeps the other source controls on the screen instead of linking back to itself", async () => {
  await render();
  expect(host.querySelector('a[href="/settings/sources"]')).toBeNull();
  const details = [...host.querySelectorAll("details")].find(
    (item) =>
      item.querySelector("summary")?.textContent === "Other lead sources",
  )!;
  await act(async () => {
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
  });
  expect(host.querySelector('[data-brand="google"]')).not.toBeNull();
  expect(host.textContent).toContain("Website form");
});

// Owner bugs #75 and #76: no save bar until something changes; Discard puts the checks back.
it("shows the save bar only while a choice is unsaved, and Discard restores it", async () => {
  await render();
  const saveBar = () => host.querySelector('[aria-label="Unsaved forms"]');
  const pressed = () =>
    [...host.querySelectorAll("button[aria-pressed]")].map((item) =>
      item.getAttribute("aria-pressed"),
    );
  expect(saveBar()).toBeNull();
  expect(host.textContent).toContain("3 of 3 forms bring in leads · 2 Pages");
  const before = pressed();
  await tap("Earlier campaign");
  expect(saveBar()?.textContent).toContain("1 change");
  expect(host.textContent).toContain("2 of 3 forms");
  await tap("Discard");
  expect(saveBar()).toBeNull();
  expect(pressed()).toEqual(before);
  expect(calls.filter((call) => call.body !== null)).toHaveLength(0);
});

it("selects or clears every form of one Page from its header", async () => {
  await render();
  await tap("Clear");
  const first = host.querySelector(
    'section[aria-label="Forms on Sample One"]',
  )!;
  expect(
    [...first.querySelectorAll("button[aria-pressed]")].map((item) =>
      item.getAttribute("aria-pressed"),
    ),
  ).toEqual(["false", "false"]);
  const second = host.querySelector(
    'section[aria-label="Forms on Sample Two"]',
  )!;
  expect(
    second.querySelector("button[aria-pressed]")?.getAttribute("aria-pressed"),
  ).toBe("true");
  await tap("Save forms");
  expect(
    calls.find((call) => call.path.endsWith("/p1/disconnect")),
  ).toBeDefined();
});

it("does not send people to an unavailable Facebook connector", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ configured: false, pages: [] })),
  );
  await render();
  expect(
    host.querySelector('a[href="/v1/lead-desk/meta/connect-sources"]'),
  ).toBeNull();
  expect(host.textContent).toContain("not set up in this environment");
});
