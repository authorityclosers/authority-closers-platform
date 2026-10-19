"use client";

/**
 * Organisation → Integrations: API keys and the webhook, for owners and admins.
 * A key or signing secret is shown once in a dialog with a Copy button and is
 * never shown again; the list keeps only its first characters. Problems go to
 * the corner card (notify), field mistakes stay next to the field.
 */
import {
  Check,
  Copy,
  KeyRound,
  Link2,
  RefreshCw,
  Send,
  Webhook as WebhookIcon,
} from "lucide-react";
import { useEffect, useId, useState } from "react";

import { notify } from "../../notice-center";
import {
  Badge,
  Button,
  Dialog,
  Empty,
  Field,
  Panel,
  Skeleton,
  Table,
  type Tone,
} from "../../ui/kit";
import {
  createKey,
  disableHandover,
  disconnect,
  registerApp,
  removeApp,
  DELIVERY_LABEL,
  disableWebhook,
  finishRotation,
  IntegrationsError,
  readDeliveries,
  readIntegrations,
  retryDelivery,
  revokeKey,
  rotateSecret,
  saveHandover,
  saveWebhook,
  sendTest,
  testWords,
  type ApiKey,
  type Connection,
  type Handover,
  type OAuthApp,
  type Delivery,
  type Integrations,
  type Webhook,
} from "./integrations-client";
import { AiRepliesSettings } from "../../leads/ai-replies";
import { SocialSettings } from "../../leads/social-settings";
import { WhatsAppSettings } from "../../leads/whatsapp-settings";
import styles from "./integrations.module.css";

const STATE_TONE: Record<ApiKey["state"], Tone> = {
  active: "good",
  expired: "warn",
  revoked: "neutral",
};
const DELIVERY_TONE: Record<string, Tone> = {
  delivered: "good",
  pending: "warn",
  dead_letter: "bad",
  rejected: "bad",
  dropped: "neutral",
};

const when = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("en-IN", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

function problem(error: unknown, title: string) {
  if (error instanceof DOMException && error.name === "AbortError") return;
  notify({
    id: `integrations:${title}`,
    tone: "error",
    title,
    message:
      error instanceof IntegrationsError
        ? error.message
        : "Try again in a moment.",
  });
}

/** The once-only secret: shown with Copy, gone when the dialog closes. */
function SecretOnce({
  title,
  secret,
  note,
  onClose,
}: {
  title: string;
  secret: string | null;
  note: string;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <Dialog
      open={secret !== null}
      title={title}
      description="Copy it now. For your safety it is not shown again."
      onClose={() => {
        setCopied(false);
        onClose();
      }}
      actions={
        <Button
          variant="primary"
          onClick={() => {
            setCopied(false);
            onClose();
          }}
        >
          I have saved it
        </Button>
      }
    >
      <div className={styles.secret}>
        <code data-testid="secret-once">{secret}</code>
        <Button
          variant="secondary"
          aria-label="Copy"
          onClick={() => {
            if (!secret) return;
            void navigator.clipboard?.writeText(secret).then(
              () => setCopied(true),
              () => setCopied(false),
            );
          }}
        >
          {copied ? <Check size={14} /> : <Copy size={14} />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <p className={styles.note}>{note}</p>
    </Dialog>
  );
}

function NewKeyDialog({
  open,
  data,
  onClose,
  onMade,
}: {
  open: boolean;
  data: Integrations;
  onClose: () => void;
  onMade: (key: ApiKey, secret: string) => void;
}) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>([]);
  const [expiry, setExpiry] = useState<number | null>(90);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const expiryId = useId();
  const reset = () => {
    setName("");
    setScopes([]);
    setExpiry(90);
    setError(null);
  };
  return (
    <Dialog
      open={open}
      title="New API key"
      description="Give it a name you will recognise and only the permissions it needs."
      onClose={() => {
        reset();
        onClose();
      }}
      actions={
        <>
          <Button
            onClick={() => {
              reset();
              onClose();
            }}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => {
              if (!name.trim()) return setError("Give the key a name.");
              if (!scopes.length)
                return setError("Choose at least one permission.");
              setBusy(true);
              createKey({ name: name.trim(), scopes, expiresDays: expiry })
                .then(({ key, secret }) => {
                  reset();
                  onMade(key, secret);
                })
                .catch((caught: unknown) =>
                  setError(
                    caught instanceof IntegrationsError
                      ? caught.message
                      : "The key was not made. Try again.",
                  ),
                )
                .finally(() => setBusy(false));
            }}
          >
            Create key
          </Button>
        </>
      }
    >
      <div className={styles.form}>
        <Field label="Name" error={error}>
          <input
            value={name}
            maxLength={80}
            placeholder="For example: Our CRM"
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <fieldset className={styles.choices}>
          <legend>Permissions</legend>
          {data.scopes.map((scope) => (
            <label key={scope.key} className={styles.choice}>
              <input
                type="checkbox"
                checked={scopes.includes(scope.key)}
                onChange={(event) =>
                  setScopes((current) =>
                    event.target.checked
                      ? [...current, scope.key]
                      : current.filter((item) => item !== scope.key),
                  )
                }
              />
              <span>
                {scope.label}
                <code>{scope.key}</code>
              </span>
            </label>
          ))}
        </fieldset>
        <label className={styles.inline} htmlFor={expiryId}>
          Expires
          <select
            id={expiryId}
            value={expiry === null ? "never" : String(expiry)}
            onChange={(event) =>
              setExpiry(
                event.target.value === "never"
                  ? null
                  : Number(event.target.value),
              )
            }
          >
            {data.expiryDays.map((days) => (
              <option key={days} value={days}>
                In {days} days
              </option>
            ))}
            <option value="never">Never</option>
          </select>
        </label>
      </div>
    </Dialog>
  );
}

