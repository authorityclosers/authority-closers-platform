"use client";

/**
 * Lead rules › Message limits (v1.95, owner 22 Nov 2026: "every message we
 * send is tracked, so we never feel spammy"). How often one lead may hear
 * from the team, the rest after unanswered messages, and what each channel
 * does at a limit: count it, warn, or hold the send. A draft like the rest
 * of the page; the page's one Save sends it (PUT /outreach/rules, revision
 * safe, the same revision as the team's lead settings).
 */
import { Check, Minus, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { notify } from "../../notice-center";
import {
  OutreachError,
  readOutreachRules,
  saveOutreachRules,
  type OutreachMode,
  type OutreachRules,
  type OutreachRulesChange,
} from "../../outreach/outreach-client";
import { Skeleton } from "../../ui/kit";
import card from "./lead-split.module.css";
import { OnOff } from "./on-off";
import styles from "./message-limits.module.css";
import rules from "./rules.module.css";

type Modes = OutreachRules["modes"];

export type LimitsDraft = {
  enabled: boolean;
  per_day: number;
  per_week: number;
  rest_after: number;
  rest_days: number;
  modes: Modes;
};

/** The channels the card lists, each one row (WhatsApp twice: people, automations). */
export const CHANNEL_ROWS: readonly {
  channel: string;
  side: "people" | "automations" | "both";
  label: string;
}[] = [
  { channel: "whatsapp", side: "people", label: "WhatsApp, people" },
  {
    channel: "whatsapp",
    side: "automations",
    label: "WhatsApp, automations",
  },
  { channel: "sms", side: "both", label: "SMS" },
  { channel: "email", side: "both", label: "Email" },
  { channel: "messenger", side: "both", label: "Messenger" },
  { channel: "instagram", side: "both", label: "Instagram" },
  { channel: "call", side: "both", label: "Calls" },
];

/** What a channel does at a limit, in plain words. */
const CHOICES: readonly { mode: OutreachMode; label: string }[] = [
  { mode: "show", label: "Count" },
  { mode: "warn", label: "Warn" },
  { mode: "block", label: "Hold" },
];

const draftOf = (from: OutreachRules): LimitsDraft => ({
  enabled: from.enabled,
  per_day: from.per_day,
  per_week: from.per_week,
  rest_after: from.rest_after,
  rest_days: from.rest_days,
  modes: Object.fromEntries(
    Object.entries(from.modes).map(([channel, mode]) => [channel, { ...mode }]),
  ),
});

/** Only what changed, so a field someone else saved meanwhile stays. */
export function limitsChange(
  saved: OutreachRules,
  draft: LimitsDraft,
  revision: number,
): OutreachRulesChange | null {
  const change: OutreachRulesChange = { expected_revision: revision };
  let any = false;
  for (const name of [
    "enabled",
    "per_day",
    "per_week",
    "rest_after",
    "rest_days",
  ] as const) {
    if (draft[name] !== saved[name]) {
      (change as Record<string, unknown>)[name] = draft[name];
      any = true;
    }
  }
  const modes: Modes = {};
  for (const [channel, mode] of Object.entries(draft.modes)) {
    const was = saved.modes[channel];
    if (
      !was ||
      was.people !== mode.people ||
      was.automations !== mode.automations
    )
      modes[channel] = mode;
  }
  if (Object.keys(modes).length) {
    change.modes = modes;
    any = true;
  }
  return any ? change : null;
}

export type MessageLimitsState = ReturnType<typeof useMessageLimits>;

export function useMessageLimits(enabled = true) {
  const [saved, setSaved] = useState<OutreachRules | null>(null);
  const [draft, setDraft] = useState<LimitsDraft | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    const control = new AbortController();
    readOutreachRules(control.signal).then(
      (next) => {
        if (control.signal.aborted) return;
        setSaved(next);
        setDraft(draftOf(next));
        setFailed(false);
      },
      () => {
        if (!control.signal.aborted) setFailed(true);
      },
    );
    return () => control.abort();
  }, [attempt, enabled]);

  const change = useMemo(
    () => (saved && draft ? limitsChange(saved, draft, saved.revision) : null),
    [saved, draft],
  );

  /**
   * Saves on `revision` when the team's settings were just saved (one
   * revision for both), else on the one read; the revision after, or false.
   */
  const save = async (revision?: number): Promise<number | true | false> => {
    if (!saved || !draft) return true;
    const body = limitsChange(saved, draft, revision ?? saved.revision);
    if (!body) return true;
    setBusy(true);
    try {
      const next = await saveOutreachRules(body);
      setSaved(next);
      setDraft(draftOf(next));
      return next.revision;
    } catch (reason) {
      notify({
        id: "message-limits",
        tone: "error",
        title: "Message limits not saved",
        message:
          reason instanceof OutreachError ? reason.message : "Try again.",
      });
      return false;
    } finally {
      setBusy(false);
    }
  };

  return {
    saved,
    draft,
    failed,
    busy,
    retry: () => setAttempt((value) => value + 1),
    set: (part: Partial<LimitsDraft>) =>
      setDraft((now) => (now ? { ...now, ...part } : now)),
    setMode: (
      channel: string,
      side: "people" | "automations" | "both",
      mode: OutreachMode,
    ) =>
      setDraft((now) => {
        if (!now) return now;
        const was = now.modes[channel] ?? {
          people: "show" as OutreachMode,
          automations: "show" as OutreachMode,
        };
        const next =
          side === "both"
            ? { people: mode, automations: mode }
            : { ...was, [side]: mode };
        return { ...now, modes: { ...now.modes, [channel]: next } };
      }),
    changed: change !== null,
    /** The team's settings were saved: the same revision moved on. */
    adoptRevision: (revision: number) =>
      setSaved((now) => (now ? { ...now, revision } : now)),
    discard: () => {
      if (saved) setDraft(draftOf(saved));
    },
    save,
  };
}

