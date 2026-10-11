"use client";

import {
  ArrowDown,
  Headphones,
  PencilLine,
  Sparkles,
  Target,
} from "lucide-react";
import type { ReactNode } from "react";
import { PillarHeading, StoryCard } from "../report-visuals/visuals";
import { kitStyles } from "../ui/kit";
import type {
  Coaching,
  Evidence,
  Strength,
  TextLesson,
} from "./coaching-client";
import {
  BETTER,
  FOCUS,
  NEXT,
  gapCopy,
  type CoachingPillarCopy,
} from "./coaching-copy";
import { timeLabel } from "./coaching-format";
import { EvidencePlayer } from "./evidence-player";
import { CoachingMedia, requestClip } from "./media-player";
import type { CoachingClip } from "./media-contract";
import styles from "./coaching.module.css";

export { callDate } from "./coaching-format";

/**
 * One numbered pillar with the Report's own heading (Strike A's primitive):
 * the number, Dipak's title and his subtitle, then the content (spec 2, 7, 9).
 */
export function Pillar({
  id,
  copy,
  label,
  level = 2,
  children,
}: {
  id: string;
  copy: CoachingPillarCopy;
  /** Another rep's view words the title for "them". */
  label?: string;
  /** 3 inside a page that already has its own section heading (the Report). */
  level?: 2 | 3;
  children: ReactNode;
}) {
  const heading = `${id}-heading`;
  return (
    <section
      id={id}
      className={styles.pillar}
      aria-labelledby={heading}
      data-coaching-pillar={copy.number}
    >
      <PillarHeading
        index={copy.number}
        level={level}
        id={heading}
        title={label ?? copy.label}
        subtitle={copy.subtitle}
      />
      {children}
    </section>
  );
}

/** A quiet label inside a card, as the Report's cards carry. */
export function CardLabel({ children }: { children: ReactNode }) {
  return <span className={styles.cardLabel}>{children}</span>;
}

export type Chip = { text: string; tone?: "accent" | "good" | "neutral" };

/**
 * Spec pillar 1, optional coach media: Dipak's recommended clip, if it is
 * open to play, one tap away from the focus. Locked clips are never offered.
 */
export function dipakTake(clips?: CoachingClip[]) {
  const first = clips?.[0];
  return first && first.access !== "locked" ? first : null;
}

/** Pillar 1: the one focus, readable in a few seconds. */
export function FocusHero({
  label,
  chips,
  explanation,
  why,
  reason,
  mission,
  missionAnchor,
  take,
  children,
}: {
  label: string;
  chips: Chip[];
  explanation: string;
  why: string;
  reason: string;
  mission: string;
  missionAnchor: string;
  /** Dipak's recommended clip in pillar 3 ("Hear Dipak's take"). */
  take?: CoachingClip | null;
  children?: ReactNode;
}) {
  return (
    <StoryCard emphasis>
      {chips.length ? (
        <p className={styles.chips}>
          {chips.map((chip) => (
            <span
              key={chip.text}
              className={styles.chip}
              data-tone={chip.tone ?? "neutral"}
            >
              {chip.text}
            </span>
          ))}
        </p>
      ) : null}
      <p className={styles.focusTitle}>{label}</p>
      <p className={styles.lead}>{explanation}</p>
      {take ? (
        <button
          type="button"
          className={`${kitStyles.button} ${styles.take}`}
          onClick={() => requestClip(take)}
        >
          <Headphones size={14} aria-hidden="true" />
          {FOCUS.take} · {timeLabel(take.end_ms - take.start_ms)}
        </button>
      ) : null}
      {children}
      <div className={styles.pair}>
        <div className={styles.fact}>
          <CardLabel>{FOCUS.whyMatters}</CardLabel>
          <p>{why}</p>
        </div>
        <div className={styles.fact}>
          <CardLabel>{FOCUS.whyFocus}</CardLabel>
          <p>{reason}</p>
        </div>
      </div>
      <div className={styles.nextCall}>
        <p>
          <span>{FOCUS.onNextCall}</span>
          <span>{mission}</span>
        </p>
        <a className={styles.jump} href={`#${missionAnchor}`}>
          {FOCUS.seeMission} <ArrowDown size={13} aria-hidden="true" />
        </a>
      </div>
    </StoryCard>
  );
}

type Lesson = Omit<TextLesson, "own_call"> & { own_call: Evidence | null };

/**
 * Pillar 3 in the spec's order: idea, framework, your call against a better
 * direction, then Dipak's reviewed clip. With a clip the text stays a short
 * summary; without one it is the complete lesson. Never an empty state.
 */
