"use client";

import { ArrowRight, ChevronRight, PhoneCall } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { kitStyles, List, Panel, Row } from "../ui/kit";
import type {
  CallSummary,
  Coaching,
  MasteryState,
  ProgressPoint,
} from "./coaching-client";
import {
  ABOUT,
  CALLS,
  COACHING_PILLARS,
  CONFIDENCE_COPY,
  FOCUS,
  MASTERY_COPY,
  NEXT,
  PATH,
  POINT_COPY,
  PROGRESS,
  THEIR_FOCUS,
  TREND_ARROW,
  WHY,
  gapCopy,
} from "./coaching-copy";
import {
  callDate,
  FocusHero,
  LessonPanel,
  MissionPanel,
  Pillar,
} from "./coaching-ui";
import { MomentList } from "./evidence-player";
import { FocusFeedback, SharePanel } from "./sharing-ui";
import type { SharingView } from "./sharing-client";
import { requestedSkillLabel, type RequestedSkill } from "./focus-request";
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
  if (!points?.length) return null;
  const after = points.filter((point) => point.after_mission);
  const quiet = after.filter((point) => point.state === "no_suggestion");
  const firstAfter = points.findIndex((point) => point.after_mission);
  return (
    <div className={styles.progress}>
      <ol className={styles.timeline} aria-label={PROGRESS.calls}>
        {points.map((point, index) => (
          <li
            key={point.submission_id}
            data-state={point.state}
            data-mission-start={index === firstAfter ? "" : undefined}
            title={`${callDate(point.created_at)} · ${POINT_COPY[point.state]}`}
          >
            <span className={styles.srOnly}>
              {callDate(point.created_at)}: {POINT_COPY[point.state]}
            </span>
          </li>
        ))}
      </ol>
      <p className={styles.legend} aria-hidden="true">
        {(Object.keys(POINT_COPY) as ProgressPoint["state"][]).map((state) => (
          <span key={state} data-state={state}>
            {POINT_COPY[state]}
          </span>
        ))}
      </p>
      <p>
        {after.length
          ? PROGRESS.sinceMission(quiet.length, after.length)
          : PROGRESS.noCallSince}
      </p>
    </div>
  );
}

/**
 * Every analysed call has its own coaching, even before a pattern exists.
 * Wide screens open with the eight newest calls and one-column screens with
 * three (spec 12.7); the rest stay one tap away.
 */
