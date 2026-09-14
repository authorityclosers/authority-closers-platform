// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import liveCatalogFixture from "./provider-catalog.fixture.json";

import {
  buildConfiguration,
  prepareConfiguration,
  parseProviderControlsPayload,
  parseImportedConfiguration,
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

const importedConfiguration: RegistryConfiguration = {
  ...template,
  revision: "sales-xray-reviewed-groq-facts-v1",
  policy: {
    ...template.policy,
    allow_paid: true,
    paid_approval_ref: "ref:approval/reviewed-groq-facts",
  },
  providers: [
    {
      schema: "ac.sales_xray.provider_config/1",
      provider_id: "groq",
      model_id: "openai/gpt-oss-120b",
      endpoint: "https://api.groq.com/openai/v1/chat/completions",
      endpoint_sha256:
        "dfd2a15f09373fda210f3abc40f9c258363058225f1ec5b33ce607d37ff1ae57",
      credential_ref: "ref:credential/groq",
      provider_terms_ref: "ref:provider-terms/groq",
      privacy_ref: "ref:privacy/groq",
      pricing_ref: "ref:pricing/groq",
      free_allowance_ref: null,
      permission_ref: "ref:permission/facts",
      endpoint_approval_ref: "ref:approval/groq-endpoint",
      local_endpoint_approval_ref: null,
      max_cost_paise: 700,
    },
  ],
  routes: [
    {
      schema: "ac.sales_xray.route_config/1",
      task: "facts",
      provider_id: "groq",
      model_id: "openai/gpt-oss-120b",
      recipe_revision: "reviewed-facts-v1",
      profile_revision: "reviewed-profile-v1",
      prompt_revision: "reviewed-prompt-v1",
      required_input_stage: "C2",
      reuses_checkpoint_stage: "C2",
    },
  ],
};

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

function setTextareaValue(textarea: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  setter?.call(textarea, value);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
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
  it("validates a reviewed non-secret registry import before saving", async () => {
    expect(
      parseImportedConfiguration(JSON.stringify(importedConfiguration)),
    ).toEqual(importedConfiguration);
    expect(() =>
      parseImportedConfiguration(
        JSON.stringify({
          ...importedConfiguration,
          api_key: "should-not-appear",
        }),
      ),
    ).toThrow("non-secret profile JSON");
  });

  it("does not restore a stale import preview after text changes during digesting", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(payload()));
    await renderPanel();

    let releaseDigest: ((value: ArrayBuffer) => void) | undefined;
    const digest = vi.spyOn(crypto.subtle, "digest").mockImplementation(
      () =>
        new Promise<ArrayBuffer>((resolve) => {
          releaseDigest = resolve;
        }),
    );
    const textarea = host.querySelector(
      'textarea[aria-label="Reviewed provider configuration JSON"]',
    ) as HTMLTextAreaElement;
    setTextareaValue(textarea, JSON.stringify(importedConfiguration));

    await act(async () => {
      [...host.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("Check profile"))!
        .click();
      await Promise.resolve();
    });
    expect(host.textContent).toContain("Checking…");

    await act(async () => {
      setTextareaValue(textarea, "{");
      await Promise.resolve();
    });
    expect(host.textContent).not.toContain("Local contract check passed");

    await act(async () => {
      releaseDigest?.(new ArrayBuffer(32));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(host.textContent).not.toContain("Local contract check passed");
    digest.mockRestore();
  });

  it("previews and saves an imported profile through the current revision", async () => {
    const saved = {
      id: "imported-registry",
      revision: 3,
      configuration_sha256: "b".repeat(64),
      configuration: importedConfiguration,
      created_at: "2026-09-14T00:00:00Z",
      execution_activated: false,
      activation: null,
      activation_options: [],
    };
    fetchMock
      .mockResolvedValueOnce(jsonResponse(payload()))
      .mockResolvedValueOnce(jsonResponse(saved));

    await renderPanel();
    const textarea = host.querySelector(
      'textarea[aria-label="Reviewed provider configuration JSON"]',
    ) as HTMLTextAreaElement;
    setTextareaValue(textarea, JSON.stringify(importedConfiguration));
    await act(async () => {
      [...host.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("Check profile"))!
        .click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(host.textContent).toContain("Local contract check passed");
    expect(host.textContent).toContain("groq/openai/gpt-oss-120b");
    expect(host.textContent).toContain("₹7.00 per dispatch ceiling");
    expect(host.textContent).toContain(importedConfiguration.revision);

    await act(async () => {
      [...host.querySelectorAll("button")]
        .find((button) =>
          button.textContent?.includes("Save imported revision"),
        )!
        .click();
      await Promise.resolve();
      await Promise.resolve();
    });

    const request = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(request?.[0]).toBe("/v1/admin/conversation/providers");
    expect(request?.[1]?.headers).toEqual(
      expect.objectContaining({ "idempotency-key": expect.any(String) }),
    );
    expect(JSON.parse(request?.[1]?.body as string)).toEqual({
      expected_revision: 0,
      configuration: importedConfiguration,
    });
    expect(host.textContent).toContain("Imported revision saved");
  });

  it("keeps an imported profile pending when the saved revision is stale", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(payload()))
      .mockResolvedValueOnce(jsonResponse({ detail: "stale" }, 409));

    await renderPanel();
    const textarea = host.querySelector(
      'textarea[aria-label="Reviewed provider configuration JSON"]',
    ) as HTMLTextAreaElement;
    setTextareaValue(textarea, JSON.stringify(importedConfiguration));
    await act(async () => {
      [...host.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("Check profile"))!
        .click();
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      [...host.querySelectorAll("button")]
        .find((button) =>
          button.textContent?.includes("Save imported revision"),
        )!
        .click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(host.textContent).toContain("Provider settings changed");
    expect(host.textContent).toContain("Reload the current revision");
    expect(host.textContent).toContain("ready to save");
  });

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
    expect(host.textContent).toContain("Unavailable");
    expect(host.textContent).toContain("catalog metadata only");
    expect(host.textContent).not.toContain("execution_activated false");
    expect(host.textContent).not.toContain("API key");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("surfaces the approved stage data paths while keeping technical editors advanced", async () => {
    const current = {
      id: "registry-proof",
      revision: 4,
      configuration_sha256: "a".repeat(64),
      configuration: importedConfiguration,
      created_at: "2026-09-14T00:00:00Z",
      execution_activated: false,
      activation: null,
      activation_options: [],
    };
    fetchMock.mockResolvedValue(
      jsonResponse({
        ...payload(current),
        tasks: [
          ...tasks,
          {
            schema: "ac.sales_xray.task_contract/1",
            task: "asr" as const,
            input_stage: "C0" as const,
            reuse_stage: null,
            profile_required: false,
          },
          {
            schema: "ac.sales_xray.task_contract/1",
            task: "coaching" as const,
            input_stage: "C4" as const,
            reuse_stage: "C4" as const,
            profile_required: true,
          },
        ],
      }),
    );

    await renderPanel();

    expect(host.querySelector("#workflow-title")?.textContent).toContain(
      "What each approved route does",
    );
    expect(host.textContent).toContain("Transcription");
    expect(host.textContent).toContain("Analysis");
    expect(host.textContent).toContain("Report style");
    expect(host.textContent).toContain("Spending and future plans");
    expect(host.textContent).toContain(
      "Destination: Groq open weights via groq_openai_compatible_https (hosted).",
    );

    const advanced = [...host.querySelectorAll("details")];
    expect(
      advanced.find((entry) =>
        entry.textContent?.includes("import a reviewed provider JSON profile"),
      )?.open,
    ).toBe(false);
    expect(
      advanced.find((entry) =>
        entry.textContent?.includes(
          "provider bindings and technical references",
        ),
      )?.open,
    ).toBe(false);
  });

  it("activates only a server-listed approved revision for future plans", async () => {
    const current = {
      id: "registry-proof",
      revision: 4,
      configuration_sha256: "a".repeat(64),
      configuration: template,
      created_at: "2026-09-14T00:00:00Z",
      execution_activated: false,
      activation: null,
      activation_options: [
        {
          id: "approved-revision",
          revision: 4,
          configuration_sha256: "a".repeat(64),
          routes: [
            {
              task: "facts",
              provider: "gemini",
              model: "gemini-3.8-flash",
              max_cost_paise: 500,
            },
          ],
        },
      ],
    };
    const activated = {
      ...current,
      execution_activated: true,
      activation: {
        id: "activation-receipt",
        sequence: 1,
        revision: 4,
        configuration_sha256: "a".repeat(64),
        created_at: "2026-09-14T00:01:00Z",
      },
    };
    fetchMock
      .mockResolvedValueOnce(jsonResponse(payload(current)))
      .mockResolvedValueOnce(jsonResponse(activated));

    await renderPanel();
    const activate = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Activate for new plans"),
    );
    expect(activate).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      (activate as HTMLButtonElement).click();
      await Promise.resolve();
      await Promise.resolve();
    });

    const postCall = fetchMock.mock.calls.find(
      ([url, init]) =>
        url === "/v1/admin/conversation/providers/activate" &&
        init?.method === "POST",
    );
    expect(postCall?.[1]?.headers).toEqual(
      expect.objectContaining({ "idempotency-key": expect.any(String) }),
    );
    expect(JSON.parse(postCall?.[1]?.body as string)).toEqual({
      expected_revision: 4,
      target_revision: 4,
    });
    expect(host.textContent).toContain("active for new plans");
  });

  it("selects the first approved revision when the active revision is absent", async () => {
    const current = {
      id: "registry-proof",
      revision: 5,
      configuration_sha256: "a".repeat(64),
      configuration: template,
      created_at: "2026-09-14T00:00:00Z",
      execution_activated: true,
      activation: {
        id: "active-revision",
        sequence: 1,
        revision: 1,
        configuration_sha256: "b".repeat(64),
        created_at: "2026-09-14T00:00:00Z",
      },
      activation_options: [
        {
          id: "approved-revision-2",
          revision: 2,
          configuration_sha256: "c".repeat(64),
          routes: [
            {
              task: "facts",
              provider: "gemini",
              model: "gemini-3.8-flash",
              max_cost_paise: 500,
            },
          ],
        },
      ],
    };
    const activated = {
      ...current,
      activation: {
        ...current.activation,
        revision: 2,
        configuration_sha256: "c".repeat(64),
      },
    };
    fetchMock
      .mockResolvedValueOnce(jsonResponse(payload(current)))
      .mockResolvedValueOnce(jsonResponse(activated));

    await renderPanel();
    const activate = [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Activate for new plans"),
    );
    expect(activate).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      (activate as HTMLButtonElement).click();
      await Promise.resolve();
      await Promise.resolve();
    });

    const postCall = fetchMock.mock.calls.find(
      ([url, init]) =>
        url === "/v1/admin/conversation/providers/activate" &&
        init?.method === "POST",
    );
    expect(JSON.parse(postCall?.[1]?.body as string)).toEqual({
      expected_revision: 5,
      target_revision: 2,
    });
    expect(host.textContent).toContain("active for new plans");
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

  it("preserves saved paid approvals and caps on model edits without authorizing a new cap", () => {
    const providerDefaults = {
      schema: "ac.sales_xray.provider_config/1",
      endpoint: null,
      endpoint_sha256: null,
      credential_ref: null,
      provider_terms_ref: null,
      privacy_ref: null,
      pricing_ref: null,
      free_allowance_ref: null,
      permission_ref: null,
      endpoint_approval_ref: null,
      local_endpoint_approval_ref: null,
    };
    const approved: RegistryConfiguration = {
      ...template,
      policy: {
        ...template.policy,
        allow_paid: true,
        paid_approval_ref: "ref:approval/bounded-review",
      },
      providers: [
        {
          ...providerDefaults,
          provider_id: "elevenlabs",
          model_id: "scribe",
          max_cost_paise: 1100,
        },
        {
          ...providerDefaults,
          provider_id: "google",
          model_id: "gemini",
          max_cost_paise: 500,
        },
      ],
    };
    const current = {
      id: "registry-proof",
      revision: 4,
      configuration_sha256: "a".repeat(64),
      configuration: approved,
      created_at: "2026-09-14T00:00:00Z",
      execution_activated: false,
    };
    expect(
      parseProviderControlsPayload(payload(current)).current?.configuration
        .policy,
    ).toEqual(approved.policy);
    const draft = {
      revision: approved.revision,
      providers: approved.providers.map((provider) => ({
        ...provider,
        model_id: `${provider.model_id}-edited`,
      })),
      routes: [],
    };
    const result = buildConfiguration(draft, approved, 4);
    expect(result.policy).toEqual(approved.policy);
    expect(result.providers.map((provider) => provider.max_cost_paise)).toEqual(
      [1100, 500],
    );
    const enlarged = buildConfiguration(
      {
        ...draft,
        providers: [{ ...draft.providers[0]!, max_cost_paise: 9999 }],
      },
      approved,
      4,
    );
    expect(enlarged.providers[0]?.max_cost_paise).toBe(0);
    const newProvider = buildConfiguration(
      {
        ...draft,
        providers: [
          { ...draft.providers[0]!, provider_id: "unapproved-provider" },
        ],
      },
      approved,
      4,
    );
    expect(newProvider.providers[0]?.max_cost_paise).toBe(0);
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

  it("saves a model edit against the current paid revision instead of the empty template", async () => {
    const approved: RegistryConfiguration = {
      ...template,
      policy: {
        ...template.policy,
        allow_paid: true,
        paid_approval_ref: "ref:approval/existing-budget",
      },
      providers: [
        {
          schema: "ac.sales_xray.provider_config/1",
          provider_id: "groq",
          model_id: "openai/gpt-oss-120b",
          endpoint: null,
          endpoint_sha256: null,
          credential_ref: null,
          provider_terms_ref: null,
          privacy_ref: null,
          pricing_ref: null,
          free_allowance_ref: null,
          permission_ref: null,
          endpoint_approval_ref: null,
          local_endpoint_approval_ref: null,
          max_cost_paise: 500,
        },
      ],
      routes: [],
    };
    const current = {
      id: "registry-proof",
      revision: 4,
      configuration_sha256: "a".repeat(64),
      configuration: approved,
      created_at: "2026-09-14T00:00:00Z",
      execution_activated: false,
    };
    const nextCatalog = catalog.map((entry) =>
      entry.provider_id === "groq"
        ? {
            ...entry,
            models: [
              ...entry.models,
              { ...entry.models[0]!, model_id: "replacement-model" },
            ],
          }
        : entry,
    );
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ ...payload(current), catalog: nextCatalog }),
      )
      .mockResolvedValueOnce(jsonResponse({ ...current, revision: 5 }));
    await renderPanel();
    const model = host.querySelector(
      'select[aria-label="Model 1"]',
    ) as HTMLSelectElement;
    await act(async () => {
      model.value = "replacement-model";
      model.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await act(async () => {
      [...host.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("Save settings"))!
        .click();
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      await vi.waitFor(() => {
        expect(
          fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
        ).toBe(true);
      });
    });
    const request = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(request).toBeDefined();
    const saved = JSON.parse(request![1].body as string);
    expect(saved.expected_revision).toBe(4);
    expect(saved.configuration.policy).toEqual(approved.policy);
    expect(saved.configuration.providers[0]).toMatchObject({
      model_id: "replacement-model",
      max_cost_paise: 500,
    });
    await act(async () => {
      [...host.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("Remove"))!
        .click();
    });
    await act(async () => {
      [...host.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("Save settings"))!
        .click();
    });
    expect(host.textContent).toContain(
      "Keep at least one provider with its saved paid cap",
    );
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(1);
  });
});
