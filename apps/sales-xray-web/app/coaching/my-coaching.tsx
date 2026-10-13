"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useRef } from "react";

import { StoryCard } from "../report-visuals/visuals";
import { kitStyles } from "../ui/kit";
import type { Coaching, MasteryState, ProgressPoint } from "./coaching-client";
import {
  ABOUT,
  COACHING_PILLARS,
  CONFIDENCE_COPY,
  FOCUS,
  MASTERY_COPY,
  NEXT,
  PATH,
  POINT_COPY,
  PROGRESS,
  REGRESSION_COPY,
  START,
  THEIR,
  THEIR_PILLARS,
  TREND_COPY,
  TREND_ARROW,
  WHY,
  gapCopy,
} from "./coaching-copy";
import {
  callDate,
  dipakTake,
  FocusHero,
  LessonPanel,
  MissionPanel,
  Pillar,
} from "./coaching-ui";
import {
  CallsOpenReports,
  TheirCoaching,
  useTheirCoaching,
} from "./coaching-voice";
import { MomentList } from "./evidence-player";
import { FocusFeedback, SharePanel } from "./sharing-ui";
import type { SharingView } from "./sharing-client";
import { requestedSkillLabel, type RequestedSkill } from "./focus-request";
import { RepCallLinks } from "./rep-call-links";
import { CallsPanel, callsOnSkill, type CallsPanelHandle } from "./calls-panel";
import styles from "./coaching.module.css";

const JOURNEY: MasteryState[] = [
  "emerging",
  "developing",
  "consistent",
  "strong",
  "mastered",
];

/** "Developing ↑"; nothing while there is not enough evidence to say. */
function statusText(mastery: Coaching["mastery"]) {
  if (mastery.state === "not_enough_evidence") return null;
  return `${MASTERY_COPY[mastery.state]}${TREND_ARROW[mastery.trend] ?? ""}`;
}

/** This skill's calls, oldest first. Reports say what they saw, never success. */
function ProgressStrip({ points }: { points?: ProgressPoint[] }) {
  const they = useTheirCoaching();
  if (!points?.length) return null;
  // "calls on this skill": a call that gave no chance to use it isn't one.
  const after = points.filter(
    (point) => point.after_mission && point.state !== "not_covered",
  );
  const quiet = after.filter((point) => point.state === "no_suggestion");
  const firstAfter = points.findIndex((point) => point.after_mission);
  const count = (state: ProgressPoint["state"]) =>
    points.filter((point) => point.state === state).length;
  return (
    <div className={styles.progress}>
      <span className={styles.cardLabel} aria-hidden="true">
        {they ? THEIR.callsLabel : PROGRESS.callsLabel}
        {" · "}
        <span className={styles.cardLabelMuted}>{PROGRESS.oldestFirst}</span>
      </span>
      {/* Screen readers get one sentence, not a row per dot. */}
      <p className={styles.srOnly}>
        {they ? THEIR.calls : PROGRESS.calls}:{" "}
        {PROGRESS.summary(
          count("suggested"),
          count("no_suggestion"),
          count("not_covered"),
        )}
      </p>
      <ol className={styles.timeline} aria-hidden="true">
        {points.map((point, index) => (
          <li
            key={point.submission_id}
            data-state={point.state}
            data-mission-start={index === firstAfter ? "" : undefined}
            title={`${callDate(point.created_at)} · ${POINT_COPY[point.state]}`}
          />
        ))}
      </ol>
      <p className={styles.legend} aria-hidden="true">
        {(Object.keys(POINT_COPY) as ProgressPoint["state"][]).map((state) => (
          <span key={state} data-state={state}>
            {POINT_COPY[state]}
          </span>
        ))}
        {firstAfter >= 0 ? (
          <span data-mark="mission">{PROGRESS.missionStart}</span>
        ) : null}
      </p>
      <p>
        {after.length
          ? (they ? THEIR.sinceMission : PROGRESS.sinceMission)(
              quiet.length,
              after.length,
            )
          : they
            ? THEIR.noCallSince
            : PROGRESS.noCallSince}
      </p>
    </div>
  );
}

