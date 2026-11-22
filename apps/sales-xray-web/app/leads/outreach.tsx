"use client";

/**
 * The outreach log on a lead (v1.95, owner 22 Nov 2026: "every message we send
 * is tracked, so we never feel spammy"; spec boards/sx-redesign/review/
 * v195-outreach-log-spec.md §4.2): the counter line (the server's own words,
 * with an amber chip on a warning and a red one on a hold), the same line
 * before every send, a manager's "Send anyway" with its reason, the touch lines
 * in the lead's history and the touch sheet. The server decides; this only says.
 */

import {
  Check,
  Circle,
  Handshake,
  Mail,
  MessageCircle,
  MessageSquareText,
  Phone,
  Send,
} from "lucide-react";
import { Fragment, useEffect, useState, type ReactNode } from "react";

import { notify } from "../notice-center";
import { Button } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import {
  grantOverride,
  LeadsError,
  readOutreach,
  readTouches,
  when,
  type OutreachChannel,
  type OutreachGuard,
  type OverrideReason,
  type TouchView,
} from "./leads-client";
import { WhatsAppGlyph } from "./whatsapp-glyph";
import styles from "./outreach.module.css";

/* ---------- Words ---------- */

const CHANNEL_WORDS: Record<OutreachChannel, string> = {
  whatsapp: "WhatsApp",
  sms: "SMS",
  email: "Email",
  call: "Call",
  messenger: "Messenger",
  instagram: "Instagram",
  in_person: "In person",
  other: "Message",
};

const STATUS_WORDS: Record<string, string> = {
  queued: "Waiting to send",
  opened: "Opened in the app",
  sent: "Sent",
  delivered: "Delivered",
  read: "Read",
  failed: "Failed",
  expired: "Not sent",
};

const AUTOMATION_WORDS: Record<string, string> = {
  first_reply: "First reply",
  out_of_hours: "After-hours reply",
  ai_reply: "AI reply",
  drip: "Drip",
  broadcast: "Broadcast",
};

const OVERRIDE_REASONS: { key: OverrideReason; label: string }[] = [
  { key: "lead_asked", label: "The lead asked for it" },
  { key: "time_sensitive", label: "Time-sensitive: a quote or a meeting" },
  { key: "wrong_count", label: "The count is wrong" },
  { key: "other", label: "Something else" },
];

const OVERRIDE_SAID: Record<string, string> = {
  lead_asked: "lead asked for it",
  time_sensitive: "time-sensitive",
  wrong_count: "the count was wrong",
};

/** Who sent a touch: the person, else the automation or the outside tool. */
export function touchSender(touch: TouchView): string {
  if (touch.sender_type === "automation")
    return (
      touch.sender_label ??
      (touch.automation
        ? (AUTOMATION_WORDS[touch.automation] ?? touch.automation)
        : "An automation")
    );
  return touch.by_name ?? touch.sender_label ?? "Someone";
}

/** What went: our own summary, else the file's or the template's name. */
export function touchWhat(touch: TouchView): string | null {
  return (
    touch.summary?.trim() ||
    touch.attachment?.name ||
    touch.template_name ||
    null
  );
}

/** "Sent anyway by Shivam · lead asked for it", for a send past a hold: the
 *  Outreach page's own words for it (v1.95 judge round 1: one phrase). */
export function pastLimitWords(touch: TouchView): string | null {
  if (!touch.after_block) return null;
  const who = touch.override_by_name ?? touchSender(touch);
  const why = touch.override_reason
    ? (OVERRIDE_SAID[touch.override_reason] ?? touch.override_reason)
    : null;
  return `Sent anyway by ${who}${why ? ` · ${why}` : ""}`;
}

/** The chip on a warning or a hold: a few words for the reason that holds. */
export function chipWords(guard: OutreachGuard): string | null {
  if (guard.verdict === "ok") return null;
  const reason =
    guard.reasons.find((item) => item.level === guard.verdict) ??
    guard.reasons[0];
  switch (reason?.code) {
    case "week_cap":
      return `${guard.counts?.week ?? 3} this week`;
    case "day_cap":
      return "Touched today";
    case "rest":
      return "Resting";
    case "opted_out":
      return "Said stop";
    case "quiet":
      return "Outside sending hours";
    case "in_bin":
      return "In the Bin";
    case "archived":
      return "Archived";
    case "history":
      return "Past lead";
    case "test_data":
      return "Test lead";
    default:
      return guard.verdict === "block" ? "Held" : "Check first";
  }
}

/** Why, and when it is OK again ("3 touches in the last 7 days · OK again
 *  Mon 10:00 am"); a STOP is never OK again by waiting. */
