// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import liveCatalogFixture from "./provider-catalog.fixture.json";

import {
  buildConfiguration,
  prepareConfiguration,
  ProviderControlsPanel,
  type RegistryConfiguration,
} from "./provider-controls";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const template: RegistryConfiguration = {
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
};

const catalog = [
  {
    provider_id: "local",
    display_name: "AC local deterministic tools",
    protocol: "local_process",
    status: "implemented" as const,
    readiness: "transport_available",
    deployment: "deterministic_tool" as const,
    models: [
      {
        model_id: "audioatlas",
        endpoint: null,
        transport_status: "implemented" as const,
        readiness: "transport_available",
        task_support: [],
      },
    ],
    note: "Local process metadata.",
  },
  {
    provider_id: "groq",
    display_name: "Groq open weights",
    protocol: "groq_openai_compatible_https",
    status: "implemented" as const,
    readiness: "transport_available",
    deployment: "hosted" as const,
    models: [
      {
        model_id: "openai/gpt-oss-120b",
        endpoint: "https://api.groq.com/openai/v1/chat/completions",
        transport_status: "implemented" as const,
        readiness: "transport_available",
        task_support: [
          { task: "facts" as const, status: "contract_only" as const },
        ],
      },
    ],
    note: "Structured generation remains contract-only.",
  },
  {
    provider_id: "ollama",
    display_name: "Local Ollama",
    protocol: "ollama_http",
    status: "planned" as const,
    readiness: "planned_no_transport",
    deployment: "local" as const,
    models: [],
    note: "Planned local option.",
  },
];

const tasks = [
  {
    schema: "ac.sales_xray.task_contract/1",
    task: "facts" as const,
    input_stage: "C2" as const,
    reuse_stage: "C2" as const,
    profile_required: false,
  },
];

function payload(current: null | Record<string, unknown> = null) {
  return {
    catalog,
    tasks,
    configuration_template: template,
    current,
    max_paid_paise: 0 as const,
    execution_activated: false as const,
    message:
      "Settings are saved as revisions. Provider tests and activation are separate.",
  };
}

function jsonResponse(value: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => value,
  } as Response;
}

let host: HTMLDivElement;
let root: Root;
let fetchMock: ReturnType<typeof vi.fn>;

async function renderPanel() {
  await act(async () => {
    root.render(createElement(ProviderControlsPanel));
    await Promise.resolve();
    await Promise.resolve();
  });
}

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

describe("provider control access boundaries", () => {
  it("hides all controls after an unauthenticated response", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 401));

    await renderPanel();

    expect(host.textContent).toContain("Sign in to your AC admin account");
    expect(host.textContent).not.toContain("Choose providers and models");
    expect(host.querySelector("select")).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/admin/conversation/providers",
      expect.objectContaining({
        credentials: "same-origin",
        cache: "no-store",
      }),
    );
  });

  it("hides all controls after a forbidden response and asks for the verified AC account", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 403));

    await renderPanel();

    expect(host.textContent).toContain("Verify your AC admin account");
    expect(host.textContent).not.toContain("Add model");
    expect(host.querySelector("input")).toBeNull();
  });
});

describe("provider control contract", () => {
  it("renders the complete catalog returned by the deployed API", async () => {
    fetchMock.mockResolvedValue(jsonResponse(liveCatalogFixture));
    await renderPanel();
    expect(host.textContent).not.toContain("Provider controls unavailable");
    expect(host.textContent).toContain("Choose providers and models");
    const addModel = Array.from(host.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Add model"),
    );
    expect(addModel).toBeDefined();
    await act(async () => addModel?.click());
    expect(host.querySelector("select")).not.toBeNull();
  });

  it("renders server catalog statuses and makes one same-origin read", async () => {
    fetchMock.mockResolvedValue(jsonResponse(payload()));

    await renderPanel();

    expect(host.textContent).toContain("Local Ollama");
    expect(host.textContent).toContain("planned_no_transport");
    expect(host.textContent).toContain("Groq open weights");
    expect(host.textContent).toContain("₹0");
    expect(host.textContent).toContain("execution_activated false");
    expect(host.textContent).not.toContain("API key");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("builds a multi-task configuration with zero paid spend and reference-only settings", () => {
    const configuration = buildConfiguration(
      {
        revision: "admin-draft-v1",
        providers: [
          {
            schema: "ignored",
            provider_id: "groq",
            model_id: "openai/gpt-oss-120b",
            endpoint: "https://api.groq.com/openai/v1/chat/completions",
            endpoint_sha256: null,
            credential_ref: "ref:secrets/groq",
            provider_terms_ref: "ref:terms/groq",
            privacy_ref: "ref:privacy/groq",
            pricing_ref: "ref:pricing/groq",
            free_allowance_ref: "ref:allowance/groq",
            permission_ref: "ref:permission/facts",
            endpoint_approval_ref: "ref:approval/groq",
            local_endpoint_approval_ref: null,
            max_cost_paise: 999,
          },
        ],
        routes: [
          {
            schema: "ignored",
            task: "facts",
            provider_id: "groq",
            model_id: "openai/gpt-oss-120b",
            recipe_revision: "recipe-facts-v1",
            profile_revision: "profile-facts-v1",
            prompt_revision: "prompt-facts-v1",
            required_input_stage: "C2",
            reuses_checkpoint_stage: "C2",
          },
        ],
      },
      template,
      2,
    );

    expect(configuration.revision).toBe("admin-draft-r3");
    expect(configuration.policy.allow_paid).toBe(false);
    expect(configuration.policy.auto_purchase).toBe(false);
    expect(configuration.providers[0]?.max_cost_paise).toBe(0);
    expect(JSON.stringify(configuration)).not.toMatch(
      /api[_-]?key|secret_value|token_value/i,
    );
    expect(configuration.providers[0]?.credential_ref).toBe("ref:secrets/groq");
    expect(configuration.routes).toHaveLength(1);
  });

  it("derives the exact catalog endpoint digest before an implemented provider save", async () => {
    const configuration = await prepareConfiguration(
      {
        revision: "admin-draft-v1",
        providers: [
          {
            schema: "ignored",
            provider_id: "groq",
            model_id: "openai/gpt-oss-120b",
            endpoint: "https://api.groq.com/openai/v1/chat/completions",
            endpoint_sha256: null,
            credential_ref: null,
            provider_terms_ref: null,
            privacy_ref: null,
            pricing_ref: null,
            free_allowance_ref: null,
            permission_ref: null,
            endpoint_approval_ref: null,
            local_endpoint_approval_ref: null,
            max_cost_paise: 0,
          },
        ],
        routes: [],
      },
      template,
      catalog,
      0,
    );

    expect(configuration.providers[0]?.endpoint_sha256).toBe(
      "dfd2a15f09373fda210f3abc40f9c258363058225f1ec5b33ce607d37ff1ae57",
    );
  });

  it("keeps a stale revision visible after a 409 so the operator must reload", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(payload()))
      .mockResolvedValueOnce(jsonResponse({ detail: "conflict" }, 409));

    await renderPanel();
    const save = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Save settings"),
    );
    expect(save).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      (save as HTMLButtonElement).click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(host.textContent).toContain("Reload the current revision");
    expect(host.textContent).toContain("Provider settings changed");
    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(postCall?.[0]).toBe("/v1/admin/conversation/providers");
    expect(postCall?.[1]?.headers).toEqual(
      expect.objectContaining({ "idempotency-key": expect.any(String) }),
    );
    expect(JSON.parse(postCall?.[1]?.body as string)).toEqual(
      expect.objectContaining({ expected_revision: 0 }),
    );
  });
});
