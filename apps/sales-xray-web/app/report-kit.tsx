"use client";

import { Check, Copy, Lock } from "lucide-react";
import {
  useId,
  useMemo,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { voicesOf } from "./call-data";
import { Emote, type EmoteName } from "./emote";
import {
  formatClipRange,
  isPlayableRange,
  spokenClipRange,
} from "./lightbox/time";
import type { ReportEvidence, Transcript } from "./report-contract";
import type { ContextualSourcePlayback } from "./source-playback-context";
import { RichText, type EntityKind } from "./report-entities";
import { confirmedRoles } from "./sales-signals";
import { getShellState } from "./shell/shell-store";
import { ClipPlayIcon, ClipPlayState } from "./source-waveform";
import { SpeakerAvatar } from "./speaker-avatar";
import { speakerName, useSpeakerProfiles } from "./speaker-profiles";
import styles from "./report-kit.module.css";

// The report's shared building blocks, so every tab reads the same way:
// one colour per meaning, the speaker beside every quote, one play control,
// and long text folded until asked for (print always shows it all).

/** One colour per meaning, used the same way on every tab. */
export type Tone =
  | "strength"
  | "change"
  | "missed"
  | "objection"
  | "closing"
  | "hypothesis"
  | "info"
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

/** A tab section: optional emote, title, one-line hint, count and action. */
export function KitSection({
  emote,
  title,
  hint,
  count,
  action,
  tone = "neutral",
  index = 0,
  children,
}: {
  emote?: EmoteName;
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
        {emote ? (
          <span className={styles.headEmote}>
            <Emote name={emote} size={22} />
          </span>
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

/** A card in one of the report's tones. */
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

/** A small label with an emote, in a tone. */
export function Tag({
  tone = "neutral",
  emote,
  children,
}: {
  tone?: Tone;
  emote?: EmoteName;
  children: ReactNode;
}) {
  return (
    <span className={`${styles.tag} ${styles.tone}`} data-tone={tone}>
      {emote ? <Emote name={emote} size={15} /> : null}
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
 * Exact words from the call: who said them, when, and one play control that
 * turns into Pause while this clip plays. Long quotes fold to three lines.
 */
export function Clip({
  evidence,
  title,
  onPlay,
  person,
  said = "said",
  context,
}: {
  evidence: ReportEvidence;
  title: string;
  onPlay: (evidence: ReportEvidence, title: string) => void;
  person?: Person | null;
  said?: string;
  /** A rewatch clip can also play with the lines around it. */
  context?: {
    playback: ContextualSourcePlayback;
    onPlay: (playback: ContextualSourcePlayback, title: string) => void;
  } | null;
}) {
  const [open, setOpen] = useState(false);
  const long = evidence.quote.length > 240;
  const range = formatClipRange(evidence.start_ms, evidence.end_ms);
  return (
    <figure className={styles.clip}>
      <figcaption className={styles.clipHead}>
        {person ? person.avatar(22) : null}
        <span className={styles.clipWho}>
          {person ? `${person.name} ${said}` : "From the call"}
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
                <ClipPlayIcon playing={playing} size={10} />
                {range}
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
                <ClipPlayIcon playing={playing} size={10} />
                With context
              </button>
            )}
          </ClipPlayState>
        ) : null}
      </figcaption>
      <blockquote
        className={styles.quote}
        data-folded={long && !open ? "" : undefined}
      >
        <RichText text={evidence.quote} kinds={QUOTE_KINDS} />
      </blockquote>
      {long ? (
        <button
          type="button"
          className={styles.fold}
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "Show less" : "Show all"}
        </button>
      ) : null}
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
        <Emote name="speech-balloon" size={16} />
        {label}
        <button
          type="button"
          className={styles.copy}
          onClick={() => {
            void navigator.clipboard?.writeText(text).then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1400);
            });
          }}
        >
          {copied ? (
            <Check size={12} aria-hidden="true" />
          ) : (
            <Copy size={12} aria-hidden="true" />
          )}
          {copied ? "Copied" : "Copy"}
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
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <p className={styles.note}>
      <b>{label}</b> {children}
    </p>
  );
}

/** Withheld guest findings: a count and a sign-in action, never the content. */
export function Locked({
  count,
  noun,
  onUnlock,
}: {
  count: number;
  noun: string;
  onUnlock?: () => void;
}) {
  if (count <= 0) return null;
  return (
    <aside className={styles.locked}>
      <Lock size={14} aria-hidden="true" />
      <span>
        {count} more {noun} {count === 1 ? "is" : "are"} saved for your account.
      </span>
      {onUnlock ? (
        <button type="button" onClick={onUnlock}>
          Sign in to see {count === 1 ? "it" : "them"}
        </button>
      ) : null}
    </aside>
  );
}

/** A calm empty state that says what is missing, not what to feel. */
export function Empty({
  emote = "seedling",
  children,
}: {
  emote?: EmoteName;
  children: ReactNode;
}) {
  return (
    <p className={styles.empty}>
      <Emote name={emote} size={20} />
      <span>{children}</span>
    </p>
  );
}
