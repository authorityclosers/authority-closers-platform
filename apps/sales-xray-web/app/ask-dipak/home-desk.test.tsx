/**
 * The Coach's desk (owner's pick H-A, 17 Nov 2026): Continue opens the lesson
 * last opened on this device, or the library on a first visit; today's
 * mission shows only while one is active, and a call waiting for an answer
 * asks "tried?" right on the home, never scoring it. A fake server holds
 * fictional missions and calls.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { TopicArt, hasArt } from "./art";
import { COPY } from "./copy";
import { ContinueCard, MissionStrip } from "./home-desk";
import { CATEGORIES, QUESTIONS, questionById, questionLabel } from "./library";
import type { AskView } from "./nav";
import { lastLesson, rememberLesson } from "./recent";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
let opened: AskView[];
let fake: {
  active: string[];
  waiting: boolean;
  done: number;
  down: boolean;
  writes: { path: string; body: unknown }[];
};

function serve() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace("/v1/sales-xray/ask-dipak", "");
      const json = (value: unknown, status = 200) =>
        new Response(JSON.stringify(value), { status });
      if (fake.down) return json({ detail: "Down." }, 503);
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as {
          answers: { done: boolean }[];
        };
        fake.writes.push({ path, body });
        if (body.answers[0].done) fake.done += 1;
        fake.waiting = false;
        return json({});
      }
      if (path === "/growth")
        return json({
          max_active: 3,
          active: fake.active,
          missions: ["PB03", "OB03"].map((code) => ({
            question_id: code,
            title: `Title ${code}`,
            mission: `Mission for ${code}`,
            active: fake.active.includes(code),
            ticked: true,
            done_calls: code === "PB03" ? fake.done : 0,
            not_done_calls: 0,
          })),
        });
      if (path === "/calls")
        return json({
          active: [],
          calls: [
            {
              call_id: "call-1",
              lead_name: "Fictional Lead",
              called_at: "2026-11-14T10:00:00+05:30",
              answered: [],
              waiting: fake.waiting ? fake.active : [],
            },
          ],
        });
      return json({ detail: "Not found." }, 404);
    }),
  );
}

async function show(node: (open: (view: AskView) => void) => ReactNode) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => {
    root.render(node((view) => opened.push(view)));
  });
  await act(async () => {});
}

const button = (label: string) =>
  Array.from(host.querySelectorAll("button")).find(
    (item) => item.textContent?.trim() === label,
  );

beforeEach(() => {
  opened = [];
  fake = { active: ["PB03"], waiting: true, done: 0, down: false, writes: [] };
  window.localStorage.clear();
  serve();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("shows the whole library on a first visit, with its real counts", async () => {
  await show((open) => <ContinueCard open={open} />);
  const card = host.querySelector("a[data-continue]");
  expect(card?.getAttribute("data-continue")).toBe("first");
  expect(card?.textContent).toContain(
    COPY.libraryMeta(QUESTIONS.length, CATEGORIES.length),
  );
  expect(card?.textContent).toContain("150 lessons · 10 topics");
  (card as HTMLAnchorElement).click();
  expect(opened).toEqual([{ kind: "topics" }]);
});

it("continues the lesson last opened here", async () => {
  rememberLesson("OB03");
  await show((open) => <ContinueCard open={open} />);
  const card = host.querySelector("a[data-continue]");
  expect(card?.getAttribute("href")).toBe("/ask-dipak?lesson=OB03");
  expect(card?.textContent).toContain(questionLabel(questionById("OB03")!));
  expect(card?.textContent).toContain(COPY.continue);
  (card as HTMLAnchorElement).click();
  expect(opened).toEqual([{ kind: "lesson", id: "OB03" }]);
});

it("remembers only real lesson ids", () => {
  rememberLesson("../x");
  expect(lastLesson()).toBeNull();
  rememberLesson("PB03");
  expect(lastLesson()).toBe("PB03");
});

it("asks about the waiting call on the home and records the seller's yes", async () => {
  await show((open) => <MissionStrip open={open} />);
  const strip = host.querySelector("[data-mission-strip]");
  expect(strip?.getAttribute("data-mission-strip")).toBe("PB03");
  expect(strip?.textContent).toContain("Mission for PB03");
  expect(strip?.textContent).toContain("Fictional Lead");
  expect(strip?.textContent).toContain(COPY.checkinNote);
  await act(async () => button(COPY.checkinYes)?.click());
  await act(async () => {});
  expect(fake.writes).toEqual([
    {
      path: "/calls/call-1/check",
      body: { answers: [{ question_id: "PB03", done: true }] },
    },
  ]);
  expect(host.textContent).toContain(COPY.checkinThanks(1));
  expect(host.querySelector("[data-checkin]")).toBeNull();
});

it("takes 'no chance' as not done, with no penalty words", async () => {
  await show((open) => <MissionStrip open={open} />);
  await act(async () => button(COPY.checkinNo)?.click());
  await act(async () => {});
  expect(fake.writes[0].body).toEqual({
    answers: [{ question_id: "PB03", done: false }],
  });
  expect(host.textContent).not.toMatch(/fail|wrong|score:/i);
});

it("links to My missions when no call is waiting", async () => {
  fake.waiting = false;
  await show((open) => <MissionStrip open={open} />);
  const ask = host.querySelector<HTMLAnchorElement>(
    'a[href="/ask-dipak?view=missions"]',
  );
  expect(ask?.textContent).toBe(COPY.missionAsk);
  ask?.click();
  expect(opened).toEqual([{ kind: "missions" }]);
});

it("shows no strip without an active mission, or when the API is down", async () => {
  fake.active = [];
  await show((open) => <MissionStrip open={open} />);
  expect(host.querySelector("[data-mission-strip]")).toBeNull();
  await act(async () => root.unmount());
  host.remove();
  fake.active = ["PB03"];
  fake.down = true;
  await show((open) => <MissionStrip open={open} />);
  expect(host.querySelector("[data-mission-strip]")).toBeNull();
});

it("draws every category, with no words in the drawings", async () => {
  for (const category of CATEGORIES) expect(hasArt(category.id)).toBe(true);
  await show(() => <TopicArt featured="price" />);
  const art = host.querySelector("svg");
  expect(art?.getAttribute("aria-hidden")).toBe("true");
  expect(art?.getAttribute("data-art")).toBe("08");
  expect(host.querySelector("svg text")).toBeNull();
});
