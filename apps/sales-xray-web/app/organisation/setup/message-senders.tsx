"use client";

/**
 * Lead rules › Message senders (v1.95, owner 22 Nov 2026): the tools and
 * automations that message leads for the team (sx-engage, the testers'
 * auto-replies, the owner's own WhatsApp tool), each bound to one API key
 * and logging every message here. Owners and admins only: they add one,
 * and pause or resume it at once (pausing is not a draft: it stops sends).
 */
import { Bot, UserRound } from "lucide-react";
import { useEffect, useState } from "react";

import { notify } from "../../notice-center";
import {
  createSender,
  OutreachError,
  pauseSender,
  readSenders,
  type SenderView,
  type TouchChannel,
} from "../../outreach/outreach-client";
import {
  readIntegrations,
  type ApiKey,
} from "../integrations/integrations-client";
import family from "../family.module.css";
import { Skeleton } from "../../ui/kit";
import { Sheet } from "../../ui/sheet";
import card from "./lead-split.module.css";
import styles from "./message-limits.module.css";

const CHANNELS: readonly { channel: TouchChannel; label: string }[] = [
  { channel: "whatsapp", label: "WhatsApp" },
  { channel: "sms", label: "SMS" },
  { channel: "email", label: "Email" },
];

const CHANNEL_WORDS: Record<string, string> = {
  whatsapp: "WhatsApp",
  sms: "SMS",
  email: "Email",
  messenger: "Messenger",
  instagram: "Instagram",
  call: "Calls",
};

