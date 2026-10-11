"use client";

import { ArrowRight, ChevronRight, PhoneCall } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge, kitStyles, List, Panel, Row } from "../ui/kit";
import type {
  CallSummary,
  Coaching,
  MasteryState,
  ProgressPoint,
} from "./coaching-client";
import {
  callDate,
  FocusHero,
  gapLabel,
  LessonPanel,
  MissionPanel,
} from "./coaching-ui";
import { MomentList } from "./evidence-player";
import { requestedSkillLabel, type RequestedSkill } from "./focus-request";
import styles from "./coaching.module.css";

const masteryLabel: Record<MasteryState, string> = {
  not_enough_evidence: "Not Enough Evidence",
  emerging: "Emerging",
  developing: "Developing",
  consistent: "Consistent",
  strong: "Strong",
  mastered: "Mastered",
  regression_detected: "Regression Detected",
  re_stabilizing: "Re-stabilizing",
};
const JOURNEY: MasteryState[] = [
  "emerging",
  "developing",
  "consistent",
  "strong",
  "mastered",
];

/** Mirrors the final grid, so nothing moves when the data arrives. */

const POINT: Record<ProgressPoint["state"], string> = {
  suggested: "Suggested again",
  no_suggestion: "Evidence, no suggestion",
  not_covered: "Not covered",
};

/** Comparable calls, oldest first. Reports say what they saw, never success. */
function ProgressStrip({ points }: { points?: ProgressPoint[] }) {
  if (!points?.length) return null;
  const after = points.filter((point) => point.after_mission);
  const quiet = after.filter((point) => point.state === "no_suggestion");
  const firstAfter = points.findIndex((point) => point.after_mission);
  return (
    <div className={styles.progress}>
      <ol
        className={styles.timeline}
        aria-label="Comparable calls, oldest first"
      >
        {points.map((point, index) => (
          <li
            key={point.submission_id}
            data-state={point.state}
            data-mission-start={index === firstAfter ? "" : undefined}
            title={`${callDate(point.created_at)} · ${POINT[point.state]}`}
          >
            <span className={styles.srOnly}>
              {callDate(point.created_at)}: {POINT[point.state]}
            </span>
          </li>
        ))}
      </ol>
      <p className={styles.legend} aria-hidden="true">
        {(Object.keys(POINT) as ProgressPoint["state"][]).map((state) => (
          <span key={state} data-state={state}>
            {POINT[state]}
          </span>
        ))}
      </p>
      <p>
        {after.length
          ? `Since your mission started: ${quiet.length} of ${after.length} comparable call${after.length === 1 ? "" : "s"} had evidence for this skill and no suggestion. That is not proof of change yet.`
          : "No comparable call since your mission started. Your next call is the first check."}
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
    <Panel title="Coaching for each call" sub={`${calls.length} recent`}>
      <div
        className={styles.callList}
        data-expanded={expanded ? "" : undefined}
      >
        <List label="Your recent calls">
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
                  ? "Analysing…"
                  : call.state === "unavailable"
                    ? "No usable report"
                    : (call.focus_label ?? "One practice for your next call"),
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
          Show all {calls.length} calls
        </button>
      ) : null}
    </Panel>
  );
}

function StartCoaching({ coaching }: { coaching: Coaching }) {
  return (
    <div className={styles.layout}>
      <div className={styles.main}>
        <section className={styles.hero} aria-labelledby="coaching-focus">
          <div className={styles.eyebrow}>
            <h2 id="coaching-focus" className={styles.label}>
              What You Should Work On Now
            </h2>
            <Badge>Still learning your pattern</Badge>
          </div>
          <p className={styles.focusTitle}>
            {coaching.analysed_calls
              ? "Start with one call’s coaching"
              : "Analyse a call to start"}
          </p>
          <p className={styles.lead}>
            {coaching.analysed_calls
              ? "Your calls do not yet show one skill to work on across calls. Each analysed call below already has its own focus and next-call mission."
              : "Coaching follows your own analysed calls. Your first report brings one focus and one mission for your next call."}
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
        </section>
        <CallsPanel calls={coaching.calls} />
      </div>
    </div>
  );
}

