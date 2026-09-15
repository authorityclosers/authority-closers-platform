"use client";

import { useEffect, useRef, useState } from "react";
import { Plus, RefreshCw, Save, ShieldCheck, Trash2 } from "lucide-react";
import { z } from "zod";

import { newIdempotencyKey } from "@ac/operations-web/api";

import { AdminShell } from "../components/admin-shell";
import { SalesXrayNavigation } from "./sales-xray-navigation";
import { ExecutionControlsPanel } from "./execution-controls";
import { AnalysisSettingsPanel } from "./analysis-settings";
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
const REGISTRY_CONFIG_SCHEMA = "ac.sales_xray.provider_registry_config/1";
const MAX_IMPORT_BYTES = 512 * 1024;
const SENSITIVE_IMPORT_FIELD =
  /"(?:api[_-]?key|access[_-]?token|password|private[_-]?key|secret(?:[_-]value)?)"\s*:/i;
const SENSITIVE_IMPORT_VALUE =
  /(?:AIza[0-9A-Za-z_-]{16,}|(?:sk|gsk|xai)-[0-9A-Za-z_-]{12,}|Bearer\s+\S+|Basic\s+\S+)/i;

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
    execution_activated: z.boolean().default(false),
    activation: z
      .object({
        id: z.string().min(1),
        sequence: z.number().int().positive(),
        revision: z.number().int().positive(),
        configuration_sha256: z.string().regex(SHA256),
        created_at: z.string().min(1),
      })
      .nullable()
      .default(null),
    activation_options: z
      .array(
        z
          .object({
            id: z.string().min(1),
            revision: z.number().int().positive(),
            configuration_sha256: z.string().regex(SHA256),
            routes: z.array(
              z
                .object({
                  task: z.string().min(1),
                  provider: z.string().min(1),
                  model: z.string().min(1),
                  max_cost_paise: z.number().int().nonnegative(),
                })
                .strict(),
            ),
          })
          .strict(),
      )
      .default([]),
  })
  .strict();

