"use client";

import { PencilLine, Target } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { DocumentReportData } from "./report-document-data";
import type { ReportEvidence, SalesReport } from "./report-contract";
import { REPORT_SKILLS } from "./report-pillars";
import { basisChip } from "./coaching/call-coaching";
import {
  CALL_PILLARS,
  FOCUS,
  NEXT,
  RETAINED,
  WHY,
} from "./coaching/coaching-copy";
import {
  dipakTake,
  FocusHero,
  LessonPanel,
  MissionPanel,
  Pillar,
} from "./coaching/coaching-ui";
import coachingStyles from "./coaching/coaching.module.css";
import { MomentList } from "./coaching/evidence-player";
import { Quote, StoryCard } from "./report-visuals/visuals";
import { kitStyles } from "./ui/kit";
import type { ContextualSourcePlayback } from "./source-playback-context";
import styles from "./report-call-coaching.module.css";
import { useWorkspaceAccess } from "./workspace-access";
import { notify, dismissNotice } from "./notice-center";
import {
  parseCallCoaching,
  readCallCoaching,
  CallCoachingReadError,
  type CallCoaching,
} from "./report-call-coaching-client";

/**
 * A v8 report has no overview: its own coaching mission, linked to one
 * "What Didn't" issue (`coaching_mission_for`), is the proposed focus, as on
 * the server (report_adapter.with_pillars_overview). No link, no proposal.
 */
function pillarsFocus(report: SalesReport) {
  const deal = report.pillars?.deal as
    | { coaching_mission?: string | null; coaching_mission_for?: unknown }
    | undefined;
  const index = deal?.coaching_mission_for;
  return deal?.coaching_mission &&
    typeof index === "number" &&
    Number.isInteger(index) &&
    index >= 0 &&
    index < report.improvements.length
    ? {
        improvement_index: index,
        behavior: deal.coaching_mission,
        target: null,
      }
    : undefined;
}

/** A retained finding supplies a suggestion, never a new diagnosis or score. */
export function callCoachingFocus(report: SalesReport) {
  if (report.preview) return null;
  const proposed = report.overview?.next_call_focus ?? pillarsFocus(report);
  const proposedFinding = proposed
    ? report.improvements[proposed.improvement_index]
    : undefined;
  const index = proposedFinding?.evidence.length
    ? proposed!.improvement_index
    : report.improvements.findIndex((finding) => finding.evidence.length);
  const improvement = index >= 0;
  const finding = improvement
    ? report.improvements[index]
    : report.strengths.find((item) => item.evidence.length);
  if (!finding) return null;
  const linkedFocus =
    improvement && proposed?.improvement_index === index ? proposed : null;
  const detail = improvement
    ? report.overview?.improvement_details.find(
        (item) => item.finding_index === index,
      )
    : null;
  const matchingSkills = report.dimensions.filter(
    (dimension) =>
      REPORT_SKILLS.some(([id]) => id === dimension.dimension_id) &&
      ["observed", "partial"].includes(dimension.status) &&
      dimension.evidence?.some((source) =>
        finding.evidence.some(
          (ref) =>
            ref.segment_id === source.segment_id &&
            ref.start_ms === source.start_ms &&
            ref.end_ms === source.end_ms &&
            ref.quote === source.quote,
        ),
      ),
  );
  return {
    finding,
    improvement,
    behavior: linkedFocus?.behavior ?? finding.title,
    target: linkedFocus?.target ?? null,
    replacement: detail?.replacement_behavior ?? null,
    why: detail?.why_it_matters ?? null,
    practice:
      improvement && report.overview?.practice?.improvement_index === index
        ? report.overview.practice
        : null,
    // Shared words alone cannot disambiguate two assessed skills.
    skillId:
      matchingSkills.length === 1 ? matchingSkills[0].dimension_id : null,
  };
}

