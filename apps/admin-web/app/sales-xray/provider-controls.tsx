"use client";

import { useEffect, useRef, useState } from "react";
import { Plus, RefreshCw, Save, ShieldCheck, Trash2 } from "lucide-react";
import { z } from "zod";

import { newIdempotencyKey } from "@ac/operations-web/api";

import { AdminShell } from "../components/admin-shell";
import { SalesXrayNavigation } from "./sales-xray-navigation";
import styles from "./provider-controls.module.css";

const TASK_NAMES = [
  "asr",
  "facts",
  "embeddings",
  "retrieval",
  "rerank",
  "coaching",
  "presentation",
] as const;
const CHECKPOINT_STAGES = ["C0", "C1", "C2", "C3", "C4", "C5", "C6"] as const;
const SHA256 = /^[0-9a-f]{64}$/;
const EXTERNAL_REFERENCE = /^ref:[A-Za-z][A-Za-z0-9_.:/-]{0,255}$/;

const taskSchema = z
  .object({
    schema: z.string().min(1),
    task: z.enum(TASK_NAMES),
    input_stage: z.enum(CHECKPOINT_STAGES),
    reuse_stage: z.enum(CHECKPOINT_STAGES).nullable(),
    profile_required: z.boolean(),
  })
  .strict();

const modelSchema = z
  .object({
    model_id: z.string().min(1),
    endpoint: z.string().min(1).nullable(),
    transport_status: z.enum(["implemented", "planned"]),
    readiness: z.string().min(1),
    task_support: z.array(
      z
        .object({
          task: z.enum(TASK_NAMES),
          status: z.enum([
            "implemented",
            "contract_only",
            "planned",
            "unavailable",
          ]),
        })
        .strict(),
    ),
  })
  .strict();

const catalogEntrySchema = z
  .object({
    provider_id: z.string().min(1),
    display_name: z.string().min(1),
    protocol: z.string().min(1),
    status: z.enum(["implemented", "planned"]),
    readiness: z.string().min(1),
    deployment: z.enum(["hosted", "gateway", "local", "deterministic_tool"]),
    models: z.array(modelSchema),
    note: z.string(),
  })
  .strict();

const referenceSchema = z.string().regex(EXTERNAL_REFERENCE).nullable();
const providerConfigSchema = z
  .object({
    schema: z.string().min(1),
    provider_id: z.string().min(1),
    model_id: z.string().min(1),
    endpoint: z.string().min(1).nullable(),
    endpoint_sha256: z.string().regex(SHA256).nullable(),
    credential_ref: referenceSchema,
    provider_terms_ref: referenceSchema,
    privacy_ref: referenceSchema,
    pricing_ref: referenceSchema,
    free_allowance_ref: referenceSchema,
    permission_ref: referenceSchema,
    endpoint_approval_ref: referenceSchema,
    local_endpoint_approval_ref: referenceSchema,
    max_cost_paise: z.number().int().nonnegative().nullable(),
  })
  .strict();

const routeSchema = z
  .object({
    schema: z.string().min(1),
    task: z.enum(TASK_NAMES),
    provider_id: z.string().min(1),
    model_id: z.string().min(1),
    recipe_revision: z.string().min(1),
    profile_revision: z.string().min(1),
    prompt_revision: z.string().min(1),
    required_input_stage: z.enum(CHECKPOINT_STAGES),
    reuses_checkpoint_stage: z.enum(CHECKPOINT_STAGES).nullable(),
  })
  .strict();

const policySchema = z
  .object({
    schema: z.string().min(1),
    allow_paid: z.boolean(),
    auto_purchase: z.literal(false),
    paid_approval_ref: z.string().regex(EXTERNAL_REFERENCE).nullable(),
  })
  .strict();

const registrySchema = z
  .object({
    schema: z.string().min(1),
    revision: z.string().min(1),
    policy: policySchema,
    providers: z.array(providerConfigSchema).max(64),
    routes: z.array(routeSchema).max(64),
  })
  .strict();

const currentSchema = z
  .object({
    id: z.string().min(1),
    revision: z.number().int().nonnegative(),
    configuration_sha256: z.string().regex(SHA256),
    configuration: registrySchema,
    created_at: z.string().min(1),
    execution_activated: z.literal(false),
  })
  .strict();