export function CoachingStory({
  coaching,
  requestedFocus,
  readOnly = false,
}: {
  coaching: Coaching;
  requestedFocus?: RequestedSkill;
  /** Another rep's coaching (a fictional AC Sandbox rep): nothing to save here. */
  readOnly?: boolean;
}) {
  const { focus, mission, lesson, evidence, practice, mastery } = coaching;
  if (!focus || !mission || !lesson || !practice)
    return <StartCoaching coaching={coaching} />;
  const pattern = coaching.pattern;
  const recurring = focus.status === "active";
  const step = JOURNEY.indexOf(mastery.state);
  const path = coaching.development_path;
  // One conversation in spec order (1–6); on wide screens the mission (4)
  // stays beside the story instead of a stack of side panels (spec 3, 9).
  return (
    <div className={styles.conversation}>
      <FocusHero
        heading="What You Should Work On Now"
        label={focus.label}
        badges={[
          recurring
            ? { text: "Active focus", tone: "accent" }
            : { text: "Provisional focus" },
          ...(pattern.relevant_call_count > 1
            ? [
                {
                  text: `In ${pattern.attention_call_count} of ${pattern.relevant_call_count} comparable calls`,
                },
              ]
            : []),
          ...(mastery.state !== "not_enough_evidence"
            ? [{ text: masteryLabel[mastery.state], tone: "good" as const }]
            : []),
          ...(coaching.sandbox ? [{ text: "Fictional AC Sandbox" }] : []),
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
      <Panel
        title="Why This Keeps Happening"
        sub={`${evidence.length} moment${evidence.length === 1 ? "" : "s"}`}
      >
        <div className={styles.body}>
          <p>{pattern.summary}</p>
          <p className={styles.hypothesis}>
            <span className={styles.eyebrow}>
              Likely reason, a working hypothesis
              <Badge>{gapLabel(coaching.root_cause.gap_type)}</Badge>
            </span>
            {coaching.root_cause.hypothesis}
          </p>
        </div>
        <MomentList evidence={evidence} fictional={coaching.sandbox} />
      </Panel>
      <LessonPanel
        lesson={lesson}
        clips={coaching.media_clips}
        fallbackObservation={focus.explanation}
        strength={coaching.strength}
        acrossCalls
      />
      <aside className={styles.conversationRail} aria-label="Your next call">
        <MissionPanel
          id="mission"
          mission={mission}
          practice={practice}
          since={callDate(mission.active_since)}
          foot="It stays until real calls show the change."
        />
      </aside>
      <Panel title="See How You’re Improving">
        <div className={styles.body}>
          <span className={styles.eyebrow}>
            Mastery
            <Badge
              tone={
                mastery.state === "not_enough_evidence" ? "neutral" : "good"
              }
            >
              {masteryLabel[mastery.state]}
            </Badge>
            <ol className={styles.stepper} aria-label="Mastery journey">
              {JOURNEY.map((state, index) => (
                <li
                  key={state}
                  title={masteryLabel[state]}
                  data-on={step >= index ? "" : undefined}
                  aria-current={mastery.state === state ? "step" : undefined}
                >
                  <span className={styles.srOnly}>{masteryLabel[state]}</span>
                </li>
              ))}
            </ol>
          </span>
          <ProgressStrip points={coaching.progress} />
          {mastery.relevant_count !== null ? (
            <p>
              {mastery.correct_count} successful executions in{" "}
              {mastery.relevant_count} relevant opportunities.
            </p>
          ) : null}
          <details className={styles.more}>
            <summary>How progress is measured</summary>
            <div className={styles.moreBody}>
              <p>{mastery.explanation}</p>
              <p>{coaching.regression.action}</p>
              {mastery.baseline ? (
                <p>Previous baseline: {mastery.baseline}</p>
              ) : null}
              {mastery.historical_achievement ? (
                <p>
                  Previous achievement:{" "}
                  {masteryLabel[mastery.historical_achievement]}
                </p>
              ) : null}
              <p className={styles.note}>
                Watching a lesson is participation. Improvement needs evidence
                from real opportunities.
              </p>
            </div>
          </details>
        </div>
      </Panel>
      <Panel title="Where We Go From Here">
        <div className={styles.body}>
          <ol className={styles.route} aria-label="Your development path">
            <li data-now="">
              <span>Now</span>
              {path.current ?? focus.label}
            </li>
            <li>
              <span>Likely next</span>
              {path.likely_next ?? "Your next calls decide"}
            </li>
            <li>
              <span>Later</span>
              {path.later ?? "Your future calls will guide this"}
            </li>
          </ol>
          {path.maintain ? (
            <p className={styles.note}>Keep strong: {path.maintain}</p>
          ) : null}
          {coaching.reflection_question ? (
            <p className={styles.reflection}>{coaching.reflection_question}</p>
          ) : null}
        </div>
      </Panel>
      <div className={styles.late}>
        <CallsPanel calls={coaching.calls} />
      </div>
      <details className={`${styles.more} ${styles.late}`}>
        <summary>About this coaching</summary>
        <ul className={styles.takeaways}>
          <li>{path.explanation}</li>
          {coaching.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
          {readOnly ? null : (
            <li>
              Saving your agreement, disagreement and reflection comes with
              sharing.
            </li>
          )}
        </ul>
      </details>
    </div>
  );
}
