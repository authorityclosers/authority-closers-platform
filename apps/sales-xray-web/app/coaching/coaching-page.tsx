"use client";

import {
  ArrowRight,
  ChevronRight,
  FileSearch,
  PhoneCall,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import {
  Badge,
  Button,
  Empty,
  kitStyles,
  List,
  PageHeader,
  Panel,
  QueryTabs,
  Row,
  Skeleton,
} from "../ui/kit";
import { StandaloneStudio } from "../standalone-studio";
import { useWorkspaceAccess } from "../workspace-access";
import type { CallSummary, Coaching, MasteryState } from "./coaching-client";
import { CallCoachingStory } from "./call-coaching";
import {
  isCallCoaching,
  isTeamCoaching,
  readCoaching,
  requestedCall,
  type CoachingResult,
} from "./coaching-read";
import {
  callDate,
  FocusHero,
  gapLabel,
  LessonPanel,
  MissionPanel,
} from "./coaching-ui";
import { TeamCoachingStory } from "./team-coaching";
import { MomentList } from "./evidence-player";
import {
  requestedSkill,
  requestedSkillLabel,
  type RequestedSkill,
} from "./focus-request";
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
export function CoachingSkeleton() {
  return (
    <div
      className={styles.skeleton}
      role="status"
      aria-busy="true"
      aria-label="Loading Coaching"
    >
      <Skeleton width={220} height={24} />
      <Skeleton width={320} height={13} />
      <div className={styles.layout}>
        <div className={styles.main}>
          <span className={styles.skeletonBlock} style={{ height: 232 }} />
          <span className={styles.skeletonBlock} style={{ height: 200 }} />
          <span className={styles.skeletonBlock} style={{ height: 280 }} />
        </div>
        <div className={styles.rail}>
          <span className={styles.skeletonBlock} style={{ height: 300 }} />
          <span className={styles.skeletonBlock} style={{ height: 160 }} />
        </div>
      </div>
    </div>
  );
}

/** Every analysed call has its own coaching, even before a pattern exists. */
function CallsPanel({ calls }: { calls?: CallSummary[] }) {
  if (!calls?.length) return null;
  return (
    <Panel title="Coaching for each call" sub={`${calls.length} recent`}>
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
            <Link
              className={kitStyles.button}
              data-variant={coaching.analysed_calls ? undefined : "primary"}
              href="/analysis/new"
            >
              Analyse a call <ArrowRight size={14} aria-hidden="true" />
            </Link>
          </div>
        </section>
        <CallsPanel calls={coaching.calls} />
      </div>
    </div>
  );
}

export function CoachingStory({
  coaching,
  requestedFocus,
}: {
  coaching: Coaching;
  requestedFocus?: RequestedSkill;
}) {
  const { focus, mission, lesson, evidence, practice, mastery } = coaching;
  if (!focus || !mission || !lesson || !practice)
    return <StartCoaching coaching={coaching} />;
  const pattern = coaching.pattern;
  const recurring = focus.status === "active";
  const step = JOURNEY.indexOf(mastery.state);
  return (
    <div className={styles.layout}>
      <div className={styles.main}>
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
            <div className={styles.hypothesis}>
              <span className={styles.eyebrow}>
                Likely reason · a working hypothesis
                <Badge>{gapLabel(coaching.root_cause.gap_type)}</Badge>
              </span>
              <p>{coaching.root_cause.hypothesis}</p>
            </div>
          </div>
          <MomentList evidence={evidence} />
          {evidence.length === 1 ? (
            <p className={styles.body}>
              <span className={styles.note}>
                Only one supporting moment so far. We will not invent more.
              </span>
            </p>
          ) : null}
        </Panel>
        <LessonPanel
          lesson={lesson}
          clips={coaching.media_clips}
          fallbackObservation={focus.explanation}
        />
        <div className={styles.late}>
          <CallsPanel calls={coaching.calls} />
        </div>
      </div>
      <aside className={styles.rail} aria-label="Mission and progress">
        <MissionPanel
          id="mission"
          mission={mission}
          practice={practice}
          since={callDate(mission.active_since)}
          foot="The mission stays until real calls show the change. A lesson view or a new date does not complete it."
        />
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
            </span>
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
            <p>{mastery.explanation}</p>
            {mastery.relevant_count !== null ? (
              <p>
                {mastery.correct_count} successful executions in{" "}
                {mastery.relevant_count} relevant opportunities.
              </p>
            ) : null}
            {mastery.baseline ? (
              <p className={styles.note}>
                Previous baseline: {mastery.baseline}
              </p>
            ) : null}
            <details className={styles.more}>
              <summary>Regression and history</summary>
              <div className={styles.moreBody}>
                <p>{coaching.regression.action}</p>
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
            <dl className={styles.path}>
              <div>
                <dt>Working on now</dt>
                <dd>{coaching.development_path.current ?? focus.label}</dd>
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
            <p className={styles.note}>
              {coaching.development_path.explanation}
            </p>
            {coaching.reflection_question ? (
              <p className={styles.reflection}>
                {coaching.reflection_question}
              </p>
            ) : null}
            <div
              className={styles.actions}
              aria-label="Learner response unavailable"
            >
              {["Agree", "Not completely", "Add context"].map((label) => (
                <Button key={label} disabled>
                  {label}
                </Button>
              ))}
            </div>
            <p className={styles.note}>
              Your context matters. Saving agreement, disagreement and
              reflection is not available yet.
            </p>
          </div>
        </Panel>
        <details className={`${styles.more} ${styles.late}`}>
          <summary>Evidence scope and limitations</summary>
          <ul className={styles.takeaways}>
            {coaching.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </details>
      </aside>
    </div>
  );
}

function CoachingResultBody({
  result,
  callId,
  requestedFocus,
  retry,
}: {
  result: CoachingResult | null;
  callId: string | null;
  requestedFocus?: RequestedSkill;
  retry: () => void;
}) {
  const data = result?.data;
  return (
    <>
      {data ? (
        isCallCoaching(data) ? (
          <CallCoachingStory coaching={data} />
        ) : isTeamCoaching(data) ? (
          <TeamCoachingStory coaching={data} />
        ) : (
          <CoachingStory coaching={data} requestedFocus={requestedFocus} />
        )
      ) : result?.error ? (
        <Panel title="Coaching">
          <Empty
            icon={FileSearch}
            title="Coaching is temporarily unavailable"
            text="Your calls and reports are unaffected. Open the call to check its report and analysis status."
            action={{
              href: callId ? `/analysis/calls/${callId}` : "/analysis/calls",
              label: callId ? "Open the call" : "Open calls",
            }}
          />
        </Panel>
      ) : (
        <CoachingSkeleton />
      )}
      {result?.error ? (
        <aside className={styles.error} role="alert">
          <p>{result.error}</p>
          <div className={styles.actions}>
            <Button onClick={retry}>
              <RefreshCw size={14} aria-hidden="true" />
              Try again
            </Button>
          </div>
        </aside>
      ) : null}
    </>
  );
}

function AccountCoaching({
  personId,
  tenantId,
  sessionId,
  requestedFocus,
  callId,
  initialResult,
  invalidCall,
  team,
}: {
  personId: string;
  tenantId: string;
  sessionId: string;
  requestedFocus?: RequestedSkill;
  callId: string | null;
  initialResult: CoachingResult | null;
  invalidCall: boolean;
  team: boolean;
}) {
  const [result, setResult] = useState<CoachingResult | null>(initialResult);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (invalidCall) return;
    if (attempt === 0 && initialResult !== null) return;
    const controller = new AbortController();
    void readCoaching(team ? "team" : callId, {
      signal: controller.signal,
    }).then((view) => {
      if (controller.signal.aborted) return;
      if (
        view.data &&
        (view.data.person_id !== personId ||
          view.data.tenant_id !== tenantId ||
          (view.data.session_id != null && view.data.session_id !== sessionId))
      )
        setResult({ data: null, error: "Your workspace changed. Try again." });
      else setResult(view);
    });
    return () => controller.abort();
  }, [
    attempt,
    personId,
    tenantId,
    sessionId,
    callId,
    initialResult,
    invalidCall,
    team,
  ]);
  return (
    <CoachingResultBody
      result={result}
      callId={callId}
      requestedFocus={requestedFocus}
      retry={() => {
        if (!invalidCall) setResult(null);
        setAttempt((value) => value + 1);
      }}
    />
  );
}

