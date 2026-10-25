// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notify = vi.fn();
vi.mock("../notice-center", () => ({ notify: (n: unknown) => notify(n) }));

import { resetBackCloseForTests } from "../ui/back-close";
import { AssignSheet } from "./assign-sheet";
import type { RepView } from "./leads-client";
import { leftWords, type Distribution } from "./team-engine-client";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const rep = (id: string, name: string, available = true): RepView => ({
  person_id: id,
  name,
  role: "member",
  revision: 1,
  available,
  max_open: 40,
  languages: [],
  areas: [],
  interests: [],
  open_leads: 12,
  due_now: 0,
  calls_today: 0,
  connected_today: 0,
});

const REPS = [
  rep("p1", "priya sample"),
  rep("p2", "rohan example"),
  rep("p3", "kavya fictional", false),
];

const plan = (preview: boolean): Distribution => ({
  rule: "even",
  preview,
  leads: 40,
  moved: 38,
  given: [
    {
      person_id: "p1",
      name: "priya sample",
      leads: 19,
      open_after: 31,
      max_open: 40,
    },
    {
      person_id: "p2",
      name: "rohan example",
      leads: 19,
      open_after: 31,
      max_open: 40,
    },
  ],
  left: { closed: 2 },
  sources: { Facebook: 30, Website: 10 },
  cities: {},
  more: false,
  words: "38 leads given out evenly: 19 each to 2 sellers.",
});

let root: Root;
let host: HTMLDivElement;
let bodies: {
  preview: boolean;
  rule: string;
  sellers?: string[];
  command_id: string;
}[];

beforeEach(() => {
  vi.useFakeTimers();
  bodies = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      bodies.push(body);
      return new Response(JSON.stringify(plan(body.preview)), {
        headers: { "content-type": "application/json" },
      });
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
  vi.useRealTimers();
});

async function settle() {
  await act(async () => vi.advanceTimersByTime(400));
  await act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });
}

const sheet = () => document.querySelector("dialog")!;

it("words what stays and why", () => {
  expect(leftWords({ closed: 1, everyone_at_cap: 3 })).toEqual([
    "1 is closed",
    "3 wait: everyone is at their limit",
  ]);
});

// Owner program, 25 Oct 2026: an owner assigns leads by rules, plan first.
it("shows the plan before anything moves, then gives the leads out", async () => {
  const onDone = vi.fn();
  await act(async () =>
    root.render(
      <AssignSheet
        open
        target={{ kind: "unassigned", count: 40 }}
        reps={REPS}
        onClose={() => {}}
        onDone={onDone}
      />,
    ),
  );
  await settle();
  expect(bodies[0]).toMatchObject({
    preview: true,
    rule: "even",
    unassigned: true,
    sellers: ["p1", "p2"],
  });
  expect(sheet().textContent).toContain("40 leads with no owner");
  expect(sheet().textContent).toContain("Priya Sample+1931 open of 40");
  expect(sheet().textContent).toContain("2 are closed");
  const give = Array.from(sheet().querySelectorAll("button")).find((b) =>
    b.textContent?.startsWith("Give out"),
  )!;
  expect(give.textContent).toBe("Give out 38 leads");
  await act(async () => give.click());
  await settle();
  const applied = bodies.find((body) => !body.preview)!;
  expect(applied.preview).toBe(false);
  expect(applied.command_id).toBe(bodies[0].command_id);
  expect(onDone).toHaveBeenCalledOnce();
  expect(notify).toHaveBeenCalledWith(
    expect.objectContaining({ tone: "success", title: "38 leads given out" }),
  );
});

it("maps each source to the sellers picked for it", async () => {
  await act(async () =>
    root.render(
      <AssignSheet
        open
        target={{ kind: "unassigned", count: 40 }}
        reps={REPS}
        onClose={() => {}}
        onDone={() => {}}
      />,
    ),
  );
  await settle();
  const bySource = Array.from(sheet().querySelectorAll("label")).find((label) =>
    label.textContent?.startsWith("By source"),
  )!;
  await act(async () => bySource.querySelector("input")!.click());
  await settle();
  expect(sheet().textContent).toContain("Facebook30");
  const priya = Array.from(sheet().querySelectorAll("li"))
    .find((li) => li.textContent?.startsWith("Facebook"))!
    .querySelector("button")!;
  await act(async () => priya.click());
  await settle();
  expect(bodies.at(-1)).toMatchObject({
    rule: "by_source",
    groups: { Facebook: ["p1"] },
  });
});