/** "2 h ago", "3 days ago", "never". */
export function seenWords(at: string | null, now = Date.now()): string {
  if (!at) return "Not used yet";
  const minutes = Math.max(0, Math.round((now - Date.parse(at)) / 60_000));
  if (minutes < 2) return "Last seen just now";
  if (minutes < 60) return `Last seen ${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `Last seen ${hours} h ago`;
  const days = Math.round(hours / 24);
  return `Last seen ${days} ${days === 1 ? "day" : "days"} ago`;
}

/** Line 1: "WhatsApp · 42 this week" (a person's tool says whose first). */
export function senderLine(sender: SenderView): string {
  return [
    sender.kind === "person_tool" && sender.person_name
      ? `For ${sender.person_name}`
      : null,
    sender.channels
      .map((channel) => CHANNEL_WORDS[channel] ?? channel)
      .join(", "),
    `${sender.touches_week} this week`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Behind Details: "Short key sx-engage · API key sxk_live_9f3a…". */
export function senderDetails(sender: SenderView): string {
  return [
    `Short key ${sender.key}`,
    sender.api_key_prefix
      ? `API key ${sender.api_key_prefix}…`
      : "No API key yet",
    sender.guard_mode === "hold" ? "Holds at a limit" : "Logs and advises",
  ].join(" · ");
}

const slug = (words: string) =>
  words
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);

function AddSender({
  open,
  onClose,
  onAdded,
  people,
}: {
  open: boolean;
  onClose: () => void;
  onAdded: (sender: SenderView) => void;
  people: readonly { id: string; name: string }[];
}) {
  const [label, setLabel] = useState("");
  const [key, setKey] = useState("");
  const [keyTouched, setKeyTouched] = useState(false);
  const [kind, setKind] = useState<"automation" | "person_tool">("automation");
  const [person, setPerson] = useState("");
  const [channels, setChannels] = useState<TouchChannel[]>(["whatsapp"]);
  const [hold, setHold] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    const control = new AbortController();
    readIntegrations(control.signal).then(
      (found) => {
        if (control.signal.aborted) return;
        setKeys(
          found.keys.filter(
            (item) =>
              item.state === "active" && item.scopes.includes("outreach:write"),
          ),
        );
      },
      () => {
        if (!control.signal.aborted) setKeys([]);
      },
    );
    return () => control.abort();
  }, [open]);

  const shownKey = keyTouched ? key : slug(label);
  const ready =
    label.trim().length > 0 &&
    /^[a-z0-9][a-z0-9-]{1,39}$/.test(shownKey) &&
    channels.length > 0 &&
    (kind === "automation" || person !== "");

  const add = async () => {
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      const sender = await createSender({
        command_id: crypto.randomUUID(),
        key: shownKey,
        label: label.trim(),
        kind,
        person_id: kind === "person_tool" ? person : null,
        api_key_id: apiKey || null,
        channels,
        guard_mode: hold ? "hold" : "report",
      });
      onAdded(sender);
      onClose();
    } catch (reason) {
      setError(
        reason instanceof OutreachError
          ? reason.message
          : "Not added. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Add a message sender"
      description="A tool that messages leads for you. Every message it sends is logged on the lead."
      wide="center"
      footer={
        <div className={styles.sheetActions}>
          <button
            type="button"
            className={family.primary}
            disabled={!ready || busy}
            data-sx-feature="outreach_sender_added"
            onClick={() => void add()}
          >
            {busy ? "Adding…" : "Add sender"}
          </button>
        </div>
      }
    >
      <div className={styles.form}>
        <label className={styles.field}>
          <span>Name</span>
          <input
            value={label}
            maxLength={80}
            placeholder="Follow-up engine"
            onChange={(event) => setLabel(event.target.value)}
          />
          <small>What a lead&apos;s history says sent the message.</small>
        </label>
        <label className={styles.field}>
          <span>Short key</span>
          <input
            value={shownKey}
            maxLength={40}
            placeholder="follow-up-engine"
            onChange={(event) => {
              setKeyTouched(true);
              setKey(event.target.value.toLowerCase());
            }}
          />
          <small>Small letters, numbers and dashes. The tool sends it.</small>
        </label>
        <label className={styles.field}>
          <span>Who it sends for</span>
          <select
            value={kind}
            onChange={(event) =>
              setKind(event.target.value as "automation" | "person_tool")
            }
          >
            <option value="automation">An automation</option>
            <option value="person_tool">A person&apos;s own tool</option>
          </select>
        </label>
        {kind === "person_tool" ? (
          <label className={styles.field}>
            <span>Person</span>
            <select
              value={person}
              onChange={(event) => setPerson(event.target.value)}
            >
              <option value="">Pick a person</option>
              {people.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <div className={styles.field}>
          <span id="sender-channels">Channels</span>
          <div
            className={styles.chips}
            role="group"
            aria-labelledby="sender-channels"
          >
            {CHANNELS.map((item) => (
              <button
                key={item.channel}
                type="button"
                aria-pressed={channels.includes(item.channel)}
                onClick={() =>
                  setChannels((now) =>
                    now.includes(item.channel)
                      ? now.filter((value) => value !== item.channel)
                      : [...now, item.channel],
                  )
                }
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
        <label className={styles.field}>
          <span>API key</span>
          <select
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
          >
            <option value="">
              {keys === null ? "Loading keys…" : "Bind a key later"}
            </option>
            {(keys ?? []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.prefix}…)
              </option>
            ))}
          </select>
          <small>
            Only keys with the outreach scope. Make one in Settings ›
            Developers.
          </small>
        </label>
        <div className={styles.field}>
          <span id="sender-hold">At a limit</span>
          <div
            className={styles.chips}
            role="group"
            aria-labelledby="sender-hold"
          >
            <button
              type="button"
              aria-pressed={!hold}
              onClick={() => setHold(false)}
            >
              Log and advise
            </button>
            <button
              type="button"
              aria-pressed={hold}
              onClick={() => setHold(true)}
            >
              Hold the send
            </button>
          </div>
        </div>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </Sheet>
  );
}

export function MessageSenders({
  people = [],
}: {
  /** The team, for a person's own tool. */
  people?: readonly { id: string; name: string }[];
}) {
  const [senders, setSenders] = useState<SenderView[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    const control = new AbortController();
    readSenders(control.signal).then(
      (next) => {
        if (control.signal.aborted) return;
        setSenders(next);
        setFailed(false);
      },
      () => {
        if (!control.signal.aborted) setFailed(true);
      },
    );
    return () => control.abort();
  }, [attempt]);

  const toggle = async (sender: SenderView) => {
    setBusy(sender.sender_id);
    try {
      const next = await pauseSender(sender, sender.status === "active");
      setSenders((now) =>
        (now ?? []).map((item) =>
          item.sender_id === next.sender_id ? next : item,
        ),
      );
      notify({
        id: "message-senders",
        tone: "success",
        title:
          next.status === "paused"
            ? `${next.label} is paused`
            : `${next.label} is sending again`,
      });
    } catch (reason) {
      notify({
        id: "message-senders",
        tone: "error",
        title: "Not changed",
        message:
          reason instanceof OutreachError ? reason.message : "Try again.",
      });
    } finally {
      setBusy(null);
    }
  };

  if (!senders)
    return failed ? (
      <section className={card.card}>
        <h3 className={card.title}>Message senders</h3>
        <p className={card.sub}>The senders didn&apos;t load.</p>
        <button
          type="button"
          className={card.retry}
          onClick={() => setAttempt((value) => value + 1)}
        >
          Try again
        </button>
      </section>
    ) : (
      <div aria-busy="true" aria-label="Loading message senders">
        <Skeleton height={160} />
      </div>
    );

  return (
    <section className={card.card} aria-labelledby="message-senders-title">
      <div className={card.head}>
        <h3 id="message-senders-title" className={card.title}>
          Message senders
        </h3>
      </div>
      <p className={card.sub}>
        Tools that message leads for you. Each logs every message here and
        follows the limits above.
      </p>
      {senders.length ? (
        <ul className={styles.senders}>
          {senders.map((sender) => (
            <li key={sender.sender_id} className={styles.sender}>
              <span className={family.tile}>
                {sender.kind === "person_tool" ? (
                  <UserRound aria-hidden="true" />
                ) : (
                  <Bot aria-hidden="true" />
                )}
              </span>
              <span className={styles.senderText}>
                <span className={styles.senderName}>
                  {sender.label}
                  <span
                    className={styles.status}
                    data-tone={sender.status === "active" ? "good" : "amber"}
                  >
                    {sender.status === "active" ? "Sending" : "Paused"}
                  </span>
                </span>
                <span className={styles.senderLine}>{senderLine(sender)}</span>
                <span className={styles.senderSeen}>
                  {seenWords(sender.last_seen_at)}
                </span>
                <details className={styles.senderDetails}>
                  <summary>Details</summary>
                  <span>{senderDetails(sender)}</span>
                </details>
              </span>
              <button
                type="button"
                className={styles.small}
                disabled={busy === sender.sender_id}
                data-sx-feature="outreach_sender_paused"
                onClick={() => void toggle(sender)}
              >
                {sender.status === "active" ? "Pause" : "Resume"}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className={card.sub}>
          No senders yet. Add one so the messages your tools send count here
          too.
        </p>
      )}
      <button
        type="button"
        className={styles.add}
        onClick={() => setAdding(true)}
      >
        Add a sender
      </button>
      <AddSender
        open={adding}
        onClose={() => setAdding(false)}
        people={people}
        onAdded={(sender) => setSenders((now) => [...(now ?? []), sender])}
      />
    </section>
  );
}
