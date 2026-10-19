/**
 * Settings → Integrations (/v1/sales-xray/integrations): API keys and the
 * organisation's webhook. Owner order 19 Oct: connecting an app must be as
 * simple as with top SaaS apps, with no ops step per customer. Owners and
 * admins only; a key or signing secret is shown once and never again.
 */

export const API = "/v1/sales-xray/integrations";

export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  state: "active" | "expired" | "revoked";
  createdAt: string;
  expiresAt: string | null;
  lastUsedAt: string | null;
  revokedAt: string | null;
};

export type Webhook = {
  id: string;
  url: string;
  host: string;
  events: string[];
  factsProfile: string | null;
  managedInApp: boolean;
  secretHint: string | null;
  rotating: boolean;
  nextSecretHint: string | null;
  createdAt: string;
};

export type Delivery = {
  id: string;
  eventType: string;
  status: string;
  attempts: number;
  lastHttpStatus: number | null;
  lastErrorCode: string | null;
  createdAt: string;
  deliveredAt: string | null;
};

export type OAuthApp = {
  id: string;
  clientId: string;
  name: string;
  redirectUris: string[];
  confidential: boolean;
  createdAt: string;
  revokedAt: string | null;
};

export type Connection = {
  id: string;
  app: string;
  clientId: string;
  scopes: string[];
  createdAt: string;
  lastUsedAt: string | null;
  revokedAt: string | null;
};

export type Integrations = {
  apiBase: string | null;
  keyMode: "live" | "test";
  scopes: { key: string; label: string }[];
  expiryDays: number[];
  keys: ApiKey[];
  webhooksReady: boolean;
  events: { key: string; label: string }[];
  factsProfiles: string[];
  webhook: Webhook | null;
  apps: OAuthApp[];
  connections: Connection[];
};

export type TestResult = {
  delivered: boolean;
  httpStatus: number | null;
  errorCode: string | null;
  durationMs: number;
};

export class IntegrationsError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "IntegrationsError";
  }
}

const FALLBACK: Record<number, string> = {
  401: "Sign in to see this.",
  403: "Only an owner or admin of an organisation can manage integrations.",
  404: "This is not here any more.",
  409: "This changed. Refresh and try again.",
  422: "Check the details and try again.",
  503: "This is not switched on here yet.",
};

const obj = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const text = (value: unknown, fallback = "") =>
  typeof value === "string" ? value : fallback;
const maybe = (value: unknown) => (typeof value === "string" ? value : null);
const num = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const list = (value: unknown) => (Array.isArray(value) ? value : []);
const strings = (value: unknown) =>
  list(value).filter((item): item is string => typeof item === "string");

export function normalizeKey(raw: unknown): ApiKey {
  const key = obj(raw);
  const state = text(key.state);
  return {
    id: text(key.id),
    name: text(key.name),
    prefix: text(key.prefix),
    scopes: strings(key.scopes),
    state: state === "revoked" || state === "expired" ? state : "active",
    createdAt: text(key.created_at),
    expiresAt: maybe(key.expires_at),
    lastUsedAt: maybe(key.last_used_at),
    revokedAt: maybe(key.revoked_at),
  };
}

export function normalizeWebhook(raw: unknown): Webhook | null {
  if (!raw || typeof raw !== "object") return null;
  const hook = obj(raw);
  return {
    id: text(hook.id),
    url: text(hook.url),
    host: text(hook.host),
    events: strings(hook.events),
    factsProfile: maybe(hook.facts_profile),
    managedInApp: hook.managed_in_app === true,
    secretHint: maybe(hook.secret_hint),
    rotating: hook.rotating === true,
    nextSecretHint: maybe(hook.next_secret_hint),
    createdAt: text(hook.created_at),
  };
}

export function normalizeApp(raw: unknown): OAuthApp {
  const app = obj(raw);
  return {
    id: text(app.id),
    clientId: text(app.client_id),
    name: text(app.name),
    redirectUris: strings(app.redirect_uris),
    confidential: app.confidential === true,
    createdAt: text(app.created_at),
    revokedAt: maybe(app.revoked_at),
  };
}

export function normalizeConnection(raw: unknown): Connection {
  const item = obj(raw);
  return {
    id: text(item.id),
    app: text(item.app),
    clientId: text(item.client_id),
    scopes: strings(item.scopes),
    createdAt: text(item.created_at),
    lastUsedAt: maybe(item.last_used_at),
    revokedAt: maybe(item.revoked_at),
  };
}

export function normalizeIntegrations(raw: unknown): Integrations {
  const body = obj(raw);
  const menu = obj(body.webhook_menu);
  const pairs = (value: unknown) =>
    list(value).map((item) => {
      const pair = obj(item);
      return { key: text(pair.key), label: text(pair.label, text(pair.key)) };
    });
  return {
    apiBase: maybe(body.api_base),
    keyMode: body.key_mode === "live" ? "live" : "test",
    scopes: pairs(body.scopes),
    expiryDays: list(body.expiry_days).flatMap((day) =>
      typeof day === "number" ? [day] : [],
    ),
    keys: list(body.keys).map(normalizeKey),
    webhooksReady: body.webhooks_ready === true,
    events: pairs(menu.events),
    factsProfiles: strings(menu.facts_profiles),
    webhook: normalizeWebhook(body.webhook),
    apps: list(body.apps).map(normalizeApp),
    connections: list(body.connections).map(normalizeConnection),
  };
}