function StartCoaching({
  coaching,
  readOnly = false,
  sharing,
}: {
  coaching: Coaching;
  /** Another rep's view: say "their", offer no action that is the viewer's. */
  readOnly?: boolean;
  sharing?: SharingView;
}) {
  if (readOnly)
    return (
      <div className={styles.conversation}>
        <Pillar id="coaching-focus" copy={THEIR_PILLARS.focus}>
          <StoryCard emphasis>
            <p className={styles.chips}>
              <span className={styles.chip} data-tone="neutral">
                {FOCUS.theirNotYet}
              </span>
            </p>
            <p className={styles.focusTitle}>
              {coaching.analysed_calls
                ? START.theirNoFocus
                : START.theirNoCalls}
            </p>
            <p className={styles.lead}>
              {coaching.analysed_calls
                ? START.theirNoFocusText
                : START.theirNoCallsText}
            </p>
            <RepCallLinks calls={coaching.calls} sandbox={coaching.sandbox} />
          </StoryCard>
        </Pillar>
        <CallsPanel calls={coaching.calls} />
      </div>
    );
  return (
    <div className={styles.conversation}>
      <Pillar id="coaching-focus" copy={COACHING_PILLARS.focus}>
        <StoryCard emphasis>
          <p className={styles.chips}>
            <span className={styles.chip} data-tone="neutral">
              {FOCUS.notYet}
            </span>
          </p>
          <p className={styles.focusTitle}>
            {coaching.analysed_calls ? START.noFocus : START.noCalls}
          </p>
          <p className={styles.lead}>
            {coaching.analysed_calls ? START.noFocusText : START.noCallsText}
          </p>
          {coaching.pending_calls > 0 ? (
            <p className={styles.note}>
              {START.pending(coaching.pending_calls)}
            </p>
          ) : null}
          <div className={styles.actions}>
            {coaching.sandbox_reps ? (
              <Link
                className={kitStyles.button}
                data-variant="primary"
                href="/coaching?view=team"
              >
                {START.sandboxReps(coaching.sandbox_reps)}{" "}
                <ArrowRight size={14} aria-hidden="true" />
              </Link>
            ) : null}
            <Link
              className={kitStyles.button}
              data-variant={
                coaching.analysed_calls || coaching.sandbox_reps
                  ? undefined
                  : "primary"
              }
              href="/analysis/new"
            >
              {START.analyse} <ArrowRight size={14} aria-hidden="true" />
            </Link>
          </div>
          {coaching.sandbox_reps ? (
            <p className={styles.note}>{START.sandboxNote}</p>
          ) : null}
        </StoryCard>
      </Pillar>
      <CallsPanel calls={coaching.calls} />
      {/* Sharing can always be stopped, focus or not. */}
      <SharePanel initial={sharing} />
    </div>
  );
}

type StoryProps = {
  coaching: Coaching;
  requestedFocus?: RequestedSkill;
  /** A known sharing state (design review); otherwise the panel reads it. */
  sharing?: SharingView;
  /**
   * Another rep's coaching (a fictional AC Sandbox rep, or a rep who shared
   * theirs): nothing to save here, and every label says "their".
   */
  readOnly?: boolean;
};

export function CoachingStory(props: StoryProps) {
  return (
    <TheirCoaching.Provider value={props.readOnly ?? false}>
      <CallsOpenReports.Provider
        value={Boolean(props.readOnly) && !props.coaching.sandbox}
      >
        <Story {...props} />
      </CallsOpenReports.Provider>
    </TheirCoaching.Provider>
  );
}

