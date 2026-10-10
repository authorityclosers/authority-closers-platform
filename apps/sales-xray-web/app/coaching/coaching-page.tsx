"use client";

import { ArrowRight, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { OperationalEmpty, OperationalPanel } from "../ui/operational-panel";
import { StandaloneStudio } from "../standalone-studio";
import { useWorkspaceAccess } from "../workspace-access";
import {
  CoachingReadError,
  fetchCoaching,
  MASTERY_STATES,
  type Coaching,
  type MasteryState,
} from "./coaching-client";
import { EvidencePlayer } from "./evidence-player";
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

export function CoachingSkeleton() {
  return (
    <div
      className={styles.skeleton}
      role="status"
      aria-label="Loading Coaching"
    >
      <span className={styles.skeletonTitle} />
      {Array.from({ length: 4 }, (_, i) => (
        <div className={styles.skeletonPanel} key={i} />
      ))}
    </div>
  );
}

export function CoachingStory({ coaching }: { coaching: Coaching }) {
  const { focus, mission, lesson, evidence, practice } = coaching;
  if (!focus || !mission || !lesson || !practice) {
    return (
      <OperationalPanel
        id="coaching-empty"
        title="What You Should Work On Now"
        headingLevel="h2"
      >
        <OperationalEmpty
          title="Still learning your pattern"
          description={`${coaching.analysed_calls ? "Your analysed calls do not yet support a skill-linked mission." : "Analyse a real call to start your Coaching history."} We will keep uncertain evidence uncertain.`}
          action={
            <Link className={styles.button} href="/analysis/new">
              Analyse a call <ArrowRight size={15} aria-hidden="true" />
            </Link>
          }
        />
        {coaching.pending_calls > 0 ? (
          <p>
            {coaching.pending_calls} call
            {coaching.pending_calls === 1 ? " is" : "s are"} still being
            analysed. Refresh when the report is ready.
          </p>
        ) : null}
        {coaching.unavailable_calls > 0 ? (
          <p>
            {coaching.unavailable_calls} retained call
            {coaching.unavailable_calls === 1 ? " does" : "s do"} not currently
            have usable Coaching evidence.
          </p>
        ) : null}
      </OperationalPanel>
    );
  }
  return (
    <div className={styles.story}>
      <OperationalPanel
        id="focus"
        title="What You Should Work On Now"
        headingLevel="h2"
        className={styles.hero}
      >
        <div className={styles.meta}>
          <span>One focus</span>
          <span>{masteryLabel[coaching.mastery.state]}</span>
        </div>
        <h3 className={styles.focus}>{focus.label}</h3>
        <p>{focus.explanation}</p>
        <p>
          <strong>Why it matters</strong> {focus.why_it_matters}
        </p>
        <p className={styles.muted}>{focus.selected_reason}</p>
        <p className={styles.verdict}>{focus.verdict}</p>
        <a className={styles.button} href="#mission">
          Your next-call mission <ArrowRight size={15} aria-hidden="true" />
        </a>
      </OperationalPanel>

      <OperationalPanel
        id="diagnosis"
        title="Why This Keeps Happening"
        headingLevel="h2"
      >
        <p>{coaching.pattern.summary}</p>
        <p>
          <strong>Working hypothesis</strong> {coaching.root_cause.hypothesis}
        </p>
        <p className={styles.muted}>
          Gap type:{" "}
          {coaching.root_cause.gap_type === "uncertain"
            ? "Unknown / Uncertain"
            : coaching.root_cause.gap_type.replaceAll("_", " ")}
        </p>
        <EvidencePlayer
          key={evidence[0].submission_id + evidence[0].segment_id}
          evidence={evidence[0]}
        />
        {evidence.length > 1 ? (
          <details className={styles.disclosure}>
            <summary>
              Compare {evidence.length - 1} more evidence moment
              {evidence.length === 2 ? "" : "s"}
            </summary>
            {evidence.slice(1).map((moment) => (
              <EvidencePlayer
                key={moment.submission_id + moment.segment_id}
                evidence={moment}
              />
            ))}
          </details>
        ) : (
          <p className={styles.muted}>
            Only one supporting moment is available. We will not invent
            additional evidence.
          </p>
        )}
      </OperationalPanel>

      <OperationalPanel
        id="lesson"
        title="Here’s What Better Looks Like"
        headingLevel="h2"
      >
        <span className={styles.meta}>Recommended text lesson</span>
        <h3>{lesson.title}</h3>
        <p>{lesson.quick_idea}</p>
        <ol className={styles.framework}>
          {lesson.framework.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <p>
          <strong>Your call</strong> {lesson.own_call.observation}
        </p>
        <p>
          <strong>Better direction</strong> {lesson.better_direction}
        </p>
        <details className={styles.disclosure}>
          <summary>Read the full lesson</summary>
          <h4>Why this matters</h4>
          <p>{lesson.why_it_matters}</p>
          <h4>What good looks like</h4>
          <p>{lesson.good_looks_like}</p>
          {lesson.example_wording.length ? (
            <>
              <h4>Optional wording, in your own style</h4>
              <ul>
                {lesson.example_wording.map((wording) => (
                  <li key={wording}>{wording}</li>
                ))}
              </ul>
            </>
          ) : null}
          <h4>When to use it</h4>
          <p>{lesson.when_to_use}</p>
          <h4>When to stop</h4>
          <p>{lesson.when_not}</p>
          <h4>Quick checklist</h4>
          <ul>
            {lesson.checklist.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ul>
          <p>
            <strong>Your next-call connection</strong>{" "}
            {lesson.next_call_connection}
          </p>
          <p className={styles.muted}>{lesson.source}</p>
        </details>
      </OperationalPanel>

      <OperationalPanel
        id="mission"
        title="Try This on Your Next Call"
        headingLevel="h2"
        foot="This mission is reconstructed from retained call history. A new date or lesson view does not complete it."
      >
        <h3>One practice</h3>
        <p>{practice.exercise}</p>
        <p>
          <strong>Success</strong> {practice.success_condition}
        </p>
        <div className={styles.mission}>
          <div className={styles.meta}>
            <span>Active mission</span>
            <span>
              Since {new Date(mission.active_since).toLocaleDateString()}
            </span>
          </div>
          <h3>{mission.behavior}</h3>
          <p>
            <strong>Use it when</strong> {mission.context}
          </p>
          <p>
            <strong>Done when</strong> {mission.done_when}
          </p>
          <p className={styles.verdict}>{mission.cue}</p>
        </div>
      </OperationalPanel>

      <OperationalPanel
        id="progress"
        title="See How You’re Improving"
        headingLevel="h2"
      >
        <h3>{masteryLabel[coaching.mastery.state]}</h3>
        <p>{coaching.mastery.explanation}</p>
        {coaching.mastery.relevant_count !== null ? (
          <p>
            {coaching.mastery.correct_count} successful executions in{" "}
            {coaching.mastery.relevant_count} relevant opportunities.
          </p>
        ) : null}
        {coaching.mastery.baseline ? (
          <p>Previous baseline: {coaching.mastery.baseline}</p>
        ) : null}
        <details className={styles.disclosure}>
          <summary>Mastery journey and regression</summary>
          <ol className={styles.mastery}>
            {MASTERY_STATES.map((state) => (
              <li
                key={state}
                aria-current={
                  coaching.mastery.state === state ? "step" : undefined
                }
              >
                {masteryLabel[state]}
              </li>
            ))}
          </ol>
          <p>{coaching.regression.action}</p>
          {coaching.mastery.historical_achievement ? (
            <p>
              Previous achievement:{" "}
              {masteryLabel[coaching.mastery.historical_achievement]}
            </p>
          ) : null}
          <p>
            Watching a lesson is participation. Improvement needs evidence from
            real opportunities.
          </p>
        </details>
      </OperationalPanel>

      <OperationalPanel
        id="path"
        title="Where We Go From Here"
        headingLevel="h2"
      >
        <dl className={styles.path}>
          <div>
            <dt>Working on now</dt>
            <dd>{coaching.development_path.current}</dd>
          </div>
          <div>
            <dt>Likely next</dt>
            <dd>
              {coaching.development_path.likely_next ??
                "Still gathering evidence"}
            </dd>
          </div>
          <div>
            <dt>Maintain</dt>
            <dd>
              {coaching.development_path.maintain ??
                "No established strength yet"}
            </dd>
          </div>
          <div>
            <dt>Later</dt>
            <dd>
              {coaching.development_path.later ??
                "Your future calls will guide this"}
            </dd>
          </div>
        </dl>
        <p>{coaching.development_path.explanation}</p>
        <h3>{coaching.reflection_question}</h3>
        <p className={styles.muted}>
          Your context matters. Saving agreement, disagreement and reflection is
          not available yet.
        </p>
        <div
          className={styles.responses}
          aria-label="Learner response unavailable"
        >
          {["Agree", "Not completely", "Add context"].map((label) => (
            <button
              className={styles.button}
              type="button"
              key={label}
              disabled
            >
              {label}
            </button>
          ))}
        </div>
      </OperationalPanel>
      <details className={styles.disclosure}>
        <summary>Evidence scope and limitations</summary>
        <ul>
          {coaching.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function AccountCoaching({
  personId,
  tenantId,
}: {
  personId: string;
  tenantId: string;
}) {
  const [coaching, setCoaching] = useState<Coaching | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void fetchCoaching(controller.signal)
      .then((view) => {
        if (controller.signal.aborted) return;
        if (view.person_id !== personId || view.tenant_id !== tenantId)
          throw new CoachingReadError("Your workspace changed. Try again.");
        setCoaching(view);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof CoachingReadError
              ? reason.message
              : "Coaching could not be loaded. Try again.",
          );
      });
    return () => controller.abort();
  }, [attempt, personId, tenantId]);
  return (
    <>
      {coaching ? (
        <CoachingStory coaching={coaching} />
      ) : error ? (
        <OperationalEmpty
          title="Coaching is temporarily unavailable"
          description="Your saved calls remain available."
          action={
            <Link href="/analysis/calls" className={styles.button}>
              Open calls
            </Link>
          }
        />
      ) : (
        <CoachingSkeleton />
      )}
      {error ? (
        <aside className={styles.error} role="alert">
          <p>{error}</p>
          <button
            type="button"
            className={styles.button}
            onClick={() => {
              setError(null);
              setAttempt((value) => value + 1);
            }}
          >
            <RefreshCw size={15} aria-hidden="true" />
            Try again
          </button>
        </aside>
      ) : null}
    </>
  );
}

export function CoachingPage() {
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;
  const ready = access?.status === "ready" && authenticated && access.context;
  return (
    <AcquisitionShell
      active="coaching"
      authenticated={authenticated}
      loading={!access || access.status === "loading"}
    >
      <div className={styles.root}>
        <header className={styles.header}>
          <div>
            <h1>Coaching</h1>
            <p>One focus, grounded in your saved calls.</p>
          </div>
          <span className={styles.meta}>Provisional</span>
        </header>
        {ready ? (
          <AccountCoaching
            key={JSON.stringify([
              ready.personId,
              access?.context?.sessionId,
              ready.tenantId,
            ])}
            personId={ready.personId}
            tenantId={ready.tenantId}
          />
        ) : !access || access.status === "loading" ? (
          <CoachingSkeleton />
        ) : (
          <OperationalEmpty
            title={
              access.authenticated === false
                ? "Sign in for your Coaching"
                : "Choose your workspace"
            }
            description="Coaching follows your own retained call history in the selected workspace."
            action={
              access.authenticated === false ? (
                <Link href="/login" className={styles.button}>
                  Sign in
                </Link>
              ) : undefined
            }
          />
        )}
      </div>
    </AcquisitionShell>
  );
}

/** New routes use the existing account bootstrap until the shared shell owns them. */
export function CoachingRoute() {
  const access = useWorkspaceAccess();
  return access ? (
    <CoachingPage />
  ) : (
    <StandaloneStudio>
      <CoachingPage />
    </StandaloneStudio>
  );
}
