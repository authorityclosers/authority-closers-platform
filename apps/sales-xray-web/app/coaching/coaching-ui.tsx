"use client";

import { ArrowDown } from "lucide-react";
import type { ReactNode } from "react";
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
import { CoachingMedia } from "./media-player";
import type { CoachingClip } from "./media-contract";
import styles from "./coaching.module.css";

export { callDate } from "./coaching-format";

/**
 * One numbered pillar, headed the way the Report heads its six parts: the
 * number, Dipak's title and his subtitle, then the content (spec 2, 7, 9).
 */
export function Pillar({
  id,
  copy,
  label,
  aside,
  children,
}: {
  id: string;
  copy: CoachingPillarCopy;
  /** Another rep's view words the title for "them". */
  label?: string;
  /** A quiet count beside the title, e.g. "4 moments". */
  aside?: ReactNode;
  children: ReactNode;
}) {
  const heading = `coaching-${id}-heading`;
  return (
    <section
      id={id}
      className={styles.pillar}
      aria-labelledby={heading}
      data-coaching-pillar={copy.number}
    >
      <header className={styles.pillarHead}>
        <span className={styles.pillarNumber} aria-hidden="true">
          {copy.number}
        </span>
        <div>
          <h2 id={heading} className={styles.pillarTitle}>
            {label ?? copy.label}
          </h2>
          <p className={styles.pillarSubtitle}>{copy.subtitle}</p>
        </div>
        {aside ? <span className={styles.pillarAside}>{aside}</span> : null}
      </header>
      {children}
    </section>
  );
}

/** A small uppercase label, as the Report's cards carry. */
export function CardLabel({ children }: { children: ReactNode }) {
  return <span className={styles.cardLabel}>{children}</span>;
}

export type Chip = { text: string; tone?: "accent" | "good" | "neutral" };

/** Pillar 1: the one focus, readable in a few seconds. */
export function FocusHero({
  label,
  chips,
  explanation,
  why,
  reason,
  mission,
  missionAnchor,
  children,
}: {
  label: string;
  chips: Chip[];
  explanation: string;
  why: string;
  reason: string;
  mission: string;
  missionAnchor: string;
  children?: ReactNode;
}) {
  return (
    <div className={styles.hero}>
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
    </div>
  );
}

type Lesson = Omit<TextLesson, "own_call"> & { own_call: Evidence | null };

/**
 * Pillar 3 in the spec's order: idea, framework, your call against a better
 * direction, then Dipak's reviewed clip. With a clip the text stays a short
 * summary; without one it is the complete lesson. Never an empty state.
 */
export function LessonPanel({
  copy,
  lesson,
  clips,
  fallbackObservation,
  strength,
  acrossCalls = false,
}: {
  copy: CoachingPillarCopy;
  lesson: Lesson;
  clips?: CoachingClip[];
  fallbackObservation: string;
  strength?: Strength | null;
  /** My coaching: the strength comes from the newest call that showed one. */
  acrossCalls?: boolean;
}) {
  const media = Boolean(clips?.length);
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
    <Pillar
      id="coaching-better"
      copy={copy}
      aside={media ? BETTER.dipak : BETTER.textLesson}
    >
      <div className={styles.card}>
        <h3 className={styles.lessonTitle}>{lesson.title}</h3>
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
      </div>
      <CoachingMedia clips={clips} />
      {media ? null : wording ? (
        <div className={styles.card}>{wording}</div>
      ) : null}
      {strength ? (
        <section
          className={styles.callout}
          data-tone="good"
          aria-label={BETTER.strength}
        >
          <CardLabel>{BETTER.strength}</CardLabel>
          <p className={styles.strengthTitle}>{strength.title}</p>
          <ul className={styles.moments} aria-label="What worked on this call">
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
        </section>
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
  copy,
  mission,
  practice,
  since,
  foot,
}: {
  id: string;
  copy: CoachingPillarCopy;
  mission: NonNullable<Coaching["mission"]>;
  practice: NonNullable<Coaching["practice"]>;
  since?: string;
  foot?: ReactNode;
}) {
  return (
    <Pillar id={id} copy={copy}>
      <div className={styles.callout} data-tone="accent" data-active-mission="">
        <CardLabel>
          {NEXT.mission}
          {since ? (
            <span className={styles.cardLabelMuted}>{NEXT.since(since)}</span>
          ) : null}
        </CardLabel>
        <p className={styles.missionBehavior}>{mission.behavior}</p>
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
      </div>
      <div className={styles.callout}>
        <CardLabel>
          {NEXT.practice}
          {practice.estimated_minutes ? (
            <span className={styles.cardLabelMuted}>
              {NEXT.minutes(practice.estimated_minutes)}
            </span>
          ) : null}
        </CardLabel>
        <p>{practice.exercise}</p>
        <p className={styles.momentNote}>
          <strong>{NEXT.success}:</strong> {practice.success_condition}
        </p>
      </div>
      {foot ? <p className={styles.note}>{foot}</p> : null}
    </Pillar>
  );
}

/** Dipak's name for a gap type (spec pillar 2 table). */
export function gapLabel(gap: string) {
  return gapCopy(gap).name;
}