export function normalizeDelivery(raw: unknown): Delivery {
  const item = obj(raw);
  return {
    id: text(item.id),
    eventType: text(item.event_type),
    status: text(item.status),
    attempts: num(item.attempts) ?? 0,
    lastHttpStatus: num(item.last_http_status),
    lastErrorCode: maybe(item.last_error_code),
    createdAt: text(item.created_at),
    deliveredAt: maybe(item.delivered_at),
  };
}

async function request(path: string, init: RequestInit = {}): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      ...init,
      headers: {
        accept: "application/json",
        ...(init.body ? { "content-type": "application/json" } : {}),
        ...(init.headers ?? {}),
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new IntegrationsError("Sales Xray isn't answering. Try again.", 0);
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* no body */
    }
    throw new IntegrationsError(
      detail ?? FALLBACK[response.status] ?? "Something went wrong. Try again.",
      response.status,
    );
  }
  return response.json();
}

export async function readIntegrations(signal?: AbortSignal) {
  return normalizeIntegrations(await request("", { signal }));
}

export async function createKey(input: {
  name: string;
  scopes: string[];
  expiresDays: number | null;
}): Promise<{ key: ApiKey; secret: string }> {
  const body = obj(
    await request("/keys", {
      method: "POST",
      body: JSON.stringify({
        name: input.name,
        scopes: input.scopes,
        expires_days: input.expiresDays,
      }),
    }),
  );
  return { key: normalizeKey(body), secret: text(body.key) };
}

export async function revokeKey(id: string) {
  return normalizeKey(
    await request(`/keys/${encodeURIComponent(id)}/revoke`, { method: "POST" }),
  );
}

export async function saveWebhook(input: {
  url: string;
  events: string[];
  factsProfile: string | null;
}): Promise<{ webhook: Webhook | null; secret: string | null }> {
  const body = obj(
    await request("/webhook", {
      method: "PUT",
      body: JSON.stringify({
        url: input.url,
        events: input.events,
        facts_profile: input.factsProfile,
      }),
    }),
  );
  return {
    webhook: normalizeWebhook(body.webhook),
    secret: maybe(body.secret),
  };
}

export async function rotateSecret() {
  const body = obj(await request("/webhook/rotate", { method: "POST" }));
  return { webhook: normalizeWebhook(body.webhook), secret: text(body.secret) };
}

export async function finishRotation() {
  const body = obj(await request("/webhook/rotate/finish", { method: "POST" }));
  return normalizeWebhook(body.webhook);
}

export async function sendTest(): Promise<TestResult> {
  const body = obj(await request("/webhook/test", { method: "POST" }));
  return {
    delivered: body.delivered === true,
    httpStatus: num(body.http_status),
    errorCode: maybe(body.error_code),
    durationMs: num(body.duration_ms) ?? 0,
  };
}

export async function disableWebhook() {
  await request("/webhook/disable", { method: "POST" });
}

export async function readDeliveries(signal?: AbortSignal) {
  const body = obj(await request("/webhook/deliveries", { signal }));
  return list(body.deliveries).map(normalizeDelivery);
}

export async function retryDelivery(id: string) {
  const body = obj(
    await request(`/webhook/deliveries/${encodeURIComponent(id)}/retry`, {
      method: "POST",
    }),
  );
  return list(body.deliveries).map(normalizeDelivery);
}

export async function registerApp(input: {
  name: string;
  redirectUris: string[];
  confidential: boolean;
}): Promise<{ app: OAuthApp; secret: string | null }> {
  const body = obj(
    await request("/apps", {
      method: "POST",
      body: JSON.stringify({
        name: input.name,
        redirect_uris: input.redirectUris,
        confidential: input.confidential,
      }),
    }),
  );
  return { app: normalizeApp(body), secret: maybe(body.client_secret) };
}

export async function removeApp(id: string) {
  const body = obj(
    await request(`/apps/${encodeURIComponent(id)}/revoke`, { method: "POST" }),
  );
  return list(body.apps).map(normalizeApp);
}

export async function disconnect(id: string) {
  const body = obj(
    await request(`/connections/${encodeURIComponent(id)}/revoke`, {
      method: "POST",
    }),
  );
  return list(body.connections).map(normalizeConnection);
}

/** "Delivered · 204 · 312 ms" or why it was not. */
export function testWords(result: TestResult): string {
  if (result.delivered)
    return `Delivered · ${result.httpStatus} · ${result.durationMs} ms`;
  if (result.httpStatus !== null)
    return `Your app answered ${result.httpStatus}. Check its address and that it accepts the signature.`;
  const reasons: Record<string, string> = {
    url_refused:
      "The address must be https:// and reachable from the internet.",
    address_refused: "The address points to a private network.",
    timeout: "Your app did not answer within 10 seconds.",
    connect_error: "Your app could not be reached. Check the address.",
  };
  return (
    (result.errorCode && reasons[result.errorCode]) ??
    "Your app could not be reached. Check the address."
  );
}

export const DELIVERY_LABEL: Record<string, string> = {
  delivered: "Delivered",
  pending: "Retrying",
  dead_letter: "Stopped",
  rejected: "Rejected",
  dropped: "Not sent",
};
