// @vitest-environment happy-dom
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
const state = { environment: "staging", control, budget: null, history: [] };
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
const render = async () => {
  await act(async () => root.render(createElement(ExecutionControlsPanel)));
};
const button = (label: string) =>
  [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(label),
  )!;

it("saves a scoped pause with a revision and idempotency key, then offers resume", async () => {
  let paused = false;
  const fetcher = vi.fn(async (_url: string, init: RequestInit) => {
    if (init.method === "POST") {
      paused = true;
      return json({ ...control, revision: 1, paused });
    }
    return json({
      ...state,
      control: { ...control, revision: paused ? 1 : 0, paused },
    });
  });
  vi.stubGlobal("fetch", fetcher);
  await render();
  await act(async () => button("Pause new analysis").click());
  expect(button("Resume new analysis")).toBeTruthy();
  const request = fetcher.mock.calls.find(
    ([, init]) => init.method === "POST",
  )![1];
  expect(JSON.parse(request.body as string)).toEqual({
    paused: true,
    expected_revision: 0,
  });
  expect(new Headers(request.headers).get("Idempotency-Key")).toBeTruthy();
  expect(request.credentials).toBe("same-origin");
  expect(host.textContent).toContain("Already-started work may finish");
});

it("does not show an unconfirmed save as success or enable another mutation", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url, init) =>
      init.method === "POST" ? json({}, 503) : json(state),
    ),
  );
  await render();
  await act(async () => button("Pause new analysis").click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "could not be confirmed",
  );
  expect(button("Pause new analysis").disabled).toBe(true);
  expect(host.textContent).not.toContain("New analysis is paused");
});

it("warns using the returned ledger and keeps uncertain money separate from settled cost", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      json({
        ...state,
        budget: {
          cap_paise: 10000,
          available_paise: 2000,
          committed_paise: 8000,
          settled_paise: 2000,
          held_paise: 6000,
          uncertain_paise: 1000,
          reservation_count: 3,
          warning: "warning",
          warning_percent: 80,
          critical_percent: 90,
        },
      }),
    ),
  );
  await render();
  expect(host.textContent).toContain("at least 80%");
  expect(host.textContent).toContain("₹10.00 is held");
  expect(host.textContent).toContain("not provider invoices");
});
