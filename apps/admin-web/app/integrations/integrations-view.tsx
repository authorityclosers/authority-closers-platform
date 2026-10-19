/**
 * Admin -> Integrations: every organisation's API keys, webhooks and
 * connected apps, needing-a-look first. Organisations set these up
 * themselves in Sales Xray (Settings -> Integrations); staff see them here
 * and can stop a key or a webhook at once. Keys show by prefix and webhooks
 * by host: no key or secret ever reaches this page.
 */
import { Plug } from "lucide-react";

import { when } from "../calls/call-data";
import { KIND_BADGE, KIND_TONE } from "../lib/workspaces";
import { Badge, Card, Empty, Kpi, Panel, Table, Tiles } from "../ui/kit";
import { IntegrationAction } from "./integration-action";
import {
  attention,
  ordered,
  type ApiKey,
  type Integrations,
  type Webhook,
} from "./integrations-data";
import styles from "./integrations.module.css";

const KEY_STATE: Record<
  ApiKey["state"],
  { label: string; tone: "good" | "neutral" | "bad" }
> = {
  active: { label: "Active", tone: "good" },
  expired: { label: "Expired", tone: "neutral" },
  revoked: { label: "Revoked", tone: "bad" },
};

const ago = (value: string | null, never = "Never") =>
  value ? when(value) : never;

function Scopes({ items }: { items: string[] }) {
  return items.length ? (
    <span className={styles.scopes}>
      {items.map((item) => (
        <code key={item}>{item}</code>
      ))}
    </span>
  ) : (
    <span className={styles.muted}>None</span>
  );
}

function keyUse(key: ApiKey): string {
  if (key.state === "revoked")
    return `Revoked ${ago(key.revokedAt, "")}${key.revokedBy ? ` by ${key.revokedBy}` : ""}`;
  if (key.state === "expired") return `Expired ${ago(key.expiresAt, "")}`;
  return `Last used ${ago(key.lastUsedAt)}`;
}

function delivery(hook: Webhook): string {
  if (hook.status === "disabled")
    return `Turned off ${ago(hook.disabledAt, "")}`;
  if (!hook.lastDeliveryAt) return "No deliveries yet";
  return `Last sent ${when(hook.lastDeliveryAt)}${hook.lastStatus ? ` · ${hook.lastStatus}` : ""}`;
}

