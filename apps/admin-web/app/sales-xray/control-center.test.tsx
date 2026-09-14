// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ProviderControlsPayload } from "./provider-controls";

vi.mock("./provider-controls", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./provider-controls")>()),
  loadProviderControls: vi.fn(),
}));

import { loadProviderControls } from "./provider-controls";
import { ControlCenterPanel } from "./control-center";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const payload: ProviderControlsPayload = {
  catalog: [
    {
      provider_id: "groq",
      display_name: "Groq",
      protocol: "groq_openai_compatible_https",
      status: "implemented",
      deployment: "hosted",
      readiness: "transport_available",
      models: [],
      note: "Bounded transport.",
    },
    {
      provider_id: "ollama",
      display_name: "Local Ollama",
      protocol: "ollama_http",
      status: "planned",
      deployment: "local",
      readiness: "planned_no_transport",
      models: [],
      note: "Planned.",
    },
  ],
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
  current: {
    id: "revision-id",
    revision: 4,
    configuration_sha256: "0".repeat(64),
    configuration: {
      schema: "ac.sales_xray.provider_registry_config/1",
      revision: "admin-draft-r4",
      policy: {
        schema: "ac.sales_xray.registry_policy/1",
        allow_paid: false,
        auto_purchase: false,
        paid_approval_ref: null,
      },
      providers: [],
      routes: [
        {
          schema: "ac.sales_xray.route_config/1",
          task: "facts",
          provider_id: "groq",
          model_id: "model",
          recipe_revision: "recipe-v1",
          profile_revision: "profile-v1",
          prompt_revision: "prompt-v1",
          required_input_stage: "C2",
          reuses_checkpoint_stage: "C2",
        },
      ],
    },
    created_at: "2026-09-13T00:00:00Z",
    execution_activated: false,
    activation: null,
    activation_options: [],
  },
  max_paid_paise: 0,
  approved_budget_cap_paise: null,
  execution_activated: false,
  message: "Provider settings loaded.",
};

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

async function render() {
  await act(async () => {
    root.render(createElement(ControlCenterPanel));
    await Promise.resolve();
  });
}

describe("Sales Xray control center", () => {
  it("shows setup status and supported entrypoints", async () => {
    vi.mocked(loadProviderControls).mockResolvedValue(payload);

    await render();

    expect(host.textContent).toContain("#4");
    expect(host.textContent).toContain("settings only · no provider calls");
    expect(host.textContent).toContain(
      "calibration metadata, not model training",
    );
    expect(host.querySelector('a[href="/sales-xray/settings"]')).toBeTruthy();
    expect(host.querySelector('a[href="/sales-xray/review"]')).toBeTruthy();
    expect(host.querySelector('a[href="/sales-xray/benchmark"]')).toBeTruthy();
    expect(host.textContent).not.toContain("execution_activated false");
    expect(host.textContent).not.toContain("Start benchmark");
  });

  it("fails closed when the provider status adapter denies access", async () => {
    vi.mocked(loadProviderControls).mockRejectedValue(new Error("forbidden"));

    await render();

    expect(host.textContent).toContain("Verified AC admin account required");
    expect(host.querySelector('a[href="/login"]')).toBeTruthy();
    expect(host.querySelector('a[href="/sales-xray/settings"]')).toBeNull();
  });
});