function KeysSection({
  data,
  onChange,
}: {
  data: Integrations;
  onChange: (keys: ApiKey[]) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const label = (key: string) =>
    data.scopes.find((scope) => scope.key === key)?.label ?? key;
  return (
    <Panel
      title="API keys"
      sub="Let your other apps read calls and leads, or add leads"
      tools={
        <Button variant="primary" onClick={() => setCreating(true)}>
          <KeyRound size={14} aria-hidden="true" /> New key
        </Button>
      }
    >
      {data.apiBase ? (
        <p className={styles.howto}>
          Send{" "}
          <code>
            Authorization: Bearer{" "}
            {data.keyMode === "live" ? "sxk_live_…" : "sxk_test_…"}
          </code>{" "}
          to <code>{data.apiBase}</code>
        </p>
      ) : null}
      {data.keys.length ? (
        <Table label="API keys">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Key</th>
              <th scope="col">Permissions</th>
              <th scope="col">Last used</th>
              <th scope="col">Expires</th>
              <th scope="col">State</th>
              <th scope="col">
                <span className={styles.hidden}>Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {data.keys.map((key) => (
              <tr key={key.id}>
                <th scope="row">{key.name}</th>
                <td>
                  <code>{key.prefix}…</code>
                </td>
                <td>{key.scopes.map(label).join(", ")}</td>
                <td>{key.lastUsedAt ? when(key.lastUsedAt) : "Never"}</td>
                <td>{key.expiresAt ? when(key.expiresAt) : "Never"}</td>
                <td>
                  <Badge tone={STATE_TONE[key.state]}>
                    {key.state === "active"
                      ? "Active"
                      : key.state === "expired"
                        ? "Expired"
                        : "Revoked"}
                  </Badge>
                </td>
                <td>
                  {key.state === "active" ? (
                    <Button variant="ghost" onClick={() => setRevoking(key)}>
                      Revoke
                    </Button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : (
        <Empty
          icon={KeyRound}
          title="No API keys yet"
          text="Make one for each app that connects, so you can revoke it alone."
          action={{ onClick: () => setCreating(true), label: "New key" }}
        />
      )}
      <NewKeyDialog
        open={creating}
        data={data}
        onClose={() => setCreating(false)}
        onMade={(key, made) => {
          setCreating(false);
          onChange([key, ...data.keys]);
          setSecret(made);
        }}
      />
      <SecretOnce
        title="Your new API key"
        secret={secret}
        note="Keep it in your app's settings or secret store. Anyone with it can act within its permissions until you revoke it."
        onClose={() => setSecret(null)}
      />
      <Dialog
        open={revoking !== null}
        title={`Revoke “${revoking?.name ?? ""}”?`}
        description="Apps using this key stop working at once. This cannot be undone."
        onClose={() => setRevoking(null)}
        actions={
          <>
            <Button onClick={() => setRevoking(null)}>Keep it</Button>
            <Button
              variant="primary"
              onClick={() => {
                const target = revoking;
                setRevoking(null);
                if (!target) return;
                revokeKey(target.id)
                  .then((revoked) =>
                    onChange(
                      data.keys.map((key) =>
                        key.id === revoked.id ? revoked : key,
                      ),
                    ),
                  )
                  .catch((error: unknown) =>
                    problem(error, "The key was not revoked"),
                  );
              }}
            >
              Revoke key
            </Button>
          </>
        }
      />
    </Panel>
  );
}

function WebhookForm({
  data,
  current,
  onSaved,
  onCancel,
}: {
  data: Integrations;
  current: Webhook | null;
  onSaved: (webhook: Webhook | null, secret: string | null) => void;
  onCancel?: () => void;
}) {
  const [url, setUrl] = useState(current?.url ?? "");
  const [events, setEvents] = useState<string[]>(
    current?.events ?? data.events.map((event) => event.key),
  );
  const [profile, setProfile] = useState<string | null>(
    current?.factsProfile ?? null,
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const profileId = useId();
  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        if (!/^https:\/\/\S+$/.test(url.trim()))
          return setError("Use an https:// address your app answers on.");
        if (!events.length) return setError("Choose at least one event.");
        setBusy(true);
        setError(null);
        saveWebhook({ url: url.trim(), events, factsProfile: profile })
          .then(({ webhook, secret }) => onSaved(webhook, secret))
          .catch((caught: unknown) =>
            setError(
              caught instanceof IntegrationsError
                ? caught.message
                : "The webhook was not saved. Try again.",
            ),
          )
          .finally(() => setBusy(false));
      }}
    >
      <Field
        label="Your app's address"
        hint="Sales X-Ray sends a signed POST here for each event."
        error={error}
        wide
      >
        <input
          type="url"
          inputMode="url"
          value={url}
          placeholder="https://your-app.example.com/hooks/sales-xray"
          onChange={(event) => setUrl(event.target.value)}
        />
      </Field>
      <fieldset className={styles.choices}>
        <legend>Events</legend>
        {data.events.map((item) => (
          <label key={item.key} className={styles.choice}>
            <input
              type="checkbox"
              checked={events.includes(item.key)}
              onChange={(event) =>
                setEvents((list) =>
                  event.target.checked
                    ? [...list, item.key]
                    : list.filter((key) => key !== item.key),
                )
              }
            />
            <span>
              {item.label}
              <code>{item.key}</code>
            </span>
          </label>
        ))}
      </fieldset>
      {data.factsProfiles.length ? (
        <label className={styles.inline} htmlFor={profileId}>
          Facts for quotes
          <select
            id={profileId}
            value={profile ?? ""}
            onChange={(event) => setProfile(event.target.value || null)}
          >
            <option value="">None</option>
            {data.factsProfiles.map((name) => (
              <option key={name} value={name}>
                {name.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <div className={styles.actions}>
        {onCancel ? <Button onClick={onCancel}>Cancel</Button> : null}
        <Button variant="primary" type="submit" disabled={busy}>
          {current ? "Save changes" : "Add webhook"}
        </Button>
      </div>
    </form>
  );
}

function Deliveries({ reloadKey }: { reloadKey: number }) {
  const [items, setItems] = useState<Delivery[] | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    readDeliveries(controller.signal).then(setItems, (error: unknown) => {
      problem(error, "The delivery log did not load");
      setItems([]);
    });
    return () => controller.abort();
  }, [reloadKey]);
  if (items === null)
    return (
      <div className={styles.skeletons} aria-busy="true">
        <Skeleton height={14} />
        <Skeleton height={14} />
      </div>
    );
  if (!items.length)
    return (
      <p className={styles.note}>No events sent yet. New events show here.</p>
    );
  return (
    <Table label="Delivery log">
      <thead>
        <tr>
          <th scope="col">When</th>
          <th scope="col">Event</th>
          <th scope="col">State</th>
          <th scope="col">Tries</th>
          <th scope="col">Last answer</th>
          <th scope="col">
            <span className={styles.hidden}>Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.id}>
            <th scope="row">{when(item.createdAt)}</th>
            <td>
              <code>{item.eventType}</code>
            </td>
            <td>
              <Badge tone={DELIVERY_TONE[item.status] ?? "neutral"}>
                {DELIVERY_LABEL[item.status] ?? item.status}
              </Badge>
            </td>
            <td>{item.attempts}</td>
            <td>{item.lastHttpStatus ?? item.lastErrorCode ?? "—"}</td>
            <td>
              {item.status === "dead_letter" ? (
                <Button
                  variant="ghost"
                  onClick={() =>
                    retryDelivery(item.id).then(setItems, (error: unknown) =>
                      problem(error, "The event was not queued again"),
                    )
                  }
                >
                  Send again
                </Button>
              ) : null}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function WebhookSection({
  data,
  onChange,
}: {
  data: Integrations;
  onChange: (webhook: Webhook | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [confirmOff, setConfirmOff] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const hook = data.webhook;
  const eventLabel = (key: string) =>
    data.events.find((item) => item.key === key)?.label ?? key;
  if (!data.webhooksReady)
    return (
      <Panel title="Webhook" sub="Events sent to your app">
        <Empty
          icon={WebhookIcon}
          title="Not switched on here yet"
          text="Webhooks open on this server soon. API keys work now."
        />
      </Panel>
    );
  return (
    <Panel
      title="Webhook"
      sub="Sales X-Ray tells your app when something happens"
      tools={
        hook && !editing ? (
          <Button
            variant="secondary"
            disabled={testing}
            onClick={() => {
              setTesting(true);
              setResult(null);
              sendTest()
                .then((answer) => {
                  setResult(testWords(answer));
                  setReloadKey((n) => n + 1);
                })
                .catch((error: unknown) =>
                  problem(error, "The test was not sent"),
                )
                .finally(() => setTesting(false));
            }}
          >
            <Send size={14} aria-hidden="true" /> Send test event
          </Button>
        ) : null
      }
    >
      {!hook || editing ? (
        <WebhookForm
          data={data}
          current={hook}
          onCancel={hook ? () => setEditing(false) : undefined}
          onSaved={(saved, made) => {
            setEditing(false);
            onChange(saved);
            if (made) setSecret(made);
          }}
        />
      ) : (
        <div className={styles.hook}>
          <dl className={styles.facts}>
            <div>
              <dt>Address</dt>
              <dd>
                <code>{hook.url}</code>
              </dd>
            </div>
            <div>
              <dt>Events</dt>
              <dd>{hook.events.map(eventLabel).join(" · ")}</dd>
            </div>
            <div>
              <dt>Signing secret</dt>
              <dd>
                {hook.managedInApp ? (
                  <code>whsec_…{hook.secretHint}</code>
                ) : (
                  "Set up by AC. Save the webhook here to get your own secret."
                )}
                {hook.rotating ? (
                  <span className={styles.rotating}>
                    {" "}
                    and the new <code>whsec_…{hook.nextSecretHint}</code> (both
                    sign)
                  </span>
                ) : null}
              </dd>
            </div>
            {hook.factsProfile ? (
              <div>
                <dt>Facts for quotes</dt>
                <dd>{hook.factsProfile.replaceAll("_", " ")}</dd>
              </div>
            ) : null}
          </dl>
          {result ? (
            <p className={styles.result} role="status">
              {result}
            </p>
          ) : null}
          <div className={styles.actions}>
            <Button onClick={() => setEditing(true)}>Change</Button>
            {hook.managedInApp && !hook.rotating ? (
              <Button
                onClick={() =>
                  rotateSecret()
                    .then(({ webhook, secret: made }) => {
                      onChange(webhook);
                      setSecret(made);
                    })
                    .catch((error: unknown) =>
                      problem(error, "No new secret was made"),
                    )
                }
              >
                <RefreshCw size={14} aria-hidden="true" /> New signing secret
              </Button>
            ) : null}
            {hook.rotating ? (
              <Button
                variant="primary"
                onClick={() =>
                  finishRotation()
                    .then(onChange)
                    .catch((error: unknown) =>
                      problem(error, "The change did not finish"),
                    )
                }
              >
                My app uses the new secret
              </Button>
            ) : null}
            <Button variant="ghost" onClick={() => setConfirmOff(true)}>
              Turn off
            </Button>
          </div>
          <h3 className={styles.subhead}>Delivery log</h3>
          <Deliveries reloadKey={reloadKey} />
        </div>
      )}
      <SecretOnce
        title="Your webhook signing secret"
        secret={secret}
        note="Check each request: X-SX-Signature is t=<time>,v1=<HMAC-SHA256 of “<time>.<body>”>. Until you finish a change, requests carry two v1 values."
        onClose={() => setSecret(null)}
      />
      <Dialog
        open={confirmOff}
        title="Turn off the webhook?"
        description="Sales X-Ray stops sending events. Events not yet sent are dropped."
        onClose={() => setConfirmOff(false)}
        actions={
          <>
            <Button onClick={() => setConfirmOff(false)}>Keep it on</Button>
            <Button
              variant="primary"
              onClick={() => {
                setConfirmOff(false);
                disableWebhook()
                  .then(() => onChange(null))
                  .catch((error: unknown) =>
                    problem(error, "The webhook was not turned off"),
                  );
              }}
            >
              Turn off
            </Button>
          </>
        }
      />
    </Panel>
  );
}

const QUESTION_LABEL: Record<string, string> = {
  "address.line1": "Address line 1",
  "address.line2": "Address line 2",
  "address.city": "City",
  "address.state": "State",
  "address.pin_code": "PIN code",
  "attribution.campaign": "Campaign",
  "requirement.system_type": "System type",
  "requirement.capacity_kw": "Capacity (kW)",
};

function HandoverSection({
  data,
  onChange,
}: {
  data: Integrations;
  onChange: (handover: Handover | null) => void;
}) {
  const current = data.handover;
  const menu = data.handoverMenu;
  const [editing, setEditing] = useState(false);
  const [address, setAddress] = useState(current?.url ?? "");
  const [serviceKey, setServiceKey] = useState("");
  const [parts, setParts] = useState<string[]>(current?.leadFields.send ?? []);
  const [questions, setQuestions] = useState<Record<string, string>>(
    current?.leadFields.questions ?? {},
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmOff, setConfirmOff] = useState(false);
  const open = editing || current === null;
  if (!data.webhooksReady || menu === null) return null;
  const save = () => {
    if (!/^https:\/\/\S+$/.test(address.trim()))
      return setError("Use your app's https:// address.");
    if (!current && !serviceKey.trim())
      return setError("Paste the service key your app gave you.");
    setBusy(true);
    setError(null);
    const asked = Object.fromEntries(
      Object.entries(questions).filter(
        ([path, text]) =>
          text.trim() &&
          parts.includes(
            menu.questions.find((q) => q.path === path)?.part ?? "",
          ),
      ),
    );
    saveHandover({
      address: address.trim(),
      serviceKey: serviceKey.trim() || null,
      leadFields: { send: parts, questions: asked, consents: [] },
    })
      .then((saved) => {
        setServiceKey("");
        setEditing(false);
        onChange(saved);
      })
      .catch((caught: unknown) =>
        setError(
          caught instanceof IntegrationsError
            ? caught.message
            : "The hand-over was not saved. Try again.",
        ),
      )
      .finally(() => setBusy(false));
  };
  return (
    <Panel
      title="Hand-over to your customer app"
      sub="When a lead is won, Sales X-Ray sends the customer to your app"
    >
      {open ? (
        <div className={styles.form}>
          <Field
            label="Your app's address"
            hint={`Sales X-Ray calls ${menu.path} on it.`}
            error={error}
            wide
          >
            <input
              type="url"
              inputMode="url"
              value={address}
              placeholder="https://your-app.example.com"
              onChange={(event) => setAddress(event.target.value)}
            />
          </Field>
          <Field
            label="Service key"
            hint={
              current
                ? "Leave empty to keep the current key."
                : "Paste the key your app issued for Sales X-Ray. It is kept sealed and never shown again."
            }
          >
            <input
              type="password"
              autoComplete="off"
              value={serviceKey}
              onChange={(event) => setServiceKey(event.target.value)}
            />
          </Field>
          <fieldset className={styles.choices}>
            <legend>Also send (name and phone always go)</legend>
            {menu.parts.map((part) => (
              <label key={part.key} className={styles.choice}>
                <input
                  type="checkbox"
                  checked={parts.includes(part.key)}
                  onChange={(event) =>
                    setParts((list) =>
                      event.target.checked
                        ? [...list, part.key]
                        : list.filter((key) => key !== part.key),
                    )
                  }
                />
                <span>{part.label}</span>
              </label>
            ))}
          </fieldset>
          {menu.questions
            .filter((question) => parts.includes(question.part))
            .map((question) => (
              <Field
                key={question.path}
                label={`Form question for ${QUESTION_LABEL[question.path] ?? question.path}`}
                hint="Exactly as it appears on your lead form, or leave empty."
              >
                <input
                  value={questions[question.path] ?? ""}
                  maxLength={200}
                  onChange={(event) =>
                    setQuestions((map) => ({
                      ...map,
                      [question.path]: event.target.value,
                    }))
                  }
                />
              </Field>
            ))}
          <div className={styles.actions}>
            {current ? (
              <Button onClick={() => setEditing(false)}>Cancel</Button>
            ) : null}
            <Button variant="primary" disabled={busy} onClick={save}>
              {current ? "Save changes" : "Set up hand-over"}
            </Button>
          </div>
        </div>
      ) : current ? (
        <div className={styles.hook}>
          <dl className={styles.facts}>
            <div>
              <dt>Address</dt>
              <dd>
                <code>{current.url}</code>
              </dd>
            </div>
            <div>
              <dt>Service key</dt>
              <dd>
                {current.managedInApp ? (
                  <code>…{current.keyHint}</code>
                ) : (
                  "Set up by AC. Save it here with your own key."
                )}
              </dd>
            </div>
            <div>
              <dt>Also sends</dt>
              <dd>
                {current.leadFields.send.length
                  ? current.leadFields.send
                      .map(
                        (key) =>
                          menu.parts.find((part) => part.key === key)?.label ??
                          key,
                      )
                      .join(" · ")
                  : "Name and phone only"}
              </dd>
            </div>
          </dl>
          <div className={styles.actions}>
            <Button onClick={() => setEditing(true)}>Change</Button>
            <Button variant="ghost" onClick={() => setConfirmOff(true)}>
              Turn off
            </Button>
          </div>
        </div>
      ) : null}
      <Dialog
        open={confirmOff}
        title="Turn off the hand-over?"
        description="Won leads stop going to your app. Hand-overs not yet sent are dropped."
        onClose={() => setConfirmOff(false)}
        actions={
          <>
            <Button onClick={() => setConfirmOff(false)}>Keep it on</Button>
            <Button
              variant="primary"
              onClick={() => {
                setConfirmOff(false);
                disableHandover()
                  .then(() => onChange(null))
                  .catch((caught: unknown) =>
                    problem(caught, "The hand-over was not turned off"),
                  );
              }}
            >
              Turn off
            </Button>
          </>
        }
      />
    </Panel>
  );
}

function AppsSection({
  data,
  onApps,
  onConnections,
}: {
  data: Integrations;
  onApps: (apps: OAuthApp[]) => void;
  onConnections: (connections: Connection[]) => void;
}) {
  const [registering, setRegistering] = useState(false);
  const [name, setName] = useState("");
  const [uris, setUris] = useState("");
  const [confidential, setConfidential] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState<{
    clientId: string;
    secret: string | null;
  } | null>(null);
  const label = (key: string) =>
    data.scopes.find((scope) => scope.key === key)?.label ?? key;
  const connected = data.connections.filter((item) => item.revokedAt === null);
  const apps = data.apps.filter((app) => app.revokedAt === null);
  return (
    <Panel
      title="Connected apps"
      sub="Apps your organisation allowed with “Connect to Sales X-Ray”"
      tools={
        <Button onClick={() => setRegistering(true)}>
          <Link2 size={14} aria-hidden="true" /> Register your own app
        </Button>
      }
    >
      {connected.length ? (
        <Table label="Connected apps">
          <thead>
            <tr>
              <th scope="col">App</th>
              <th scope="col">Can</th>
              <th scope="col">Connected</th>
              <th scope="col">Last used</th>
              <th scope="col">
                <span className={styles.hidden}>Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {connected.map((item) => (
              <tr key={item.id}>
                <th scope="row">{item.app}</th>
                <td>{item.scopes.map(label).join(", ")}</td>
                <td>{when(item.createdAt)}</td>
                <td>{item.lastUsedAt ? when(item.lastUsedAt) : "Never"}</td>
                <td>
                  <Button
                    variant="ghost"
                    onClick={() =>
                      disconnect(item.id).then(
                        onConnections,
                        (caught: unknown) =>
                          problem(caught, "The app was not disconnected"),
                      )
                    }
                  >
                    Disconnect
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : (
        <p className={styles.note}>
          No apps connected. When an app asks to connect, you approve it on a
          Sales X-Ray screen and it shows here.
        </p>
      )}
      {apps.length ? (
        <>
          <h3 className={styles.subhead}>Your apps</h3>
          <Table label="Your apps">
            <thead>
              <tr>
                <th scope="col">App</th>
                <th scope="col">Client ID</th>
                <th scope="col">Returns to</th>
                <th scope="col">
                  <span className={styles.hidden}>Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {apps.map((app) => (
                <tr key={app.id}>
                  <th scope="row">{app.name}</th>
                  <td>
                    <code>{app.clientId}</code>
                  </td>
                  <td>{app.redirectUris.join(", ")}</td>
                  <td>
                    <Button
                      variant="ghost"
                      onClick={() =>
                        removeApp(app.id).then(onApps, (caught: unknown) =>
                          problem(caught, "The app was not removed"),
                        )
                      }
                    >
                      Remove
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </>
      ) : null}
      <Dialog
        open={registering}
        title="Register your own app"
        description="For an app you build that should ask organisations to connect."
        onClose={() => setRegistering(false)}
        actions={
          <>
            <Button onClick={() => setRegistering(false)}>Cancel</Button>
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => {
                const list = uris
                  .split(/\s+/)
                  .map((uri) => uri.trim())
                  .filter(Boolean);
                if (!name.trim()) return setError("Give the app a name.");
                if (!list.length)
                  return setError("Add the address to return to.");
                setBusy(true);
                setError(null);
                registerApp({
                  name: name.trim(),
                  redirectUris: list,
                  confidential,
                })
                  .then(({ app, secret }) => {
                    onApps([app, ...data.apps]);
                    setRegistering(false);
                    setName("");
                    setUris("");
                    setMade({ clientId: app.clientId, secret });
                  })
                  .catch((caught: unknown) =>
                    setError(
                      caught instanceof IntegrationsError
                        ? caught.message
                        : "The app was not registered. Try again.",
                    ),
                  )
                  .finally(() => setBusy(false));
              }}
            >
              Register
            </Button>
          </>
        }
      >
        <div className={styles.form}>
          <Field label="App name" error={error}>
            <input
              value={name}
              maxLength={80}
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <Field
            label="Return addresses"
            hint="One per line, exactly as your app sends them. https://, or http://127.0.0.1 for a desktop app."
          >
            <textarea
              className={styles.textarea}
              rows={3}
              value={uris}
              onChange={(event) => setUris(event.target.value)}
            />
          </Field>
          <label className={styles.choice}>
            <input
              type="checkbox"
              checked={confidential}
              onChange={(event) => setConfidential(event.target.checked)}
            />
            <span>My app has a server that can keep a secret</span>
          </label>
        </div>
      </Dialog>
      <SecretOnce
        title="Your app's credentials"
        secret={
          made
            ? `${made.clientId}${made.secret ? `\n${made.secret}` : ""}`
            : null
        }
        note={
          made?.secret
            ? "First line: client ID. Second line: client secret, shown once. Send people to /connect with PKCE (S256)."
            : "This is your client ID. Your app uses PKCE (S256) without a secret."
        }
        onClose={() => setMade(null)}
      />
    </Panel>
  );
}

/** The parts Settings shows in its own sections (20 Oct): apps, AI replies, developers. */
export type IntegrationPart =
  | "whatsapp"
  | "social"
  | "ai"
  | "keys"
  | "webhook"
  | "handover"
  | "apps";
const ALL_PARTS: readonly IntegrationPart[] = [
  "whatsapp",
  "social",
  "ai",
  "keys",
  "webhook",
  "handover",
  "apps",
];
const DEVELOPER_PARTS: ReadonlySet<IntegrationPart> = new Set([
  "keys",
  "webhook",
  "handover",
  "apps",
]);

export function IntegrationsPanel({
  parts = ALL_PARTS,
}: {
  parts?: readonly IntegrationPart[];
}) {
  const [data, setData] = useState<Integrations | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  // Keys, the webhook, hand-over and apps share one read; the rest read their own.
  const needsData = parts.some((part) => DEVELOPER_PARTS.has(part));
  useEffect(() => {
    if (!needsData) return;
    const controller = new AbortController();
    readIntegrations(controller.signal).then(
      (value) => {
        setData(value);
        setFailed(false);
      },
      (error: unknown) => {
        problem(error, "Integrations did not load");
        setFailed(true);
      },
    );
    return () => controller.abort();
  }, [attempt, needsData]);
  const shows = (part: IntegrationPart) => parts.includes(part);
  const own = (
    <>
      {shows("whatsapp") ? <WhatsAppSettings /> : null}
      {shows("social") ? <SocialSettings /> : null}
      {shows("ai") ? <AiRepliesSettings /> : null}
    </>
  );
  if (needsData && failed && !data)
    return (
      <div className={styles.stack}>
        {own}
        <Empty
          icon={KeyRound}
          title="Integrations did not load"
          action={{
            onClick: () => setAttempt((n) => n + 1),
            label: "Try again",
          }}
        />
      </div>
    );
  if (needsData && !data)
    return (
      <div className={styles.stack}>
        {own}
        <div className={styles.skeletons} aria-busy="true">
          <Skeleton height={120} />
          <Skeleton height={160} />
        </div>
      </div>
    );
  return (
    <div className={styles.stack}>
      {own}
      {data && shows("keys") ? (
        <KeysSection
          data={data}
          onChange={(keys) => setData({ ...data, keys })}
        />
      ) : null}
      {data && shows("webhook") ? (
        <WebhookSection
          data={data}
          onChange={(webhook) => setData({ ...data, webhook })}
        />
      ) : null}
      {data && shows("handover") ? (
        <HandoverSection
          data={data}
          onChange={(handover) => setData({ ...data, handover })}
        />
      ) : null}
      {data && shows("apps") ? (
        <AppsSection
          data={data}
          onApps={(apps) => setData({ ...data, apps })}
          onConnections={(connections) => setData({ ...data, connections })}
        />
      ) : null}
    </div>
  );
}
