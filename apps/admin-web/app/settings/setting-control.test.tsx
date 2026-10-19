// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import {
  ChangeRefused,
  displayValue,
  maximumFor,
  normalizeRegistry,
  optionsFor,
  pointer,
  requestBody,
} from "./registry-data";
import { SettingControl } from "./setting-control";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const merge = (container: string, key: string[]) => ({ container, key });
const REGISTRY = normalizeRegistry({
  schema: "ac.admin-settings/1",
  settings: [
    {
      id: "execution.paused",
      area: "execution",
      label: "Analyses",
      kind: "bool",
      labels: { true: "Paused", false: "Running" },
      read: {
        path: "/v1/admin/conversation/execution",
        value: "/control/paused",
        revision: "/control/revision",
      },
      write: {
        method: "POST",
        path: "/v1/admin/conversation/execution",
        body: { expected_revision: "$revision", paused: "$value" },
        idempotency_key: true,
        merge: null,
        needs_reason: false,
      },
    },
    {
      id: "budget.cap_paise",
      area: "execution",
      label: "AI budget",
      kind: "money_paise",
      minimum: 0,
      maximum_from: "/approved_cap_paise",
      read: {
        path: "/v1/admin/conversation/budget",
        value: "/budget/cap_paise",
        revision: "/revision",
      },
      write: {
        method: "POST",
        path: "/v1/admin/conversation/budget",
        body: {
          expected_revision: "$revision",
          new_cap_paise: "$value",
          reason: "$reason",
        },
        idempotency_key: true,
        merge: null,
        needs_reason: true,
      },
    },
    {
      id: "analysis.report_detail",
      area: "analysis",
      label: "Report detail",
      kind: "enum",
      options: [
        { value: "standard", label: "Standard" },
        { value: "detailed", label: "Detailed" },
      ],
      read: {
        path: "/v1/admin/conversation/analysis-settings",
        value: "/settings/c5_output_profile",
        revision: "/revision",
      },
      write: {
        method: "POST",
        path: "/v1/admin/conversation/analysis-settings",
        body: { expected_revision: "$revision", settings: "$merged" },
        idempotency_key: true,
        merge: merge("/settings", ["c5_output_profile"]),
        needs_reason: false,
      },
    },
    {
      id: "call_data.fast.daily_cap_inr",
      area: "call-data",
      label: "Fast pipeline: daily cap (₹)",
      kind: "int",
      minimum: 0,
      maximum: 5000,
      read: {
        path: "/v1/admin/call-data",
        value: "/config/fast/daily_cap_inr",
        revision: "/revision",
      },
      write: {
        method: "PUT",
        path: "/v1/admin/call-data/settings",
        body: { expected_revision: "$revision", config: "$merged" },
        idempotency_key: false,
        merge: merge("/config", ["fast", "daily_cap_inr"]),
        needs_reason: false,
      },
    },
    {
      id: "call_data.fast.model",
      area: "call-data",
      label: "Fast pipeline: model",
      kind: "enum",
      options_from: { list: "/models", value: "model", label: "label" },
      read: {
        path: "/v1/admin/call-data",
        value: "/config/fast/model",
        revision: "/revision",
      },
      write: {
        method: "PUT",
        path: "/v1/admin/call-data/settings",
        body: { expected_revision: "$revision", config: "$merged" },
        idempotency_key: false,
        merge: merge("/config", ["fast", "model"]),
        needs_reason: false,
      },
    },
    {
      id: "budget.ceiling_paise",
      area: "execution",
      label: "Budget ceiling",
      kind: "money_paise",
      read: {
        path: "/v1/admin/conversation/budget",
        value: "/settings/ceiling_paise",
      },
      write: null,
      why_not:
        "The owner sets the ceiling and its period on the Running and AI budget page.",
    },
  ],
});
const find = (id: string) => REGISTRY.settings.find((item) => item.id === id)!;

const EXECUTION = { control: { paused: false, revision: 3 } };
const BUDGET = {
  revision: 9,
  approved_cap_paise: 5_000_000,
  budget: { cap_paise: 3_000_000 },
};
const ANALYSIS = {
  revision: 4,
  settings: {
    c4_max_requests: 64,
    c5_output_profile: "detailed",
    report_language_default: "en",
  },
};
const CALL_DATA = {
  revision: 7,
  config: {
    fast: {
      enabled: true,
      model: "gemini-3.8-flash",
      daily_cap_inr: 150,
      max_call_minutes: 60,
    },
    deep: {
      enabled: true,
      model: "gemini-3.8-flash",
      daily_cap_inr: 300,
      max_call_minutes: 60,
    },
    streaming: { provider: "", model: "" },
  },
  models: [
    { model: "gemini-3.8-flash", label: "Gemini Flash" },
    { model: "gemini-3.8-pro", label: "Gemini Pro" },
  ],
};

let host: HTMLDivElement;
let root: Root;
let fetcher: ReturnType<typeof vi.fn>;
const answerWith = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  refresh.mockReset();
  fetcher = vi.fn(async () => answerWith(200, {}));
  vi.stubGlobal("fetch", fetcher);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function type(
  element: HTMLInputElement | HTMLSelectElement,
  value: string,
) {
  const proto =
    element instanceof HTMLSelectElement
      ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(element, value);
  await act(async () => {
    element.dispatchEvent(
      new Event(element instanceof HTMLSelectElement ? "change" : "input", {
        bubbles: true,
      }),
    );
  });
}
const button = (text: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) => item.textContent === text,
  )!;