export function LessonPanel({
  id = "coaching-better",
  level,
  copy,
  lesson,
  clips,
  fallbackObservation,
  strength,
  acrossCalls = false,
}: {
  id?: string;
  level?: 2 | 3;
  copy: CoachingPillarCopy;
  lesson: Lesson;
  clips?: CoachingClip[];
  fallbackObservation: string;
  strength?: Strength | null;
  /** My coaching: the strength comes from the newest call that showed one. */
  acrossCalls?: boolean;
}) {
  const media = Boolean(clips?.length);
  // One level below the pillar heading (h3 under an h2, h4 inside the Report).
  const Title = level === 3 ? "h4" : "h3";
  const wording = lesson.example_wording.length ? (
    <div>
      <CardLabel>{BETTER.wording}</CardLabel>
      <ul className={styles.wording}>
        {lesson.example_wording.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </div>
  ) : null;
  return (
    <Pillar id={id} copy={copy} level={level}>
      <StoryCard label={media ? BETTER.dipak : BETTER.textLesson} tone="accent">
        <Title className={styles.lessonTitle}>{lesson.title}</Title>
        <p>{lesson.quick_idea}</p>
        {lesson.framework.length ? (
          <div className={styles.framework}>
            <ol className={styles.steps} aria-label={BETTER.framework}>
              {lesson.framework.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
            <p className={styles.note}>{BETTER.frameworkNote}</p>
          </div>
        ) : null}
        <div className={styles.compare}>
          <div>
            {/* The quote itself is the first moment in pillar 2, just above. */}
            <CardLabel>
              {lesson.own_call
                ? BETTER.yourCallAt(timeLabel(lesson.own_call.start_ms))
                : BETTER.yourCall}
            </CardLabel>
            <p>{lesson.own_call?.observation ?? fallbackObservation}</p>
          </div>
          <div data-kind="better">
            <CardLabel>{BETTER.betterDirection}</CardLabel>
            <p>{lesson.better_direction}</p>
          </div>
        </div>
      </StoryCard>
      <CoachingMedia clips={clips} headingLevel={level === 3 ? 4 : 3} />
      {media ? null : wording ? <StoryCard>{wording}</StoryCard> : null}
      {strength ? (
        <StoryCard label={BETTER.strength} tone="good" icon={Sparkles}>
          <p className={styles.strengthTitle}>{strength.title}</p>
          <ul
            className={`${styles.moments} ${styles.inset}`}
            aria-label="What worked on this call"
          >
            {strength.evidence.map((moment) => (
              <EvidencePlayer
                key={`${moment.segment_id}:${moment.start_ms}`}
                evidence={moment}
                showCall={acrossCalls}
              />
            ))}
          </ul>
          <p className={styles.note}>
            {acrossCalls ? BETTER.strengthAcross : BETTER.strengthCall}{" "}
            {BETTER.strengthKeep}
          </p>
        </StoryCard>
      ) : null}
      <details className={styles.more}>
        <summary>{BETTER.fullLesson}</summary>
        <div className={styles.moreBody}>
          {media ? wording : null}
          <p>
            <CardLabel>{BETTER.whyMatters}</CardLabel>
            {lesson.why_it_matters}
          </p>
          <p>
            <CardLabel>{BETTER.good}</CardLabel>
            {lesson.good_looks_like}
          </p>
          <p>
            <CardLabel>{BETTER.whenUse}</CardLabel>
            {lesson.when_to_use}
          </p>
          <p>
            <CardLabel>{BETTER.whenNot}</CardLabel>
            {lesson.when_not}
          </p>
          {lesson.checklist.length ? (
            <div>
              <CardLabel>{BETTER.checklist}</CardLabel>
              <ul>
                {lesson.checklist.map((check) => (
                  <li key={check}>{check}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {/* Spec 6.6: the full lesson ends with the same active mission. */}
          <p>
            <CardLabel>{BETTER.mission}</CardLabel>
            {lesson.next_call_connection}
          </p>
          <p className={styles.note}>{lesson.source}</p>
        </div>
      </details>
    </Pillar>
  );
}

/** Pillar 4: one practice and exactly one observable next-call mission. */
export function MissionPanel({
  id,
  level,
  copy,
  mission,
  practice,
  since,
  foot,
}: {
  id: string;
  level?: 2 | 3;
  copy: CoachingPillarCopy;
  mission: NonNullable<Coaching["mission"]>;
  practice: Pick<
    NonNullable<Coaching["practice"]>,
    "exercise" | "success_condition"
  > & { estimated_minutes?: number | null };
  since?: string;
  foot?: ReactNode;
}) {
  return (
    <Pillar id={id} copy={copy} level={level}>
      <StoryCard
        label={NEXT.mission}
        tone="accent"
        icon={Target}
        aside={since ? NEXT.since(since) : undefined}
      >
        <p className={styles.missionBehavior} data-active-mission="">
          {mission.behavior}
        </p>
        <dl className={styles.terms}>
          <div>
            <dt>{NEXT.useWhen}</dt>
            <dd>{mission.context}</dd>
          </div>
          <div>
            <dt>{NEXT.doneWhen}</dt>
            <dd>{mission.done_when}</dd>
          </div>
        </dl>
        <p className={styles.cue}>
          <span>{NEXT.cue}</span> {mission.cue}
        </p>
      </StoryCard>
      <StoryCard
        label={NEXT.practice}
        icon={PencilLine}
        aside={
          practice.estimated_minutes
            ? NEXT.minutes(practice.estimated_minutes)
            : undefined
        }
      >
        <p>{practice.exercise}</p>
        <p className={styles.momentNote}>
          <strong>{NEXT.success}:</strong> {practice.success_condition}
        </p>
      </StoryCard>
      {foot ? <p className={styles.note}>{foot}</p> : null}
    </Pillar>
  );
}

/** Dipak's name for a gap type (spec pillar 2 table). */
export function gapLabel(gap: string) {
  return gapCopy(gap).name;
}