const responseSchema = z
  .object({
    catalog: z.array(catalogEntrySchema),
    tasks: z.array(taskSchema),
    configuration_template: registrySchema,
    current: currentSchema.nullable(),
    max_paid_paise: z.literal(0),
    execution_activated: z.literal(false),
    message: z.string().min(1),
  })
  .strict();

const saveResponseSchema = currentSchema;

export type ProviderControlsPayload = z.infer<typeof responseSchema>;
export type ProviderView = z.infer<typeof currentSchema>;
export type RegistryConfiguration = z.infer<typeof registrySchema>;
type CatalogEntry = z.infer<typeof catalogEntrySchema>;
type ProviderConfig = z.infer<typeof providerConfigSchema>;
type RouteConfig = z.infer<typeof routeSchema>;
export type DraftState = {
  providers: ProviderConfig[];
  routes: RouteConfig[];
  revision: string;
};

const PROVIDER_CONFIG_SCHEMA = "ac.sales_xray.provider_config/1";
const ROUTE_SCHEMA = "ac.sales_xray.route_config/1";

const referenceFields = [
  [
    "credential_ref",
    "Credential reference",
    "Reference to the server-held credential.",
  ],
  [
    "provider_terms_ref",
    "Provider terms reference",
    "Reference to the reviewed provider terms.",
  ],
  [
    "privacy_ref",
    "Privacy reference",
    "Reference to the approved privacy and retention record.",
  ],
  ["pricing_ref", "Pricing reference", "Reference to the pricing decision."],
  [
    "free_allowance_ref",
    "Free allowance reference",
    "Reference to the allowance or quota record.",
  ],
  [
    "permission_ref",
    "Permission reference",
    "Reference to the approved task permission.",
  ],
  [
    "endpoint_approval_ref",
    "Endpoint approval reference",
    "Reference to endpoint review.",
  ],
  [
    "local_endpoint_approval_ref",
    "Local endpoint approval",
    "Required later for approved local HTTP endpoints.",
  ],
] as const;

function newProvider(catalog: CatalogEntry[]): ProviderConfig {
  const provider = catalog[0];
  const model = provider?.models[0];
  return {
    schema: PROVIDER_CONFIG_SCHEMA,
    provider_id: provider?.provider_id ?? "",
    model_id: model?.model_id ?? "",
    endpoint: model?.endpoint ?? null,
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
  };
}

function draftFromConfiguration(
  configuration: RegistryConfiguration,
): DraftState {
  return {
    providers: configuration.providers.map((provider) => ({ ...provider })),
    routes: configuration.routes.map((route) => ({ ...route })),
    revision: configuration.revision,
  };
}

export function buildConfiguration(
  draft: DraftState,
  template: RegistryConfiguration,
  expectedRevision: number,
): RegistryConfiguration {
  return {
    schema: template.schema,
    revision: `admin-draft-r${expectedRevision + 1}`,
    policy: {
      ...template.policy,
      auto_purchase: false,
    },
    providers: draft.providers.map((provider) => ({
      ...provider,
      schema: PROVIDER_CONFIG_SCHEMA,
      // This editor has no budget controls. Preserve only a cap already present
      // for this provider in the server's current revision, including model edits.
      max_cost_paise: template.providers.some(
        (saved) =>
          saved.provider_id === provider.provider_id &&
          saved.max_cost_paise === provider.max_cost_paise,
      )
        ? provider.max_cost_paise
        : 0,
    })),
    routes: draft.routes.map((route) => ({ ...route, schema: ROUTE_SCHEMA })),
  };
}

async function sha256Text(value: string) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export async function prepareConfiguration(
  draft: DraftState,
  template: RegistryConfiguration,
  catalog: CatalogEntry[],
  expectedRevision: number,
) {
  const providers = await Promise.all(
    draft.providers.map(async (provider) => {
      const catalogProvider = providerFor(catalog, provider.provider_id);
      const endpointSha =
        catalogProvider?.status === "implemented" && provider.endpoint
          ? await sha256Text(provider.endpoint)
          : provider.endpoint_sha256;
      return { ...provider, endpoint_sha256: endpointSha };
    }),
  );
  return buildConfiguration(
    { ...draft, providers },
    template,
    expectedRevision,
  );
}

