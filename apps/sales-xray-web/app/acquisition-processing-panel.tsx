"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Check,
  FileAudio2,
  MoreHorizontal,
  ShieldCheck,
} from "lucide-react";
import {
  acquisition,
  AcquisitionError,
  submissionPath,
  type Progress,
} from "./acquisition-client";
import { ProcessingStatusCopy } from "./processing-status-copy";
import { projectProcessing, type ProcessingStage } from "./processing-state";
import {
  formatElapsed,
  PROCESSING_STEPS,
  projectSteps,
  readLivePlan,
  stepIndexForStage,
  type LivePlan,
  type StepState,
} from "./processing-steps";
import { useWorkspaceAccess } from "./workspace-access";
import styles from "./acquisition-processing-panel.module.css";

export type AcquisitionProcessingStageRow = {
  stage: ProcessingStage;
  state: string | null;
  label?: string;
};

type Props = {
  /** Pass projectProcessing(progress, waitingForApproval).rows; never advance these from a timer. */
  stageRows: readonly AcquisitionProcessingStageRow[];
  /** A server-backed status title, such as projectProcessing(...).title. */
  statusText: string;
  fileName?: string;
  fileMeta?: string;
  allowanceLabel?: string;
  paused?: boolean;
  submissionId?: string;
  progress?: Progress | null;
  waitingForApproval?: boolean;
  accepted?: boolean;
  refreshProblem?: boolean;
  /** When the call was saved (ISO), for the elapsed time; omitted when unknown. */
  startedAt?: string;
  /** Local review only: render static synthetic stages without live-call claims. */
  staticPreview?: boolean;
  children?: ReactNode;
};

const POLL_MS = 3_000;
const HIDDEN_POLL_MS = 15_000;
// A ready report the page hasn't opened after this long gets a button.
const OPEN_FALLBACK_MS = 8_000;
const DONE = PROCESSING_STEPS.length;

type Times = { start: (number | null)[]; end: (number | null)[] };
const noTimes = (): Times => ({
  start: PROCESSING_STEPS.map(() => null),
  end: PROCESSING_STEPS.map(() => null),
});

/**
 * The plan's live stage, read every few seconds while the call is analysed
 * (slower in a background tab). Step durations are kept only for steps this
 * screen saw start and finish, so nothing is guessed.
 */
function useLivePlan(submissionId: string | undefined, enabled: boolean) {
  const [plan, setPlan] = useState<LivePlan | null>(null);
  const [times, setTimes] = useState<Times>(noTimes);
  const lastIndex = useRef<number | null>(null);
  useEffect(() => {
    if (!submissionId || !enabled) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const tick = async () => {
      try {
        const next = readLivePlan(
          await acquisition(`${submissionPath(submissionId)}/plan`, {
            signal: abort.signal,
          }),
        );
        if (abort.signal.aborted) return;
        if (next) {
          const finished =
            next.reportReady ||
            next.state === "completed" ||
            next.state === "cancelled";
          const index = finished ? DONE : stepIndexForStage(next.stage);
          const before = lastIndex.current;
          if (index !== null && before !== null && index > before) {
            const now = Date.now();
            setTimes((current) => ({
              start: current.start.map((value, step) =>
                step === index ? now : value,
              ),
              end: current.end.map((value, step) =>
                step >= before && step < index ? now : value,
              ),
            }));
          }
          if (index !== null) lastIndex.current = index;
          setPlan(next);
          stopped = finished;
        }
      } catch (error) {
        if (abort.signal.aborted) return;
        // A call without a plan (older servers) keeps the task rows as truth.
        if (
          error instanceof AcquisitionError &&
          [401, 403, 404].includes(error.status)
        )
          stopped = true;
      }
      if (!stopped && !abort.signal.aborted)
        timer = setTimeout(
          () => void tick(),
          document.visibilityState === "hidden" ? HIDDEN_POLL_MS : POLL_MS,
        );
    };
    void tick();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, [submissionId, enabled]);
  return { plan, times };
}

/** The browser's own offline signal, for one honest line. */
function useOffline() {
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    const sync = () => setOffline(!navigator.onLine);
    const first = setTimeout(sync, 0);
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      clearTimeout(first);
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
    };
  }, []);
  return offline;
}

