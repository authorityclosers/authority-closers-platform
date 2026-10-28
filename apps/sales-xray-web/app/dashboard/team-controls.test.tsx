// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notify = vi.hoisted(() => vi.fn());
vi.mock("../notice-center", () => ({ notify }));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: unknown; href: string }) => (
    <a href={href}>{children as never}</a>
  ),
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { TeamControls } from "./team-controls";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner Home v3 (28 Oct 2026): Team controls behind a gear. Fictional names.
const rep = (id: string, name: string) => ({
  person_id: id,
  name,
  role: "member",
  revision: 1,
  available: true,
  max_open: 40,
  languages: [],
  areas: [],
  interests: [],
  open_leads: 12,
  due_now: 0,
  calls_today: 0,
  connected_today: 0,
});

let sent: { method: string; path: string; body: unknown }[];
let savedNudges: boolean | undefined;
const team = () => ({
  reps: [rep("p1", "priya sample"), rep("p2", "rohan example")],
  settings: {
    revision: 3,
    auto_reassign: false,
    reassign_minutes: 10,
    default_country: "IN",
    nudges_off_for: ["p2"],
    ...(savedNudges === undefined ? {} : { nudges: savedNudges }),
  },
  by_stage: {},
  by_source: {},
  unassigned: 0,
  waiting_first_call: 0,
});

const answer = (path: string) => {
  if (path === "/v1/lead-desk/team") return team();
  if (path === "/v1/lead-desk/targets/team")
    return {
      sellers: [
        {
          person_id: "p1",
          targets: [
            { metric: "calls", period: "day", value: 40 },
            { metric: "meetings", period: "week", value: 3 },
          ],
          progress: [
            {
              metric: "calls",
              period: "day",
              target: 40,
              done: 18,
              pace: 0.65,
              expected: 26,
              behind: true,
              short: 8,
            },
          ],
        },
      ],
    };
  if (path === "/v1/lead-desk/targets")
    return { person_id: "p1", targets: [], progress: [] };
  return null;
};

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  sent = [];
  savedNudges = undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const path = String(input);
      sent.push({
        method: init?.method ?? "GET",
        path,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      const body = answer(path);
      return body
        ? new Response(JSON.stringify(body), {
            headers: { "content-type": "application/json" },
          })
        : new Response("{}", { status: 404 });
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  notify.mockClear();
  vi.unstubAllGlobals();
});

async function settle() {
  await act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });
}

const sheet = () => document.querySelector("dialog[open]");
const button = (scope: ParentNode | null, label: string) =>
  Array.from(scope?.querySelectorAll("button") ?? []).find(
    (each) =>
      each.textContent?.trim() === label ||
      each.getAttribute("aria-label") === label,
  );

async function openControls() {
  await act(async () => root.render(<TeamControls />));
  // Nothing is read until the gear is pressed.
  expect(sent).toHaveLength(0);
  await act(async () => button(host, "Controls")?.click());
  await settle();
}

it("opens one sheet: targets per seller, nudges with who gets them, the lead rules", async () => {
  await openControls();
  const open = sheet();
  expect(open?.textContent).toContain("Team controls");
  expect(open?.textContent).toContain("Targets per seller");
  expect(open?.textContent).toContain("18 today");
  // The app's own pickers, never a native select.
  expect(open?.querySelector("select")).toBeNull();
  // Nudges on unless turned off; who gets them as rows with checks.
  expect(open?.textContent).toContain("Nudges and alerts");
  const rows = Array.from(
    open?.querySelectorAll('ul[aria-label="Nudges for"] button') ?? [],
  );
  expect(rows.map((row) => row.getAttribute("aria-pressed"))).toEqual([
    "true",
    "false",
  ]);
  expect(rows[0].textContent).toContain("Priya Sample");
  expect(rows[1].textContent).toContain("Rohan Example");
  expect(button(open, "Save targets")).toBeUndefined();
  expect(sent.filter((each) => each.method === "PUT")).toHaveLength(0);
  await act(async () => button(open, "Targets")?.click());
  expect(
    open?.querySelector('a[href="/settings/lead-rules"]')?.textContent,
  ).toContain("Lead rules");
});

it("opens Alerts without changing a saved off choice", async () => {
  savedNudges = false;
  await openControls();
  expect(
    sheet()?.querySelector('[role="switch"]')?.getAttribute("aria-checked"),
  ).toBe("false");
  expect(button(sheet(), "Save targets")).toBeUndefined();
  expect(sent.filter((each) => each.method !== "GET")).toHaveLength(0);
});

it("steps a target and saves all eight kinds for that seller only", async () => {
  await openControls();
  await act(async () => button(sheet(), "Targets")?.click());
  const save = button(sheet(), "Save targets");
  expect(save?.disabled).toBe(true);
  await act(async () =>
    button(sheet(), "One more: Priya Sample: Calls, a day")?.click(),
  );
  expect(
    sheet()?.querySelector<HTMLInputElement>(
      'input[aria-label="Priya Sample: Calls, a day"]',
    )?.value,
  ).toBe("41");
  expect(button(sheet(), "Save targets")?.disabled).toBe(false);
  await act(async () => button(sheet(), "Save targets")?.click());
  await settle();
  const saves = sent.filter((each) => each.method === "PUT");
  expect(saves).toHaveLength(1);
  const body = saves[0].body as {
    person_id: string;
    targets: { metric: string; period: string; value: number }[];
  };
  expect(body.person_id).toBe("p1");
  expect(body.targets).toHaveLength(8);
  expect(body.targets).toContainEqual({
    metric: "calls",
    period: "day",
    value: 41,
  });
  // The kind not on screen keeps its value.
  expect(body.targets).toContainEqual({
    metric: "meetings",
    period: "week",
    value: 3,
  });
  expect(notify).toHaveBeenCalledWith(
    expect.objectContaining({ tone: "success", title: "Targets saved" }),
  );
});

it("switches the kind of target in place", async () => {
  await openControls();
  await act(async () => button(sheet(), "Targets")?.click());
  await act(async () => button(sheet(), "A week")?.click());
  await act(async () => button(sheet(), "Meetings")?.click());
  expect(
    sheet()?.querySelector<HTMLInputElement>(
      'input[aria-label="Priya Sample: Meetings, a week"]',
    )?.value,
  ).toBe("3");
  expect(sheet()?.textContent).toContain("0 this week");
});
