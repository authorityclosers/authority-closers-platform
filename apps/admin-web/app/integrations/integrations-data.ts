/**
 * Every organisation's integrations (GET /v1/admin/integrations, schema
 * sx-integrations-admin/2): API keys by prefix, webhooks by scheme and host,
 * and apps connected through OAuth. Never a full key or secret. Pure.
 */
import { read } from "../lib/read";
import { asKind, type WorkspaceKind } from "../lib/workspaces";

export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  state: "active" | "expired" | "revoked";
  createdAt: string | null;
  createdBy: string | null;
  expiresAt: string | null;
  lastUsedAt: string | null;
  revokedAt: string | null;
  revokedBy: string | null;
  unused30d: boolean;
};

export type Webhook = {
  id: string;
  host: string;
  events: string[];
  status: "active" | "disabled";
  managedInApp: boolean;
  createdAt: string | null;
  disabledAt: string | null;
  lastDeliveryAt: string | null;
  lastStatus: string | null;
  failures24h: number;
};

export type Connection = {
  id: string;
  app: string;
  scopes: string[];
  createdAt: string | null;
  lastUsedAt: string | null;
  revokedAt: string | null;
};

export type IntegrationOrganisation = {
  id: string;
  name: string;
  kind: WorkspaceKind;
  keys: ApiKey[];
  webhooks: Webhook[];
  connections: Connection[];
};

export type Integrations = {
  environment: string | null;
  counts: {
    activeKeys: number;
    keysUnused30d: number;
    activeWebhooks: number;
    webhooksFailing: number;
    connectedApps: number;
  };
  organisations: IntegrationOrganisation[];
};

const strings = (raw: unknown) =>
  read.array(raw).filter((item): item is string => typeof item === "string");

const label = (raw: unknown) => {
  const person = read.object(raw);
  return read.optionalString(person.label);
};

/** A key row, as the read and the revoke answer both return it. */
export function normalizeKey(raw: unknown): ApiKey {
  const row = read.object(raw);
  const state = read.string(row.state, "active");
  return {
    id: read.string(row.id),
    name: read.string(row.name, "Unnamed key"),
    prefix: read.string(row.prefix),
    scopes: strings(row.scopes),
    state: state === "revoked" || state === "expired" ? state : "active",
    createdAt: read.optionalString(row.created_at),
    createdBy: label(row.created_by),
    expiresAt: read.optionalString(row.expires_at),
    lastUsedAt: read.optionalString(row.last_used_at),
    revokedAt: read.optionalString(row.revoked_at),
    revokedBy: label(row.revoked_by),
    unused30d: read.boolean(row.unused_30d),
  };
}

/** A webhook row, as the read and the disable answer both return it. */
export function normalizeWebhook(raw: unknown): Webhook {
  const row = read.object(raw);
  const last = row.last_status;
  return {
    id: read.string(row.id),
    host: read.string(row.host, "Not recorded"),
    events: strings(row.events),
    status: read.string(row.status) === "active" ? "active" : "disabled",
    managedInApp: read.boolean(row.managed_in_app),
    createdAt: read.optionalString(row.created_at),
    disabledAt: read.optionalString(row.disabled_at),
    lastDeliveryAt: read.optionalString(row.last_delivery_at),
    lastStatus:
      typeof last === "number" ? String(last) : read.optionalString(last),
    failures24h: read.number(row.failures_24h),
  };
}

export function normalizeIntegrations(raw: unknown): Integrations {
  const body = read.object(raw);
  const counts = read.object(body.counts);
  return {
    environment: read.optionalString(body.environment),
    counts: {
      activeKeys: read.number(counts.active_keys),
      keysUnused30d: read.number(counts.keys_unused_30d),
      activeWebhooks: read.number(counts.active_webhooks),
      webhooksFailing: read.number(counts.webhooks_failing),
      connectedApps: read.number(counts.connected_apps),
    },
    organisations: read.array(body.organisations).map((item) => {
      const row = read.object(item);
      return {
        id: read.string(row.id),
        name: read.string(row.name, "Unnamed organisation"),
        kind: asKind(row.kind),
        keys: read.array(row.keys).map(normalizeKey),
        webhooks: read.array(row.webhooks).map(normalizeWebhook),
        connections: read.array(row.connections).map((entry) => {
          const connection = read.object(entry);
          return {
            id: read.string(connection.id),
            app: read.string(connection.app, "Unnamed app"),
            scopes: strings(connection.scopes),
            createdAt: read.optionalString(connection.created_at),
            lastUsedAt: read.optionalString(connection.last_used_at),
            revokedAt: read.optionalString(connection.revoked_at),
          };
        }),
      };
    }),
  };
}

/** What needs a look: failing webhooks first, then active keys unused for 30 days. */
export function attention(organisation: IntegrationOrganisation): string[] {
  const failing = organisation.webhooks.filter(
    (hook) => hook.status === "active" && hook.failures24h > 0,
  ).length;
  const unused = organisation.keys.filter(
    (key) => key.state === "active" && key.unused30d,
  ).length;
  return [
    failing ? `${failing} webhook${failing === 1 ? "" : "s"} failing` : null,
    unused ? `${unused} key${unused === 1 ? "" : "s"} unused 30 days` : null,
  ].filter((item): item is string => item !== null);
}

/** Organisations needing a look first, then by name (the API's order). */
export function ordered(
  organisations: IntegrationOrganisation[],
): IntegrationOrganisation[] {
  return organisations
    .map((organisation, index) => ({ organisation, index }))
    .sort(
      (a, b) =>
        Number(attention(b.organisation).length > 0) -
          Number(attention(a.organisation).length > 0) || a.index - b.index,
    )
    .map((item) => item.organisation);
}