export function whyWords(guard: OutreachGuard): string | null {
  if (guard.verdict === "ok") return null;
  const reason =
    guard.reasons.find((item) => item.level === guard.verdict) ??
    guard.reasons[0];
  // The count is in the counter and the chip already: said once (v1.95 judge).
  const said =
    reason?.code === "week_cap"
      ? "At the weekly limit"
      : reason?.code === "day_cap"
        ? "Touched once today already"
        : (reason?.words ?? null);
  const parts = [said];
  if (guard.opted_out) parts.push("nobody can send past a stop");
  // A rest already says until when.
  else if (guard.next_ok_at && reason?.code !== "rest")
    parts.push(`OK again ${when(guard.next_ok_at)}`);
  else if (guard.quiet_until)
    parts.push(`sending hours start ${when(guard.quiet_until)}`);
  return parts.filter(Boolean).join(" · ") || null;
}

/** A send this guard holds: a hold not passed by a manager's override. */
export const isHeld = (guard: OutreachGuard | null | undefined) =>
  guard?.verdict === "block" && !guard.override_id;

/** A manager may pass this hold once (never a STOP). */
export const canPass = (
  guard: OutreachGuard | null | undefined,
  manager: boolean,
) =>
  manager && isHeld(guard) && !guard?.opted_out && !!guard?.override?.possible;

function ChannelIcon({
  channel,
  size = 16,
}: {
  channel: OutreachChannel;
  size?: number;
}) {
  switch (channel) {
    case "whatsapp":
      return <WhatsAppGlyph size={size} />;
    case "sms":
      return <MessageSquareText size={size} aria-hidden="true" />;
    case "email":
      return <Mail size={size} aria-hidden="true" />;
    case "call":
      return <Phone size={size} aria-hidden="true" />;
    case "in_person":
      return <Handshake size={size} aria-hidden="true" />;
    case "messenger":
    case "instagram":
      return <MessageCircle size={size} aria-hidden="true" />;
    default:
      return <Send size={size} aria-hidden="true" />;
  }
}

/* ---------- The counter line ---------- */

/**
 * "Last touched 2 days ago · 3 touches this week · 2 calls", with an amber
 * chip on a warning and a red one on a hold, and why and when it is OK again.
 * The same line on the lead and before every send.
 */
export function OutreachLine({
  guard,
  onOpen,
  label,
}: {
  guard: OutreachGuard;
  /** Opens the lead's touches (the touch sheet). */
  onOpen?: () => void;
  /** Before a send: which channel the line is for ("WhatsApp"). */
  label?: string;
}) {
  const chip = chipWords(guard);
  const why = whyWords(guard);
  return (
    <div
      className={styles.line}
      data-verdict={guard.verdict}
      data-sx-feature="outreach_line"
    >
      <p className={styles.counter}>
        <span className={styles.icon} aria-hidden="true">
          <ChannelIcon channel={guard.channel} size={14} />
        </span>
        <span className={styles.words}>
          {label ? <strong>{label}: </strong> : null}
          {/* Each part keeps its words together: a line breaks at a dot. */}
          {guard.words.split(" · ").map((part, index) => (
            <Fragment key={index}>
              {index ? " · " : null}
              <span className={styles.part}>{part}</span>
            </Fragment>
          ))}
          {chip ? (
            <>
              {" "}
              <span className={styles.chip} data-verdict={guard.verdict}>
                {chip}
              </span>
            </>
          ) : null}
        </span>
        {onOpen ? (
          <button
            type="button"
            className={styles.open}
            data-sx-feature="outreach_touches_open"
            onClick={onOpen}
          >
            Touches
          </button>
        ) : null}
      </p>
      {why ? (
        <p
          className={styles.why}
          role={guard.verdict === "block" ? "status" : undefined}
        >
          {why}
        </p>
      ) : null}
    </div>
  );
}

/** The guard for one lead and channel, read when asked for (null: none yet). */
export function useOutreach(
  leadId: string | null,
  channel: OutreachChannel,
  initial: OutreachGuard | null = null,
) {
  const [read, setRead] = useState<{
    key: string;
    guard: OutreachGuard | null;
  } | null>(null);
  const [round, setRound] = useState(0);
  const key = `${leadId}:${channel}`;
  useEffect(() => {
    if (!leadId) return;
    const controller = new AbortController();
    readOutreach(leadId, channel, controller.signal).then(
      (guard) => setRead({ key, guard }),
      () => undefined,
    );
    return () => controller.abort();
  }, [leadId, channel, key, round]);
  const fallback = initial && initial.channel === channel ? initial : null;
  return {
    guard: read?.key === key ? read.guard : fallback,
    reload: () => setRound((value) => value + 1),
  };
}

/* ---------- Send anyway (managers) ---------- */

/**
 * A manager passes a hold once, with a reason (spec §4.4): 30 minutes, one
 * send; the history says "Sent anyway by …". A STOP has none. In the send's own
 * place (the message sheet, the WhatsApp thread), never a second sheet over it.
 */
