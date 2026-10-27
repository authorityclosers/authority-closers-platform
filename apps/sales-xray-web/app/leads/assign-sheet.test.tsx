// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notify = vi.fn();
vi.mock("../notice-center", () => ({ notify: (n: unknown) => notify(n) }));
const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

import { resetBackCloseForTests } from "../ui/back-close";
import { AssignSheet, nothingWhy, ruleExample } from "./assign-sheet";
import type { RepView } from "./leads-client";
import { leftWords, type Distribution } from "./team-engine-client";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const rep = (
  id: string,
  name: string,
  available = true,
  open = 12,
): RepView => ({
  person_id: id,
  name,
  role: "member",
  revision: 1,
  available,
  max_open: 40,
  languages: [],
  areas: [],
  interests: [],
  open_leads: open,
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
// What the next previews return instead of plan(), when a test sets it.
let answer: Distribution | null = null;

beforeEach(() => {
  vi.useFakeTimers();
  bodies = [];
  answer = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      bodies.push(body);
      return new Response(JSON.stringify(answer ?? plan(body.preview)), {
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
  push.mockClear();
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

// Owner bug #55, 28 Oct 2026: "Confusion of this feature." The sheet says what
// it does, and each choice shows what it would do with the team's own numbers.
it("says what it does, with an example from the team's numbers under each choice", async () => {
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
  const text = sheet().textContent;
  expect(text).toContain("This gives them out once, the way you pick below.");
  expect(text).toContain("New leads keep going out by your lead rules.");
  expect(text).toContain("40 leads → 20 each for 2 sellers");
  expect(text).toContain("Everyone has 12 open now, so it shares like Even");
  expect(text).toContain("Facebook leads to Priya, Website to Rohan");
  expect(text).toContain("None of these leads has a city to go by");
});

it("works each example out from real numbers", () => {
  const light = rep("a", "asha sample", true, 2);
  const heavy = rep("b", "ravi example", true, 9);
  const four = [
    light,
    heavy,
    rep("c", "meera sample"),
    rep("d", "dev example"),
  ];
  expect(ruleExample("even", 13, four, null)).toBe(
    "13 leads → 3 or 4 each for 4 sellers",
  );
  expect(ruleExample("even", 2, four, null)).toBe(
    "2 leads → 1 each to 2 of your 4 sellers",
  );
  expect(ruleExample("even", 1, four, null)).toBe(
    "1 lead → one of your 4 sellers",
  );
  expect(ruleExample("even", 0, four, null)).toBe(
    "For example, 12 new leads → 3 each for 4 sellers",
  );
  expect(ruleExample("even", 5, [light], null)).toBe("5 leads → all to Asha");
  expect(ruleExample("balanced", 5, [heavy, light], null)).toBe(
    "Asha has 2 open, Ravi 9: Asha gets leads first",
  );
  expect(ruleExample("balanced", 5, [light], null)).toBeNull();
  expect(ruleExample("by_city", 0, [light, heavy], null)).toBe(
    "For example, one city's leads to Asha, another's to Ravi",
  );
  expect(ruleExample("even", 5, [], null)).toBeNull();
});

it("says why nothing moves, and what to do about it", () => {
  const none: Distribution = { ...plan(true), moved: 0, given: [], left: {} };
  expect(nothingWhy(none, 0, "even")).toEqual({
    line: "Tick at least one seller under To.",
    button: "Pick a seller first",
  });
  expect(nothingWhy(none, 0, "by_city").line).toBe(
    "Pick a seller for at least one city.",
  );
  expect(
    nothingWhy({ ...none, left: { everyone_at_cap: 40 } }, 2, "even").button,
  ).toBe("Everyone is full");
  expect(
    nothingWhy({ ...none, left: { no_seller_for_it: 40 } }, 1, "by_source")
      .line,
  ).toBe("No seller is picked for these leads' sources yet.");
  expect(nothingWhy({ ...none, left: { closed: 3 } }, 2, "even").line).toBe(
    "These leads are won, lost or junk. Closed leads stay where they are.",
  );
});

it("names the reason on the button instead of a dead 'Nothing to give out'", async () => {
  answer = {
    ...plan(true),
    moved: 0,
    given: [],
    left: { everyone_at_cap: 40 },
  };
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
  expect(sheet().textContent).toContain(
    "Everyone you picked is at their open-lead limit.",
  );
  const button = sheet().querySelector("footer button") as HTMLButtonElement;
  expect(button.textContent).toBe("Everyone is full");
  expect(button.disabled).toBe(true);
});

it("with no lead waiting, explains where new leads go and opens lead rules", async () => {
  const onClose = vi.fn();
  answer = { ...plan(true), leads: 0, moved: 0, given: [], left: {} };
  await act(async () =>
    root.render(
      <AssignSheet
        open
        target={{ kind: "unassigned", count: 0 }}
        reps={REPS}
        onClose={onClose}
        onDone={() => {}}
      />,
    ),
  );
  await settle();
  const text = sheet().textContent;
  expect(text).toContain("Every open lead has an owner");
  expect(text).toContain("New leads go out by your lead rules.");
  expect(text).toContain("Nothing to share right now.");
  expect(text).toContain("For example, 6 new leads → 3 each for 2 sellers");
  expect(text).not.toContain("Nothing to give out");
  const button = sheet().querySelector("footer button") as HTMLButtonElement;
  expect(button.textContent).toBe("Open lead rules");
  await act(async () => button.click());
  expect(onClose).toHaveBeenCalledOnce();
  expect(push).toHaveBeenCalledWith("/settings/lead-rules");
});
