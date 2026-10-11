"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { DocumentReportData } from "./report-document-data";
import type { ReportEvidence, SalesReport } from "./report-contract";
import { REPORT_SKILLS } from "./report-pillars";
import { RichText } from "./report-entities";
import { Clip } from "./report-kit";
import { basisChip } from "./coaching/call-coaching";
import { CALL_PILLARS, NEXT, WHY } from "./coaching/coaching-copy";
import {
  dipakTake,
  FocusHero,
  LessonPanel,
  MissionPanel,
  Pillar,
} from "./coaching/coaching-ui";
import coachingStyles from "./coaching/coaching.module.css";
import { MomentList } from "./coaching/evidence-player";
import { StoryCard } from "./report-visuals/visuals";
import { kitStyles } from "./ui/kit";
import { formatClock } from "./lightbox/time";
import {
  buildContextualSourcePlayback,
  type ContextualSourcePlayback,
} from "./source-playback-context";
import styles from "./report-call-coaching.module.css";
import { useWorkspaceAccess } from "./workspace-access";
import { notify, dismissNotice } from "./notice-center";
import {
  parseCallCoaching,
  readCallCoaching,
  CallCoachingReadError,
  type CallCoaching,
} from "./report-call-coaching-client";

/** A retained finding supplies a suggestion, never a new diagnosis or score. */
export function callCoachingFocus(report: SalesReport) {
  if (report.preview) return null;
  const proposed = report.overview?.next_call_focus;
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

function RetainedCallCoaching({
  data,
  callId,
  onSelectEvidence,
  onSelectContextualPlayback,
}: Props) {
  const report = data.report;
  if (!report || report.preview) return null;
  const focus = callCoachingFocus(report);
  return (
    <div
      className={styles.coaching}
      data-call-coaching
      data-state="report-focus"
    >
      <p className={styles.context}>
        A suggestion from this call’s report. One call does not establish a
        recurring pattern.
      </p>
      {focus ? (
        <>
          <section aria-label="Focus for this call">
            <h3>{focus.improvement ? "One focus" : "Keep doing"}</h3>
            <p className={styles.focus}>
              <RichText text={focus.behavior} />
            </p>
          </section>
          <section aria-label="Why this focus">
            <h3>What happened on this call</h3>
            <p>
              <RichText text={focus.finding.explanation} />
            </p>
            {focus.why && (
              <p>
                <span className={styles.label}>Why it may matter · </span>
                <RichText text={focus.why} />
              </p>
            )}
            <div className={styles.sources}>
              {focus.finding.evidence.map((source, index) => {
                const playback =
                  data.transcript && onSelectContextualPlayback
                    ? buildContextualSourcePlayback(
                        report,
                        data.transcript,
                        source,
                      )
                    : null;
                return onSelectEvidence ? (
                  <Clip
                    key={index}
                    evidence={source}
                    title="Coaching for this call"
                    onPlay={onSelectEvidence}
                    context={
                      playback && onSelectContextualPlayback
                        ? { playback, onPlay: onSelectContextualPlayback }
                        : null
                    }
                  />
                ) : (
                  <figure key={index}>
                    <figcaption>
                      {formatClock(source.start_ms)}–
                      {formatClock(source.end_ms)}
                    </figcaption>
                    <blockquote>
                      <RichText text={source.quote} />
                    </blockquote>
                  </figure>
                );
              })}
            </div>
          </section>
          <section aria-label="What to try">
            <h3>
              {focus.improvement
                ? "Try this next time"
                : "Carry this into the next call"}
            </h3>
            <p>
              <RichText text={focus.replacement ?? focus.behavior} />
            </p>
            {focus.replacement && (
              <small>
                Suggested wording or behavior from the report; not a quote from
                the call.
              </small>
            )}
          </section>
          <section aria-label="Next-call mission">
            <h3>Your next-call mission</h3>
            <p>
              <RichText text={focus.behavior} />
            </p>
            {focus.target ? (
              <p>
                <span className={styles.label}>Done when · </span>
                <RichText text={focus.target} />
              </p>
            ) : (
              <p className={styles.context}>
                This report did not supply a success check. Decide what you will
                look for before your next call.
              </p>
            )}
            {focus.practice && (
              <div className={styles.practice}>
                <h4>Practise once</h4>
                <p>
                  <RichText text={focus.practice.instructions} />
                </p>
                <p>
                  <span className={styles.label}>Done when · </span>
                  <RichText text={focus.practice.success_condition} />
                </p>
              </div>
            )}
          </section>
        </>
      ) : (
        <p>
          No source-backed focus was supplied for this call. Choose a skill to
          work on below.
        </p>
      )}
      <div className={styles.links}>
        {callId &&
          /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
            callId,
          ) && (
            <Link prefetch={false} href={`/coaching?call=${callId}`}>
              Open full coaching for this call
            </Link>
          )}
        <Link
          prefetch={false}
          href={
            focus?.skillId ? `/coaching?focus=${focus.skillId}` : "/coaching"
          }
        >
          My coaching across calls
        </Link>
        {!focus &&
          REPORT_SKILLS.map(([id, label]) => (
            <Link key={id} prefetch={false} href={`/coaching?focus=${id}`}>
              {label}
            </Link>
          ))}
      </div>
    </div>
  );
}