type Props = {
  data: DocumentReportData;
  callId?: string;
  onSelectEvidence?: (source: ReportEvidence, title: string) => void;
  onSelectContextualPlayback?: (
    source: ContextualSourcePlayback,
    title: string,
  ) => void;
};

export function ReportCallCoaching(props: Props) {
  const { data, callId } = props;
  const access = useWorkspaceAccess();
  const context = access?.context;
  const report = data.report;
  const permitted =
    !!callId &&
    !!context &&
    access?.authenticated === true &&
    access.status === "ready" &&
    !!report &&
    !report.preview;
  const identity = `${context?.personId}:${context?.tenantId}:${context?.sessionId}`;
  const [initialIdentity] = useState(identity);
  const baseScope = `${identity}:${callId}:${report?.source_sha256}:${report?.transcript_revision}:${data.recordingId}:${data.reportRevision}`;
  const [attempt, setAttempt] = useState(0);
  const [withheldScope, setWithheldScope] = useState<string | null>(null);
  const authorisedScope = useRef<string | null>(null);
  const scope = `${baseScope}:${attempt}`;
  const [loaded, setLoaded] = useState<{
    scope: string;
    baseScope: string;
    report: SalesReport;
    view: CallCoaching | null;
    error?: boolean;
  } | null>(null);
  const binding = permitted
    ? {
        callId: callId!,
        personId: context!.personId,
        tenantId: context!.tenantId,
        sessionId: context!.sessionId,
        sourceSha256: report!.source_sha256,
        transcriptRevision: report!.transcript_revision,
        recordingId: data.recordingId,
        reportRevision: data.reportRevision,
        transcript: data.transcript,
      }
    : null;
  let bootstrap: CallCoaching | null = null;
  if (binding && data.callCoaching) {
    try {
      bootstrap = parseCallCoaching(data.callCoaching, binding);
    } catch {}
  }
  const bootstrapped = attempt === 0 && !!bootstrap;
  useEffect(() => {
    if (bootstrapped && bootstrap?.state === "ready") {
      authorisedScope.current = baseScope;
    }
    if (!permitted || bootstrapped || !report || !callId || !context) return;
    const controller = new AbortController();
    const signal = AbortSignal.any([
      controller.signal,
      AbortSignal.timeout(15000),
    ]);
    void readCallCoaching(
      {
        callId,
        personId: context.personId,
        tenantId: context.tenantId,
        sessionId: context.sessionId,
        sourceSha256: report.source_sha256,
        transcriptRevision: report.transcript_revision,
        recordingId: data.recordingId,
        reportRevision: data.reportRevision,
        transcript: data.transcript,
      },
      signal,
    )
      .then((view) => {
        if (controller.signal.aborted) return;
        setLoaded({ scope, baseScope, report, view });
        if (view.state === "ready") authorisedScope.current = baseScope;
        setWithheldScope(view.state === "unavailable" ? baseScope : null);
        dismissNotice("report-call-coaching");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (
          error instanceof CallCoachingReadError &&
          ([401, 403].includes(error.status ?? 0) ||
            (error.status === 404 && authorisedScope.current === baseScope))
        ) {
          setWithheldScope(baseScope);
        }
        setLoaded({ scope, baseScope, report, view: null, error: true });
        notify({
          id: "report-call-coaching",
          tone: "error",
          title: "Call coaching unavailable",
          message: "Your report is still available.",
          action: { label: "Try again", run: () => setAttempt((n) => n + 1) },
        });
      });
    return () => {
      controller.abort();
      dismissNotice("report-call-coaching");
    };
  }, [
    permitted,
    bootstrapped,
    bootstrap?.state,
    scope,
    baseScope,
    report,
    callId,
    context,
    data.recordingId,
    data.reportRevision,
    data.transcript,
  ]);
  if (!report || report.preview) return null;
  if (access && callId && !permitted)
    return (
      <p className={styles.context}>
        Choose your signed-in workspace to see this call’s coaching.
      </p>
    );
  // Withholding remains in force while a retry is pending; old report quotes cannot reappear.
  const current =
    (attempt === 0 ? bootstrap : null) ??
    (loaded?.scope === scope && loaded.report === report ? loaded.view : null);
  const withheld =
    withheldScope === baseScope ||
    (bootstrap?.state === "unavailable" && current?.state !== "ready");
  if (current?.state === "unavailable" || withheld)
    return (
      <div
        className={styles.coaching}
        data-call-coaching
        data-state="unavailable"
      >
        <p>This call’s coaching isn’t available right now.</p>
        <button type="button" onClick={() => setAttempt((n) => n + 1)}>
          Try again
        </button>
      </div>
    );
  if (current?.state === "ready")
    return (
      <CanonicalCallCoaching
        key={`${baseScope}:${current.report_revision}`}
        {...props}
        coaching={current}
      />
    );
  if (access && identity !== initialIdentity)
    return (
      <p className={styles.context}>
        Coaching is unavailable in this workspace. Your report can be reopened
        from the call list.
      </p>
    );
  return (
    <RetainedCallCoaching {...props} callId={permitted ? callId : undefined} />
  );
}