const responseSchema = z
  .object({
    catalog: z.array(catalogEntrySchema),
    tasks: z.array(taskSchema),
    configuration_template: registrySchema,
    current: currentSchema.nullable(),
    max_paid_paise: z.literal(0),
    approved_budget_cap_paise: z
      .number()
      .int()
      .nonnegative()
      .nullable()
      .default(null),
    execution_activated: z.boolean().default(false),
    internal_tester_policy: z
      .object({
        enabled: z.boolean(),
        accounts: z.array(z.string().min(3)),
        scopes: z.array(z.string().min(1)),
        source: z.literal("hash_pinned_hosted_approval"),
        bundle_digest: z.string().regex(SHA256).nullable(),
        limits_remaining_bounded: z.array(z.string().min(1)),
      })
      .strict()
      .optional(),
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

type ImportedProfile = {
  configuration: RegistryConfiguration;
  digest: string;
  savedRevision?: number;
};

type ActivationOption = ProviderView["activation_options"][number];

function providerDisplayName(providerId: string) {
  const knownNames: Record<string, string> = {
    deepgram: "Deepgram",
    elevenlabs: "ElevenLabs",
    gemini: "Gemini",
  };
  return (
    knownNames[providerId] ??
    providerId
      .split(/[-_]/)
      .filter(Boolean)
      .map((part) => part[0]?.toUpperCase() + part.slice(1))
      .join(" ")
  );
}

function activationOptionLabel(option: ActivationOption) {
  const transcription = option.routes.find((route) => route.task === "asr");
  const analysis = option.routes.find((route) => route.task === "facts");
  if (transcription && analysis) {
    return `${providerDisplayName(transcription.provider)} transcription · ${providerDisplayName(analysis.provider)} analysis`;
  }
  return option.routes
    .map(
      (route) =>
        `${route.task}: ${providerDisplayName(route.provider)} ${route.model}`,
    )
    .join(" · ");
}

function activationOptionRoutes(option: ActivationOption) {
  return option.routes
    .map(
      (route) =>
        `${route.task} → ${providerDisplayName(route.provider)} / ${route.model}`,
    )
    .join(" · ");
}

function preferredActivationRevision(
  current: ProviderView | null,
): number | null {
  if (!current) return null;
  const activeRevision = current.activation?.revision;
  if (
    activeRevision !== undefined &&
    current.activation_options.some(
      (option) => option.revision === activeRevision,
    )
  ) {
    return activeRevision;
  }
  return current.activation_options[0]?.revision ?? null;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

async function configurationDigest(configuration: RegistryConfiguration) {
  const bytes = new TextEncoder().encode(canonicalJson(configuration));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export function parseImportedConfiguration(
  text: string,
): RegistryConfiguration {
  if (!text.trim())
    throw new Error("Paste the reviewed configuration JSON first.");
  if (new TextEncoder().encode(text).byteLength > MAX_IMPORT_BYTES) {
    throw new Error(
      "Configuration JSON is larger than the 512 KB import limit.",
    );
  }
  if (SENSITIVE_IMPORT_FIELD.test(text) || SENSITIVE_IMPORT_VALUE.test(text)) {
    throw new Error(
      "Use the reviewed non-secret profile JSON. Credentials stay in the server environment.",
    );
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error("Configuration must be valid JSON.");
  }
  const parsed = registrySchema.safeParse(value);
  if (!parsed.success || parsed.data.schema !== REGISTRY_CONFIG_SCHEMA) {
    throw new Error(
      "Use a provider registry configuration from the reviewed AC profile format.",
    );
  }
  return parsed.data;
}

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
      </div>
      <details className={styles.advanced}>
        <summary>Technical references and source gates</summary>
        <div className={styles.routeGridAdvanced}>
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
      </details>
    </article>
  );
}

type StageSummaryProps = {
  title: string;
  eyebrow: string;
  task: "asr" | "facts" | "coaching";
  route: RouteConfig | undefined;
  providers: ProviderConfig[];
  catalog: CatalogEntry[];
  dataPath: string;
  note?: string;
  saved: boolean;
  active: boolean;
  onRouteChange?: (patch: Partial<RouteConfig>) => void;
};

function StageSummary({
  title,
  eyebrow,
  task,
  route,
  providers,
  catalog,
  dataPath,
  note,
  saved,
  active,
  onRouteChange,
}: StageSummaryProps) {
  const provider = route
    ? providers.find((entry) => bindingKey(entry) === bindingKey(route))
    : undefined;
  const catalogProvider = provider
    ? providerFor(catalog, provider.provider_id)
    : undefined;
  const model = provider
    ? modelFor(catalogProvider, provider.model_id)
    : undefined;
  const taskSupport = model?.task_support.find(
    (support) => support.task === task,
  );
  const implemented =
    catalogProvider?.status === "implemented" &&
    model?.transport_status === "implemented" &&
    taskSupport?.status === "implemented";
  const status = !route
    ? "Not configured"
    : !catalogProvider || !model
      ? "Needs catalog review"
      : catalogProvider.status === "planned" ||
          model.transport_status === "planned"
        ? "Planned · dormant"
        : !taskSupport || taskSupport.status === "unavailable"
          ? "Unavailable for task"
          : taskSupport.status === "contract_only"
            ? "Contract only"
            : taskSupport.status === "planned"
              ? "Planned · dormant"
              : implemented
                ? "Implemented"
                : "Needs catalog review";
  const providerOptions = providers.filter(
    (entry, index, all) =>
      entry.provider_id &&
      all.findIndex(
        (candidate) => candidate.provider_id === entry.provider_id,
      ) === index,
  );
  const modelOptions = route
    ? providers.filter(
        (entry, index, all) =>
          entry.provider_id === route.provider_id &&
          entry.model_id &&
          all.findIndex(
            (candidate) =>
              candidate.provider_id === entry.provider_id &&
              candidate.model_id === entry.model_id,
          ) === index,
      )
    : [];

  return (
    <article
      className={styles.stageCard}
      aria-labelledby={`${task}-stage-title`}
    >
      <div className={styles.stageHeader}>
        <div>
          <span className={styles.eyebrow}>{eyebrow}</span>
          <h2 id={`${task}-stage-title`}>{title}</h2>
        </div>
        <div className={styles.stageBadges}>
          <span
            className={
              implemented ? styles.stageStatus : styles.stageStatusMuted
            }
          >
            {status}
          </span>
          {route ? (
            <>
              <span
                className={saved ? styles.stageStatus : styles.stageStatusMuted}
              >
                {saved ? "Saved" : "Unsaved changes"}
              </span>
              <span
                className={
                  active ? styles.stageStatus : styles.stageStatusMuted
                }
              >
                {active ? "Active for new plans" : "Not active"}
              </span>
            </>
          ) : null}
        </div>
      </div>
      {route ? (
        <div className={styles.stageRoute}>
          {onRouteChange ? (
            <label className={styles.stageField}>
              <span className={styles.stageLabel}>Provider</span>
              <select
                aria-label={`${title} provider`}
                value={route.provider_id}
                onChange={(event) => {
                  const next = providers.find(
                    (entry) => entry.provider_id === event.target.value,
                  );
                  if (next)
                    onRouteChange({
                      provider_id: next.provider_id,
                      model_id: next.model_id,
                    });
                }}
              >
                {providerOptions.map((entry) => (
                  <option value={entry.provider_id} key={entry.provider_id}>
                    {providerFor(catalog, entry.provider_id)?.display_name ??
                      entry.provider_id}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <div>
              <span className={styles.stageLabel}>Provider</span>
              <strong>
                {catalogProvider?.display_name ?? route.provider_id}
              </strong>
            </div>
          )}
          {onRouteChange ? (
            <label className={styles.stageField}>
              <span className={styles.stageLabel}>Model</span>
              <select
                aria-label={`${title} model`}
                value={route.model_id}
                onChange={(event) =>
                  onRouteChange({ model_id: event.target.value })
                }
              >
                {modelOptions.map((entry) => (
                  <option value={entry.model_id} key={entry.model_id}>
                    {entry.model_id}
                  </option>
                ))}
                {!modelOptions.some(
                  (entry) => entry.model_id === route.model_id,
                ) && route.model_id ? (
                  <option value={route.model_id}>{route.model_id}</option>
                ) : null}
              </select>
            </label>
          ) : (
            <div>
              <span className={styles.stageLabel}>Model</span>
              <strong>{route.model_id || "Model not selected"}</strong>
            </div>
          )}
          <div>
            <span className={styles.stageLabel}>Task</span>
            <strong>{task}</strong>
          </div>
        </div>
      ) : (
        <p className={styles.stageEmpty}>
          No saved {task} route yet. Add or edit one in Advanced provider
          routing below.
        </p>
      )}
      <p className={styles.stageData}>
        <strong>Data sent:</strong> {dataPath}
        {catalogProvider ? (
          <>
            {" "}
            Destination: {catalogProvider.display_name} via{" "}
            {catalogProvider.protocol} ({catalogProvider.deployment}).
          </>
        ) : null}
      </p>
      {note ? <small className={styles.stageNote}>{note}</small> : null}
      {route && model?.readiness ? (
        <small className={styles.stageNote}>
          Catalog readiness: {model.readiness}
        </small>
      ) : null}
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
  const [activationState, setActivationState] = useState<
    "idle" | "activating" | "activated" | "error"
  >("idle");
  const [activationTarget, setActivationTarget] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const requestRef = useRef<AbortController | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [activationRevision, setActivationRevision] = useState<number | null>(
    null,
  );
  const [importText, setImportText] = useState("");
  const [importedProfile, setImportedProfile] =
    useState<ImportedProfile | null>(null);
  const [importError, setImportError] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const importSequence = useRef(0);

  async function validateImportedText(text: string) {
    const sequence = ++importSequence.current;
    setImportBusy(true);
    setImportError("");
    setImportedProfile(null);
    try {
      const configuration = parseImportedConfiguration(text);
      const digest = await configurationDigest(configuration);
      if (sequence !== importSequence.current) return;
      setImportedProfile({ configuration, digest });
    } catch (error: unknown) {
      if (sequence !== importSequence.current) return;
      setImportError(
        error instanceof Error
          ? error.message
          : "The provider profile could not be validated.",
      );
    } finally {
      if (sequence === importSequence.current) setImportBusy(false);
    }
  }

  async function readImportedFile(file: File | undefined) {
    if (!file) return;
    const sequence = ++importSequence.current;
    setImportBusy(true);
    setImportError("");
    setImportedProfile(null);
    if (file.size > MAX_IMPORT_BYTES) {
      setImportBusy(false);
      setImportError(
        "Configuration JSON is larger than the 512 KB import limit.",
      );
      return;
    }
    try {
      const text = await file.text();
      if (sequence !== importSequence.current) return;
      setImportText(text);
      await validateImportedText(text);
    } catch {
      if (sequence !== importSequence.current) return;
      setImportBusy(false);
      setImportedProfile(null);
      setImportError("The selected profile file could not be read.");
    }
  }

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
        setActivationRevision(preferredActivationRevision(payload.current));
        setSaveState("idle");
        setActivationState("idle");
        setActivationTarget(null);
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
  const activationOptions = current?.activation_options ?? [];
  const draftMatchesSaved =
    current !== null &&
    canonicalJson(draft.providers) ===
      canonicalJson(current.configuration.providers) &&
    canonicalJson(draft.routes) === canonicalJson(current.configuration.routes);
  const currentRevisionIsActive = Boolean(
    current?.activation && current.activation.revision === current.revision,
  );

  function updateRoute(task: RouteConfig["task"], patch: Partial<RouteConfig>) {
    setDraft((previous) => ({
      ...previous,
      routes: previous.routes.map((entry) =>
        entry.task === task ? { ...entry, ...patch } : entry,
      ),
    }));
    setSaveState("idle");
    setMessage("");
  }

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

  async function submitConfiguration(
    configuration: RegistryConfiguration,
    successMessage: string,
    importedDigest?: string,
  ) {
    if (state.status !== "ready" || saveState === "saving") return;
    const expectedRevision = state.current?.revision ?? 0;
    setSaveState("saving");
    setMessage("");
    try {
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
      setActivationRevision(preferredActivationRevision(saved));
      setDraft(draftFromConfiguration(saved.configuration));
      setSaveState("saved");
      setActivationState("idle");
      if (importedDigest) {
        setImportedProfile((previous) =>
          previous?.digest === importedDigest
            ? { ...previous, savedRevision: saved.revision }
            : previous,
        );
      }
      setMessage(successMessage);
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

  async function save() {
    if (state.status !== "ready" || saveState === "saving") return;
    const validationError = validateDraft();
    if (validationError) {
      setMessage(validationError);
      setSaveState("idle");
      return;
    }
    let configuration: RegistryConfiguration;
    try {
      configuration = await prepareConfiguration(
        draft,
        state.current?.configuration ?? state.payload.configuration_template,
        catalog,
        state.current?.revision ?? 0,
      );
    } catch {
      setSaveState("idle");
      setMessage(
        "The configuration could not be prepared. Review the fields and try again.",
      );
      return;
    }
    await submitConfiguration(
      configuration,
      "Saved as a new immutable revision. Activate an approved revision for new plans.",
    );
  }

  async function saveImportedProfile() {
    if (!importedProfile || state.status !== "ready") return;
    await submitConfiguration(
      importedProfile.configuration,
      "Imported revision saved. Activate it separately only when the server lists it as approved.",
      importedProfile.digest,
    );
  }

  async function activateRevision(targetRevision: number) {
    if (
      state.status !== "ready" ||
      !current ||
      activationState === "activating"
    )
      return;
    const options = current.activation_options;
    const target = options.find((item) => item.revision === targetRevision);
    if (!target) {
      setActivationState("error");
      setActivationTarget(targetRevision);
      setMessage(
        "This revision is not in the pinned approval. Save an approved provider/model route before activating.",
      );
      return;
    }
    setActivationRevision(targetRevision);
    setActivationTarget(targetRevision);
    setActivationState("activating");
    setSaveState("idle");
    setMessage("");
    try {
      const value = await requestJson(
        "/v1/admin/conversation/providers/activate",
        {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "idempotency-key": newIdempotencyKey(),
          },
          body: JSON.stringify({
            expected_revision: current.revision,
            target_revision: target.revision,
          }),
        },
      );
      const activated = saveResponseSchema.parse(value);
      setState((previous) =>
        previous.status === "ready"
          ? { ...previous, current: activated }
          : previous,
      );
      setActivationState("activated");
      setSaveState("saved");
      setMessage(
        `Revision #${target.revision} is active for new plans. Existing plans keep their saved provider route.`,
      );
    } catch (error: unknown) {
      setActivationState("error");
      if (error instanceof Error && error.message === "http_409") {
        setSaveState("conflict");
        setMessage(
          "Provider settings changed. Reload the current revision before switching presets.",
        );
      } else {
        setSaveState("idle");
        setMessage(
          "This revision could not be activated. The server kept the prior selection.",
        );
      }
    }
  }

  async function activate() {
    if (activationRevision === null) {
      setActivationState("error");
      setMessage("Choose an approved provider preset before activating.");
      return;
    }
    await activateRevision(activationRevision);
  }

  function retry() {
    setState((previous) => ({ status: "loading", retry: previous.retry }));
    setActivationState("idle");
    setActivationTarget(null);
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
          <h2>Provider settings and next-plan activation.</h2>
          <p>
            {state.payload.message} Choose providers and map analysis tasks
            here, then activate only a server-approved saved revision for new
            plans. This page never accepts credentials or starts a provider
            call.
          </p>
        </div>
        <span className={styles.noticeCode}>NO PROVIDER CALLS</span>
      </div>

      <div className={styles.summaryGrid} aria-label="Provider control status">
        <div className={styles.summaryCard}>
          <span>Approved cap</span>
          <strong>
            {state.payload.approved_budget_cap_paise == null
              ? "Unavailable"
              : `₹${(state.payload.approved_budget_cap_paise / 100).toFixed(2)}`}
          </strong>
          <small>release-approved ceiling, not current spend</small>
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

      <section
        className={styles.workflowSection}
        aria-labelledby="workflow-title"
      >
        <div className={styles.sectionHeader}>
          <div>
            <span className={styles.eyebrow}>Release path</span>
            <h2 id="workflow-title">What each approved route does</h2>
            <p>
              Review the real provider and model used by each stage. These cards
              describe the data path; they do not start a provider call.
            </p>
            <p className={styles.revisionState}>
              <strong>Saved:</strong>{" "}
              {current ? `revision #${current.revision}` : "none"}
              {" · "}
              <strong>Active for new plans:</strong>{" "}
              {current?.activation
                ? `revision #${current.activation.revision}`
                : "none"}
            </p>
          </div>
          <button
            className="button button-primary"
            type="button"
            onClick={() => void save()}
            disabled={saveState === "saving" || draftMatchesSaved}
          >
            {saveState === "saving" ? (
              "Saving…"
            ) : (
              <>
                <Save size={15} aria-hidden="true" /> Save settings
              </>
            )}
          </button>
        </div>
        <div className={styles.stageGrid}>
          <StageSummary
            eyebrow="01 · Transcription"
            title="Transcription"
            task="asr"
            route={draft.routes.find((route) => route.task === "asr")}
            providers={draft.providers}
            catalog={catalog}
            dataPath="The uploaded recording is sent for speech-to-text transcription."
            saved={draftMatchesSaved}
            active={currentRevisionIsActive}
            onRouteChange={(patch) => updateRoute("asr", patch)}
          />
          <StageSummary
            eyebrow="02 · Analysis"
            title="Analysis"
            task="facts"
            route={draft.routes.find((route) => route.task === "facts")}
            providers={draft.providers}
            catalog={catalog}
            dataPath="The saved transcript is sent for structured facts and checkpoints."
            saved={draftMatchesSaved}
            active={currentRevisionIsActive}
            onRouteChange={(patch) => updateRoute("facts", patch)}
          />
          <StageSummary
            eyebrow="03 · Report style"
            title="Report style"
            task="coaching"
            route={draft.routes.find((route) => route.task === "coaching")}
            providers={draft.providers}
            catalog={catalog}
            dataPath="Source-bound transcript facts and checkpoints are sent for coaching/report drafting."
            note="Report profile and detail length are controlled in Analysis settings above."
            saved={draftMatchesSaved}
            active={currentRevisionIsActive}
            onRouteChange={(patch) => updateRoute("coaching", patch)}
          />
        </div>
      </section>

      <details className={styles.advancedPanel}>
        <summary>Advanced: import a reviewed provider JSON profile</summary>
        <section
          className={styles.section}
          aria-labelledby="approved-profile-import-title"
        >
          <div className={styles.sectionHeader}>
            <div>
              <span className={styles.eyebrow}>Approved profile import</span>
              <h2 id="approved-profile-import-title">
                Load a reviewed provider configuration.
              </h2>
              <p>
                Paste or choose the non-secret JSON prepared for this AC
                release. It is validated locally, then saved through the same
                revision and approval checks as the settings editor. Credentials
                stay in the server environment.
              </p>
            </div>
            <ShieldCheck size={20} aria-hidden="true" />
          </div>
          <label className={styles.field}>
            <span className={styles.fieldLabel}>
              Reviewed provider configuration JSON
            </span>
            <textarea
              aria-label="Reviewed provider configuration JSON"
              value={importText}
              onChange={(event) => {
                importSequence.current += 1;
                setImportText(event.target.value);
                setImportedProfile(null);
                setImportBusy(false);
                setImportError("");
              }}
              placeholder='{"schema":"ac.sales_xray.provider_registry_config/1", ...}'
              spellCheck={false}
              rows={8}
            />
            <small>
              JSON only, up to 512 KB. Use opaque ref:... values; never paste
              credentials, passwords, tokens, or credential contents.
            </small>
          </label>
          <div className={styles.buttonRow}>
            <button
              className="button button-primary"
              type="button"
              onClick={() => void validateImportedText(importText)}
              disabled={importBusy || !importText.trim()}
            >
              {importBusy ? "Checking…" : "Check profile"}
            </button>
            <label className="button button-secondary">
              Choose JSON file
              <input
                className={styles.srOnly}
                type="file"
                accept="application/json,.json"
                aria-label="Choose reviewed provider configuration JSON file"
                onChange={(event) =>
                  void readImportedFile(event.target.files?.[0])
                }
              />
            </label>
          </div>
          {importError ? (
            <div className={styles.error} role="alert">
              <p>{importError}</p>
            </div>
          ) : null}
          {importedProfile ? (
            <div className={styles.card} role="status">
              <div className={styles.cardHeader}>
                <div>
                  <span className={styles.eyebrow}>
                    Local contract check passed
                  </span>
                  <h3>{importedProfile.configuration.revision}</h3>
                </div>
                <span className={styles.status}>
                  {importedProfile.savedRevision
                    ? `saved revision #${importedProfile.savedRevision}`
                    : "ready to save"}
                </span>
              </div>
              <p>
                Digest <code>{importedProfile.digest}</code>. The server still
                decides whether this exact revision is approved for activation.
              </p>
              <div className={styles.providerList}>
                {importedProfile.configuration.providers.map((provider) => (
                  <div
                    className={styles.routeMeta}
                    key={`${provider.provider_id}::${provider.model_id}`}
                  >
                    <strong>
                      {provider.provider_id}/{provider.model_id}
                    </strong>
                    <span>
                      {provider.max_cost_paise == null
                        ? "cost ceiling unavailable"
                        : `₹${(provider.max_cost_paise / 100).toFixed(2)} per dispatch ceiling`}
                    </span>
                  </div>
                ))}
              </div>
              <div className={styles.routeMeta}>
                <span>
                  Routes:{" "}
                  {importedProfile.configuration.routes
                    .map(
                      (route) =>
                        `${route.task} → ${route.provider_id}/${route.model_id}`,
                    )
                    .join(" · ") || "none"}
                </span>
              </div>
              <div className={styles.buttonRow}>
                <button
                  className="button button-primary"
                  type="button"
                  onClick={() => void saveImportedProfile()}
                  disabled={
                    saveState === "saving" ||
                    saveState === "conflict" ||
                    Boolean(importedProfile.savedRevision)
                  }
                >
                  {saveState === "saving"
                    ? "Saving…"
                    : "Save imported revision"}
                </button>
                <small>
                  Uses current revision {current?.revision ?? 0}; a stale
                  revision is rejected and must be reloaded.
                </small>
              </div>
            </div>
          ) : null}
        </section>
      </details>

      {message ? (
        <div
          className={
            saveState === "saved" || activationState === "activated"
              ? styles.success
              : saveState === "conflict" || activationState === "error"
                ? styles.error
                : styles.notice
          }
          role={
            saveState === "conflict" || activationState === "error"
              ? "alert"
              : "status"
          }
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
        className={styles.workflowSection}
        aria-labelledby="provider-activation-title"
      >
        <div className={styles.sectionHeader}>
          <div>
            <span className={styles.eyebrow}>04 · Spending</span>
            <h2 id="provider-activation-title">Spending and future plans.</h2>
            <p>
              The approved ceiling is enforced by the server. Select a saved
              revision only when it is already covered by release approval;
              existing plans keep their saved provider route.
            </p>
          </div>
          <ShieldCheck size={20} aria-hidden="true" />
        </div>
        {activationOptions.length === 0 ? (
          <div className={styles.empty}>
            <p>
              No saved revision is currently eligible. A catalog entry alone
              cannot be activated until its adapter, credentials, privacy,
              pricing and release approval all match.
            </p>
          </div>
        ) : (
          <>
            <div
              className={styles.presetGrid}
              aria-label="Approved provider presets"
            >
              {activationOptions.map((option) => {
                const active =
                  current?.activation?.revision === option.revision;
                const busy =
                  activationState === "activating" &&
                  activationTarget === option.revision;
                return (
                  <article
                    className={styles.presetCard}
                    key={option.id}
                    aria-label={activationOptionLabel(option)}
                  >
                    <div className={styles.presetHeader}>
                      <div>
                        <span className={styles.eyebrow}>Approved preset</span>
                        <h3>{activationOptionLabel(option)}</h3>
                      </div>
                      <span
                        className={
                          active ? styles.stageStatus : styles.stageStatusMuted
                        }
                      >
                        {active ? "Active" : "Approved"}
                      </span>
                    </div>
                    <p className={styles.presetRoutes}>
                      {activationOptionRoutes(option)}
                    </p>
                    <div className={styles.presetFooter}>
                      <small>Saved revision #{option.revision}</small>
                      <button
                        className="button button-secondary"
                        type="button"
                        aria-label={`Switch to ${activationOptionLabel(option)} revision #${option.revision}`}
                        onClick={() => void activateRevision(option.revision)}
                        disabled={active || activationState === "activating"}
                      >
                        {busy
                          ? "Switching…"
                          : active
                            ? "Active for new plans"
                            : "Use this preset"}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
            <div className={styles.fieldRow}>
              <label className={styles.field}>
                <span className={styles.fieldLabel}>Approved revision</span>
                <select
                  aria-label="Approved provider revision"
                  value={activationRevision ?? activationOptions[0]?.revision}
                  onChange={(event) =>
                    setActivationRevision(Number(event.target.value))
                  }
                >
                  {activationOptions.map((option) => (
                    <option value={option.revision} key={option.revision}>
                      Revision #{option.revision} ·{" "}
                      {option.routes
                        .map((route) => `${route.provider}/${route.model}`)
                        .join(" · ")}
                    </option>
                  ))}
                </select>
                <small>
                  Active now:{" "}
                  {current?.activation
                    ? `revision #${current.activation.revision}`
                    : "the saved default"}
                </small>
              </label>
              <div className={styles.buttonRow}>
                <button
                  className="button button-primary"
                  type="button"
                  onClick={() => void activate()}
                  disabled={activationState === "activating"}
                >
                  <ShieldCheck size={15} aria-hidden="true" />
                  {activationState === "activating"
                    ? "Activating…"
                    : "Activate for new plans"}
                </button>
              </div>
            </div>
          </>
        )}
      </section>

      <details className={styles.advancedPanel}>
        <summary>Advanced: provider bindings and technical references</summary>
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
                      providers: previous.providers.map(
                        (entry, currentIndex) =>
                          currentIndex === index
                            ? { ...entry, ...patch }
                            : entry,
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
                Recipe, profile, and prompt values are revision identifiers for
                a future approved run. They select configuration; they do not
                train a model or start analysis.
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
                Status describes catalog metadata; it does not mean this page
                can call a provider.
              </p>
            </div>
            <span className={styles.dormant}>catalog metadata only</span>
          </div>
          <div className={styles.catalogList}>
            {catalog.map((provider) => (
              <article
                className={styles.catalogItem}
                key={provider.provider_id}
              >
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
      </details>

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
        <ExecutionControlsPanel />
        <AnalysisSettingsPanel />
        <ProviderControlsPanel />
      </div>
    </AdminShell>
  );
}