/** A clock for the elapsed time, ticking only while it is shown. */
function useNow(running: boolean) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (!running) return;
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const timer = setInterval(tick, 1_000);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [running]);
  return now;
}

/** A step's status: measured time when seen, else the server's own label. */
function stepStatus(
  state: StepState,
  duration: number | null,
  row: AcquisitionProcessingStageRow | undefined,
) {
  if (state === "done") {
    if (duration !== null) return `Done · ${formatElapsed(duration)}`;
    return row?.state === "completed"
      ? "Complete"
      : row?.state === "saved"
        ? "Work saved"
        : "Done";
  }
  if (state === "active") return "In progress";
  if (state === "attention")
    return row?.state === "uncertain"
      ? "Paused · needs attention"
      : ["failed", "held"].includes(row?.state ?? "")
        ? "Needs attention"
        : "Paused";
  return row?.state === "queued" || row?.state === "pending" ? "Queued" : "";
}

export function AcquisitionProcessingPanel({
  stageRows,
  fileName,
  fileMeta,
  paused = false,
  submissionId,
  refreshProblem = false,
  progress,
  waitingForApproval = false,
  accepted = false,
  startedAt,
  staticPreview = false,
  children,
}: Props) {
  const access = useWorkspaceAccess();
  const offline = useOffline();
  const projection = projectProcessing(progress ?? null, waitingForApproval);
  const live = useLivePlan(submissionId, !staticPreview);
  const needsAttention =
    paused ||
    projection.paused ||
    stageRows.some((row) =>
      ["held", "failed", "cancelled", "uncertain"].includes(row.state ?? ""),
    ) ||
    ["held", "failed"].includes(live.plan?.state ?? "");
  const hasReport = Boolean(progress?.has_report || live.plan?.reportReady);
  const states = projectSteps({
    plan: live.plan,
    rows: stageRows,
    attention: needsAttention,
    hasReport,
  });
  const notStarted = waitingForApproval && !accepted && !live.plan?.stage;
  const working =
    !staticPreview && !needsAttention && !hasReport && !notStarted;
  const started = startedAt ? Date.parse(startedAt) : NaN;
  const now = useNow(working && Number.isFinite(started));
  const elapsed =
    now !== null && Number.isFinite(started)
      ? formatElapsed(now - started)
      : null;

  const [openStale, setOpenStale] = useState(false);
  useEffect(() => {
    if (!hasReport || staticPreview) return;
    const timer = setTimeout(() => setOpenStale(true), OPEN_FALLBACK_MS);
    return () => clearTimeout(timer);
  }, [hasReport, staticPreview]);

  const phase = staticPreview
    ? "example"
    : needsAttention
      ? "attention"
      : hasReport
        ? "done"
        : notStarted
          ? "ready"
          : "working";
  const headline =
    phase === "example"
      ? "Example processing state"
      : phase === "attention"
        ? projection.paused
          ? "Analysis paused"
          : "Your call needs attention"
        : phase === "done"
          ? "Your report is ready"
          : phase === "ready"
            ? "Ready to start"
            : "Analysing your call";
  const subline =
    phase === "example"
      ? "Paused interface example. No call was uploaded or analysed."
      : phase === "attention"
        ? "This stage needs checking before analysis can continue."
        : phase === "done"
          ? "Opening it now."
          : phase === "ready"
            ? "Your recording is saved. Start analysis to generate your report."
            : refreshProblem || offline
              ? `${offline ? "Your browser is offline." : "Status cannot currently be refreshed."} The steps show the last confirmed update.`
              : `Usually about 2–4 minutes${elapsed ? ` · ${elapsed} so far` : ""}`;
  const signedIn = access?.authenticated === true;
  // Recovery and start actions stay in view; the rest wait in the ⋯ menu.
  const actionsInline = phase === "attention" || phase === "ready";

  return (
    <section
      className={styles.panel}
      aria-label={
        staticPreview ? "Example analysis progress" : "Analysis progress"
      }
      data-phase={phase}
      data-paused={needsAttention}
      data-fixture={staticPreview}
    >
      <div className={styles.head}>
        <span className={styles.signal} data-phase={phase} aria-hidden="true">
          {phase === "attention" ? (
            <AlertTriangle size={16} strokeWidth={2.2} />
          ) : phase === "done" ? (
            <Check size={16} strokeWidth={2.6} />
          ) : (
            <i />
          )}
        </span>
        <div
          className={styles.headCopy}
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          {phase === "attention" && submissionId ? (
            // The reason and any safe retry (Strike C) come from the status copy.
            <ProcessingStatusCopy
              submissionId={submissionId}
              progress={progress ?? null}
              title={headline}
              paused={projection.paused}
              needsAttention
              refreshProblem={refreshProblem || offline}
              waitingForApproval={waitingForApproval}
            />
          ) : (
            <>
              <h2 id="acquisition-processing-title">{headline}</h2>
              <p>{subline}</p>
            </>
          )}
        </div>
      </div>

      <ol className={styles.steps} aria-label="Processing stages">
        {PROCESSING_STEPS.map((step, index) => {
          const state = states[index];
          const start = live.times.start[index];
          const end = live.times.end[index];
          const duration =
            start !== null && end !== null ? Math.max(0, end - start) : null;
          return (
            <li
              key={step.id}
              className={styles.step}
              data-stage={step.id}
              data-state={state}
              aria-current={state === "active" ? "step" : undefined}
            >
              <span className={styles.marker} aria-hidden="true">
                {state === "done" ? (
                  <Check size={13} strokeWidth={3} />
                ) : state === "attention" ? (
                  <AlertTriangle size={12} strokeWidth={2.4} />
                ) : null}
              </span>
              <span className={styles.stepCopy}>
                <strong>{step.title}</strong>
                <span>{step.description}</span>
              </span>
              <small className={styles.stepStatus}>
                {stepStatus(
                  state,
                  duration,
                  stageRows.find((row) => row.stage === step.id),
                )}
              </small>
            </li>
          );
        })}
      </ol>

      {!staticPreview && phase === "attention" && (
        <aside className={styles.savedWork} aria-label="Saved work">
          <ShieldCheck size={16} aria-hidden="true" />
          <div>
            <strong>Your recording is saved</strong>
            <p>There’s no need to upload it again.</p>
            <p>
              {projection.savedTranscript
                ? "The completed transcript stays attached to this call."
                : "A completed transcript has not been confirmed yet."}
            </p>
            {projection.savedEvidence && (
              <p>Some conversation analysis is saved with this call.</p>
            )}
          </div>
        </aside>
      )}

      {!staticPreview && actionsInline && children ? (
        <div className={styles.actions} role="group" aria-label="Call actions">
          {children}
        </div>
      ) : null}

      {phase === "done" && openStale ? (
        <div className={styles.actions}>
          <button
            type="button"
            className="primary-button"
            onClick={() => window.location.reload()}
          >
            Open report
          </button>
        </div>
      ) : null}

      <div className={styles.file}>
        <FileAudio2 size={16} strokeWidth={1.9} aria-hidden="true" />
        <strong title={fileName || undefined}>
          {fileName || (staticPreview ? "Example audio" : "Your recording")}
        </strong>
        {fileMeta && <small>{fileMeta}</small>}
        {!staticPreview && !actionsInline && children ? (
          <details className={styles.more}>
            <summary aria-label="More actions" title="More actions">
              <MoreHorizontal size={16} aria-hidden="true" />
            </summary>
            <div className={styles.menu} role="group" aria-label="Call actions">
              {children}
            </div>
          </details>
        ) : null}
      </div>

      {phase === "working" && (
        <p className={styles.note}>
          {signedIn
            ? "You can leave this page. Your report will appear in Calls when it’s ready."
            : "You can leave this page. Keep this call’s link to come back while your session and call remain available."}
        </p>
      )}
    </section>
  );
}
