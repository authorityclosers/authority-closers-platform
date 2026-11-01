// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const opened = vi.hoisted(() => ({ steps: [] as Array<string | undefined> }));
vi.mock("./capture-setup-gate", () => ({
  openCaptureSetup: (step?: string) => opened.steps.push(step),
}));

import { WorkspaceAccessContext } from "../workspace-access";
import { missingWords, RecordingLine } from "./recording-check";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Competitor teardown #13, 1 Nov 2026: "4 calls today have no recording · Fix"
// is one line at the top of Calls and Reports, never a floating card, counted
// from Home's own calls so it never contradicts "Tried 0". Phone personas
// ph1-27: the bell's See why opens that day's calls and their fix.

const LEAD = "00000000-0000-4000-8000-000000000401";
const ITEMS = [
  {
    event_id: "00000000-0000-4000-8000-000000000501",
    lead_id: LEAD,
    lead_name: "Rohan Fictional",
    at: "2026-10-30T09:05:00+00:00",
    seconds: 95,
  },
  {
    event_id: "00000000-0000-4000-8000-000000000502",
    lead_id: "00000000-0000-4000-8000-000000000402",
    lead_name: null,
    at: "2026-10-30T06:40:00+00:00",
    seconds: 42,
  },
];

let root: Root;
let host: HTMLDivElement;
let asked: string[];

beforeEach(() => {
  opened.steps.length = 0;
  asked = [];
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

async function mount(calls: number, tried: number, items = ITEMS) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      asked.push(String(input));
      return new Response(
        JSON.stringify({
          schema: "sales-xray-missing-recordings/1",
          calls,
          tried,
          latest_at: calls ? ITEMS[0].at : null,
          items: calls ? items : [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }),
  );
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: "p", sessionId: "s", tenantId: "t" },
          workspaces: [],
          retry: () => {},
        }}
      >
        <RecordingLine />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  for (let i = 0; i < 8; i++) await act(async () => await Promise.resolve());
}

const button = (label: string) =>
  [...host.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === label,
  );

it("says how many in plain words, today or on the bell's day", () => {
  expect(missingWords(4, null)).toBe("4 calls today have no recording");
  expect(missingWords(1, null)).toBe("1 call today has no recording");
  expect(missingWords(2, "2026-10-30")).toBe(
    "30 Oct: 2 calls had no recording",
  );
});

it("is one line whose count opens the calls and whose Fix opens the failing step", async () => {
  await mount(2, 9);
  expect(asked[0]).toMatch(/\/capture-setup\/missing$/);
  const line = host.querySelector("section");
  expect(line?.textContent).toBe("2 calls today have no recording·Fix");
  // The calls stay folded until the count is tapped.
  expect(host.querySelector("ul")).toBeNull();
  const count = button("2 calls today have no recording")!;
  expect(count.getAttribute("aria-expanded")).toBe("false");
  await act(async () => count.click());
  const rows = [...host.querySelectorAll("li")];
  expect(rows).toHaveLength(2);
  expect(rows[0].querySelector("a")?.getAttribute("href")).toBe(
    `/leads?lead=${LEAD}`,
  );
  expect(rows[0].textContent).toContain("Rohan Fictional");
  expect(rows[0].textContent).toContain("1:35");
  // A lead with no name yet, never a number.
  expect(rows[1].textContent).toContain("A lead");
  expect(rows[1].textContent).not.toMatch(/\d{10}/);
  // On the web, Fix opens the setup at "open the app on your phone".
  await act(async () => button("Fix")!.click());
  for (let i = 0; i < 4; i++) await act(async () => await Promise.resolve());
  expect(opened.steps).toEqual(["phone"]);
});

// QA robot reports 845, 846 and 857 (1 Nov 2026): rows and Call buttons sat
// under the old corner card. The line is part of the page, at its top, as
// NoticeDock's notices are: nothing in it is pinned or lifted over the rows.
it("sits in the page's flow, never pinned over the rows", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const css = readFileSync(join(here, "capture-setup.module.css"), "utf8");
  const rules = css.match(/[^{}]*\.missingLine[^{}]*\{[^}]*\}/g) ?? [];
  expect(rules.length).toBeGreaterThan(5);
  for (const rule of rules)
    expect(rule).not.toMatch(
      /position:\s*(fixed|sticky|absolute)|z-index|inset|translate/,
    );
});

it("shows nothing when Home tried nothing today, or every call has its recording", async () => {
  await mount(3, 0);
  expect(host.innerHTML).toBe("");
  await act(async () => root.unmount());
  root = createRoot(host);
  await mount(0, 12);
  expect(host.innerHTML).toBe("");
});

it("opens at the bell's day, named as the bell names it, with its calls listed", async () => {
  window.history.replaceState(
    null,
    "",
    "/analysis/calls?no-recording=2026-10-30",
  );
  await mount(2, 6);
  expect(asked[0]).toMatch(/\/capture-setup\/missing\/2026-10-30$/);
  expect(button("30 Oct: 2 calls had no recording")).toBeDefined();
  expect(host.querySelectorAll("li")).toHaveLength(2);
});

it("says the bell's day is fine once its recordings arrived", async () => {
  window.history.replaceState(
    null,
    "",
    "/analysis/calls?no-recording=2026-10-30",
  );
  await mount(0, 6);
  expect(host.textContent).toBe("30 Oct: every call has its recording now");
  expect(button("Fix")).toBeUndefined();
});
