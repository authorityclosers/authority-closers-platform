import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { notify } from "../../notice-center";
import { runLine } from "./meta-accounts";
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

// Owner, 2 Nov 2026: Facebook & Instagram by the account that shared each Page,
// the Pages bringing leads first, a wrong account disconnected and old Pages
// removed, older leads only when asked. Made-up accounts and Pages only.
let host: HTMLDivElement, root: Root;
const calls: { path: string; body: Record<string, unknown> | null }[] = [];
let real = false;
const hourAgo = new Date(Date.now() - 2 * 3600_000).toISOString();
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  calls.length = 0;
  real = false;
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
              account: {
                id: "77",
                name: "Mira Fictional",
                connectedAt: "2026-10-12T05:00:00Z",
              },
              active: true,
              received: 2,
              lastReceivedAt: hourAgo,
              realLeads: real,
              forms: ["one"],
              formsCovered: [{ id: "one", name: "New form", status: "ACTIVE" }],
              formsOnPage: [
                { id: "old", name: "Cached form", status: "ACTIVE" },
              ],
            },
            {
              pageId: "p2",
              name: "Old Brand Page",
              account: { id: "77", name: "Mira Fictional" },
              active: false,
              received: 0,
              formsOnPage: [{ id: "x", name: "Form", status: "ARCHIVED" }],
            },
            {
              pageId: "p3",
              name: "Sample Three",
              account: { id: "88", name: "Tali Example" },
              active: false,
              received: 0,
              removed: true,
            },
          ],
        });
      if (path.endsWith("/p1/forms"))
        return Response.json([
          { id: "one", name: "New form", status: "ACTIVE" },
          { id: "two", name: "Second form", status: "ACTIVE" },
          { id: "archived", name: "Earlier campaign", status: "ARCHIVED" },
        ]);
      if (path.endsWith("/v1/lead-desk/team"))
        return Response.json({
          reps: [
            { person_id: "s1", name: "Asha Seller", available: true },
            { person_id: "o1", name: "Owner Person", available: false },
          ],
        });
      if (path.endsWith("/p1/older"))
        return Response.json({
          until: "2026-11-02T05:00:00Z",
          counts: [
            { days: 7, leads: 2 },
            { days: 30, leads: 9 },
            { days: 90, leads: 40 },
          ],
          capped: false,
        });
      return Response.json({ pages: [] });
    }),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    for (let i = 0; i < 12; i++) await Promise.resolve();
  });
}
async function render() {
  await act(async () => {
    root.render(<OrganisationSources />);
  });
  await settle();
}
async function tap(text: string, within: ParentNode = host) {
  const button = [...within.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === text,
  );
  expect(button, text).toBeDefined();
  await act(async () => button!.click());
  await settle();
}
const account = (name: string) =>
  host.querySelector(`section[aria-label="Facebook account ${name}"]`)!;

it("says what is connected and working, by account, without saving on load", async () => {
  await render();
  expect(host.textContent).toContain(
    "2 Facebook accounts · 1 Page bringing leads · last lead 2 h ago",
  );
  const mira = account("Mira Fictional");
  expect(mira.textContent).toContain("Connected");
  expect(mira.textContent).toContain("Sample One");
  expect(mira.textContent).toContain(
    "On · 1 form · last lead 2 h ago · 2 leads",
  );
  // Fresh forms from Meta, active ones; archived behind their fold.
  expect(mira.textContent).toContain("Second form");
  expect(mira.textContent).not.toContain("Cached form");
  expect(mira.textContent).toContain("Show archived (1)");
  expect(mira.textContent).toContain("Other Pages from this account (1)");
  expect(account("Tali Example").textContent).toContain("Removed Pages (1)");
  expect(calls.every((call) => call.body === null)).toBe(true);
  // No real form has sent a lead yet: said plainly.
  expect(host.textContent).toContain(
    "Only Meta test leads so far: no real form has sent a lead yet",
  );
});

it("drops the test-leads line once a real form has sent a lead", async () => {
  real = true;
  await render();
  expect(host.textContent).not.toContain("Only Meta test leads");
});

it("asks before disconnecting an account, naming what stops", async () => {
  await render();
  const mira = account("Mira Fictional");
  await tap("Disconnect", mira);
  expect(calls.some((call) => call.path.includes("/disconnect"))).toBe(false);
  expect(mira.textContent).toContain(
    "Disconnect Mira Fictional? 2 Pages and 1 form stop bringing leads. Leads already here stay.",
  );
  await tap("Keep", mira);
  expect(calls.some((call) => call.path.includes("/disconnect"))).toBe(false);
  await tap("Disconnect", mira);
  await tap("Disconnect", mira.querySelector('[role="alertdialog"]')!);
  expect(
    calls.find((call) => call.path.endsWith("/accounts/77/disconnect"))?.body,
  ).toEqual({});
});

it("turns another Page on, removes one and puts one back", async () => {
  await render();
  const mira = account("Mira Fictional");
  await tap("Turn on", mira);
  expect(calls.find((call) => call.path.endsWith("/pages/p2"))?.body).toEqual({
    forms: "all",
  });
  await tap("Remove", mira);
  expect(calls.some((call) => call.path.endsWith("/pages/p2/remove"))).toBe(
    true,
  );
  await tap("Put back", account("Tali Example"));
  expect(calls.some((call) => call.path.endsWith("/pages/p3/restore"))).toBe(
    true,
  );
});

