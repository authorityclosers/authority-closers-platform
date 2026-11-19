/**
 * My Next-call missions (redesign study §5 S5; 13 Nov 2026 meeting, section
 * 5): the calls waiting for an answer come first as check-in cards, up to
 * three ticked missions stay active, and each shows on how many calls it was
 * tried. A fake server holds fictional missions and calls.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { COPY } from "./copy";
import { MISSION_WORDS, MissionsScreen } from "./missions-screen";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

type Fake = {
  ticked: string[];
  active: string[];
  answers: Record<string, Record<string, boolean>>;
  writes: { path: string; body: unknown }[];
};

const TITLES: Record<string, string> = {
  PB03: "Price question",
  OB03: "Think-about-it question",
  DM02: "Partner question",
  NX02: "Next-step question",
};

let host: HTMLDivElement | null = null;
let root: Root | null = null;
let fake: Fake;

function growth() {
  const done = (code: string) =>
    Object.values(fake.answers).filter((call) => call[code] === true).length;
  const order = [...new Set([...fake.active, ...fake.ticked])];
  return {
    max_active: 3,
    active: fake.active,
    missions: order.map((code) => ({
      question_id: code,
      title: TITLES[code],
      mission: `Mission for ${code}`,
      active: fake.active.includes(code),
      ticked: fake.ticked.includes(code),
      done_calls: done(code),
      not_done_calls: 0,
    })),
  };
}

function serve() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace("/v1/sales-xray/ask-dipak", "");
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      const json = (value: unknown, status = 200) =>
        new Response(JSON.stringify(value), { status });
      if (method === "PUT") fake.writes.push({ path, body });
      if (path === "/growth") return json(growth());
      if (path === "/calls")
        return json({
          active: fake.active.map((code) => ({
            question_id: code,
            title: TITLES[code],
          })),
          calls: [
            {
              call_id: "call-1",
              lead_name: "Fictional Lead",
              called_at: "2026-11-14T10:00:00+05:30",
              answered: Object.keys(fake.answers["call-1"] ?? {}),
              waiting: fake.active.filter(
                (code) => !(code in (fake.answers["call-1"] ?? {})),
              ),
            },
          ],
        });
      const focus = path.match(/^\/focus\/(.+)$/);
      if (focus) {
        const code = decodeURIComponent(focus[1]);
        if (body.active) {
          if (fake.active.length >= 3)
            return json(
              { detail: "3 missions are already active; drop one first." },
              409,
            );
          fake.active.push(code);
        } else fake.active = fake.active.filter((item) => item !== code);
        return json(growth());
      }
      const check = path.match(/^\/calls\/(.+)\/check$/);
      if (check) {
        const [answer] = body.answers as {
          question_id: string;
          done: boolean;
        }[];
        fake.answers[check[1]] = {
          ...(fake.answers[check[1]] ?? {}),
          [answer.question_id]: answer.done,
        };
        return json({});
      }
      return json({ detail: "Not found." }, 404);
    }),
  );
}

async function show(): Promise<HTMLDivElement> {
  const element = document.createElement("div");
  document.body.append(element);
  const made = createRoot(element);
  host = element;
  root = made;
  await act(async () => {
    made.render(<MissionsScreen />);
  });
  await act(async () => {});
  return element;
}

const page = (): HTMLDivElement => {
  if (!host) throw new Error("not shown");
  return host;
};

const button = (label: string, within: ParentNode = page()) =>
  Array.from(within.querySelectorAll("button")).filter(
    (item) => item.textContent?.trim() === label,
  );

async function click(element: Element | undefined) {
  if (!element) throw new Error("nothing to click");
  await act(async () => {
    (element as HTMLElement).click();
  });
  await act(async () => {});
}

beforeEach(() => {
  fake = { ticked: [], active: [], answers: {}, writes: [] };
  serve();
});

afterEach(async () => {
  if (root) await act(async () => root?.unmount());
  host?.remove();
  root = null;
  host = null;
  vi.unstubAllGlobals();
});

it("says how to start when no mission is ticked, with a way to the topics", async () => {
  await show();
  expect(page().textContent).toContain(MISSION_WORDS.none);
  expect(page().textContent).toContain(MISSION_WORDS.noneHint);
  const go = Array.from(page().querySelectorAll("a")).find(
    (link) => link.textContent === MISSION_WORDS.explore,
  );
  expect(go?.getAttribute("href")).toContain("topics");
  expect(page().querySelector("[data-call]")).toBeNull();
});

it("asks only when a mission is active", async () => {
  fake.ticked = ["PB03"];
  await show();
  expect(page().textContent).toContain(MISSION_WORDS.noActive);
  expect(page().querySelector("[data-call]")).toBeNull();
});

it("keeps three active at most, and drops one to add another", async () => {
  fake.ticked = ["PB03", "OB03", "DM02", "NX02"];
  fake.active = ["PB03", "OB03"];
  await show();
  expect(page().textContent).toContain(`${MISSION_WORDS.active} (2/3)`);
  await click(
    page().querySelector('[data-mission="DM02"]')?.querySelector("button") ??
      undefined,
  );
  expect(fake.active).toEqual(["PB03", "OB03", "DM02"]);
  expect(page().textContent).toContain(MISSION_WORDS.full);
  const add = page()
    .querySelector('[data-mission="NX02"]')
    ?.querySelector("button");
  expect(add?.disabled).toBe(true);
  await click(
    page().querySelector('[data-mission="PB03"]')?.querySelector("button") ??
      undefined,
  );
  expect(fake.writes.at(-1)).toEqual({
    path: "/focus/PB03",
    body: { active: false },
  });
  expect(page().textContent).toContain(`${MISSION_WORDS.active} (2/3)`);
});

it("asks after a call for each active mission, and counts the yes", async () => {
  fake.ticked = ["PB03", "OB03"];
  fake.active = ["PB03", "OB03"];
  await show();
  const call = page().querySelector('[data-call="call-1"]');
  expect(call?.textContent).toContain("Fictional Lead");
  expect(call?.textContent).toContain(COPY.checkinNote);
  // The check-in is the screen's first thing to do, before the missions.
  const first = page().querySelector("[data-call], [data-mission]");
  expect(first?.getAttribute("data-call")).toBe("call-1");
  expect(button(MISSION_WORDS.did, call ?? page())).toHaveLength(2);
  await click(button(MISSION_WORDS.did, call ?? page())[0]);
  expect(fake.writes.at(-1)).toEqual({
    path: "/calls/call-1/check",
    body: { answers: [{ question_id: "PB03", done: true }] },
  });
  expect(page().querySelector('[data-mission="PB03"]')?.textContent).toContain(
    COPY.triedOn(1),
  );
  await click(
    button(
      MISSION_WORDS.didnt,
      page().querySelector('[data-call="call-1"]') ?? page(),
    )[0],
  );
  expect(fake.answers["call-1"]).toEqual({ PB03: true, OB03: false });
  expect(page().querySelector('[data-call="call-1"]')?.textContent).toContain(
    `${MISSION_WORDS.answered}:`,
  );
  // "No chance" carries no penalty: only the tries are counted.
  expect(
    page().querySelector('[data-mission="OB03"]')?.textContent,
  ).not.toContain("Tried on");
});

it("shows a mission's lesson once when the server has no mission words", async () => {
  fake.ticked = ["PB03"];
  fake.active = ["PB03"];
  const original = globalThis.fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const response = await original(input, init);
      if (!String(input).endsWith("/growth")) return response;
      const body = (await response.json()) as {
        missions: { mission: string | null }[];
      };
      for (const mission of body.missions) mission.mission = null;
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  await show();
  const card = page().querySelector('[data-mission="PB03"]');
  const said = card?.textContent?.split(TITLES.PB03).length ?? 0;
  expect(said - 1).toBe(1);
});

it("passes on the server's own words when it refuses", async () => {
  fake.ticked = ["PB03", "OB03", "DM02", "NX02"];
  fake.active = ["PB03", "OB03", "DM02"];
  const { setActive } = await import("./coaching-client");
  await expect(setActive("NX02", true)).rejects.toThrow(
    "3 missions are already active; drop one first.",
  );
});