const sent = () => {
  const [path, init] = fetcher.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  return {
    path,
    method: init.method,
    body: JSON.parse(String(init.body)),
    headers: init.headers as Record<string, string>,
  };
};

it("builds each change the way the API's registry does", () => {
  expect(pointer(CALL_DATA, "/config/fast/model")).toBe("gemini-3.8-flash");
  expect(pointer(CALL_DATA, "/config/nope")).toBeUndefined();
  const cap = requestBody(find("call_data.fast.daily_cap_inr"), CALL_DATA, 400);
  expect(cap.expected_revision).toBe(7);
  expect(cap.config).toEqual({
    ...CALL_DATA.config,
    fast: { ...CALL_DATA.config.fast, daily_cap_inr: 400 },
  });
  // The answer it was built from is never changed.
  expect(CALL_DATA.config.fast.daily_cap_inr).toBe(150);
  expect(() => requestBody(find("budget.cap_paise"), BUDGET, 1)).toThrow(
    ChangeRefused,
  );
  expect(
    requestBody(find("budget.cap_paise"), BUDGET, 1, "  more calls "),
  ).toEqual({
    expected_revision: 9,
    new_cap_paise: 1,
    reason: "more calls",
  });
  expect(() => requestBody(find("budget.ceiling_paise"), BUDGET, 1)).toThrow(
    /owner/,
  );
  expect(displayValue(find("execution.paused"), EXECUTION)).toBe("Running");
  expect(displayValue(find("budget.cap_paise"), BUDGET)).toBe("₹30,000");
  expect(displayValue(find("call_data.fast.model"), CALL_DATA)).toBe(
    "Gemini Flash",
  );
  expect(
    optionsFor(find("call_data.fast.model"), CALL_DATA).map(
      (item) => item.value,
    ),
  ).toEqual(["gemini-3.8-flash", "gemini-3.8-pro"]);
  expect(maximumFor(find("budget.cap_paise"), BUDGET)).toBe(5_000_000);
});

it("flips an on/off setting in one click, with the revision it read", async () => {
  await act(async () =>
    root.render(
      <SettingControl setting={find("execution.paused")} answer={EXECUTION} />,
    ),
  );
  await act(async () => button("Pause").click());
  const request = sent();
  expect(request.path).toBe("/v1/admin/conversation/execution");
  expect(request.method).toBe("POST");
  expect(request.body).toEqual({ expected_revision: 3, paused: true });
  expect(request.headers["idempotency-key"]).toBeTruthy();
  expect(host.querySelector('[role="status"]')?.textContent).toBe("Changed");
  expect(refresh).toHaveBeenCalled();
});

it("changes a choice by sending the area's whole document with one field set", async () => {
  await act(async () =>
    root.render(
      <SettingControl
        setting={find("analysis.report_detail")}
        answer={ANALYSIS}
      />,
    ),
  );
  await act(async () => button("Change").click());
  await type(host.querySelector("select")!, "standard");
  await act(async () => button("Save").click());
  expect(sent().body).toEqual({
    expected_revision: 4,
    settings: { ...ANALYSIS.settings, c5_output_profile: "standard" },
  });
});

it("keeps a number inside its bounds and uses PUT without a key where the area does", async () => {
  await act(async () =>
    root.render(
      <SettingControl
        setting={find("call_data.fast.daily_cap_inr")}
        answer={CALL_DATA}
      />,
    ),
  );
  await act(async () => button("Change").click());
  const input = host.querySelector("input")!;
  await type(input, "6000");
  expect(button("Save").disabled).toBe(true);
  expect(host.textContent).toContain("Between 0 and 5000");
  await type(input, "450");
  await act(async () => button("Save").click());
  const request = sent();
  expect(request.method).toBe("PUT");
  expect(request.path).toBe("/v1/admin/call-data/settings");
  expect(request.headers["idempotency-key"]).toBeUndefined();
  expect(request.body.config.fast.daily_cap_inr).toBe(450);
});

it("asks why before an amount changes, in rupees, and shows a refusal as it is", async () => {
  fetcher.mockImplementation(async () =>
    answerWith(409, {
      detail: "This changed meanwhile. Reload and try again.",
    }),
  );
  await act(async () =>
    root.render(
      <SettingControl setting={find("budget.cap_paise")} answer={BUDGET} />,
    ),
  );
  await act(async () => button("Change").click());
  const [amount, why] = [...host.querySelectorAll("input")];
  expect(amount.value).toBe("30000");
  await type(amount, "40000");
  expect(button("Save").disabled).toBe(true); // no reason yet
  await type(why, "More calls this month");
  await act(async () => button("Save").click());
  expect(sent().body).toEqual({
    expected_revision: 9,
    new_cap_paise: 4_000_000,
    reason: "More calls this month",
  });
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "This changed meanwhile. Reload and try again.",
  );
  expect(refresh).not.toHaveBeenCalled();
});

it("offers nothing for a setting changed only on its page", async () => {
  await act(async () =>
    root.render(
      <SettingControl setting={find("budget.ceiling_paise")} answer={BUDGET} />,
    ),
  );
  expect(host.innerHTML).toBe("");
});