it("counts older leads first and brings in only the days picked", async () => {
  await render();
  const mira = account("Mira Fictional");
  await tap("Bring in older leads", mira);
  expect(calls.some((call) => call.path.endsWith("/pages/p1/older"))).toBe(
    true,
  );
  expect(mira.textContent).toContain("Last 7 days · 2 leads");
  expect(mira.textContent).toContain("Last 90 days · 40 leads");
  const radios = mira.querySelectorAll<HTMLInputElement>('input[type="radio"]');
  await act(async () => radios[1].click());
  await tap("Bring in 9 leads", mira);
  expect(
    calls.find((call) => call.path.endsWith("/pages/p1/backfill"))?.body,
  ).toEqual({ days: 30 });
});

it("keeps every form with one switch, or the forms picked", async () => {
  await render();
  const mira = account("Mira Fictional");
  const all = mira.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
  expect(all.checked).toBe(false);
  await act(async () => all.click());
  await settle();
  expect(calls.find((call) => call.path.endsWith("/pages/p1"))?.body).toEqual({
    forms: "all",
  });
  calls.length = 0;
  // The last form on stays on, enabled, and says why (ux-audit).
  const only = [...mira.querySelectorAll("label")]
    .find((label) => label.textContent?.includes("New form"))!
    .querySelector<HTMLInputElement>('input[type="checkbox"]')!;
  expect(only.disabled).toBe(false);
  await act(async () => only.click());
  await settle();
  expect(only.checked).toBe(true);
  expect(calls.some((call) => call.body !== null)).toBe(false);
  expect(vi.mocked(notify)).toHaveBeenCalledWith(
    expect.objectContaining({ title: expect.stringContaining("at least one") }),
  );
  // Square boxes beside each name, like All forms (ux-audit): several can be on.
  const second = [...mira.querySelectorAll("label")].find((label) =>
    label.textContent?.includes("Second form"),
  )!;
  const box = second.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
  expect(box.checked).toBe(false);
  await act(async () => box.click());
  await settle();
  expect(calls.find((call) => call.path.endsWith("/pages/p1"))?.body).toEqual({
    forms: ["one", "two"],
  });
});

it("adds Pages within each account and another account at the end", async () => {
  await render();
  const links = [...host.querySelectorAll("a")].map((link) => [
    link.textContent,
    link.getAttribute("href"),
  ]);
  expect(links).toEqual(
    expect.arrayContaining([
      ["Add Pages", "/v1/lead-desk/meta/connect-sources"],
      [
        "Connect another Facebook account",
        "/v1/lead-desk/meta/connect-another",
      ],
    ]),
  );
  expect(
    account("Mira Fictional").querySelector(
      'a[href="/v1/lead-desk/meta/connect-sources"]',
    ),
  ).not.toBeNull();
});

// Orchestrator, 2 Nov 2026 (the live run on dev): with none new, the line says
// how many were already here, never "0 older leads brought in · on Cold".
it("says what a run of older leads brought, or that they were already here", () => {
  const done = { state: "done" as const, seen: 2 };
  expect(runLine({ ...done, created: 0, known: 2 })).toBe(
    "2 older leads already here",
  );
  expect(runLine({ ...done, created: 0, linked: 1 })).toBe(
    "1 older lead already here",
  );
  expect(runLine({ ...done, created: 0 })).toBe("No older leads in those days");
  expect(runLine({ ...done, created: 9, known: 2 })).toBe(
    "9 older leads brought in · on Cold",
  );
  expect(runLine({ state: "running", created: 3, seen: 5 })).toBe(
    "Bringing in older leads… 3 so far",
  );
});

// Owner, 2 Nov 2026: leads go to sellers, never to owners; a Page asks "Who gets
// these leads?" with three answers.
it("says who gets a Page's new leads, and changes it to one seller", async () => {
  await render();
  const mira = account("Mira Fictional");
  expect(mira.textContent).toContain("New leads: shared between your sellers");
  await tap("Change", mira);
  const choice = mira.querySelector("fieldset")!;
  expect(choice.textContent).toContain("Who gets these leads?");
  const radio = (words: string) =>
    [...choice.querySelectorAll("label")]
      .find((label) => label.textContent === words)!
      .querySelector<HTMLInputElement>('input[type="radio"]')!;
  await act(async () => radio("One seller").click());
  // Sellers only: the owner, who doesn't take new leads, isn't offered.
  expect(choice.textContent).toContain("Asha Seller");
  expect(choice.textContent).not.toContain("Owner Person");
  // The sellers sit under "One seller", before the last answer (ux-audit, 2 Nov 2026).
  expect(
    [...choice.querySelectorAll(":scope > label, :scope > ul")].map((item) =>
      item.tagName === "UL" ? "sellers" : item.textContent,
    ),
  ).toEqual([
    "Share between my sellers",
    "One seller",
    "sellers",
    "Leave them for me to assign",
  ]);
  const save = [...choice.querySelectorAll("button")].find(
    (button) => button.textContent === "Save",
  )!;
  expect(save.disabled).toBe(true);
  await act(async () => radio("Asha Seller").click());
  await tap("Save", choice);
  expect(
    calls.find((call) => call.path.endsWith("/pages/p1/assign"))?.body,
  ).toEqual({ mode: "one", personId: "s1" });
});

// /settings/sources redirects to this hub: linking to it here would send people in a loop.
it("keeps the other source controls on the screen, without a second Facebook card", async () => {
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
  expect(
    calls.filter((call) => call.path.endsWith("/meta/status")),
  ).toHaveLength(1);
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