export function parseProviderControlsPayload(
  value: unknown,
): ProviderControlsPayload {
  return responseSchema.parse(value);
}

function providerFor(catalog: CatalogEntry[], providerId: string) {
  return catalog.find((provider) => provider.provider_id === providerId);
}

function modelFor(provider: CatalogEntry | undefined, modelId: string) {
  return provider?.models.find((model) => model.model_id === modelId);
}

function bindingKey(
  provider: Pick<ProviderConfig, "provider_id" | "model_id">,
) {
  return `${provider.provider_id}::${provider.model_id}`;
}

function supportedTasks(
  catalog: CatalogEntry[],
  provider: ProviderConfig,
  tasks: ProviderControlsPayload["tasks"],
) {
  const catalogProvider = providerFor(catalog, provider.provider_id);
  if (!catalogProvider || catalogProvider.status === "planned") return tasks;
  const model = modelFor(catalogProvider, provider.model_id);
  return tasks.filter((task) =>
    model?.task_support.some(
      (support) =>
        support.task === task.task && support.status !== "unavailable",
    ),
  );
}

async function requestJson(path: string, init: RequestInit = {}) {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json", ...(init.headers ?? {}) },
  });
  if (response.status === 401) throw new Error("unauthenticated");
  if (response.status === 403) throw new Error("forbidden");
  if (!response.ok) throw new Error(`http_${response.status}`);
  return response.json() as Promise<unknown>;
}

export async function loadProviderControls(
  signal?: AbortSignal,
): Promise<ProviderControlsPayload> {
  return parseProviderControlsPayload(
    await requestJson("/v1/admin/conversation/providers", { signal }),
  );
}

function ExternalReferenceField({
  label,
  helper,
  value,
  inputId,
  onChange,
}: {
  label: string;
  helper: string;
  value: string;
  inputId: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className={styles.field}>
      <span className={styles.fieldLabel}>{label}</span>
      <input
        id={inputId}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="ref:..."
        autoComplete="off"
        spellCheck={false}
        aria-describedby={`${inputId}-help`}
      />
      <small id={`${inputId}-help`}>{helper}</small>
    </label>
  );
}

