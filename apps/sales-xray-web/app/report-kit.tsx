"use client";

import { Check, Copy, Info, Lock, type LucideIcon } from "lucide-react";
import {
  useId,
  useMemo,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { voicesOf } from "./call-data";
import {
  formatClipRange,
  isPlayableRange,
  spokenClipRange,
} from "./lightbox/time";
import type { ReportEvidence, Transcript } from "./report-contract";
import { RichText, type EntityKind } from "./report-entities";
import { confirmedRoles } from "./sales-signals";
import { getShellState } from "./shell/shell-store";
import type { ContextualSourcePlayback } from "./source-playback-context";
import { ClipPlayIcon, ClipPlayState } from "./source-waveform";
import { SpeakerAvatar } from "./speaker-avatar";
import { speakerName, useSpeakerProfiles } from "./speaker-profiles";
import styles from "./report-kit.module.css";

// The report's shared building blocks, so every tab reads the same way:
// calm surfaces, one colour per meaning shown as a small accent, the speaker
// beside every quote, one play control, and long text folded until asked for.

/** One colour per meaning, used the same way on every tab. */
export type Tone =
  | "strength"
  | "change"
  | "missed"
  | "objection"
  | "closing"
  | "hypothesis"
  | "info"
  | "teal"
  | "neutral";

export type Person = {
  id: string;
  name: string;
  avatar: (size: number) => ReactNode;
};

/** Who said what, from this call's names and roles (never guessed). */
export function useReportPeople(callId: string | null, transcript: Transcript) {
  const { profiles } = useSpeakerProfiles(callId);
  const accountName = getShellState().profileName;
  const voices = useMemo(() => voicesOf(transcript), [transcript]);
  const speakerBySegment = useMemo(
    () =>
      new Map(
        transcript.segments.map((segment) => [segment.id, segment.speaker_id]),
      ),
    [transcript],
  );
  const roles = confirmedRoles(
    voices,
    Object.fromEntries(voices.map((id) => [id, profiles[id]?.role])),
  );
  const person = (id: string | null | undefined): Person | null => {
    if (!id || !voices.includes(id)) return null;
    const voice = voices.indexOf(id);
    return {
      id,
      name: speakerName(voice, profiles[id], accountName),
      avatar: (size: number) => (
        <SpeakerAvatar
          voice={voice}
          profile={profiles[id]}
          youName={accountName}
          size={size}
        />
      ),
    };
  };
  const speakerOf = (evidence: ReportEvidence | undefined) =>
    evidence ? person(speakerBySegment.get(evidence.segment_id)) : null;
  return {
    roles,
    person,
    speakerOf,
    prospect: person(roles?.prospect),
    seller: person(roles?.seller),
  };
}

// A superellipse ("squircle"): softer than a rounded square.
const SQUIRCLE =
  "M20 0C33.6 0 40 6.4 40 20S33.6 40 20 40 0 33.6 0 20 6.4 0 20 0Z";

/**
 * Our icon mark: a line icon on a soft squircle in its tone's colour, with a
 * light top gradient. Used in place of emoji everywhere in the report.
 */
export function IconBadge({
  icon: Glyph,
  tone = "neutral",
  size = 32,
}: {
  icon: LucideIcon;
  tone?: Tone;
  size?: number;
}) {
  const id = useId();
  return (
    <span
      className={`${styles.badge} ${styles.tone}`}
      data-tone={tone}
      style={{ "--size": `${size}px` } as CSSProperties}
      aria-hidden="true"
    >
      <svg viewBox="0 0 40 40" width={size} height={size}>
        <defs>
          <linearGradient id={`${id}-fill`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" className={styles.badgeTop} />
            <stop offset="1" className={styles.badgeBottom} />
          </linearGradient>
        </defs>
        <path d={SQUIRCLE} fill={`url(#${id}-fill)`} />
        <path d={SQUIRCLE} className={styles.badgeEdge} />
      </svg>
      <Glyph size={Math.round(size * 0.5)} strokeWidth={2} />
    </span>
  );
}

/**
 * A tab section: an icon mark or a step number, a title, a one-line hint,
 * an optional count and action.
 */
export function KitSection({
  icon,
  step,
  title,
  hint,
  count,
  action,
  tone = "neutral",
  index = 0,
  children,
}: {
  icon?: LucideIcon;
  step?: number;
  title: string;
  hint?: ReactNode;
  count?: number;
  action?: ReactNode;
  tone?: Tone;
  index?: number;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section
      className={`${styles.section} ${styles.tone}`}
      aria-labelledby={id}
      data-tone={tone}
      style={{ "--i": index } as CSSProperties}
    >
      <header className={styles.head}>
        {step !== undefined ? (
          <span className={styles.step} aria-hidden="true">
            {step}
          </span>
        ) : icon ? (
          <IconBadge icon={icon} tone={tone} size={30} />
        ) : null}
        <span className={styles.headText}>
          <h3 id={id}>
            {title}
            {count !== undefined ? (
              <em className={styles.count}>{count}</em>
            ) : null}
          </h3>
          {hint ? <small>{hint}</small> : null}
        </span>
        {action ? <span className={styles.action}>{action}</span> : null}
      </header>
      {children}
    </section>
  );
}

/** A calm card; its tone shows only as a thin accent and its tag. */
export function Card({
  tone = "neutral",
  children,
  className,
  index = 0,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  index?: number;
}) {
  return (
    <article
      className={`${styles.card} ${styles.tone} ${className ?? ""}`}
      data-tone={tone}
      style={{ "--i": index } as CSSProperties}
    >
      {children}
    </article>
  );
}

/**
 * A card's words and its evidence. Side by side when the card is wide
 * enough, stacked when it is not; the card decides, whatever the screen.
 */
export function Split({ main, aside }: { main: ReactNode; aside: ReactNode }) {
  return (
    <div className={styles.split}>
      <div>{main}</div>
      <div>{aside}</div>
    </div>
  );
}

/** A small label in a tone, with an optional line icon. */
export function Tag({
  tone = "neutral",
  icon: Glyph,
  children,
}: {
  tone?: Tone;
  icon?: LucideIcon;
  children: ReactNode;
}) {
  return (
    <span className={`${styles.tag} ${styles.tone}`} data-tone={tone}>
      {Glyph ? <Glyph size={12} strokeWidth={2.2} aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

// Quotes are spoken words: only mentions worth a glance become chips.
const QUOTE_KINDS: readonly EntityKind[] = [
  "brand",
  "program",
  "money",
  "place",
  "document",
  "team",
];

/**
 * Exact words from the call on one calm line: who said them, when, one play
 * control (it turns into Pause while this clip plays). Long quotes fold to
 * two lines; tap the words to read them all.
 */
export function Clip({
  evidence,
  title,
  onPlay,
  person,
  context,
}: {
  evidence: ReportEvidence;
  title: string;
  onPlay: (evidence: ReportEvidence, title: string) => void;
  person?: Person | null;
  /** A rewatch clip can also play with the lines around it. */
  context?: {
    playback: ContextualSourcePlayback;
    onPlay: (playback: ContextualSourcePlayback, title: string) => void;
  } | null;
}) {
  const [open, setOpen] = useState(false);
  const long = evidence.quote.length > 150;
  const range = formatClipRange(evidence.start_ms, evidence.end_ms);
  return (
    <figure className={styles.clip}>
      <figcaption className={styles.clipHead}>
        {person ? person.avatar(18) : null}
        <span className={styles.clipWho}>
          {person?.name ?? "From the call"}
        </span>
        {isPlayableRange(evidence.start_ms, evidence.end_ms) ? (
          <ClipPlayState startMs={evidence.start_ms} endMs={evidence.end_ms}>
            {(playing) => (
              <button
                type="button"
                className={styles.clipPlay}
                aria-pressed={playing}
                aria-label={`${playing ? "Pause" : "Play"} source moment, ${spokenClipRange(evidence.start_ms, evidence.end_ms)}`}
                onClick={() => onPlay(evidence, title)}
              >
                <ClipPlayIcon playing={playing} size={9} />
                {playing ? "Pause" : range}
              </button>
            )}
          </ClipPlayState>
        ) : (
          <span className={styles.clipTime}>{range}</span>
        )}
        {context ? (
          <ClipPlayState
            startMs={context.playback.playback_range.start_ms}
            endMs={context.playback.playback_range.end_ms}
          >
            {(playing) => (
              <button
                type="button"
                className={styles.clipContext}
                aria-pressed={playing}
                aria-label={`${playing ? "Pause context playback" : "Play with context"}, ${spokenClipRange(context.playback.playback_range.start_ms, context.playback.playback_range.end_ms)}: ${title}`}
                onClick={() => context.onPlay(context.playback, title)}
              >
                {playing ? "Pause" : "With context"}
              </button>
            )}
          </ClipPlayState>
        ) : null}
      </figcaption>
      <blockquote
        className={styles.quote}
        data-folded={long && !open ? "" : undefined}
        role={long ? "button" : undefined}
        tabIndex={long ? 0 : undefined}
        aria-expanded={long ? open : undefined}
        title={long && !open ? "Show all" : undefined}
        onClick={long ? () => setOpen((value) => !value) : undefined}
        onKeyDown={
          long
            ? (event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                setOpen((value) => !value);
              }
            : undefined
        }
      >
        <RichText text={evidence.quote} kinds={QUOTE_KINDS} />
      </blockquote>
    </figure>
  );
}

/** Words to use on the next call, with a copy button. */
export function Script({
  label = "Try saying",
  text,
}: {
  label?: string;
  text: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <div className={styles.script}>
      <span className={styles.scriptHead}>
        {label}
        <button
          type="button"
          className={styles.copy}
          aria-label={copied ? "Copied" : `Copy: ${label}`}
          onClick={() => {
            void navigator.clipboard?.writeText(text).then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1400);
            });
          }}
        >
          {copied ? (
            <Check size={13} aria-hidden="true" />
          ) : (
            <Copy size={13} aria-hidden="true" />
          )}
        </button>
      </span>
      <p>
        <RichText text={text} />
      </p>
    </div>
  );
}

/** A labelled line of report text: "Why it matters: …". */
export function Note({
  label,
  children,
  muted = false,
}: {
  label: string;
  children: ReactNode;
  muted?: boolean;
}) {
  return (
    <p className={styles.note} data-muted={muted ? "" : undefined}>
      <b>{label}</b> <span>{children}</span>
    </p>
  );
}

/** Withheld guest findings: a count and an unlock action, never the content. */
export function Locked({
  count,
  noun,
  onUnlock,
  section,
  visible,
  total,
}: {
  count: number;
  noun: string;
  onUnlock?: () => void;
  /** The preview section these counts come from. */
  section?: string;
  visible?: number;
  total?: number;
}) {
  if (count <= 0) return null;
  return (
    <aside
      className={styles.locked}
      data-preview-section={section}
      data-visible-count={visible}
      data-total-count={total}
    >
      <Lock size={14} aria-hidden="true" />
      <span>
        {count} more {noun} {count === 1 ? "is" : "are"} saved for your account.
      </span>
      {onUnlock ? (
        <button type="button" onClick={onUnlock}>
          Unlock with a free account
        </button>
      ) : null}
    </aside>
  );
}

/** A calm empty state that says what is missing. */
export function Empty({
  icon: Glyph = Info,
  children,
}: {
  icon?: LucideIcon;
  children: ReactNode;
}) {
  return (
    <p className={styles.empty}>
      <Glyph size={16} aria-hidden="true" />
      <span>{children}</span>
    </p>
  );
}