export function OverrideForm({
  leadId,
  guard,
  onCancel,
  onGranted,
}: {
  leadId: string;
  guard: OutreachGuard;
  onCancel: () => void;
  onGranted: () => void;
}) {
  const [reason, setReason] = useState<OverrideReason | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const needsText = reason === "other" && !text.trim();
  const grant = async () => {
    if (!reason || needsText || busy) return;
    setBusy(true);
    try {
      await grantOverride(leadId, {
        channel: guard.channel,
        reason_key: reason,
        reason_text: text.trim() || undefined,
      });
      setReason(null);
      setText("");
      onGranted();
    } catch (problem) {
      notify({
        id: "outreach-override",
        tone: "error",
        title: "Not allowed",
        message:
          problem instanceof LeadsError
            ? problem.message
            : "That didn't work. Try again.",
      });
    } finally {
      setBusy(false);
    }
  };
  const textId = `${leadId}-override-text`;
  return (
    <div className={styles.override} data-sx-feature="outreach_override">
      <p className={styles.label}>Why send past the limit?</p>
      <div className={styles.reasons} role="radiogroup" aria-label="Why">
        {OVERRIDE_REASONS.map((item) => (
          <button
            key={item.key}
            type="button"
            role="radio"
            aria-checked={reason === item.key}
            className={styles.reason}
            disabled={busy}
            onClick={() => setReason(item.key)}
          >
            <span>{item.label}</span>
            {reason === item.key ? (
              <Check
                className={styles.chosen}
                size={20}
                strokeWidth={2.5}
                aria-hidden="true"
              />
            ) : (
              <Circle className={styles.free} size={20} aria-hidden="true" />
            )}
          </button>
        ))}
      </div>
      <label className={styles.label} htmlFor={textId}>
        {reason === "other" ? "Why, in a few words" : "Note (optional)"}
      </label>
      <textarea
        id={textId}
        className={styles.note}
        value={text}
        maxLength={200}
        rows={2}
        onChange={(event) => setText(event.target.value)}
      />
      <p className={styles.small}>
        It allows one send in the next 30 minutes, and the history says who
        allowed it and why.
      </p>
      <div className={styles.overrideActions}>
        <Button variant="secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </Button>
        <Button
          variant="primary"
          className={styles.green}
          disabled={!reason || needsText || busy}
          data-sx-feature="outreach_send_anyway"
          onClick={() => void grant()}
        >
          {busy ? "Allowing…" : "Send anyway"}
        </Button>
      </div>
    </div>
  );
}

/** The same, as a sheet of its own where there is no send sheet (Email from More). */
export function OverrideSheet({
  open,
  leadId,
  name,
  guard,
  onClose,
  onGranted,
}: {
  open: boolean;
  leadId: string;
  name: string;
  guard: OutreachGuard;
  onClose: () => void;
  onGranted: () => void;
}) {
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={`Send to ${name} anyway?`}
      wide="center"
      className={styles.opaque}
    >
      <OutreachLine guard={guard} label={CHANNEL_WORDS[guard.channel]} />
      <OverrideForm
        leadId={leadId}
        guard={guard}
        onCancel={onClose}
        onGranted={onGranted}
      />
    </Sheet>
  );
}

const firstWord = (name: string) => name.trim().split(/\s+/)[0] || name;

/**
 * Before a send: the line, and on a hold either "Send anyway" (a manager, in
 * the send's own place) or why, and one way on: a follow-up when it is OK again
 * (everyone else). `children` is the send itself, shown unless it is held.
 */
