// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notify = vi.hoisted(() => vi.fn());
vi.mock("../notice-center", () => ({ notify }));

import { resetBackCloseForTests } from "../ui/back-close";
import { TeamControls } from "./team-controls";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 31 Oct 2026: five cards with their values; exceptions inside a card.
// Fictional names.
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
let hours: Record<string, unknown> | null;
let offFor: string[];
let sla: Record<string, unknown>;
const team = () => ({
  reps: [rep("p1", "priya sample"), rep("p2", "rohan example")],
  settings: {
    revision: 3,
    auto_reassign: false,
    reassign_minutes: 10,
    default_country: "IN",
    nudges: true,
    nudges_off_for: offFor,
    work_hours: hours,
  },
  by_stage: {},
  by_source: {},
  unassigned: 0,
  waiting_first_call: 0,
});

const answer = (
  method: string,
  path: string,
  body: Record<string, unknown>,
) => {
  if (path === "/v1/lead-desk/team") return team();
  if (path === "/v1/lead-desk/sla" && method === "GET") return sla;
  if (path === "/v1/lead-desk/sla") return (sla = { ...sla, ...body });
  if (path === "/v1/lead-desk/nudges") {
    offFor = body.off_for as string[];
    return team();
  }
  if (path === "/v1/lead-desk/work-hours") {
    hours = { ...body, inside: true, next_start: null };
    return team();
  }
  return null;
};

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  sent = [];
  hours = null;
  offFor = ["p2"];
  sla = {
    on: true,
    minutes: 10,
    alertManagers: false,
    targets: [5, 10, 15, 30, 60, 120],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const path = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      sent.push({ method, path, body });
      const reply = answer(method, path, body ?? {});
      return reply
        ? new Response(JSON.stringify(reply), {
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
const button = (label: string) =>
  Array.from(sheet()?.querySelectorAll("button") ?? []).find(
    (each) =>
      each.textContent?.trim() === label ||
      each.getAttribute("aria-label") === label,
  );
const chips = () =>
  Array.from(sheet()?.querySelectorAll("[data-control]") ?? [], (card) => [
    card.getAttribute("data-control"),
    card.querySelector("[data-tone], span:nth-child(3)")?.textContent,
  ]);
const card = async (key: string) => {
  await act(async () =>
    (sheet()?.querySelector(`[data-control=${key}]`) as HTMLElement).click(),
  );
  await settle();
};

async function openControls() {
  await act(async () => root.render(<TeamControls />));
  // Nothing is read until the gear is pressed.
  expect(sent).toHaveLength(0);
  await act(async () =>
    Array.from(host.querySelectorAll("button"))
      .find((each) => each.textContent?.trim() === "Controls")
      ?.click(),
  );
  await settle();
}

it("shows five cards with their values, and no tabs or rows of sellers", async () => {
  await openControls();
  expect(chips()).toEqual([
    ["hours", "Not set"],
    ["first_call", "Within 10 min"],
    ["nudges", "On, except 1"],
    ["alerts", "0 of 3 on"],
    ["summary", "7:00 PM · Soon"],
  ]);
  expect(button("Alerts")).toBeUndefined();
  expect(button("Targets")).toBeUndefined();
  expect(sheet()?.textContent).not.toContain("Rohan");
});

it("sets the first-call limit in one tap", async () => {
  await openControls();
  await card("first_call");
  const fifteen = Array.from(
    sheet()?.querySelectorAll("[role=radio]") ?? [],
  ).find((radio) => radio.textContent === "15 min") as HTMLElement;
  await act(async () => fifteen.click());
  await settle();
  expect(sent.at(-1)).toEqual({
    method: "PUT",
    path: "/v1/lead-desk/sla",
    body: { on: true, minutes: 15, alertManagers: false },
  });
  await act(async () => button("Team controls")?.click());
  await settle();
  expect(chips()[1]).toEqual(["first_call", "Within 15 min"]);
});

it("excepts one seller from nudges inside its card", async () => {
  await openControls();
  await card("nudges");
  expect(sheet()?.textContent).toContain("Rohan Example");
  await act(async () => button("Pick a seller")?.click());
  const priya = Array.from(sheet()?.querySelectorAll("button") ?? []).find(
    (each) => each.textContent === "Priya Sample",
  ) as HTMLElement;
  await act(async () => priya.click());
  await settle();
  expect(sent.at(-1)).toEqual({
    method: "PUT",
    path: "/v1/lead-desk/nudges",
    body: { expected_revision: 3, enabled: true, off_for: ["p2", "p1"] },
  });
});

it("starts working hours from the owner's usual day: 10:30 to 7, lunch 1:30 to 2:15", async () => {
  await openControls();
  await card("hours");
  await act(async () => button("Use these hours")?.click());
  await settle();
  expect(sent.at(-1)).toEqual({
    method: "PUT",
    path: "/v1/lead-desk/work-hours",
    body: {
      expected_revision: 3,
      days: [0, 1, 2, 3, 4, 5],
      start: "10:30",
      end: "19:00",
      pause_leads: false,
      breaks: [{ start: "13:30", end: "14:15" }],
    },
  });
  await act(async () => button("Team controls")?.click());
  await settle();
  expect(chips()[0]).toEqual(["hours", "10:30–7:00 · lunch 1:30–2:15"]);
});

it("keeps what the server does not do yet switched off", async () => {
  await openControls();
  await card("alerts");
  const switches = Array.from(sheet()?.querySelectorAll("[role=switch]") ?? []);
  expect(switches.map((each) => (each as HTMLButtonElement).disabled)).toEqual([
    false,
    true,
    true,
  ]);
  await act(async () => (switches[0] as HTMLElement).click());
  await settle();
  expect(sent.at(-1)?.body).toEqual({
    on: true,
    minutes: 10,
    alertManagers: true,
  });
});
