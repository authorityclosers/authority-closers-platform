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
const emptyBudget = {
  scope_id: "11111111-1111-4111-8111-111111111111",
  revision: 0,
  approved_cap_paise: 10000,
  budget: null,
};
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
    if (_url === "/v1/admin/conversation/budget") return json(emptyBudget);
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
    vi.fn(async (url, init) => {
      if (url === "/v1/admin/conversation/budget") return json(emptyBudget);
      return init.method === "POST" ? json({}, 503) : json(state);
    }),
  );
  await render();
  await act(async () => button("Pause new analysis").click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "could not be confirmed",
  );
  expect(button("Pause new analysis").disabled).toBe(true);
  expect(host.textContent).not.toContain("New analysis is paused");
});

it.each(["expired", "malformed"])(
  "keeps pause available when the budget response is %s",
  async (failure) => {
    let paused = false;
    const fetcher = vi.fn(async (url: string, init: RequestInit) => {
      if (url === "/v1/admin/conversation/budget")
        return failure === "expired" ? json({}, 503) : json({ invalid: true });
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
    expect(button("Pause new analysis")?.disabled).toBe(false);
    expect(button("Save budget limit")).toBeUndefined();
    expect(host.textContent).toContain("Budget details are unavailable");
    await act(async () => button("Pause new analysis").click());
    expect(button("Resume new analysis")?.disabled).toBe(false);
    expect(host.textContent).toContain("New analysis is paused");
    expect(
      fetcher.mock.calls.filter(([, init]) => init.method === "POST"),
    ).toHaveLength(1);
  },
);

it("warns using the returned ledger and keeps uncertain money separate from settled cost", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) =>
      url === "/v1/admin/conversation/budget"
        ? json({
            ...emptyBudget,
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
          })
        : json({
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

it("edits the shared limit with the current revision and an audit reason", async () => {
  const currentBudget = {
    ...emptyBudget,
    budget: {
      cap_paise: 10000,
      available_paise: 10000,
      committed_paise: 0,
      settled_paise: 0,
      held_paise: 0,
      uncertain_paise: 0,
      reservation_count: 0,
      warning: "normal",
      warning_percent: 80,
      critical_percent: 90,
    },
  };
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (url === "/v1/admin/conversation/budget" && init.method === "POST") {
      return json(
        {
          ...currentBudget,
          revision: 1,
          budget: {
            ...currentBudget.budget,
            cap_paise: 7500,
            available_paise: 7500,
          },
        },
        201,
      );
    }
    if (url === "/v1/admin/conversation/budget") return json(currentBudget);
    return json({ ...state, budget: currentBudget.budget });
  });
  vi.stubGlobal("fetch", fetcher);
  await render();
  const input = host.querySelector<HTMLInputElement>(
    '[aria-label="Shared budget limit in INR"]',
  )!;
  await act(async () => {
    const setValue = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setValue.call(input, "75.00");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    button("Save budget limit").click();
  });
  const call = fetcher.mock.calls.find(
    ([url, init]) =>
      url === "/v1/admin/conversation/budget" && init.method === "POST",
  );
  expect(call).toBeTruthy();
  expect(JSON.parse(call![1].body as string)).toEqual({
    expected_revision: 0,
    new_cap_paise: 7500,
    reason: "Reviewed shared processing budget",
  });
  expect(new Headers(call![1].headers).get("Idempotency-Key")).toBeTruthy();
  expect(host.textContent).toContain("revision 1");
});