function CallsPanel({ calls }: { calls?: CallSummary[] }) {
  const [expanded, setExpanded] = useState(false);
  if (!calls?.length) return null;
  return (
    <Panel title={CALLS.title} sub={CALLS.recent(calls.length)}>
      <div
        className={styles.callList}
        data-expanded={expanded ? "" : undefined}
      >
        <List label={CALLS.label}>
          {calls.map((call) => (
            <Row
              key={call.submission_id}
              icon={<PhoneCall size={15} aria-hidden="true" />}
              title={call.call_label}
              href={
                call.state === "ready"
                  ? `/coaching?call=${call.submission_id}`
                  : `/analysis/calls/${call.submission_id}`
              }
              meta={[
                callDate(call.created_at),
                call.state === "pending"
                  ? CALLS.analysing
                  : call.state === "unavailable"
                    ? CALLS.unavailable
                    : (call.focus_label ?? CALLS.fallback),
              ]}
              end={
                call.state === "ready" ? (
                  <ChevronRight size={15} aria-hidden="true" />
                ) : null
              }
            />
          ))}
        </List>
      </div>
      {calls.length > 3 && !expanded ? (
        <button
          type="button"
          className={`${kitStyles.button} ${styles.moreCalls}`}
          data-many={calls.length > 8 ? "" : undefined}
          onClick={() => setExpanded(true)}
        >
          {CALLS.showAll(calls.length)}
        </button>
      ) : null}
    </Panel>
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
        <Pillar
          id="coaching-focus"
          copy={COACHING_PILLARS.focus}
          label={THEIR_FOCUS}
        >
          <div className={styles.hero}>
            <p className={styles.chips}>
              <span className={styles.chip} data-tone="neutral">
                {FOCUS.theirNotYet}
              </span>
            </p>
            <p className={styles.focusTitle}>
              {coaching.analysed_calls
                ? "Their calls don’t show one focus yet"
                : "No analysed calls yet"}
            </p>
            <p className={styles.lead}>
              {coaching.analysed_calls
                ? "Each analysed call below has its own focus and next-call mission."
                : "Their coaching starts with their first analysed call."}
            </p>
          </div>
        </Pillar>
        <CallsPanel calls={coaching.calls} />
      </div>
    );
  return (
    <div className={styles.conversation}>
      <Pillar id="coaching-focus" copy={COACHING_PILLARS.focus}>
        <div className={styles.hero}>
          <p className={styles.chips}>
            <span className={styles.chip} data-tone="neutral">
              {FOCUS.notYet}
            </span>
          </p>
          <p className={styles.focusTitle}>
            {coaching.analysed_calls
              ? "Start with one call’s coaching"
              : "Analyse a call to start"}
          </p>
          <p className={styles.lead}>
            {coaching.analysed_calls
              ? "Your calls don’t show one skill to work on across calls yet. Each analysed call below already has its own focus and next-call mission."
              : "Coaching follows your own calls. Your first report brings one focus and one mission for your next call."}
          </p>
          {coaching.pending_calls > 0 ? (
            <p className={styles.note}>
              {coaching.pending_calls} call
              {coaching.pending_calls === 1 ? " is" : "s are"} still being
              analysed.
            </p>
          ) : null}
          <div className={styles.actions}>
            {coaching.sandbox_reps ? (
              <Link
                className={kitStyles.button}
                data-variant="primary"
                href="/coaching?view=team"
              >
                See {coaching.sandbox_reps} fictional reps’ coaching{" "}
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
              Analyse a call <ArrowRight size={14} aria-hidden="true" />
            </Link>
          </div>
          {coaching.sandbox_reps ? (
            <p className={styles.note}>
              This is AC Sandbox: Team shows the coaching of the fictional reps
              you imported. Your own coaching follows your own calls.
            </p>
          ) : null}
        </div>
      </Pillar>
      <CallsPanel calls={coaching.calls} />
      {/* Sharing can always be stopped, focus or not. */}
      <SharePanel initial={sharing} />
    </div>
  );
}

export function CoachingStory({
  coaching,
  requestedFocus,
  readOnly = false,
  sharing,
}: {
  coaching: Coaching;
  requestedFocus?: RequestedSkill;
  /** A known sharing state (design review); otherwise the panel reads it. */
  sharing?: SharingView;
  /** Another rep's coaching (a fictional AC Sandbox rep): nothing to save here. */
  readOnly?: boolean;
}) {
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
  // One conversation, read top to bottom in Dipak's order (spec 3, 7, 9),
  // each pillar headed the way the Report heads its six parts.
  return (
    <div className={styles.conversation}>
      <Pillar
        id="coaching-focus"
        copy={COACHING_PILLARS.focus}
        label={readOnly ? THEIR_FOCUS : undefined}
      >
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
          mission={mission.behavior}
          missionAnchor="mission"
        >
          {requestedFocus && requestedFocus !== focus.skill_id ? (
            <p className={styles.note}>
              Your report brought you here for{" "}
              {requestedSkillLabel(requestedFocus)}. Your current next-call
              mission stays active.
            </p>
          ) : null}
        </FocusHero>
      </Pillar>
      <Pillar
        id="coaching-why"
        copy={COACHING_PILLARS.why}
        aside={`${evidence.length} moment${evidence.length === 1 ? "" : "s"}`}
      >
        <div className={styles.card}>
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
                {gap !== "uncertain" ? ` · ${gapCopy(gap).line}` : ""}
              </dd>
            </div>
            {confidence ? (
              <div>
                <dt>{WHY.confidence}</dt>
                <dd>{confidence}</dd>
              </div>
            ) : null}
          </dl>
        </div>
        <div className={styles.card} data-flush="">
          <MomentList evidence={evidence} fictional={coaching.sandbox} />
        </div>
      </Pillar>
      <LessonPanel
        copy={COACHING_PILLARS.better}
        lesson={lesson}
        clips={coaching.media_clips}
        fallbackObservation={focus.explanation}
        strength={coaching.strength}
        acrossCalls
      />
      <MissionPanel
        id="mission"
        copy={COACHING_PILLARS.next}
        mission={mission}
        practice={practice}
        since={callDate(mission.active_since)}
        foot={NEXT.stays}
      />
      <Pillar id="coaching-progress" copy={COACHING_PILLARS.progress}>
        <div className={styles.card}>
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
        </div>
      </Pillar>
      <Pillar id="coaching-path" copy={COACHING_PILLARS.path}>
        <div className={styles.card}>
          <ol className={styles.route} aria-label="Your development path">
            <li data-now="">
              <span>{PATH.now}</span>
              {path.current ?? focus.label}
            </li>
            <li>
              <span>{PATH.next}</span>
              {path.likely_next ?? PATH.nextFallback}
            </li>
            <li>
              <span>{PATH.later}</span>
              {path.later ?? PATH.laterFallback}
            </li>
          </ol>
          {path.maintain ? (
            <p className={styles.note}>
              {PATH.maintain}: {path.maintain}
            </p>
          ) : null}
          <p className={styles.note}>{PATH.dynamic}</p>
          {coaching.reflection_question ? (
            <p className={styles.reflection}>{coaching.reflection_question}</p>
          ) : null}
          {readOnly ? null : (
            <FocusFeedback
              focusSkillId={focus.skill_id}
              originSubmissionId={mission.origin_submission_id}
            />
          )}
        </div>
      </Pillar>
      {readOnly ? null : <SharePanel initial={sharing} />}
      <CallsPanel calls={coaching.calls} />
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
