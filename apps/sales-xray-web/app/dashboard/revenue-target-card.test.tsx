// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../notice-center", () => ({ notify: () => undefined }));

import type { Revenue, RevenueTargets } from "./revenue-client";
import {
  forgetTargetDraft,
  mismatch,
  RevenueTargetCard,
  RevenueTargetDetail,
  takesChain,
  targetChip,
} from "./revenue-target-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Team controls' sixth card (owner meeting, 28 Oct 2026). Fictional people.
const TARGETS: RevenueTargets = {
  month: "2026-10-01",
  currency: "INR",
  organisation: 1200000,
  sellers: [
    { person_id: "a", name: "Asha Fictional", own: null, split: 300000 },
    { person_id: "b", name: "Ravi Fictional", own: 500000, split: null },
    { person_id: "c", name: "Meera Fictional", own: null, split: 300000 },
    { person_id: "d", name: "Kabir Fictional", own: null, split: 300000 },
  ],
  sellers_set_own: false,
  typical_deal: null,
  revision: 4,
  can_manage: true,
};

const TEAM: Revenue = {
  scope: "team",
  month: "2026-10-01",
  currency: "INR",
  month_gone: 0.5,
  target: 500000,
  target_source: "organisation",
  won: 0,
  deals: 0,
  amount_not_set: 0,
  needs: {
    wins: 4,
    meetings: 12,
    interested: 40,
    connected: 160,
    calls: 400,
    calls_per_day: 20,
    working_days_left: 20,
    average_deal: 125000,
    estimate: true,
  },
  sellers: [],
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  forgetTargetDraft();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

function serve() {
  const sent: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      sent.push({ url, method, body });
      const reply = url.includes("/revenue/") ? TARGETS : TEAM;
      return new Response(JSON.stringify(reply), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  return sent;
}

async function settle() {
  for (let i = 0; i < 6; i++)
    await act(async () => await new Promise((done) => setTimeout(done, 0)));
}

it("says the target on its chip, like the other five cards", async () => {
  serve();
  const opened = vi.fn();
  await act(async () => root.render(<RevenueTargetCard onOpen={opened} />));
  await settle();
  const card = container.querySelector<HTMLButtonElement>("button")!;
  expect(card.textContent).toContain("Monthly revenue target");
  expect(card.textContent).toContain("₹12 L · split 4 ways");
  await act(async () => card.click());
  expect(opened).toHaveBeenCalled();
  expect(targetChip({ ...TARGETS, organisation: null })).toBe(
    "₹5 L · 1 seller",
  );
  expect(
    targetChip({
      ...TARGETS,
      organisation: null,
      sellers: TARGETS.sellers.map((line) => ({ ...line, own: null })),
    }),
  ).toBe("Not set");
});

it("works out what it takes, the owner's own example", () => {
  expect(takesChain(TEAM)).toBe(
    "₹5 L to go → 4 wins → 12 meetings → 40 interested → about 20 calls a day (estimate)",
  );
  expect(takesChain({ ...TEAM, won: 500000 })).toBe(
    "This month's target is reached.",
  );
});

it("saves the organisation's month and only the sellers that changed", async () => {
  const sent = serve();
  await act(async () => root.render(<RevenueTargetDetail />));
  await settle();
  const inputs = Array.from(
    container.querySelectorAll<HTMLInputElement>('input[inputmode="decimal"]'),
  );
  // This month and next side by side (competitor teardown #8): the
  // organisation's row, each seller's, then the typical deal.
  expect(inputs).toHaveLength(11);
  // The even share is the seller's placeholder.
  expect(inputs[2].placeholder).toBe("₹3 L");
  const type = (input: HTMLInputElement, value: string) =>
    act(() => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  type(inputs[0], "15 L");
  type(inputs[2], "4 L");
  const save = Array.from(container.querySelectorAll("button")).find((node) =>
    node.textContent?.startsWith("Save"),
  )!;
  await act(async () => save.click());
  const put = sent.find(
    (item) => item.method === "PUT" && item.url.endsWith("/revenue/targets"),
  );
  expect(put?.body).toMatchObject({
    organisation: 1500000,
    sellers: [{ person_id: "a", amount: 400000 }],
  });
  // Said by the button, where the owner looks (the corner notice sits under the sheet).
  await settle();
  expect(
    Array.from(
      container.querySelectorAll("[role=status]"),
      (node) => node.textContent,
    ).join(" | "),
  ).toMatch(/ saved$/);
});

const cell = (label: string) =>
  container.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
const button = (words: string) =>
  Array.from(container.querySelectorAll("button")).find(
    (node) => node.textContent === words,
  )!;
const typeInto = (input: HTMLInputElement, value: string) =>
  act(() => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });

// Competitor teardown #8 (1 Nov 2026): sellers x month, Split equally, Apply
// to all, and a warning when the sellers don't add up.
it("splits the month equally, applies it to next month, and warns when it doesn't add up", async () => {
  serve();
  await act(async () => root.render(<RevenueTargetDetail />));
  await settle();
  const [first, second] = Array.from(
    container.querySelectorAll("[aria-label^='Organisation, ']"),
    (node) => node.getAttribute("aria-label")!.replace("Organisation, ", ""),
  );
  // Ravi's own ₹5 L and three even shares of ₹3 L make ₹14 L against ₹12 L.
  expect(container.textContent).toContain(
    `${first}: Sellers add up to ₹14 L, ₹2 L over ₹12 L`,
  );
  typeInto(cell(`Organisation, ${first}`), "20 L");
  await act(async () => button("Split equally").click());
  expect(cell(`Asha Fictional, ${first}`).value).toBe("5,00,000");
  expect(cell(`Ravi Fictional, ${first}`).value).toBe("5,00,000");
  expect(container.textContent).not.toContain(`${first}: Sellers add up`);
  await act(async () => button("Apply to all").click());
  expect(cell(`Organisation, ${second}`).value).toBe("20 L");
  expect(cell(`Kabir Fictional, ${second}`).value).toBe("5,00,000");
});

// Hardcore phone QA ph1-29 (1 Nov 2026): amounts read as people write them,
// and Back keeps what was typed instead of discarding it.
it("shows amounts with Indian grouping, and keeps a draft through Back", async () => {
  serve();
  await act(async () => root.render(<RevenueTargetDetail />));
  await settle();
  const [first] = Array.from(
    container.querySelectorAll("[aria-label^='Organisation, ']"),
    (node) => node.getAttribute("aria-label")!.replace("Organisation, ", ""),
  );
  expect(cell(`Organisation, ${first}`).value).toBe("12,00,000");
  expect(cell(`Ravi Fictional, ${first}`).value).toBe("5,00,000");
  typeInto(cell(`Organisation, ${first}`), "18 L");
  expect(container.textContent).toContain("Not saved yet");
  // Back: the detail closes; opening it again brings the draft back.
  act(() => root.unmount());
  root = createRoot(container);
  await act(async () => root.render(<RevenueTargetDetail />));
  await settle();
  expect(cell(`Organisation, ${first}`).value).toBe("18 L");
  expect(container.textContent).toContain("Not saved yet");
});

it("says how far the sellers are from the organisation's month", () => {
  expect(
    mismatch({ org: "1500000", own: { a: "", b: "500000" } }, ["a", "b"]),
  ).toBe("Sellers add up to ₹12.5 L, ₹2.5 L short of ₹15 L");
  // No seller of their own: the even split is the organisation's.
  expect(mismatch({ org: "1500000", own: { a: "", b: "" } }, ["a", "b"])).toBe(
    null,
  );
  expect(mismatch({ org: "", own: { a: "500000" } }, ["a"])).toBe(null);
});
