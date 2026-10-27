import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { Routing } from "./routing-client";
import { RoutingRules } from "./routing-rules";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Who gets which leads (owner #39 and #42, 27 Oct 2026; Lead OS's routing
// rules): rules as sentences, edited in a sheet, saved at once, and tried.
let root: Root;
let host: HTMLDivElement;
let status = 200;
const sent: { method: string; url: string; body?: unknown }[] = [];

const PRIYA = "aaaaaaaa-0000-4000-8000-000000000001";
const RAHUL = "bbbbbbbb-0000-4000-8000-000000000002";

const routing = (over: Partial<Routing> = {}): Routing => ({
  schema: "lead-desk/1",
  revision: 7,
  can_edit: true,
  value_answer: "budget",
  rules: [
    {
      id: "r1",
      name: "Big budgets",
      enabled: true,
      when: [
        { field: "source", values: ["meta"] },
        { field: "value", op: "at_least", low: 100000, high: null },
      ],
      give_to: [PRIYA, RAHUL],
    },
  ],
  sources: {
    meta: "Facebook and Instagram lead ads",
    webhook: "Website forms and other apps",
  },
  people: [
    {
      person_id: PRIYA,
      name: "Priya Example",
      available: true,
      open_leads: 12,
      max_open: 50,
    },
    {
      person_id: RAHUL,
      // Arrives in lower case; shown with capitals.
      name: "rahul example",
      available: false,
      open_leads: 3,
      max_open: null,
    },
  ],
  questions: [
    {
      key: "budget",
      label: "Your budget",
      answered: 40,
      examples: ["50 lakh", "1 crore"],
    },
  ],
  ...over,
});

beforeEach(() => {
  sent.length = 0;
  status = 200;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    sent.push({ method, url, body });
    if (String(url).includes("/people/characters"))
      return Response.json({ characters: [] });
    if (status !== 200) return Response.json({ detail: "No." }, { status });
    if (url.endsWith("/routing-rules/try"))
      return Response.json({
        person_id: PRIYA,
        name: "Priya Example",
        rule: 1,
        rule_name: "Big budgets",
        why: "Value ₹2,00,000 ≥ ₹1,00,000: Priya (rule 1)",
        passed_over: [],
      });
    if (method === "PUT")
      return Response.json(
        routing({
          revision: 8,
          rules: body.rules,
          value_answer: body.value_answer,
        }),
      );
    return Response.json(routing());
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const settle = async () =>
  act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });

const button = (label: string) =>
  [...document.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === label,
  );

const type = async (input: HTMLInputElement, value: string) =>
  act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });

const show = async () => {
  await act(async () => root.render(<RoutingRules />));
  await settle();
};

it("reads each rule as a sentence", async () => {
  await show();
  const rule = host.querySelector("li")!;
  expect(rule.textContent).toContain("Big budgets");
  expect(rule.textContent).toContain(
    "Source is Facebook and Instagram lead ads",
  );
  expect(rule.textContent).toContain("Value ₹1,00,000 or more");
  expect(rule.textContent).toContain(
    "Priya Example and Rahul Example, in turn",
  );
});

it("stays away where the server doesn't offer it", async () => {
  status = 403;
  await show();
  expect(host.innerHTML).toBe("");
});

it("waits for Save, then saves every rule at once with the revision", async () => {
  await show();
  const toggle = host.querySelector<HTMLInputElement>('input[role="switch"]')!;
  await act(async () => toggle.click());
  expect(host.textContent).toContain("You have changes that aren't saved yet.");
  await act(async () => button("Save")!.click());
  await settle();
  const put = sent.find((item) => item.method === "PUT")!;
  expect(put.url).toBe("/v1/lead-desk/routing-rules");
  expect(put.body).toMatchObject({
    expected_revision: 7,
    value_answer: "budget",
    rules: [{ id: "r1", enabled: false }],
  });
  expect(host.textContent).toContain("Rules saved. New leads follow them now.");
});