/** "Up to [− 1 +] a day": one clean row that never wraps. */
function Count({
  before,
  after,
  value,
  min,
  max,
  label,
  disabled,
  onChange,
}: {
  before: string;
  after: string;
  value: number;
  min: number;
  max: number;
  label: string;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <div className={rules.wait}>
      <span className={styles.before}>{before}</span>
      <span className={rules.stepper}>
        <button
          type="button"
          aria-label={`${label}: one less`}
          disabled={disabled || value <= min}
          onClick={() => onChange(Math.max(min, value - 1))}
        >
          <Minus size={18} aria-hidden="true" />
        </button>
        <input
          aria-label={label}
          type="number"
          inputMode="numeric"
          min={min}
          max={max}
          value={value}
          disabled={disabled}
          onChange={(event) => {
            const next = Number(event.target.value);
            if (Number.isFinite(next))
              onChange(Math.min(max, Math.max(min, Math.round(next))));
          }}
        />
        <button
          type="button"
          aria-label={`${label}: one more`}
          disabled={disabled || value >= max}
          onClick={() => onChange(Math.min(max, value + 1))}
        >
          <Plus size={18} aria-hidden="true" />
        </button>
      </span>
      <span>{after}</span>
    </div>
  );
}

/** Count | Warn | Hold for one channel. */
function ModePills({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: OutreachMode;
  disabled: boolean;
  onChange: (mode: OutreachMode) => void;
}) {
  return (
    <div className={styles.pills} role="group" aria-label={label}>
      {CHOICES.map((choice) => (
        <button
          key={choice.mode}
          type="button"
          aria-pressed={value === choice.mode}
          disabled={disabled}
          onClick={() => onChange(choice.mode)}
        >
          {choice.label}
        </button>
      ))}
    </div>
  );
}

/** The plain sentence the preview and the card share: "Up to 1 a day, 3 a week". */
export function limitsWords(draft: LimitsDraft): string {
  if (!draft.enabled) return "Counted, never held";
  const rest = draft.rest_after
    ? `, rest ${draft.rest_days} days after ${draft.rest_after} unanswered`
    : "";
  return `Up to ${draft.per_day} a day, ${draft.per_week} a week${rest}`;
}

