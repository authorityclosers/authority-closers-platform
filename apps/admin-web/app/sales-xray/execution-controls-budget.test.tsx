// @vitest-environment happy-dom
/** One-click budget raises and the ceiling request (owner via the orchestrator, 19 Oct 2026). */
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ExecutionControlsPanel } from "./execution-controls";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
const control = { revision: 0, paused: false, changed_at: null };
// Above the old ₹10,000 limit: a ₹15,000 cap under a ₹17,000 sealed ceiling.
const account = (cap: number) => ({
  cap_paise: cap,
  available_paise: cap - 1_350_000,
  committed_paise: 1_350_000,
  settled_paise: 1_300_000,
  held_paise: 50_000,
  uncertain_paise: 50_000,
  reservation_count: 40,
  warning: "critical",
  warning_percent: 80,
  critical_percent: 90,
});
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
const button = (label: string) =>
  [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(label),
  )!;

function server(posts: { url: string; body: unknown }[]) {
  let cap = 1_500_000;
  return vi.fn(async (url: string, init: RequestInit = {}) => {
    if (init.method === "POST") {
      posts.push({ url, body: JSON.parse(init.body as string) });
      if (url === "/v1/admin/conversation/budget") {
        cap = (JSON.parse(init.body as string) as { new_cap_paise: number })
          .new_cap_paise;
        return json({
          scope_id: "11111111-1111-4111-8111-111111111111",
          revision: 1,
          approved_cap_paise: 1_700_000,
          budget: account(cap),
        });
      }
      return json({ request_id: "r", status: "sent_to_root" }, 201);
    }
    if (url === "/v1/admin/conversation/budget")
      return json({
        scope_id: "11111111-1111-4111-8111-111111111111",
        revision: 0,
        approved_cap_paise: 1_700_000,
        budget: account(cap),
      });
    return json({
      environment: "development",
      control,
      budget: account(cap),
      waiting_calls: 2,
      history: [],
    });
  });
}

it("raises the cap in one click, up to the sealed ceiling, and says calls are waiting", async () => {
  const posts: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", server(posts));
  await act(async () => root.render(createElement(ExecutionControlsPanel)));
  expect(host.textContent).toContain("90% used");
  expect(host.textContent).toContain("2 calls are waiting for AI budget");
  // +₹5,000 would pass the ₹17,000 ceiling, so only that button is off.
  expect(button("+₹1,000").disabled).toBe(false);
  expect(button("+₹5,000").disabled).toBe(true);
  await act(async () => button("+₹1,000").click());
  expect(posts[0]).toEqual({
    url: "/v1/admin/conversation/budget",
    body: {
      expected_revision: 0,
      new_cap_paise: 1_600_000,
      reason: "Raised by ₹1,000 from Execution & budget",
    },
  });
  expect(host.textContent).toContain("Raised the budget to ₹16,000");
});

it("asks Root for a higher ceiling", async () => {
  const posts: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", server(posts));
  await act(async () => root.render(createElement(ExecutionControlsPanel)));
  await act(async () => button("Ask Root to raise the ceiling").click());
  expect(posts[0]?.url).toBe("/v1/admin/conversation/budget/ceiling-request");
  expect(posts[0]?.body).toMatchObject({ requested_cap_paise: 3_400_000 });
  expect(host.textContent).toContain(
    "Root is asked to raise the ceiling to ₹34,000",
  );
});