function Story({
  coaching,
  requestedFocus,
  readOnly = false,
  sharing,
}: StoryProps) {
  const calls = useRef<CallsPanelHandle>(null);
  const { focus, mission, lesson, evidence, practice, mastery } = coaching;
  if (!focus || !mission || !lesson || !practice)
    return (
      <StartCoaching
        coaching={coaching}
        readOnly={readOnly}
        sharing={sharing}
      />
    );
  const pattern = coaching.pattern;
  const recurring = focus.status === "active";
  const status = statusText(mastery);
  const path = coaching.development_path;
  const gap = coaching.root_cause.gap_type;
  const confidence = CONFIDENCE_COPY[coaching.root_cause.confidence];
  const pillars = readOnly ? THEIR_PILLARS : COACHING_PILLARS;
  // One conversation, read top to bottom in Dipak's order (spec 3, 7, 9),
  // each pillar headed the way the Report heads its six parts.
  return (
    <div className={styles.conversation}>
      <Pillar id="coaching-focus" copy={pillars.focus}>
        <FocusHero
          label={focus.label}
          chips={[
            recurring
              ? { text: FOCUS.active, tone: "accent" }
              : { text: FOCUS.provisional },
            ...(status ? [{ text: status, tone: "good" as const }] : []),
            ...(coaching.sandbox ? [{ text: FOCUS.sandbox }] : []),
          ]}
          explanation={focus.explanation}
          why={focus.why_it_matters}
          reason={focus.selected_reason}
          evidenceAnchor={evidence.length ? "coaching-evidence" : undefined}
          mission={mission.behavior}
          missionAnchor="mission"
          take={dipakTake(coaching.media_clips)}
        >
          {readOnly ? (
            <RepCallLinks calls={coaching.calls} sandbox={coaching.sandbox} />
          ) : null}
          {!readOnly && requestedFocus && requestedFocus !== focus.skill_id ? (
            <p className={styles.note}>
              Your report brought you here for{" "}
              {requestedSkillLabel(requestedFocus)}. Your current next-call
              mission stays active.
            </p>
          ) : null}
        </FocusHero>
      </Pillar>
      <Pillar id="coaching-why" copy={pillars.why}>
        <StoryCard>
          <dl className={styles.diagnosis}>
            <div>
              <dt>{WHY.pattern}</dt>
              <dd>{pattern.summary}</dd>
            </div>
            <div>
              <dt>{WHY.likelyReason}</dt>
              <dd>
                {coaching.root_cause.hypothesis}
                {coaching.root_cause.learner_context ? (
                  <span className={styles.learnerContext}>
                    {readOnly ? WHY.theirContext : WHY.yourContext}: “
                    {coaching.root_cause.learner_context}”
                  </span>
                ) : null}
              </dd>
            </div>
            <div>
              <dt>{WHY.gap}</dt>
              <dd>
                <strong>{gapCopy(gap).name}</strong>
                {gap !== "uncertain"
                  ? ` · ${readOnly ? THEIR.gapLine(gap) : gapCopy(gap).line}`
                  : ""}
              </dd>
            </div>
            {confidence ? (
              <div>
                <dt>{WHY.confidence}</dt>
                <dd>{confidence}</dd>
              </div>
            ) : null}
          </dl>
        </StoryCard>
        <div
          id="coaching-evidence"
          className={`${styles.card} ${styles.evidenceTarget}`}
          data-flush=""
          tabIndex={-1}
        >
          <MomentList
            evidence={evidence}
            heading={readOnly ? THEIR.evidence : WHY.evidence}
            fictional={coaching.sandbox}
          />
        </div>
      </Pillar>
      <LessonPanel
        copy={pillars.better}
        lesson={lesson}
        clips={coaching.media_clips}
        fallbackObservation={focus.explanation}
        strength={coaching.strength}
        acrossCalls
      />
      <MissionPanel
        id="mission"
        copy={pillars.next}
        mission={mission}
        practice={practice}
        since={callDate(mission.active_since)}
        foot={NEXT.stays}
      />
      <Pillar id="coaching-progress" copy={pillars.progress}>
        <StoryCard>
          <dl className={styles.diagnosis}>
            <div>
              <dt>{PROGRESS.status}</dt>
              <dd>
                <strong>{status ?? MASTERY_COPY.not_enough_evidence}</strong>
              </dd>
            </div>
            {mastery.relevant_count !== null &&
            mastery.correct_count !== null ? (
              <div>
                <dt>{PROGRESS.recent}</dt>
                <dd>
                  {PROGRESS.correct(
                    mastery.correct_count,
                    mastery.relevant_count,
                  )}
                </dd>
              </div>
            ) : null}
            {mastery.baseline ? (
              <div>
                <dt>{PROGRESS.previous}</dt>
                <dd>{mastery.baseline}</dd>
              </div>
            ) : null}
            {TREND_COPY[mastery.trend] ? (
              <div>
                <dt>{PROGRESS.trend}</dt>
                <dd>{TREND_COPY[mastery.trend]}</dd>
              </div>
            ) : null}
            <div>
              <dt>{PROGRESS.regression}</dt>
              <dd>
                {readOnly && coaching.regression.state === "severe"
                  ? THEIR.severe
                  : (REGRESSION_COPY[coaching.regression.state] ??
                    REGRESSION_COPY.unknown)}
              </dd>
            </div>
          </dl>
          <ol className={styles.stepper} aria-label={PROGRESS.journey}>
            {JOURNEY.map((state, index) => (
              <li
                key={state}
                title={MASTERY_COPY[state]}
                data-on={
                  JOURNEY.indexOf(mastery.state) >= index ? "" : undefined
                }
                aria-current={mastery.state === state ? "step" : undefined}
              >
                <span>{MASTERY_COPY[state]}</span>
              </li>
            ))}
          </ol>
          <ProgressStrip points={coaching.progress} />
          {callsOnSkill(coaching.calls, coaching.progress).length ? (
            <div className={styles.actions}>
              <button
                type="button"
                className={kitStyles.button}
                aria-controls="coaching-calls"
                onClick={() => calls.current?.showSkill()}
              >
                {PROGRESS.seeCalls}
                <ArrowRight size={14} aria-hidden="true" />
              </button>
            </div>
          ) : null}
          <details className={styles.more}>
            <summary>{PROGRESS.how}</summary>
            <div className={styles.moreBody}>
              <p>{mastery.explanation}</p>
              <p>{coaching.regression.action}</p>
              {mastery.historical_achievement ? (
                <p>
                  {PROGRESS.achieved}:{" "}
                  {MASTERY_COPY[mastery.historical_achievement]}
                </p>
              ) : null}
              <p className={styles.note}>{PROGRESS.watching}</p>
            </div>
          </details>
        </StoryCard>
      </Pillar>
      <Pillar id="coaching-path" copy={pillars.path}>
        <StoryCard>
          <ol
            className={styles.route}
            aria-label={readOnly ? THEIR.path : START.path}
          >
            <li data-now="">
              <span>{PATH.now}</span>
              {path.current ?? focus.label}
            </li>
            <li>
              <span>{PATH.next}</span>
              {path.likely_next ??
                (readOnly ? THEIR.nextFallback : PATH.nextFallback)}
            </li>
            <li>
              <span>{PATH.later}</span>
              {path.later ??
                (readOnly ? THEIR.laterFallback : PATH.laterFallback)}
            </li>
          </ol>
          {path.maintain ? (
            <p className={styles.note}>
              {PATH.maintain}: {path.maintain}
            </p>
          ) : null}
          <p className={styles.note}>{PATH.dynamic}</p>
          {readOnly ? null : (
            <FocusFeedback
              focusSkillId={focus.skill_id}
              originSubmissionId={mission.origin_submission_id}
              question={coaching.reflection_question}
              evidence={evidence}
            />
          )}
        </StoryCard>
      </Pillar>
      {readOnly ? null : <SharePanel initial={sharing} />}
      <CallsPanel
        ref={calls}
        key={`${coaching.person_id}:${focus.skill_id}`}
        calls={coaching.calls}
        progress={coaching.progress}
        focusLabel={focus.label}
      />
      <details className={styles.more}>
        <summary>{ABOUT}</summary>
        <ul className={styles.takeaways}>
          <li>{path.explanation}</li>
          {coaching.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