export function CoachingPage({
  requestedFocus,
  callId = null,
  initialResult = null,
  invalidCall = false,
  team = false,
}: {
  requestedFocus?: RequestedSkill;
  callId?: string | null;
  initialResult?: CoachingResult | null;
  invalidCall?: boolean;
  team?: boolean;
} = {}) {
  const access = useWorkspaceAccess();
  const ready =
    access?.status === "ready" && access.authenticated && access.context;
  const scope = ready
    ? JSON.stringify([ready.personId, ready.tenantId, ready.sessionId])
    : null;
  const [seedScope, setSeedScope] = useState<string | null>(scope);
  if (scope !== null && seedScope === null) setSeedScope(scope);
  const seed =
    initialResult &&
    (!seedScope || seedScope === scope) &&
    (!ready ||
      !initialResult.data ||
      (initialResult.data.person_id === ready.personId &&
        initialResult.data.tenant_id === ready.tenantId &&
        (!initialResult.data.session_id ||
          initialResult.data.session_id === ready.sessionId)))
      ? initialResult
      : null;
  const authenticated =
    access?.authenticated === true ||
    ((!access || access.status === "loading") && !!seed?.data);
  const awaitingAccess = !access || access.status === "loading";
  const workspace = ready
    ? access?.workspaces?.find((item) => item.tenant_id === ready.tenantId)
    : undefined;
  // A hint only: the server decides Team access on every read.
  const showTeam =
    team ||
    (workspace?.kind === "organisation" &&
      (workspace.role === "owner" || workspace.role === "admin"));
  const seededCall =
    callId && seed?.data && isCallCoaching(seed.data) ? seed.data : null;
  return (
    <AcquisitionShell
      authenticated={authenticated}
      loading={awaitingAccess && !seed}
    >
      <div className={styles.root}>
        <PageHeader
          title={
            callId
              ? "Coaching for this call"
              : team
                ? "Team coaching"
                : "My coaching"
          }
          context={
            callId
              ? [
                  seededCall?.call_label ?? "One focus from this call’s report",
                  seededCall?.focus
                    ? callDate(seededCall.focus.selected_at)
                    : "",
                ]
              : team
                ? ["Anonymous totals from your team’s analysed calls"]
                : ["Your focus, mission and progress across calls"]
          }
          back={
            callId
              ? { href: `/analysis/calls/${callId}`, label: "Back to report" }
              : undefined
          }
          actions={
            callId ? (
              <Link className={kitStyles.button} href="/coaching">
                My coaching
              </Link>
            ) : undefined
          }
        />
        {!callId && showTeam ? (
          <QueryTabs
            base="/coaching"
            param="view"
            current={team ? "team" : "me"}
            items={[
              { key: "me", label: "My coaching" },
              { key: "team", label: "Team" },
            ]}
          />
        ) : null}
        {ready ? (
          <AccountCoaching
            key={JSON.stringify([scope, callId, team, seed])}
            personId={ready.personId}
            tenantId={ready.tenantId}
            sessionId={ready.sessionId}
            requestedFocus={requestedFocus}
            callId={callId}
            initialResult={seed}
            invalidCall={invalidCall}
            team={team}
          />
        ) : awaitingAccess ? (
          <CoachingResultBody
            result={seed}
            callId={callId}
            requestedFocus={requestedFocus}
            retry={() => access?.retry()}
          />
        ) : (
          <Panel title="Coaching">
            <Empty
              icon={FileSearch}
              title={
                access.authenticated === false
                  ? "Sign in for your Coaching"
                  : "Choose your workspace"
              }
              text="Coaching follows your own analysed calls in the selected workspace."
              action={
                access.authenticated === false
                  ? { href: "/login", label: "Sign in" }
                  : undefined
              }
            />
          </Panel>
        )}
      </div>
    </AcquisitionShell>
  );
}

/** Static preview and local checks use the same single read; hosted pages arrive with server data. */
export function CoachingRoute({
  initialResult = null,
  initialCallId = null,
  initialTeam = false,
}: {
  initialResult?: CoachingResult | null;
  initialCallId?: string | null;
  initialTeam?: boolean;
} = {}) {
  const access = useWorkspaceAccess();
  const query = useSearchParams();
  const callId = requestedCall(query.get("call"));
  const team = !callId && query.get("view") === "team";
  const invalidCall =
    query.has("call") && (!callId || query.getAll("call").length !== 1);
  const seed = invalidCall
    ? ({
        data: null,
        error: "This call link is invalid. Open the call’s report again.",
      } as const)
    : callId === initialCallId && team === initialTeam
      ? initialResult
      : null;
  const page = (
    <CoachingPage
      callId={callId}
      initialResult={seed}
      invalidCall={invalidCall}
      team={team}
      requestedFocus={requestedSkill(query.get("focus"))}
    />
  );
  return access ? page : <StandaloneStudio>{page}</StandaloneStudio>;
}