/**
 * This call's coaching inside the Report, in the same four pillars and cards
 * as the Coaching page; moments play in the Report's own player.
 */
function CanonicalCallCoaching({
  data,
  coaching,
  onSelectEvidence,
}: Props & { coaching: CallCoaching }) {
  const { focus, lesson, mission, practice } = coaching;
  if (!focus || !lesson || !mission || !practice || !data.report) return null;
  const skill = REPORT_SKILLS.some(([id]) => id === focus.skill_id)
    ? focus.skill_id
    : null;
  return (
    <div className={styles.coaching} data-call-coaching data-state="ready">
      <div className={coachingStyles.conversation}>
        <Pillar id="report-coaching-focus" copy={CALL_PILLARS.focus} level={3}>
          <FocusHero
            label={focus.label}
            chips={[basisChip(coaching.basis)]}
            explanation={focus.explanation}
            why={focus.why_it_matters}
            reason={focus.selected_reason}
            mission={mission.behavior}
            missionAnchor="report-coaching-mission"
            take={dipakTake(coaching.media_clips)}
          />
        </Pillar>
        <Pillar id="report-coaching-why" copy={CALL_PILLARS.why} level={3}>
          {coaching.evidence.length ? (
            <div className={coachingStyles.card} data-flush="">
              <MomentList
                evidence={coaching.evidence}
                showCall={false}
                heading={WHY.callEvidence}
                label="Moments from this call"
                onPlay={onSelectEvidence}
              />
            </div>
          ) : (
            <StoryCard>
              <p>{WHY.noTimestamp}</p>
            </StoryCard>
          )}
        </Pillar>
        <LessonPanel
          id="report-coaching-better"
          level={3}
          copy={CALL_PILLARS.better}
          lesson={lesson}
          clips={coaching.media_clips}
          fallbackObservation={focus.explanation}
        />
        <MissionPanel
          id="report-coaching-mission"
          level={3}
          copy={CALL_PILLARS.next}
          mission={mission}
          practice={practice}
          foot={NEXT.oneCall}
        />
        <div className={styles.links}>
          <Link
            prefetch={false}
            className={kitStyles.button}
            data-variant="primary"
            href={`/coaching?call=${coaching.submission_id}`}
          >
            Open full coaching for this call
          </Link>
          <Link
            prefetch={false}
            className={kitStyles.button}
            href={skill ? `/coaching?focus=${skill}` : "/coaching"}
          >
            My coaching across calls
          </Link>
        </div>
      </div>
    </div>
  );
}

/**
 * The fallback when this call's coaching can't be read: the report's own
 * retained suggestion in the same pillars, never a new diagnosis.
 */
