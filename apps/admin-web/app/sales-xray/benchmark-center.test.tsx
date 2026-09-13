// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { ProviderControlsPayload } from "./provider-controls";

vi.mock("./provider-controls", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./provider-controls")>()),
  loadProviderControls: vi.fn(),
}));

import { loadProviderControls } from "./provider-controls";
import { BenchmarkCenterPanel } from "./benchmark-center";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const payload = {
  catalog: [],
  tasks: [],
  configuration_template: {
    schema: "ac.sales_xray.provider_registry_config/1",
    revision: "admin-draft-v1",
    policy: {
      schema: "ac.sales_xray.registry_policy/1",
      allow_paid: false,
      auto_purchase: false,
      paid_approval_ref: null,
    },
    providers: [],
    routes: [],
  },
  current: null,
  max_paid_paise: 0,
  execution_activated: false,
  message: "Provider settings loaded.",
} satisfies ProviderControlsPayload;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  root.unmount();
  host.remove();
  vi.resetAllMocks();
});

it("documents missing benchmark APIs without rendering an unsafe run action", async () => {
  vi.mocked(loadProviderControls).mockResolvedValue(payload);

  await act(async () => {
    root.render(createElement(BenchmarkCenterPanel));
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(host.textContent).toContain("Prepare your first comparison");
  expect(host.textContent).toContain(
    "Test runs are not available from Admin yet",
  );
  expect(host.textContent).toContain("/v1/admin/conversation/benchmarks");
  expect(host.textContent).toContain("approved_call_test");
  expect(host.querySelector('a[href="/sales-xray/settings"]')).toBeTruthy();
  expect(host.querySelectorAll("details[open]")).toHaveLength(0);
  expect(host.textContent).not.toContain("execution_activated false");
  expect(host.textContent).not.toContain("authoritative run");
  expect(host.querySelector("button")).toBeNull();
  expect(host.textContent).not.toContain("Start test run");
});
