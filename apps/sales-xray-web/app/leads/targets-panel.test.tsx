// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notify = vi.fn();
vi.mock("../notice-center", () => ({ notify: (n: unknown) => notify(n) }));

import { resetBackCloseForTests } from "../ui/back-close";
import { TargetsPanel } from "./targets-panel";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

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

let team: Record<string, unknown>;
let sent: { method: string; path: string; body: unknown }[];

const answer = (path: string) => {
  if (path === "/v1/lead-desk/team") return team;
  if (path === "/v1/lead-desk/targets/team")
    return {
      schema: "lead-desk/1",
      sellers: [
        {
          person_id: "p1",
          targets: [{ metric: "calls", period: "day", value: 40 }],
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
    return { person_id: "p2", targets: [], progress: [] };
  if (path === "/v1/lead-desk/nudges")
    return {
      ...team,
      settings: { ...(team.settings as object), nudges: true, revision: 4 },
    };
  return null;
};

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  team = {
    reps: [rep("p1", "priya sample"), rep("p2", "rohan example")],
    settings: {
      revision: 3,
      auto_reassign: false,
      reassign_minutes: 10,
      default_country: "IN",
      nudges: false,
      nudges_off_for: [],
    },
    by_stage: {},
    by_source: {},
    unassigned: 0,
    waiting_first_call: 0,
  };
  sent = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const path = String(input);
      const method = init?.method ?? "GET";
      sent.push({
        method,
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

async function mount() {
  await act(async () => root.render(<TargetsPanel />));
  await act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });
}

// Owner program, 25 Oct 2026: daily and weekly targets per seller.
it("shows each seller's progress against their targets", async () => {
  await mount();
  const rows = Array.from(host.querySelectorAll("li"), (li) => li.textContent);
  expect(rows[0]).toContain("Priya Sample");
  expect(rows[0]).toContain("Calls 18/40 · 8 behind");
  expect(rows[1]).toContain("No targets yet");
});

it("sets a seller's targets from today, and turns nudges on", async () => {
  await mount();
  const set = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Set Rohan Example\'s targets"]',
  )!;
  await act(async () => set.click());
  const field = document.querySelector<HTMLInputElement>(
    'dialog input[aria-label="Calls a day"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(field, "30");
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const save = Array.from(document.querySelectorAll("dialog button")).find(
    (button) => button.textContent === "Save targets",
  ) as HTMLButtonElement;
  await act(async () => save.click());
  await act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });
  const put = sent.find((item) => item.path === "/v1/lead-desk/targets");
  expect(put?.method).toBe("PUT");
  expect(put?.body).toMatchObject({ person_id: "p2" });
  expect((put?.body as { targets: unknown[] }).targets).toContainEqual({
    metric: "calls",
    period: "day",
    value: 30,
  });
  const nudges = host.querySelector<HTMLButtonElement>(
    'button[role="switch"]',
  )!;
  expect(nudges.getAttribute("aria-checked")).toBe("false");
  await act(async () => nudges.click());
  await act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });
  expect(
    sent.find((item) => item.path === "/v1/lead-desk/nudges")?.body,
  ).toEqual({
    expected_revision: 3,
    enabled: true,
    off_for: [],
  });
  expect(nudges.getAttribute("aria-checked")).toBe("true");
});