export function SendGuard({
  leadId,
  name,
  guard,
  manager,
  onPassed,
  onFollowUp,
  children,
}: {
  leadId: string;
  name: string;
  guard: OutreachGuard | null;
  manager: boolean;
  /** The override went through: read the guard again. */
  onPassed: () => void;
  /** Held: book the next call for when it is OK again (until "Ask a manager"). */
  onFollowUp?: (at: Date) => Promise<void>;
  children: ReactNode;
}) {
  const [passing, setPassing] = useState(false);
  const [booking, setBooking] = useState(false);
  if (!guard) return <>{children}</>;
  const held = isHeld(guard);
  const okAt = guard.next_ok_at ? new Date(guard.next_ok_at) : null;
  return (
    <div className={styles.gate}>
      <OutreachLine guard={guard} label={CHANNEL_WORDS[guard.channel]} />
      {!held ? (
        children
      ) : canPass(guard, manager) ? (
        passing ? (
          <OverrideForm
            leadId={leadId}
            guard={guard}
            onCancel={() => setPassing(false)}
            onGranted={() => {
              setPassing(false);
              onPassed();
            }}
          />
        ) : (
          <button
            type="button"
            className={styles.anyway}
            data-sx-feature="outreach_send_anyway_open"
            onClick={() => setPassing(true)}
          >
            Send anyway
          </button>
        )
      ) : (
        <>
          <p className={styles.held} data-sx-feature="outreach_held">
            {guard.opted_out
              ? `${firstWord(name)} said stop on this channel, so nothing more goes out here.`
              : `Held for now, so ${firstWord(name)} never feels chased. A manager can send it anyway.`}
          </p>
          {okAt && onFollowUp && !guard.opted_out ? (
            <button
              type="button"
              className={styles.followUp}
              disabled={booking}
              data-sx-feature="outreach_held_follow_up"
              onClick={() => {
                setBooking(true);
                void onFollowUp(okAt).finally(() => setBooking(false));
              }}
            >
              {booking
                ? "Setting…"
                : `Set follow-up for ${when(okAt.toISOString())}`}
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}

/* ---------- Touch lines and the touch sheet ---------- */

/** A history line's touch: who, what, its delivery and the reply. */
export function TouchLine({
  touch,
  actor = null,
  icon = true,
}: {
  /** The channel's small icon (none where a tile shows it already). */
  icon?: boolean;
  touch: TouchView;
  /** Whom the history line already names: not said twice. */
  actor?: string | null;
}) {
  const what = touchWhat(touch);
  const past = pastLimitWords(touch);
  const sender = touchSender(touch);
  return (
    <span className={styles.touch} data-sx-feature="outreach_touch_line">
      <span className={styles.touchMain}>
        {icon ? (
          <span className={styles.touchIcon} aria-hidden="true">
            <ChannelIcon channel={touch.channel} size={13} />
          </span>
        ) : null}
        <span>
          {[sender === actor ? null : sender, what ? `“${what}”` : null]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </span>
      <span className={styles.touchMeta}>
        <span data-status={touch.status}>
          {STATUS_WORDS[touch.status] ?? touch.status}
        </span>
        {touch.replied_at ? (
          <span className={styles.replied}>
            Replied {when(touch.replied_at)}
          </span>
        ) : null}
        {!touch.counted && touch.initiated === "reply" ? (
          <span>A reply · not counted</span>
        ) : null}
      </span>
      {past ? <span className={styles.past}>{past}</span> : null}
    </span>
  );
}

/** Every touch on the lead, newest first, a page at a time. */
export function TouchSheet({
  open,
  leadId,
  name,
  guard,
  onClose,
}: {
  open: boolean;
  leadId: string;
  name: string;
  guard?: OutreachGuard | null;
  onClose: () => void;
}) {
  const [pages, setPages] = useState<{
    leadId: string;
    touches: TouchView[];
    next: string | null;
  } | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const mine = pages?.leadId === leadId ? pages : null;
  const load = (cursor: string | null) => {
    setState("loading");
    readTouches(leadId, cursor).then(
      (page) => {
        setPages((current) => ({
          leadId,
          touches: [
            ...(cursor && current?.leadId === leadId ? current.touches : []),
            ...page.touches,
          ],
          next: page.next_cursor,
        }));
        setState("idle");
      },
      () => setState("error"),
    );
  };
  useEffect(() => {
    if (!open) return;
    let live = true;
    readTouches(leadId, null).then(
      (page) =>
        live &&
        setPages({ leadId, touches: page.touches, next: page.next_cursor }),
      () => live && setState("error"),
    );
    return () => {
      live = false;
    };
  }, [open, leadId]);
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={`Touches with ${name}`}
      wide="right"
      className={styles.opaque}
    >
      {guard ? <OutreachLine guard={guard} /> : null}
      {mine === null && state !== "error" ? (
        <p className={styles.small} aria-busy="true">
          Reading the touches…
        </p>
      ) : null}
      {mine && !mine.touches.length ? (
        <p className={styles.small}>Nothing sent to {name} yet.</p>
      ) : null}
      {mine?.touches.length ? (
        <ol className={styles.list}>
          {mine.touches.map((touch) => (
            <li key={touch.touch_id} className={styles.item}>
              <span className={styles.itemIcon} aria-hidden="true">
                <ChannelIcon channel={touch.channel} size={18} />
              </span>
              <span className={styles.itemWords}>
                <strong>
                  {CHANNEL_WORDS[touch.channel]} ·{" "}
                  <time dateTime={touch.sent_at}>{when(touch.sent_at)}</time>
                </strong>
                <TouchLine touch={touch} icon={false} />
              </span>
            </li>
          ))}
        </ol>
      ) : null}
      {state === "error" ? (
        <p className={styles.small} role="alert">
          The touches didn&apos;t load.
        </p>
      ) : null}
      {mine?.next ? (
        <Button
          variant="secondary"
          className={styles.older}
          disabled={state === "loading"}
          onClick={() => load(mine.next)}
        >
          {state === "loading" ? "Reading…" : "Show older"}
        </Button>
      ) : null}
    </Sheet>
  );
}
