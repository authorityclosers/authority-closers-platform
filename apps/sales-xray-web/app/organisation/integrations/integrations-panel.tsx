"use client";

/**
 * Organisation → Integrations: API keys and the webhook, for owners and admins.
 * A key or signing secret is shown once in a dialog with a Copy button and is
 * never shown again; the list keeps only its first characters. Problems go to
 * the corner card (notify), field mistakes stay next to the field.
 */
import {
  AppWindow,
  ArrowRightLeft,
  Check,
  ChevronRight,
  Copy,
  KeyRound,
  Link2,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  Send,
  Webhook as WebhookIcon,
} from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { notify } from "../../notice-center";
import {
  Badge,
  Button,
  Dialog,
  Empty,
  Field,
  Skeleton,
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
import { ClaudeMark, CursorMark } from "../../settings/assistant-marks";
import { DevCard } from "../../settings/dev-card";
import { BrandTile } from "../../ui/brand-tile";
import { PulseTile } from "../../ui/pulse-mark";
import { SocialSettings } from "../../leads/social-settings";
import { WhatsAppSettings } from "../../leads/whatsapp-settings";
import keyStyles from "./api-keys.module.css";
import styles from "./integrations.module.css";

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

/** A day for a row's short line ("28 Oct"); the full time is not needed there. */
const day = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleDateString("en-IN", {
        day: "numeric",
        month: "short",
      })
    : "never";

/**
 * An app's own mark where we know it (Pulse, ChatGPT, Claude, Cursor), else a
 * plain app icon; "tile" marks bring their own tile, "mark" ones sit on a
 * quiet one.
 */
function appMark(name: string): { icon: ReactNode; kind?: "tile" | "mark" } {
  const key = name.trim().toLowerCase();
  if (key.startsWith("pulse"))
    return { icon: <PulseTile size={36} />, kind: "tile" };
  if (key.startsWith("chatgpt") || key.startsWith("openai"))
    return { icon: <BrandTile brands={["chatgpt"]} size={36} />, kind: "tile" };
  if (key.startsWith("claude"))
    return { icon: <ClaudeMark size={18} />, kind: "mark" };
  if (key.startsWith("cursor"))
    return { icon: <CursorMark size={18} />, kind: "mark" };
  return { icon: <AppWindow size={16} /> };
}

/** A permission in two words for a key card: "calls:read" → "Calls · read". */
export function scopeWords(scope: string): string {
  const [what, how] = scope.split(":");
  const name = what ? what.charAt(0).toUpperCase() + what.slice(1) : scope;
  return how ? `${name} · ${how}` : name;
}

/** A signing secret's last characters, whatever prefix the hint came with. */
const tail = (hint: string | null) => (hint ?? "").replace(/^whsec_…?/, "");

/**
 * One row in a panel's list (owner, 29 Oct 2026: "clean UI and icons", no
 * tables or label walls on a phone): an icon tile, the name, one or two short
 * lines, and the state and its one action at the end.
 */
function ListRow({
  icon,
  kind,
  title,
  lines,
  end,
  state,
}: {
  icon: ReactNode;
  /** "tile": the icon brings its own tile; "mark": a brand mark, quiet tile. */
  kind?: "tile" | "mark";
  title: ReactNode;
  lines: ReactNode[];
  end?: ReactNode;
  state?: string;
}) {
  return (
    <li className={styles.row} data-state={state}>
      <span className={styles.rowIcon} data-kind={kind} aria-hidden="true">
        {icon}
      </span>
      <span className={styles.rowText}>
        <strong>{title}</strong>
        {lines.filter(Boolean).map((line, index) => (
          <span key={index}>{line}</span>
        ))}
      </span>
      {end ? <span className={styles.rowEnd}>{end}</span> : null}
    </li>
  );
}

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
  onKeyMade,
}: {
  data: Integrations;
  onChange: (keys: ApiKey[]) => void;
  onKeyMade?: (key: string) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const label = (key: string) =>
    data.scopes.find((scope) => scope.key === key)?.label ?? key;
  const bearer = data.keyMode === "live" ? "sxk_live_…" : "sxk_test_…";
  return (
    <DevCard
      icon={<KeyRound />}
      tone="amber"
      title="API keys"
      info={
        <>
          {data.apiBase ? (
            <p>
              Send <code>Authorization: Bearer {bearer}</code> to{" "}
              <code>{data.apiBase}</code>
            </p>
          ) : null}
          <p>
            Make one key for each app that connects, with only the permissions
            it needs, so you can revoke one alone. A key is shown once.
          </p>
        </>
      }
      tools={
        // The empty card has its own button; never two "New key".
        data.keys.length ? (
          <Button
            variant="primary"
            className={styles.chip}
            onClick={() => setCreating(true)}
          >
            <Plus size={15} aria-hidden="true" /> New key
          </Button>
        ) : null
      }
    >
      {data.keys.length ? (
        // Each key as a key card (owner bug #104, 29 Oct 2026: "API keys have
        // no personality"): its name and state, the key's first characters,
        // what it may do, and when it was used.
        <ul className={keyStyles.keys} aria-label="API keys">
          {data.keys.map((key) => (
            <li key={key.id} className={keyStyles.key} data-state={key.state}>
              <span className={keyStyles.keyMark} aria-hidden="true">
                <KeyRound size={18} />
              </span>
              <span className={keyStyles.keyBody}>
                <span className={keyStyles.keyTop}>
                  <strong>{key.name}</strong>
                  <span className={keyStyles.keyState} data-state={key.state}>
                    {key.state === "active"
                      ? "Active"
                      : key.state === "expired"
                        ? "Expired"
                        : "Revoked"}
                  </span>
                </span>
                <code className={keyStyles.keyToken}>
                  {key.prefix}…<span aria-hidden="true">••••••••</span>
                </code>
                <span
                  className={keyStyles.scopes}
                  aria-label={`May: ${key.scopes.map(label).join(", ")}`}
                >
                  {key.scopes.map((scope) => (
                    <span key={scope} className={keyStyles.scope}>
                      {scopeWords(scope)}
                    </span>
                  ))}
                </span>
                <span className={keyStyles.keyMeta}>
                  Used {day(key.lastUsedAt)} · Expires {day(key.expiresAt)}
                </span>
              </span>
              {key.state === "active" ? (
                <button
                  type="button"
                  className={keyStyles.revoke}
                  aria-label={`Revoke ${key.name}`}
                  onClick={() => setRevoking(key)}
                >
                  Revoke
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        // An empty key slot that says what a key is for, and one button.
        <div className={keyStyles.keySlot}>
          <span className={keyStyles.keySlotMark} aria-hidden="true">
            <KeyRound size={22} />
          </span>
          <strong>No API keys yet</strong>
          <p>
            Make one for each app that connects, so you can revoke it alone.
          </p>
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus size={15} aria-hidden="true" /> New key
          </Button>
        </div>
      )}
      <NewKeyDialog
        open={creating}
        data={data}
        onClose={() => setCreating(false)}
        onMade={(key, made) => {
          setCreating(false);
          onChange([key, ...data.keys]);
          setSecret(made);
          onKeyMade?.(made);
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
    </DevCard>
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
      className={`${styles.form} ${styles.inset}`}
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
  const retry = (id: string) =>
    retryDelivery(id).then(setItems, (error: unknown) =>
      problem(error, "The event was not queued again"),
    );
  return (
    <ul className={styles.rows} aria-label="Delivery log">
      {items.map((item) => (
        <ListRow
          key={item.id}
          state={item.status}
          icon={<Send size={15} />}
          title={<code>{item.eventType}</code>}
          lines={[
            [
              when(item.createdAt),
              `${item.attempts} ${item.attempts === 1 ? "try" : "tries"}`,
              item.lastHttpStatus ?? item.lastErrorCode,
            ]
              .filter(Boolean)
              .join(" · "),
          ]}
          end={
            <>
              <Badge tone={DELIVERY_TONE[item.status] ?? "neutral"}>
                {DELIVERY_LABEL[item.status] ?? item.status}
              </Badge>
              {item.status === "dead_letter" ? (
                <Button
                  variant="ghost"
                  className={styles.chip}
                  onClick={() => void retry(item.id)}
                >
                  Send again
                </Button>
              ) : null}
            </>
          }
        />
      ))}
    </ul>
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
  const test = () => {
    setTesting(true);
    setResult(null);
    sendTest()
      .then((answer) => {
        setResult(testWords(answer));
        setReloadKey((n) => n + 1);
      })
      .catch((error: unknown) => problem(error, "The test was not sent"))
      .finally(() => setTesting(false));
  };
  if (!data.webhooksReady)
    return (
      <DevCard
        icon={<WebhookIcon />}
        tone="blue"
        title="Webhook"
        info={<p>Events sent to your app, as they happen.</p>}
      >
        <Empty
          icon={WebhookIcon}
          title="Not switched on here yet"
          text="Webhooks open on this server soon. API keys work now."
        />
      </DevCard>
    );
  return (
    <DevCard
      icon={<WebhookIcon />}
      tone="blue"
      title="Webhook"
      info={
        <p>
          Sales X-Ray sends a signed POST to your app for each event you pick,
          such as a new lead or a finished call analysis. Check each one with
          the signing secret.
        </p>
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
        <div className={`${styles.hook} ${styles.inset}`}>
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
                  <code>whsec_…{tail(hook.secretHint)}</code>
                ) : (
                  "Set up by AC. Save the webhook here to get your own secret."
                )}
                {hook.rotating ? (
                  <span className={styles.rotating}>
                    {" "}
                    and the new <code>
                      whsec_…{tail(hook.nextSecretHint)}
                    </code>{" "}
                    (both sign)
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
          <div className={styles.chips}>
            <Button className={styles.chip} disabled={testing} onClick={test}>
              <Send size={14} aria-hidden="true" />
              {testing ? "Sending…" : "Send test event"}
            </Button>
            <Button className={styles.chip} onClick={() => setEditing(true)}>
              <Pencil size={14} aria-hidden="true" /> Change
            </Button>
            {hook.managedInApp && !hook.rotating ? (
              <Button
                className={styles.chip}
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
                <RefreshCw size={14} aria-hidden="true" /> New secret
              </Button>
            ) : null}
            {hook.rotating ? (
              <Button
                variant="primary"
                className={styles.chip}
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
            <Button
              variant="ghost"
              className={`${styles.chip} ${styles.off}`}
              onClick={() => setConfirmOff(true)}
            >
              <Power size={14} aria-hidden="true" /> Turn off
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
    </DevCard>
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
    <DevCard
      icon={<ArrowRightLeft />}
      tone="teal"
      title="Hand-over to your app"
      info={
        <p>
          When a lead is won, Sales X-Ray sends it to your own customer app:
          name and phone always, and the other parts you tick.
        </p>
      }
    >
      {open ? (
        <div className={`${styles.form} ${styles.inset}`}>
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
        <div className={`${styles.hook} ${styles.inset}`}>
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
          <div className={styles.chips}>
            <Button className={styles.chip} onClick={() => setEditing(true)}>
              <Pencil size={14} aria-hidden="true" /> Change
            </Button>
            <Button
              variant="ghost"
              className={`${styles.chip} ${styles.off}`}
              onClick={() => setConfirmOff(true)}
            >
              <Power size={14} aria-hidden="true" /> Turn off
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
    </DevCard>
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
    <DevCard
      icon={<AppWindow />}
      tone="slate"
      title="Connected apps"
      info={
        <p>
          Apps you approved to reach your organisation, such as Pulse or
          ChatGPT. Building your own? Register it, and organisations can connect
          it the same way.
        </p>
      }
    >
      {connected.length ? (
        <ul className={styles.rows} aria-label="Connected apps">
          {connected.map((item) => (
            <ListRow
              key={item.id}
              {...appMark(item.app)}
              title={item.app}
              lines={[
                item.scopes.map(label).join(", "),
                `Since ${day(item.createdAt)} · used ${day(item.lastUsedAt)}`,
              ]}
              end={
                <Button
                  variant="ghost"
                  className={styles.chip}
                  aria-label={`Disconnect ${item.app}`}
                  onClick={() =>
                    disconnect(item.id).then(onConnections, (caught: unknown) =>
                      problem(caught, "The app was not disconnected"),
                    )
                  }
                >
                  Disconnect
                </Button>
              }
            />
          ))}
        </ul>
      ) : (
        <p className={`${styles.note} ${styles.inset}`}>
          No apps connected yet. When an app asks to connect, you approve it and
          it shows here.
        </p>
      )}
      {apps.length ? (
        <>
          <h3 className={`${styles.subhead} ${styles.inset}`}>Your apps</h3>
          <ul className={styles.rows} aria-label="Your apps">
            {apps.map((app) => (
              <ListRow
                key={app.id}
                icon={<AppWindow size={16} />}
                title={app.name}
                lines={[
                  <code key="id">{app.clientId}</code>,
                  `Returns to ${app.redirectUris.join(", ")}`,
                ]}
                end={
                  <Button
                    variant="ghost"
                    className={styles.chip}
                    aria-label={`Remove ${app.name}`}
                    onClick={() =>
                      removeApp(app.id).then(onApps, (caught: unknown) =>
                        problem(caught, "The app was not removed"),
                      )
                    }
                  >
                    Remove
                  </Button>
                }
              />
            ))}
          </ul>
        </>
      ) : null}
      {/* Rare, so a quiet last row rather than a button in the head. */}
      <button
        type="button"
        className={keyStyles.registerRow}
        onClick={() => setRegistering(true)}
      >
        <Link2 size={16} aria-hidden="true" />
        <span>Register your own app</span>
        <ChevronRight size={16} aria-hidden="true" />
      </button>
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
    </DevCard>
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

export type IntegrationsPanelOptions = {
  /** Shown right after a part (Settings → Developers: Try it after the keys). */
  extras?: Partial<Record<IntegrationPart, ReactNode>>;
  /** A new key, the moment it is made; the caller keeps it in memory only. */
  onKeyMade?: (key: string) => void;
  /** Changed by the caller to read again (a key was just used). */
  refresh?: number;
};

export function IntegrationsPanel({
  parts = ALL_PARTS,
  extras,
  onKeyMade,
  refresh = 0,
}: {
  parts?: readonly IntegrationPart[];
} & IntegrationsPanelOptions) {
  const [data, setData] = useState<Integrations | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  // Keys, the webhook, hand-over and apps share one read; the rest read their own.
  const needsData = parts.some((part) => DEVELOPER_PARTS.has(part));
  // Read again when asked (a key was just used) and when the page is back in
  // view (at most every 15 s), so "Last used" is current. A later read that
  // fails keeps what is shown and says nothing.
  const shown = useRef(false);
  useEffect(() => {
    if (!needsData) return;
    const controller = new AbortController();
    readIntegrations(controller.signal).then(
      (value) => {
        shown.current = true;
        setData(value);
        setFailed(false);
      },
      (error: unknown) => {
        if (shown.current || controller.signal.aborted) return;
        problem(error, "Integrations did not load");
        setFailed(true);
      },
    );
    return () => controller.abort();
  }, [attempt, needsData, refresh]);
  useEffect(() => {
    if (!needsData) return;
    let last = Date.now();
    const again = () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - last < 15_000) return;
      last = Date.now();
      setAttempt((n) => n + 1);
    };
    window.addEventListener("focus", again);
    document.addEventListener("visibilitychange", again);
    return () => {
      window.removeEventListener("focus", again);
      document.removeEventListener("visibilitychange", again);
    };
  }, [needsData]);
  const shows = (part: IntegrationPart) => parts.includes(part);
  const own = (
    <>
      {shows("whatsapp") ? (
        <>
          <WhatsAppSettings />
          {extras?.whatsapp}
        </>
      ) : null}
      {shows("social") ? (
        <>
          <SocialSettings />
          {extras?.social}
        </>
      ) : null}
      {shows("ai") ? (
        <>
          <div className={styles.aiPart}>
            <AiRepliesSettings />
          </div>
          {extras?.ai}
        </>
      ) : null}
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
          onKeyMade={onKeyMade}
          onChange={(keys) => setData({ ...data, keys })}
        />
      ) : null}
      {data && shows("keys") ? extras?.keys : null}
      {data && shows("webhook") ? (
        <WebhookSection
          data={data}
          onChange={(webhook) => setData({ ...data, webhook })}
        />
      ) : null}
      {data && shows("webhook") ? extras?.webhook : null}
      {data && shows("handover") ? (
        <HandoverSection
          data={data}
          onChange={(handover) => setData({ ...data, handover })}
        />
      ) : null}
      {data && shows("handover") ? extras?.handover : null}
      {data && shows("apps") ? (
        <AppsSection
          data={data}
          onApps={(apps) => setData({ ...data, apps })}
          onConnections={(connections) => setData({ ...data, connections })}
        />
      ) : null}
      {data && shows("apps") ? extras?.apps : null}
    </div>
  );
}