function ProviderEditor({
  catalog,
  provider,
  index,
  onChange,
  onRemove,
}: {
  catalog: CatalogEntry[];
  provider: ProviderConfig;
  index: number;
  onChange: (patch: Partial<ProviderConfig>) => void;
  onRemove: () => void;
}) {
  const catalogProvider = providerFor(catalog, provider.provider_id);
  const model = modelFor(catalogProvider, provider.model_id);
  const isPlanned = catalogProvider?.status === "planned";
  const canRemove = true;
  return (
    <article
      className={styles.card}
      aria-labelledby={`provider-${index}-title`}
    >
      <div className={styles.cardHeader}>
        <div>
          <span className={styles.eyebrow}>
            Provider model {String(index + 1).padStart(2, "0")}
          </span>
          <h3 id={`provider-${index}-title`}>
            {catalogProvider?.display_name ?? "Choose a provider"}
          </h3>
          <div className={styles.providerMeta}>
            <span>{catalogProvider?.status ?? "unselected"}</span>
            <code>{catalogProvider?.protocol ?? "provider"}</code>
            {isPlanned ? <span>DORMANT catalog entry</span> : null}
          </div>
        </div>
        <button
          className="button button-secondary"
          type="button"
          onClick={onRemove}
          disabled={!canRemove}
        >
          <Trash2 size={15} aria-hidden="true" /> Remove
        </button>
      </div>

      <div className={styles.fieldGrid}>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Provider</span>
          <select
            aria-label={`Provider ${index + 1}`}
            value={provider.provider_id}
            onChange={(event) => {
              const next = providerFor(catalog, event.target.value);
              const nextModel = next?.models[0];
              onChange({
                provider_id: event.target.value,
                model_id: nextModel?.model_id ?? "",
                endpoint: nextModel?.endpoint ?? null,
                endpoint_sha256: null,
                max_cost_paise: 0,
              });
            }}
          >
            <option value="">Choose a provider</option>
            {catalog.map((entry) => (
              <option value={entry.provider_id} key={entry.provider_id}>
                {entry.display_name} · {entry.status}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span className={styles.fieldLabel}>Model</span>
          {isPlanned ? (
            <input
              aria-label={`Model ${index + 1}`}
              value={provider.model_id}
              onChange={(event) => onChange({ model_id: event.target.value })}
              placeholder="planned-model-id"
            />
          ) : (
            <select
              aria-label={`Model ${index + 1}`}
              value={provider.model_id}
              onChange={(event) => {
                const nextModel = modelFor(catalogProvider, event.target.value);
                onChange({
                  model_id: event.target.value,
                  endpoint: nextModel?.endpoint ?? null,
                  endpoint_sha256: null,
                });
              }}
            >
              <option value="">Choose a model</option>
              {catalogProvider?.models.map((entry) => (
                <option value={entry.model_id} key={entry.model_id}>
                  {entry.model_id}
                </option>
              ))}
            </select>
          )}
          <small>
            {isPlanned
              ? "Manual model metadata remains dormant until separately approved."
              : (model?.readiness ?? "Choose a catalog model.")}
          </small>
        </label>
      </div>

      <label className={styles.field}>
        <span className={styles.fieldLabel}>Endpoint</span>
        <input
          aria-label={`Endpoint ${index + 1}`}
          value={provider.endpoint ?? ""}
          readOnly={!isPlanned}
          onChange={(event) =>
            onChange({
              endpoint: event.target.value || null,
              endpoint_sha256: null,
            })
          }
          placeholder={
            isPlanned
              ? "https://planned-endpoint.example"
              : "Local process or catalog endpoint"
          }
        />
        <small>
          {isPlanned
            ? "Manual endpoint is retained as dormant metadata; it does not make a provider ready."
            : "Implemented provider endpoints come from the server catalog."}
        </small>
      </label>

      <details className={styles.advanced}>
        <summary>Advanced references</summary>
        <p className={styles.helper}>
          Use opaque <code>ref:...</code> references only. Missing references
          keep this configuration pending.
        </p>
        <div className={styles.fieldGrid}>
          {referenceFields.map(([field, label, helper]) => (
            <ExternalReferenceField
              key={field}
              label={label}
              helper={helper}
              value={provider[field] ?? ""}
              inputId={`provider-${index}-${field}`}
              onChange={(value) => onChange({ [field]: value || null })}
            />
          ))}
        </div>
      </details>
    </article>
  );
}

function RouteEditor({
  route,
  index,
  providers,
  catalog,
  tasks,
  onChange,
  onRemove,
}: {
  route: RouteConfig;
  index: number;
  providers: ProviderConfig[];
  catalog: CatalogEntry[];
  tasks: ProviderControlsPayload["tasks"];
  onChange: (patch: Partial<RouteConfig>) => void;
  onRemove: () => void;
}) {
  const selectedProvider = providers.find(
    (provider) => bindingKey(provider) === bindingKey(route),
  );
  const options = selectedProvider
    ? supportedTasks(catalog, selectedProvider, tasks)
    : tasks;
  return (
    <article className={styles.routeCard}>
      <div className={styles.routeHeader}>
        <div>
          <span className={styles.routeLabel}>
            Task route {String(index + 1).padStart(2, "0")}
          </span>
          <div className={styles.routeMeta}>
            <span>{route.task}</span>
            <code>{route.required_input_stage} input</code>
            {route.reuses_checkpoint_stage ? (
              <code>reuses {route.reuses_checkpoint_stage}</code>
            ) : null}
          </div>
        </div>
        <button
          className="button button-secondary"
          type="button"
          onClick={onRemove}
        >
          <Trash2 size={15} aria-hidden="true" /> Remove
        </button>
      </div>
      <div className={styles.routeGrid}>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Task</span>
          <select
            aria-label={`Task ${index + 1}`}
            value={route.task}
            onChange={(event) => {
              const next = tasks.find(
                (task) => task.task === event.target.value,
              );
              if (next)
                onChange({
                  task: next.task,
                  required_input_stage: next.input_stage,
                  reuses_checkpoint_stage: next.reuse_stage,
                });
            }}
          >
            {tasks.map((task) => (
              <option
                value={task.task}
                key={task.task}
                disabled={!options.some((option) => option.task === task.task)}
              >
                {task.task}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Provider model</span>
          <select
            aria-label={`Route provider ${index + 1}`}
            value={bindingKey(route)}
            onChange={(event) => {
              const next = providers.find(
                (provider) => bindingKey(provider) === event.target.value,
              );
              if (next)
                onChange({
                  provider_id: next.provider_id,
                  model_id: next.model_id,
                });
            }}
          >
            {providers.map((provider) => (
              <option value={bindingKey(provider)} key={bindingKey(provider)}>
                {provider.provider_id} · {provider.model_id || "model required"}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Recipe revision</span>
          <input
            value={route.recipe_revision}
            onChange={(event) =>
              onChange({ recipe_revision: event.target.value })
            }
          />
        </label>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Profile revision</span>
          <input
            value={route.profile_revision}
            onChange={(event) =>
              onChange({ profile_revision: event.target.value })
            }
          />
        </label>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Prompt revision</span>
          <input
            value={route.prompt_revision}
            onChange={(event) =>
              onChange({ prompt_revision: event.target.value })
            }
          />
        </label>
      </div>
    </article>
  );
}

export function ProviderControlsPanel() {
  const [state, setState] = useState<
    | { status: "loading"; retry: number }
    | {
        status: "ready";
        payload: ProviderControlsPayload;
        current: ProviderView | null;
        retry: number;
      }
    | {
        status: "error" | "unauthenticated" | "forbidden";
        message: string;
        retry: number;
      }
  >({ status: "loading", retry: 0 });
  const [draft, setDraft] = useState<DraftState>({
    providers: [],
    routes: [],
    revision: "admin-draft-v1",
  });
  const [saveState, setSaveState] = useState<
    "idle" | "saving" | "saved" | "conflict"
  >("idle");
  const [message, setMessage] = useState("");
  const requestRef = useRef<AbortController | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    requestRef.current = controller;
    void loadProviderControls(controller.signal)
      .then((payload) => {
        setState((previous) => ({
          status: "ready",
          payload,
          current: payload.current,
          retry: previous.retry,
        }));
        setDraft(
          payload.current
            ? draftFromConfiguration(payload.current.configuration)
            : {
                providers: [],
                routes: [],
                revision: payload.configuration_template.revision,
              },
        );
        setSaveState("idle");
        setMessage("");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const reason = error instanceof Error ? error.message : "error";
        if (reason === "unauthenticated")
          setState((previous) => ({
            status: "unauthenticated",
            message:
              "Sign in to your AC admin account to manage provider settings.",
            retry: previous.retry,
          }));
        else if (reason === "forbidden")
          setState((previous) => ({
            status: "forbidden",
            message:
              "Verify your AC admin account to manage provider settings.",
            retry: previous.retry,
          }));
        else
          setState((previous) => ({
            status: "error",
            message: "Provider settings could not be loaded. Try again.",
            retry: previous.retry,
          }));
      });
    return () => {
      controller.abort();
      if (requestRef.current === controller) requestRef.current = null;
    };
  }, [loadAttempt]);

  const current = state.status === "ready" ? state.current : null;
  const catalog = state.status === "ready" ? state.payload.catalog : [];
  const tasks = state.status === "ready" ? state.payload.tasks : [];
  function addProvider() {
    if (state.status !== "ready") return;
    setDraft((previous) => ({
      ...previous,
      providers: [...previous.providers, newProvider(catalog)],
    }));
    setMessage("");
  }

  function addRoute() {
    if (state.status !== "ready") return;
    const provider = draft.providers.find(
      (entry) =>
        supportedTasks(catalog, entry, tasks).length > 0 && entry.model_id,
    );
    const task = provider
      ? supportedTasks(catalog, provider, tasks)[0]
      : undefined;
    if (!provider || !task) {
      setMessage(
        "Choose a provider model with a cataloged task before adding a route.",
      );
      return;
    }
    setDraft((previous) => ({
      ...previous,
      routes: [
        ...previous.routes,
        {
          schema: ROUTE_SCHEMA,
          task: task.task,
          provider_id: provider.provider_id,
          model_id: provider.model_id,
          recipe_revision: `admin-${task.task}`,
          profile_revision: task.profile_required
            ? `profile-${task.task}`
            : "none",
          prompt_revision: `prompt-${task.task}`,
          required_input_stage: task.input_stage,
          reuses_checkpoint_stage: task.reuse_stage,
        },
      ],
    }));
    setMessage("");
  }

  function validateDraft() {
    const keys = new Set<string>();
    for (const provider of draft.providers) {
      if (!provider.provider_id || !provider.model_id)
        return "Choose a provider and model for every provider binding.";
      const key = bindingKey(provider);
      if (keys.has(key))
        return "Each provider and model binding must be unique.";
      keys.add(key);
      for (const [field] of referenceFields) {
        const value = provider[field];
        if (value !== null && !EXTERNAL_REFERENCE.test(value))
          return `${field} must use an external ref:... reference.`;
      }
    }
    if (draft.routes.some((route) => !keys.has(bindingKey(route))))
      return "Every task route must use a configured provider model.";
    if (state.status === "ready") {
      const preserved = buildConfiguration(
        draft,
        state.current?.configuration ?? state.payload.configuration_template,
        state.current?.revision ?? 0,
      );
      if (
        preserved.policy.allow_paid &&
        !preserved.providers.some(
          (provider) => (provider.max_cost_paise ?? 0) > 0,
        )
      )
        return "Keep at least one provider with its saved paid cap. Update the approved policy before removing the final paid provider.";
    }
    return null;
  }

  async function save() {
    if (state.status !== "ready" || saveState === "saving") return;
    const validationError = validateDraft();
    if (validationError) {
      setMessage(validationError);
      setSaveState("idle");
      return;
    }
    const expectedRevision = state.current?.revision ?? 0;
    setSaveState("saving");
    setMessage("");
    try {
      const configuration = await prepareConfiguration(
        draft,
        state.current?.configuration ?? state.payload.configuration_template,
        catalog,
        expectedRevision,
      );
      const value = await requestJson("/v1/admin/conversation/providers", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": newIdempotencyKey(),
        },
        body: JSON.stringify({
          expected_revision: expectedRevision,
          configuration,
        }),
      });
      const saved = saveResponseSchema.parse(value);
      setState((previous) =>
        previous.status === "ready"
          ? { ...previous, current: saved }
          : previous,
      );
      setDraft(draftFromConfiguration(saved.configuration));
      setSaveState("saved");
      setMessage(
        "Saved as a new immutable revision. This save does not start provider calls.",
      );
    } catch (error: unknown) {
      if (error instanceof Error && error.message === "http_409") {
        setSaveState("conflict");
        setMessage(
          "Provider settings changed. Reload the current revision before saving again.",
        );
      } else if (error instanceof Error && error.message === "forbidden") {
        setState((previous) => ({
          status: "forbidden",
          message: "Verify your AC admin account to manage provider settings.",
          retry: previous.retry,
        }));
      } else if (
        error instanceof Error &&
        error.message === "unauthenticated"
      ) {
        setState((previous) => ({
          status: "unauthenticated",
          message:
            "Sign in to your AC admin account to manage provider settings.",
          retry: previous.retry,
        }));
      } else {
        setSaveState("idle");
        setMessage(
          "The revision was not saved. Try again without changing the current revision.",
        );
      }
    }
  }

  function retry() {
    setState((previous) => ({ status: "loading", retry: previous.retry }));
    setLoadAttempt((value) => value + 1);
  }

  if (state.status === "loading")
    return (
      <section className="panel" role="status">
        <h2>Checking provider control access</h2>
        <p>
          The server will return the catalog after it verifies this admin
          session.
        </p>
      </section>
    );
  if (state.status === "unauthenticated" || state.status === "forbidden") {
    return (
      <section className={styles.forbidden} role="alert">
        <h2>
          {state.status === "forbidden"
            ? "Verified AC admin account required"
            : "AC admin sign-in required"}
        </h2>
        <p>{state.message}</p>
        <div className={styles.buttonRow}>
          <a className="button button-primary" href="/login">
            {state.status === "forbidden" ? "Check admin sign-in" : "Sign in"}
          </a>
        </div>
      </section>
    );
  }
  if (state.status === "error")
    return (
      <section className={styles.error} role="alert">
        <h2>Provider controls unavailable</h2>
        <p>{state.message}</p>
        <div className={styles.buttonRow}>
          <button
            className="button button-primary"
            type="button"
            onClick={retry}
          >
            <RefreshCw size={15} aria-hidden="true" /> Try again
          </button>
        </div>
      </section>
    );
  if (state.status !== "ready") return null;

  return (
    <div className={styles.page}>
      <div className={styles.notice} role="note">
        <div>
          <h2>Provider settings are saved for review.</h2>
          <p>
            {state.payload.message} Choose providers and map analysis tasks
            here; this page records settings only and never accepts credentials
            or starts a provider call.
          </p>
        </div>
        <span className={styles.noticeCode}>NO PROVIDER CALLS</span>
      </div>

      <div className={styles.summaryGrid} aria-label="Provider control status">
        <div className={styles.summaryCard}>
          <span>Spend limit</span>
          <strong>₹0</strong>
          <small>fixed in this workspace</small>
        </div>
        <div className={styles.summaryCard}>
          <span>Provider calls</span>
          <strong>Not started here</strong>
          <small>this page only saves settings</small>
        </div>
        <div className={styles.summaryCard}>
          <span>Current revision</span>
          <strong>{current ? `#${current.revision}` : "None"}</strong>
          <small>
            {current ? current.created_at : "No saved configuration yet"}
          </small>
        </div>
      </div>

      {message ? (
        <div
          className={
            saveState === "saved"
              ? styles.success
              : saveState === "conflict"
                ? styles.error
                : styles.notice
          }
          role={saveState === "conflict" ? "alert" : "status"}
        >
          <p>{message}</p>
          {saveState === "conflict" ? (
            <div className={styles.buttonRow}>
              <button
                className="button button-secondary"
                type="button"
                onClick={retry}
              >
                <RefreshCw size={15} aria-hidden="true" /> Reload current
                settings
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      <section
        className={styles.section}
        aria-labelledby="provider-bindings-title"
      >
        <div className={styles.sectionHeader}>
          <div>
            <span className={styles.eyebrow}>Provider bindings</span>
            <h2 id="provider-bindings-title">Choose providers and models.</h2>
            <p>
              Implemented catalog entries keep their server endpoint. Planned
              entries may hold manual metadata, but remain dormant and do not
              become Ready.
            </p>
          </div>
          <button
            className="button button-secondary"
            type="button"
            onClick={addProvider}
          >
            <Plus size={15} aria-hidden="true" /> Add model
          </button>
        </div>
        {draft.providers.length === 0 ? (
          <div className={styles.empty}>
            <p>
              No provider model is configured yet. Add one to create a dormant
              binding.
            </p>
          </div>
        ) : (
          <div className={styles.providerList}>
            {draft.providers.map((provider, index) => (
              <ProviderEditor
                key={`${bindingKey(provider)}-${index}`}
                catalog={catalog}
                provider={provider}
                index={index}
                onChange={(patch) =>
                  setDraft((previous) => ({
                    ...previous,
                    providers: previous.providers.map((entry, currentIndex) =>
                      currentIndex === index ? { ...entry, ...patch } : entry,
                    ),
                  }))
                }
                onRemove={() =>
                  setDraft((previous) => {
                    const removed = previous.providers[index];
                    if (!removed) return previous;
                    const removedKey = bindingKey(removed);
                    return {
                      ...previous,
                      providers: previous.providers.filter(
                        (_, currentIndex) => currentIndex !== index,
                      ),
                      routes: previous.routes.filter(
                        (route) => bindingKey(route) !== removedKey,
                      ),
                    };
                  })
                }
              />
            ))}
          </div>
        )}
      </section>

      <section className={styles.section} aria-labelledby="task-routes-title">
        <div className={styles.sectionHeader}>
          <div>
            <span className={styles.eyebrow}>
              Task routing / analysis revisions
            </span>
            <h2 id="task-routes-title">
              Choose analysis parameters by revision.
            </h2>
            <p>
              Recipe, profile, and prompt values are revision identifiers for a
              future approved run. They select configuration; they do not train
              a model or start analysis.
            </p>
          </div>
          <button
            className="button button-secondary"
            type="button"
            onClick={addRoute}
            disabled={draft.providers.length === 0}
          >
            <Plus size={15} aria-hidden="true" /> Add task
          </button>
        </div>
        {draft.routes.length === 0 ? (
          <div className={styles.empty}>
            <p>
              No task route is configured. Routes remain optional while
              references and approvals are gathered.
            </p>
          </div>
        ) : (
          <div className={styles.routeList}>
            {draft.routes.map((route, index) => (
              <RouteEditor
                key={`${route.task}-${index}`}
                route={route}
                index={index}
                providers={draft.providers}
                catalog={catalog}
                tasks={tasks}
                onChange={(patch) =>
                  setDraft((previous) => ({
                    ...previous,
                    routes: previous.routes.map((entry, currentIndex) =>
                      currentIndex === index ? { ...entry, ...patch } : entry,
                    ),
                  }))
                }
                onRemove={() =>
                  setDraft((previous) => ({
                    ...previous,
                    routes: previous.routes.filter(
                      (_, currentIndex) => currentIndex !== index,
                    ),
                  }))
                }
              />
            ))}
          </div>
        )}
      </section>

      <section className={styles.section} aria-labelledby="catalog-title">
        <div className={styles.catalogHeader}>
          <div>
            <span className={styles.eyebrow}>Available providers</span>
            <h2 id="catalog-title">Provider options and status.</h2>
            <p>
              Status describes catalog metadata; it does not mean this page can
              call a provider.
            </p>
          </div>
          <span className={styles.dormant}>catalog metadata only</span>
        </div>
        <div className={styles.catalogList}>
          {catalog.map((provider) => (
            <article className={styles.catalogItem} key={provider.provider_id}>
              <div className={styles.catalogHeader}>
                <strong>{provider.display_name}</strong>
                <span className={styles.status}>{provider.status}</span>
              </div>
              <span className={styles.catalogStatus}>
                {provider.protocol} · {provider.readiness}
              </span>
              <p>{provider.note || "No catalog note supplied."}</p>
              <small>
                {provider.models.length
                  ? `${provider.models.length} model${provider.models.length === 1 ? "" : "s"} listed`
                  : "Model selection is planned metadata"}
              </small>
            </article>
          ))}
        </div>
      </section>

      <section className={styles.section} aria-labelledby="save-title">
        <div className={styles.sectionHeader}>
          <div>
            <span className={styles.eyebrow}>Saved revision</span>
            <h2 id="save-title">Save provider settings.</h2>
            <p>
              Saving creates a new version of these settings. It cannot spend
              money, test a provider, or start processing.
            </p>
          </div>
          <ShieldCheck size={24} aria-hidden="true" />
        </div>
        <div className={styles.buttonRow}>
          <button
            className="button button-primary"
            type="button"
            onClick={() => void save()}
            disabled={saveState === "saving"}
          >
            {saveState === "saving" ? (
              "Saving…"
            ) : (
              <>
                <Save size={15} aria-hidden="true" /> Save settings
              </>
            )}
          </button>
          {saveState === "saving" ? (
            <span className={styles.pending}>saving revision</span>
          ) : saveState === "saved" ? (
            <span className={styles.saved}>saved · dormant</span>
          ) : null}
        </div>
      </section>
    </div>
  );
}

export function ProviderControls() {
  return (
    <AdminShell
      active="sales-xray"
      surface="operations"
      eyebrow="Conversation intelligence / provider settings"
      title="Provider settings"
      description="Choose providers, map analysis tasks, and save reviewable settings."
    >
      <div className={styles.page}>
        <SalesXrayNavigation active="settings" />
        <ProviderControlsPanel />
      </div>
    </AdminShell>
  );
}