export function MessageLimitsCard({ limits }: { limits: MessageLimitsState }) {
  const { saved, draft } = limits;
  if (!saved || !draft)
    return limits.failed ? (
      <section className={card.card}>
        <h3 className={card.title}>Message limits</h3>
        <p className={card.sub}>The message limits didn&apos;t load.</p>
        <button type="button" className={card.retry} onClick={limits.retry}>
          Try again
        </button>
      </section>
    ) : (
      <div aria-busy="true" aria-label="Loading message limits">
        <Skeleton height={260} />
      </div>
    );
  const off = !saved.can_edit || limits.busy;
  const valueOf = (channel: string, side: "people" | "automations" | "both") =>
    draft.modes[channel]?.[side === "both" ? "people" : side] ?? "show";
  return (
    <section
      className={card.card}
      aria-labelledby="message-limits-title"
      data-off={draft.enabled ? undefined : ""}
    >
      <div className={card.head}>
        <h3 id="message-limits-title" className={card.title}>
          Message limits
        </h3>
        <OnOff
          label="Message limits"
          on={draft.enabled}
          disabled={off}
          feature="lead_rules_message_limits_switch"
          onChange={(enabled) => limits.set({ enabled })}
        />
      </div>
      <p className={card.sub}>
        {draft.enabled
          ? "Every message to a lead is counted. Past a limit the app warns, or holds the send."
          : "Off: every message is still counted and shown, but nothing is warned or held."}
      </p>
      <div className={styles.counts}>
        <Count
          before="Up to"
          after="a day"
          label="Messages a day"
          value={draft.per_day}
          min={1}
          max={10}
          disabled={off || !draft.enabled}
          onChange={(per_day) => limits.set({ per_day })}
        />
        <Count
          before="Up to"
          after="a week"
          label="Messages a week"
          value={draft.per_week}
          min={1}
          max={30}
          disabled={off || !draft.enabled}
          onChange={(per_week) => limits.set({ per_week })}
        />
        <Count
          before="After"
          after="unanswered"
          label="Unanswered before a rest"
          value={draft.rest_after}
          min={0}
          max={20}
          disabled={off || !draft.enabled}
          onChange={(rest_after) => limits.set({ rest_after })}
        />
        {draft.rest_after > 0 ? (
          <Count
            before="Rest"
            after="days"
            label="Days of rest"
            value={draft.rest_days}
            min={1}
            max={90}
            disabled={off || !draft.enabled}
            onChange={(rest_days) => limits.set({ rest_days })}
          />
        ) : null}
      </div>
      <ul className={styles.facts}>
        <li>
          <Check aria-hidden="true" />
          <span>
            A reply in the last 24 hours doesn&apos;t count: a conversation is
            never spam.
          </span>
        </li>
        <li>
          <Check aria-hidden="true" />
          <span>
            STOP always holds. Nothing goes to a lead who said stop on that
            channel.
          </span>
        </li>
        <li>
          <Check aria-hidden="true" />
          <span>
            Owners, admins and managers can send past a limit once, with a
            reason. Sellers ask a manager.
          </span>
        </li>
      </ul>
      <div className={styles.channels}>
        <h4 className={styles.channelsTitle}>At a limit</h4>
        <p className={styles.channelsSub}>
          Count: shown only. Warn: the sender sees why first. Hold: the send
          waits.
        </p>
        <ul className={styles.channelList}>
          {CHANNEL_ROWS.map((row) => (
            <li key={`${row.channel}:${row.side}`} className={styles.channel}>
              <span className={styles.channelName}>{row.label}</span>
              <ModePills
                label={row.label}
                value={valueOf(row.channel, row.side)}
                disabled={off || !draft.enabled}
                onChange={(mode) => limits.setMode(row.channel, row.side, mode)}
              />
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
