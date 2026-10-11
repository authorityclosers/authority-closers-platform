"use client";

import { ArrowDown } from "lucide-react";
import type { ReactNode } from "react";
import { Badge, Panel, type Tone } from "../ui/kit";
import type { Coaching, Evidence, TextLesson } from "./coaching-client";
import { CoachingMedia } from "./media-player";
import type { CoachingClip } from "./media-contract";
import styles from "./coaching.module.css";

export { callDate } from "./coaching-format";

/** Pillar 1: the one focus, readable in a few seconds. */
export function FocusHero({
  heading,
  label,
  badges,
  explanation,
  why,
  reason,
  mission,
  missionAnchor,
  children,
}: {
  heading: string;
  label: string;
  badges: { text: string; tone?: Tone }[];
  explanation: string;
  why: string;
  reason: string;
  mission: string;
  missionAnchor: string;
  children?: ReactNode;
}) {
  return (
    <section className={styles.hero} aria-labelledby="coaching-focus">
      <div className={styles.eyebrow}>
        <h2 id="coaching-focus" className={styles.label}>
          {heading}
        </h2>
        {badges.map((badge) => (
          <Badge key={badge.text} tone={badge.tone}>
            {badge.text}
          </Badge>
        ))}
      </div>
      <p className={styles.focusTitle}>{label}</p>
      <p className={styles.lead}>{explanation}</p>
      {children}
      <dl className={styles.facts}>
        <div>
          <dt className={styles.label}>Why it matters</dt>
          <dd>{why}</dd>
        </div>
        <div>
          <dt className={styles.label}>Why this focus</dt>
          <dd>{reason}</dd>
        </div>
      </dl>
      <div className={styles.nextCall}>
        <p>
          <span>On your next call</span>
          <span>{mission}</span>
        </p>
        <a className={styles.jump} href={`#${missionAnchor}`}>
          See the mission <ArrowDown size={13} aria-hidden="true" />
        </a>
      </div>
    </section>
  );
}

type Lesson = Omit<TextLesson, "own_call"> & { own_call: Evidence | null };

/** Pillar 3: a Dipak clip when one is reviewed, always a usable text lesson. */
export function LessonPanel({
  lesson,
  clips,
  fallbackObservation,
}: {
  lesson: Lesson;
  clips?: CoachingClip[];
  fallbackObservation: string;
}) {
  return (
    <Panel
      title="Here’s What Better Looks Like"
      sub={clips?.length ? "Dipak’s coaching" : "Text lesson"}
    >
      <div className={styles.body}>
        <CoachingMedia clips={clips} />
        <h3 className={styles.lessonTitle}>{lesson.title}</h3>
        <p>{lesson.quick_idea}</p>
        {lesson.framework.length ? (
          <ol className={styles.steps} aria-label="Framework">
            {lesson.framework.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        ) : null}
        <div className={styles.compare}>
          <div>
            <span className={styles.label}>Your call</span>
            {lesson.own_call ? (
              <p className={styles.quote}>{lesson.own_call.quote}</p>
            ) : null}
            <p className={styles.momentNote}>
              {lesson.own_call?.observation ?? fallbackObservation}
            </p>
          </div>
          <div data-kind="better">
            <span className={styles.label}>Better direction</span>
            <p>{lesson.better_direction}</p>
          </div>
        </div>
        {lesson.example_wording.length ? (
          <div>
            <span className={styles.label}>
              Optional wording, in your own style
            </span>
            <ul className={styles.wording}>
              {lesson.example_wording.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <details className={styles.more}>
          <summary>Read the full lesson</summary>
          <div className={styles.moreBody}>
            <p>
              <span className={styles.label}>Why this matters</span>
              {lesson.why_it_matters}
            </p>
            <p>
              <span className={styles.label}>What good looks like</span>
              {lesson.good_looks_like}
            </p>
            <p>
              <span className={styles.label}>When to use it</span>
              {lesson.when_to_use}
            </p>
            <p>
              <span className={styles.label}>When to use another approach</span>
              {lesson.when_not}
            </p>
            {lesson.checklist.length ? (
              <div>
                <span className={styles.label}>Quick checklist</span>
                <ul>
                  {lesson.checklist.map((check) => (
                    <li key={check}>{check}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            <p className={styles.note}>{lesson.source}</p>
          </div>
        </details>
      </div>
    </Panel>
  );
}

/** Pillar 4: one practice and exactly one observable next-call mission. */
export function MissionPanel({
  id,
  mission,
  practice,
  since,
  foot,
}: {
  id: string;
  mission: NonNullable<Coaching["mission"]>;
  practice: NonNullable<Coaching["practice"]>;
  since?: string;
  foot?: ReactNode;
}) {
  return (
    <div id={id} className={styles.section}>
      <Panel title="Try This on Your Next Call" foot={foot}>
        <div className={styles.mission}>
          <span className={styles.eyebrow}>
            Active mission{since ? ` · since ${since}` : ""}
          </span>
          <p className={styles.missionBehavior}>{mission.behavior}</p>
          <dl className={styles.terms}>
            <div>
              <dt className={styles.label}>Use it when</dt>
              <dd>{mission.context}</dd>
            </div>
            <div>
              <dt className={styles.label}>Done when</dt>
              <dd>{mission.done_when}</dd>
            </div>
          </dl>
          <p className={styles.cue} title="Pre-call cue">
            {mission.cue}
          </p>
        </div>
        <div className={styles.practice}>
          <span className={styles.eyebrow}>
            Practise once
            {practice.estimated_minutes
              ? ` · ${practice.estimated_minutes} min`
              : ""}
          </span>
          <p>{practice.exercise}</p>
          <p className={styles.momentNote}>
            <span className={styles.label}>Check your practice</span>
            {practice.success_condition}
          </p>
        </div>
      </Panel>
    </div>
  );
}

const GAP_LABELS: Record<string, string> = {
  knowledge: "Knowledge",
  judgment: "Judgment",
  execution: "Execution",
  habit_recall: "Habit / recall",
  confidence: "Confidence",
  cognitive_load: "Cognitive load",
  belief_buy_in: "Belief / buy-in",
  adherence: "Adherence",
  skill_dependency: "Skill dependency",
  context_specific: "Context-specific",
  uncertain: "Unknown / Uncertain",
};

export function gapLabel(gap: string) {
  return GAP_LABELS[gap] ?? GAP_LABELS.uncertain;
}
