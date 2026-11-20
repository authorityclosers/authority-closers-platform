import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ read: vi.fn(), save: vi.fn() }));
vi.mock("../../leads/routing-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../leads/routing-client")>()),
  readRouting: calls.read,
  saveRouting: calls.save,
}));
vi.mock("../../notice-center", () => ({ notify: vi.fn() }));

import { LeadSplit, nextTurns, splitRule } from "./lead-split";
import type { Routing } from "../../leads/routing-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// The percent split on the lead rules page (round-2 board 3, 20 Nov 2026).
// Made-up people only.
const A = "aaaaaaaa-0000-4000-8000-000000000001";
const B = "bbbbbbbb-0000-4000-8000-000000000002";
const C = "cccccccc-0000-4000-8000-000000000003";
const person = (person_id: string, name: string) => ({
  person_id,
  name,
  available: true,
  open_leads: 2,
  max_open: null,
});
const cityRule = {
  id: "city1",
  name: "Pune",
  enabled: true,
  when: [{ field: "city" as const, values: ["Pune"] }],
  give_to: [C],
};
const routing = (extra: Partial<Routing> = {}): Routing => ({
  schema: "lead-desk/1",
  revision: 3,
  can_edit: true,
  value_answer: null,
  rules: [cityRule],
  sources: {},
  people: [
    person(A, "Mira Sample"),
    person(B, "Anika Fictional"),
    person(C, "Ravi Example"),
  ],
  questions: [],
  ...extra,
});

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  calls.read.mockReset();
  calls.save.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const field = (name: string) =>
  host.querySelector<HTMLInputElement>(
    `input[aria-label="${name}'s share in percent"]`,
  )!;
async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const button = (text: string) =>
  [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  ) as HTMLButtonElement | undefined;

it("gives 10 leads 2 / 4 / 4 on a 20 / 40 / 40 split, the server's way", () => {
  const turns = nextTurns(
    [
      { id: "a", share: 20 },
      { id: "b", share: 40 },
      { id: "c", share: 40 },
    ],
    10,
  );
  expect(turns.filter((id) => id === "a")).toHaveLength(2);
  expect(turns.filter((id) => id === "b")).toHaveLength(4);
  expect(turns.filter((id) => id === "c")).toHaveLength(4);
  expect(turns.slice(0, 2)).toEqual(["b", "c"]);
  // A share of 0 gets none.
  expect(nextTurns([{ id: "a", share: 0 }], 3)).toEqual([]);
});

it("finds the split among the rules: no conditions, with shares", () => {
  expect(splitRule([cityRule])).toBeNull();
  const split = { ...cityRule, id: "s", when: [], shares: [100] };
  expect(splitRule([cityRule, split])).toBe(split);
});

it("saves the split after the rules for some leads, adding up to 100", async () => {
  calls.read.mockResolvedValue(routing());
  calls.save.mockImplementation(async (_revision, _value, rules) =>
    routing({ revision: 4, rules }),
  );
  await act(async () => root.render(<LeadSplit />));
  const toggle = host.querySelector<HTMLInputElement>('[role="switch"]')!;
  expect(toggle.checked).toBe(false);
  await act(async () => toggle.click());
  await type(field("Mira Sample"), "20");
  await type(field("Anika Fictional"), "40");
  expect(host.textContent).toContain("40 % left to give");
  expect(button("Save split")?.disabled).toBe(true);
  await type(field("Ravi Example"), "40");
  expect(host.textContent).toContain("Adds up to 100 %");
  expect(host.textContent).toContain("Mira 2 · Anika 4 · Ravi 4");
  await act(async () => button("Save split")!.click());
  expect(calls.save).toHaveBeenCalledTimes(1);
  const [revision, , rules] = calls.save.mock.calls[0];
  expect(revision).toBe(3);
  expect(rules[0]).toBe(cityRule);
  expect(rules[1]).toMatchObject({
    id: null,
    enabled: true,
    when: [],
    give_to: [A, B, C],
    shares: [20, 40, 40],
  });
});

it("turns a saved split off and keeps its shares for next time", async () => {
  const saved = {
    id: "split1",
    name: "Split new leads",
    enabled: true,
    when: [],
    give_to: [A, B],
    shares: [50, 50],
  };
  calls.read.mockResolvedValue(routing({ rules: [cityRule, saved] }));
  calls.save.mockImplementation(async (_revision, _value, rules) =>
    routing({ revision: 4, rules }),
  );
  await act(async () => root.render(<LeadSplit />));
  expect(field("Mira Sample").value).toBe("50");
  const toggle = host.querySelector<HTMLInputElement>('[role="switch"]')!;
  expect(toggle.checked).toBe(true);
  await act(async () => toggle.click());
  const [, , rules] = calls.save.mock.calls[0];
  expect(rules[1]).toMatchObject({
    id: "split1",
    enabled: false,
    give_to: [A, B],
    shares: [50, 50],
  });
});