it("adds a rule in its sheet: a name, a source and a person", async () => {
  await show();
  await act(async () => button("Add a rule")!.click());
  const done = button("Done")!;
  expect(done.disabled).toBe(true);
  await type(
    document.querySelector<HTMLInputElement>(
      'input[placeholder="Big budgets to Priya"]',
    )!,
    "Website to Rahul",
  );
  const website = [...document.querySelectorAll("label")].find((label) =>
    label.textContent?.includes("Website forms and other apps"),
  )!;
  await act(async () => website.querySelector("input")!.click());
  const rahul = [...document.querySelectorAll("label")].find((label) =>
    label.textContent?.includes("Rahul Example"),
  )!;
  await act(async () => rahul.querySelector("input")!.click());
  expect(button("Done")!.disabled).toBe(false);
  await act(async () => button("Done")!.click());
  const rules = [...host.querySelectorAll("li")].map(
    (item) => item.textContent,
  );
  expect(rules[1]).toContain("Website to Rahul");
  expect(rules[1]).toContain("Source is Website forms and other apps");
  expect(rules[1]).toContain("Rahul Example");
});

it("keeps both amounts across value choices, and saves a new rule with no id", async () => {
  await show();
  await act(async () => button("Add a rule")!.click());
  await type(
    document.querySelector<HTMLInputElement>(
      'input[placeholder="Big budgets to Priya"]',
    )!,
    "Middle budgets",
  );
  const what = document.querySelector<HTMLSelectElement>(
    'select[aria-label="What to check"]',
  )!;
  await act(async () => {
    what.value = "value";
    what.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const from = () =>
    document.querySelector<HTMLInputElement>(
      'input[aria-label="From, in rupees"]',
    );
  const upTo = () =>
    document.querySelector<HTMLInputElement>(
      'input[aria-label="Up to, in rupees"]',
    );
  expect(upTo()).toBeNull();
  await type(from()!, "₹50,000");
  await act(async () => button("Under")!.click());
  expect(from()).toBeNull();
  await type(upTo()!, "20000");
  await act(async () => button("Between")!.click());
  expect(from()!.value).toBe("50,000");
  expect(upTo()!.value).toBe("20,000");
  expect(document.body.textContent).toContain(
    "The first amount must be the smaller one.",
  );
  await type(upTo()!, "200000");
  expect(document.body.textContent).toContain("Value ₹50,000 to ₹2,00,000");
  const rahul = [...document.querySelectorAll("label")].find((label) =>
    label.textContent?.includes("Rahul Example"),
  )!;
  await act(async () => rahul.querySelector("input")!.click());
  await act(async () => button("Done")!.click());
  await act(async () => button("Save")!.click());
  await settle();
  const put = sent.find((item) => item.method === "PUT")!;
  expect((put.body as { rules: unknown[] }).rules[1]).toEqual({
    id: null,
    name: "Middle budgets",
    enabled: true,
    when: [{ field: "value", op: "between", low: 50000, high: 200000 }],
    give_to: [RAHUL],
  });
});

it("says whose a sample lead would be, and why", async () => {
  await show();
  await type(
    host.querySelector<HTMLInputElement>('input[aria-label="Value"]')!,
    "2 lakh",
  );
  await act(async () => button("Who gets it?")!.click());
  await settle();
  const tried = sent.find((item) => item.url.endsWith("/try"))!;
  expect(tried.body).toMatchObject({ source: "meta", value: "2 lakh" });
  expect(host.textContent).toContain("Priya Example · rule 1, Big budgets");
  expect(host.textContent).toContain(
    "Value ₹2,00,000 ≥ ₹1,00,000: Priya (rule 1)",
  );
});

it("keeps the changes when someone else saved first", async () => {
  await show();
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[role="switch"]')!.click(),
  );
  status = 409;
  await act(async () => button("Save")!.click());
  await settle();
  expect(host.textContent).toContain("Someone else saved the rules first.");
  expect(host.textContent).toContain("You have changes that aren't saved yet.");
});