function KeysTable({ keys }: { keys: ApiKey[] }) {
  return (
    <Table
      label="API keys"
      cards={keys.map((key) => (
        <Card key={key.id}>
          <strong>
            {key.name} <code className={styles.code}>{key.prefix}…</code>
          </strong>
          <span>
            <Badge tone={KEY_STATE[key.state].tone}>
              {KEY_STATE[key.state].label}
            </Badge>{" "}
            {key.unused30d && key.state === "active" ? (
              <Badge tone="warn">Unused 30 days</Badge>
            ) : null}
          </span>
          <Scopes items={key.scopes} />
          <span>
            Made {ago(key.createdAt, "")}
            {key.createdBy ? ` by ${key.createdBy}` : ""} · {keyUse(key)}
          </span>
          {key.state === "active" ? (
            <span>
              <IntegrationAction kind="key" id={key.id} name={key.name} />
            </span>
          ) : null}
        </Card>
      ))}
    >
      <thead>
        <tr>
          <th scope="col">Key</th>
          <th scope="col">Can</th>
          <th scope="col">State</th>
          <th scope="col">Made</th>
          <th scope="col">Use</th>
          <th scope="col">Action</th>
        </tr>
      </thead>
      <tbody>
        {keys.map((key) => (
          <tr key={key.id}>
            <th scope="row">
              {key.name}
              <br />
              <code className={styles.code}>{key.prefix}…</code>
            </th>
            <td>
              <Scopes items={key.scopes} />
            </td>
            <td>
              <span className={styles.badges}>
                <Badge tone={KEY_STATE[key.state].tone}>
                  {KEY_STATE[key.state].label}
                </Badge>
                {key.unused30d && key.state === "active" ? (
                  <Badge tone="warn">Unused 30 days</Badge>
                ) : null}
              </span>
            </td>
            <td>
              {ago(key.createdAt, "–")}
              {key.createdBy ? (
                <small className={styles.muted}> by {key.createdBy}</small>
              ) : null}
            </td>
            <td>{keyUse(key)}</td>
            <td>
              {key.state === "active" ? (
                <IntegrationAction kind="key" id={key.id} name={key.name} />
              ) : (
                "–"
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function WebhooksTable({ webhooks }: { webhooks: Webhook[] }) {
  const tone = (hook: Webhook) =>
    hook.status === "disabled" ? "neutral" : hook.failures24h ? "bad" : "good";
  const state = (hook: Webhook) =>
    hook.status === "disabled"
      ? "Off"
      : hook.failures24h
        ? `${hook.failures24h} failed in 24 h`
        : "Delivering";
  return (
    <Table
      label="Webhooks"
      cards={webhooks.map((hook) => (
        <Card key={hook.id}>
          <strong>
            <code className={styles.code}>{hook.host}</code>
          </strong>
          <span>
            <Badge tone={tone(hook)}>{state(hook)}</Badge>
          </span>
          <Scopes items={hook.events} />
          <span>{delivery(hook)}</span>
          {hook.status === "active" ? (
            <span>
              <IntegrationAction kind="webhook" id={hook.id} name={hook.host} />
            </span>
          ) : null}
        </Card>
      ))}
    >
      <thead>
        <tr>
          <th scope="col">Sends to</th>
          <th scope="col">Events</th>
          <th scope="col">State</th>
          <th scope="col">Delivery</th>
          <th scope="col">Action</th>
        </tr>
      </thead>
      <tbody>
        {webhooks.map((hook) => (
          <tr key={hook.id}>
            <th scope="row">
              <code className={styles.code}>{hook.host}</code>
              {hook.managedInApp ? null : (
                <small className={styles.muted}> · set up by staff</small>
              )}
            </th>
            <td>
              <Scopes items={hook.events} />
            </td>
            <td>
              <Badge tone={tone(hook)}>{state(hook)}</Badge>
            </td>
            <td>{delivery(hook)}</td>
            <td>
              {hook.status === "active" ? (
                <IntegrationAction
                  kind="webhook"
                  id={hook.id}
                  name={hook.host}
                />
              ) : (
                "–"
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

export function IntegrationsView({ data }: { data: Integrations }) {
  const { counts } = data;
  return (
    <>
      <Tiles label="Integrations">
        <Kpi
          label="Active API keys"
          value={counts.activeKeys}
          note={
            counts.keysUnused30d
              ? `${counts.keysUnused30d} unused for 30 days`
              : "All in use"
          }
          tone={counts.keysUnused30d ? "warn" : undefined}
        />
        <Kpi
          label="Active webhooks"
          value={counts.activeWebhooks}
          note={
            counts.webhooksFailing
              ? `${counts.webhooksFailing} failing in the last 24 h`
              : "None failing"
          }
          tone={
            counts.webhooksFailing
              ? "bad"
              : counts.activeWebhooks
                ? "good"
                : undefined
          }
        />
        <Kpi
          label="Connected apps"
          value={counts.connectedApps}
          note="Through Connect (OAuth)"
        />
        <Kpi
          label="Organisations"
          value={data.organisations.length}
          note="With any key, webhook or app"
        />
      </Tiles>

      {data.organisations.length ? (
        ordered(data.organisations).map((organisation) => {
          const flags = attention(organisation);
          const parts = [
            `${organisation.keys.length} ${organisation.keys.length === 1 ? "key" : "keys"}`,
            `${organisation.webhooks.length} ${organisation.webhooks.length === 1 ? "webhook" : "webhooks"}`,
            `${organisation.connections.length} connected ${organisation.connections.length === 1 ? "app" : "apps"}`,
          ];
          return (
            <Panel
              key={organisation.id}
              title={organisation.name}
              sub={parts.join(" · ")}
              tools={
                <span className={styles.badges}>
                  {flags.map((flag) => (
                    <Badge key={flag} tone="warn">
                      {flag}
                    </Badge>
                  ))}
                  <Badge tone={KIND_TONE[organisation.kind]}>
                    {KIND_BADGE[organisation.kind]}
                  </Badge>
                </span>
              }
            >
              {organisation.keys.length ? (
                <section aria-label={`${organisation.name}: API keys`}>
                  <h3 className={styles.subhead}>API keys</h3>
                  <KeysTable keys={organisation.keys} />
                </section>
              ) : null}
              {organisation.webhooks.length ? (
                <section aria-label={`${organisation.name}: webhooks`}>
                  <h3 className={styles.subhead}>Webhooks</h3>
                  <WebhooksTable webhooks={organisation.webhooks} />
                </section>
              ) : null}
              {organisation.connections.length ? (
                <section aria-label={`${organisation.name}: connected apps`}>
                  <h3 className={styles.subhead}>Connected apps</h3>
                  <ul className={styles.apps}>
                    {organisation.connections.map((connection) => (
                      <li key={connection.id}>
                        <strong>{connection.app}</strong>
                        <Scopes items={connection.scopes} />
                        <small className={styles.muted}>
                          {connection.revokedAt
                            ? `Disconnected ${when(connection.revokedAt)}`
                            : `Connected ${ago(connection.createdAt, "")} · last used ${ago(connection.lastUsedAt)}`}
                        </small>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </Panel>
          );
        })
      ) : (
        <Panel title="Organisations">
          <Empty
            icon={Plug}
            title="No integrations yet"
            text="When an organisation makes an API key, adds a webhook or connects an app in Sales Xray (Settings → Integrations), it shows here."
          />
        </Panel>
      )}
    </>
  );
}