function RetainedCallCoaching({ data, callId, onSelectEvidence }: Props) {
  const report = data.report;
  if (!report || report.preview) return null;
  const focus = callCoachingFocus(report);
  const fullCall =
    callId &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      callId,
    );
  const links = (
    <div className={styles.links}>
      {fullCall ? (
        <Link
          prefetch={false}
          className={kitStyles.button}
          data-variant="primary"
          href={`/coaching?call=${callId}`}
        >
          Open full coaching for this call
        </Link>
      ) : null}
      <Link
        prefetch={false}
        className={kitStyles.button}
        href={focus?.skillId ? `/coaching?focus=${focus.skillId}` : "/coaching"}
      >
        My coaching across calls
      </Link>
    </div>
  );
  if (!focus)
    return (
      <div
        className={styles.coaching}
        data-call-coaching
        data-state="report-focus"
      >
        <div className={coachingStyles.conversation}>
          <StoryCard>
            <p>{RETAINED.none}</p>
            <div className={coachingStyles.answers}>
              {REPORT_SKILLS.map(([id, label]) => (
                <Link
                  key={id}
                  prefetch={false}
                  className={coachingStyles.answer}
                  href={`/coaching?focus=${id}`}
                >
                  {label}
                </Link>
              ))}
            </div>
          </StoryCard>
          {links}
        </div>
      </div>
    );
  const title = focus.finding.title;
  return (
    <div
      className={styles.coaching}
      data-call-coaching
      data-state="report-focus"
    >
      <div className={coachingStyles.conversation}>
        <Pillar id="report-coaching-focus" copy={CALL_PILLARS.focus} level={3}>
          <FocusHero
            label={focus.improvement ? title : `${RETAINED.keep}: ${title}`}
            chips={[{ text: FOCUS.fromReport, tone: "accent" }]}
            explanation={focus.finding.explanation}
            why={focus.why ?? focus.finding.explanation}
            reason={RETAINED.reason}
            mission={focus.behavior}
            missionAnchor="report-coaching-mission"
          />
        </Pillar>
        <Pillar id="report-coaching-why" copy={CALL_PILLARS.why} level={3}>
          <StoryCard label={WHY.callEvidence}>
            {focus.finding.evidence.map((source, index) => (
              <Quote
                key={index}
                text={source.quote}
                source={source}
                title="Coaching for this call"
                onSelect={onSelectEvidence}
              />
            ))}
          </StoryCard>
        </Pillar>
        <Pillar
          id="report-coaching-better"
          copy={CALL_PILLARS.better}
          level={3}
        >
          <StoryCard
            label={focus.improvement ? RETAINED.tryNext : RETAINED.carry}
            tone="accent"
          >
            <p>{focus.replacement ?? focus.behavior}</p>
            {focus.replacement ? (
              <p className={coachingStyles.note}>{RETAINED.suggested}</p>
            ) : null}
          </StoryCard>
        </Pillar>
        <Pillar id="report-coaching-mission" copy={CALL_PILLARS.next} level={3}>
          <StoryCard label={NEXT.mission} tone="accent" icon={Target}>
            <p
              className={coachingStyles.missionBehavior}
              data-active-mission=""
            >
              {focus.behavior}
            </p>
            {focus.target ? (
              <dl className={coachingStyles.terms}>
                <div>
                  <dt>{NEXT.doneWhen}</dt>
                  <dd>{focus.target}</dd>
                </div>
              </dl>
            ) : (
              <p className={coachingStyles.note}>{RETAINED.noCheck}</p>
            )}
          </StoryCard>
          {focus.practice ? (
            <StoryCard label={NEXT.practice} icon={PencilLine}>
              <p>{focus.practice.instructions}</p>
              <p className={coachingStyles.momentNote}>
                <strong>{NEXT.success}:</strong>{" "}
                {focus.practice.success_condition}
              </p>
            </StoryCard>
          ) : null}
          <p className={coachingStyles.note}>{NEXT.oneCall}</p>
        </Pillar>
        {links}
      </div>
    </div>
  );
}
