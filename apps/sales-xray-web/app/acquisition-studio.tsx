"use client";
import { AnalysisAvailability } from "./analysis-availability";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AudioLines,
  ArrowRight,
  Check,
  ChevronDown,
  Clock3,
  Download,
  FileAudio,
  FileText,
  FolderOpen,
  HardDrive,
  LoaderCircle,
  ListChecks,
  MoreHorizontal,
  ShieldCheck,
  Sparkles,
  Upload,
} from "lucide-react";
import {
  CallStudio,
  parseProcessingPlan,
  type ProcessingPlan,
  type CallStudioVariant,
} from "./call-studio";
import { AcquisitionShell } from "./acquisition-shell";
import { DipakOverview } from "./dipak-overview";
import { ReportExplorer } from "./report-explorer";
import { SalesSkills } from "./sales-skills";
import { ReportMoments } from "./report-moments";
import { NextCallPlan } from "./next-call-plan";
import {
  ReportTranscript,
  formatTranscriptTime as time,
} from "./report-transcript";
import {
  parseAcquisitionReport,
  parseTranscript,
  type ReportEvidence,
  type SalesReport,
  type Transcript,
} from "./report-contract";
import {
  ACQUISITION,
  AcquisitionError,
  acquisition,
  clearRequestedSubmission,
  parseAllowance,
  parseEntry,
  parsePolicy,
  parseProgress,
  parseSubmission,
  record,
  rememberSubmission,
  requestedSubmissionId,
  savedSubmissionId,
  submissionPath,
  type Allowance,
  type Entry,
  type Progress,
  type Submission,
  type UploadPolicy,
} from "./acquisition-client";
import { ProcessingVisual } from "./processing-visual";
import { ProcessingStatusCopy } from "./processing-status-copy";
import { isNewCallRequested, setNewCallRequested } from "./new-call-navigation";
import { UploadCheck } from "./upload-check";
import { useWorkspaceAccess } from "./workspace-access";
import { CallAudioDock } from "./call-audio-dock";
import { SourceWaveformProvider } from "./source-waveform";
import styles from "./acquisition-studio.module.css";

type Result = { report: SalesReport; transcript: Transcript; claimed: boolean };
const stageNames: Record<string, string> = {
  C2: "Transcribing your call",
  C4: "Checking the conversation",
  C5: "Writing your coaching report",
};
const processingStages = ["C2", "C4", "C5"] as const;
const stageLabels = { C2: "Transcript", C4: "Conversation", C5: "Report" };
type ProcessingStage = (typeof processingStages)[number];

function latestStage(progress: Progress | null, stage: ProcessingStage) {
  return progress?.stages.findLast((row) => row.stage === stage) ?? null;
}

function stageStatusLabel(status: string | null) {
  if (status === "completed") return "Complete";
  if (status === "saved") return "Work saved";
  if (status === "running") return "In progress";
  if (status === "uncertain") return "Paused · needs attention";
  if (status === "queued" || status === "pending") return "Queued";
  if (status === "cancelled") return "Cancelled";
  if (status === "failed" || status === "held") return "Needs attention";
  return status === null ? "Not started" : "Status needs checking";
}

const message = (error: unknown) =>
  error instanceof AcquisitionError
    ? error
    : "This result could not be verified. Try again; your completed work stays saved.";

const quoteRequestKey = () => `report-plan:${crypto.randomUUID()}`;

export function savedCallsHref(embedded: boolean): string {
  return embedded ? "/sales-xray/calls" : "/calls";
}

export function remainingAllowanceLabel(
  allowance: Allowance | null,
  advertisedSeconds: number | null,
  unknown: boolean,
): string {
  if (allowance) {
    if (allowance.unlimited) return "Unlimited testing";
    const minutes = Math.floor(allowance.available_seconds / 60);
    const remainder = String(allowance.available_seconds % 60).padStart(2, "0");
    return allowance.available_seconds === 0
      ? `Remaining analysis time · ${minutes}m ${remainder}s · exhausted`
      : `Remaining analysis time · ${minutes}m ${remainder}s`;
  }
  if (unknown)
    return "Remaining analysis time · unavailable until your session is confirmed";
  if (advertisedSeconds !== null)
    return `Up to ${Math.floor(advertisedSeconds / 60)}m trial allowance`;
  return "Remaining analysis time · checking…";
}

export function AcquisitionStudio({
  variant = "standalone",
  homeHref = "/",
}: {
  variant?: CallStudioVariant;
  homeHref?: string;
}) {
  const embedded = variant === "embedded";
  // The standalone shell owns the page landmark; embedded mounts inherit one.
  const access = useWorkspaceAccess();
  const [entry, setEntry] = useState<Entry | null>(null);
  const router = useRouter();
  const [analysisPaused, setAnalysisPaused] = useState(false);
  const [policy, setPolicy] = useState<UploadPolicy | null>(null);
  const [allowance, setAllowance] = useState<Allowance | null>(null);
  const [allowanceUnknown, setAllowanceUnknown] = useState(false);
  const [session, setSession] = useState(false);
  const [claimAvailable, setClaimAvailable] = useState(false);
  const [savedCallNeedsSession, setSavedCallNeedsSession] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState("");
  const [consent, setConsent] = useState(false);
  const [token, setToken] = useState("");
  const [checkKey, setCheckKey] = useState(0);
  const [submission, setSubmission] = useState<Submission | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [plan, setPlan] = useState<ProcessingPlan | null>(null);
  // Upload consent is deliberately ephemeral. It is only eligible to approve
  // the quote for the submission created from the currently selected file.
  // Reloaded/held work must take the explicit recovery path below.
  const [consentedSubmissionId, setConsentedSubmissionId] = useState<
    string | null
  >(null);
  const [planRequiresAction, setPlanRequiresAction] = useState(false);
  const [planExpired, setPlanExpired] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState("");
  const [playbackExpanded, setPlaybackExpanded] = useState(false);
  const [error, setError] = useState<string | AcquisitionError>("");
  const [attempt, setAttempt] = useState(0);
  const [pollAttempt, setPollAttempt] = useState(0);
  const [moment, setMoment] = useState<ReportEvidence | null>(null);
  const [playbackMessage, setPlaybackMessage] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [deletionOnlyId, setDeletionOnlyId] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const controller = useRef<AbortController | null>(null);
  const active = useRef(true);
  const inFlight = useRef(false);
  const chosenId = useRef("");
  const quoteKey = useRef("");
  const requestedPlan = useRef("");
  const stalePlanRefresh = useRef<string | null>(null);
  const previewUrl = useRef("");
  const onToken = useCallback((value: string) => setToken(value), []);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      controller.current?.abort();
      if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    };
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    const signal = abort.signal;
    // Capture this navigation before any awaits. A new upload can consume the
    // URL marker while entry/session reads are still in flight.
    const requested = requestedSubmissionId();
    const newCall = !requested && isNewCallRequested();
    const saved = requested ?? (newCall ? null : savedSubmissionId());
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      abort.abort();
    }, 12_000);
    void (async () => {
      try {
        const config = parseEntry(await acquisition("/entry", { signal }));
        if (signal.aborted) return;
        setEntry(config);
        if (!config.enabled) return;
        const terms = parsePolicy(
          await acquisition("/upload-policy", { signal }),
        );
        let current: Record<string, unknown> | null = null;
        try {
          current = record(await acquisition("/session", { signal }));
        } catch (error) {
          if (embedded) throw error;
          if (!(error instanceof AcquisitionError && error.status === 401))
            throw error;
        }
        if (signal.aborted) return;
        if (embedded && (!current || current.state === "guest"))
          throw new AcquisitionError(401);
        setPolicy(terms);
        setSession(current !== null);
        if (current) {
          setAllowance(parseAllowance(current.allowance));
          setAllowanceUnknown(false);
          setClaimAvailable(
            !newCall &&
              !requested &&
              (current.claim_available === true ||
                current.state === "claim_required"),
          );
          if (
            !newCall &&
            !requested &&
            (current.claim_available === true ||
              current.state === "claim_required")
          )
            return;
        }
        setAllowanceUnknown(saved !== null);
        if (saved) {
          try {
            const loaded = await acquisition(submissionPath(saved), { signal });
            if (signal.aborted) {
              if (timedOut) throw new Error("saved_call_load_timeout");
              return;
            }
            const bound = parseSubmission(loaded);
            if (bound.id !== saved) throw new Error("submission_mismatch");
            if (requested) rememberSubmission(bound.id);
            setSubmission(bound);
            setProgress(parseProgress(loaded, bound));
            setDeletionOnlyId(null);
          } catch (error) {
            if (signal.aborted) {
              if (timedOut) throw error;
              return;
            }
            // A retained submission can stop being readable when its
            // permission expires. Keep only the opaque selector so the owner
            // still has an explicit, server-authorized deletion path; do not
            // render or infer any private content from the failed lookup.
            if (
              error instanceof AcquisitionError &&
              error.status === 401 &&
              current === null
            ) {
              // A stale opaque selector does not prove that the saved call was
              // deleted. Keep it in local storage, but give a standalone guest
              // a clean path to upload a new call without weakening ownership
              // checks for the saved call itself.
              setSavedCallNeedsSession(true);
              setError(
                "That saved call belongs to another browser session. Start a new call with your available trial allowance, or sign in to recover it.",
              );
              return;
            }
            if (
              error instanceof AcquisitionError &&
              (error.status === 403 || error.status === 404)
            ) {
              setDeletionOnlyId(saved);
              setError(
                "This saved call cannot be opened here. If you own it, you can still delete it.",
              );
              return;
            }
            throw error;
          }
        }
      } catch (error) {
        if (!signal.aborted) setError(message(error));
        else if (timedOut)
          setError(
            "Sales Xray is taking longer than expected to load. Check again to continue your guest analysis.",
          );
      } finally {
        window.clearTimeout(timeout);
      }
    })();
    return () => {
      window.clearTimeout(timeout);
      abort.abort();
    };
  }, [attempt, embedded]);

  useEffect(() => {
    const sync = setTimeout(
      () =>
        setPlanExpired(!!plan && plan.expires_at_epoch * 1000 <= Date.now()),
      0,
    );
    const expiry = plan
      ? setTimeout(
          () => setPlanExpired(true),
          Math.max(
            0,
            Math.min(2147483647, plan.expires_at_epoch * 1000 - Date.now()),
          ),
        )
      : undefined;
    return () => {
      clearTimeout(sync);
      if (expiry) clearTimeout(expiry);
    };
  }, [plan]);

  const getPlan = useCallback(
    async (bound: Submission, signal: AbortSignal) => {
      if (!quoteKey.current) quoteKey.current = quoteRequestKey();
      try {
        return parseProcessingPlan(
          await acquisition(`${submissionPath(bound.id)}/plan/quote`, {
            method: "POST",
            signal,
            headers: { "Idempotency-Key": quoteKey.current },
          }),
          bound.recordingId,
        );
      } catch (error) {
        // A failed quote cannot safely be retried with the same request key:
        // the server may already have recorded that key for a different
        // approval bundle. The quote is side-effect free, so the next explicit
        // recovery attempt gets a new bounded key.
        quoteKey.current = "";
        throw error;
      }
    },
    [],
  );

  const refreshStalePlan = useCallback(
    async (bound: Submission, signal: AbortSignal) => {
      if (stalePlanRefresh.current === bound.id) return false;
      stalePlanRefresh.current = bound.id;
      quoteKey.current = `report-plan:${crypto.randomUUID()}`;
      const next = await getPlan(bound, signal);
      if (signal.aborted) return true;
      setPlan(next);
      setPlanExpired(next.expires_at_epoch * 1000 <= Date.now());
      setPlanRequiresAction(true);
      setError("");
      setPollAttempt((n) => n + 1);
      return true;
    },
    [getPlan],
  );

  const acceptPlanRequest = useCallback(
    async (bound: Submission, shown: ProcessingPlan, signal: AbortSignal) => {
      if (analysisPaused) {
        setPlanRequiresAction(true);
        return;
      }
      if (shown.expires_at_epoch * 1000 <= Date.now()) {
        setPlanExpired(true);
        setPlanRequiresAction(true);
        return;
      }
      const accepted = parseProcessingPlan(
        await acquisition(`${submissionPath(bound.id)}/plan`, {
          method: "POST",
          signal,
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": `accept-plan:${shown.id}`,
          },
          body: JSON.stringify({
            plan_id: shown.id,
            plan_fingerprint: shown.plan_fingerprint,
            privacy_revision: shown.privacy_revision,
            accepted: true,
          }),
        }),
        bound.recordingId,
      );
      if (!signal.aborted) {
        setPlan(accepted);
        setPlanRequiresAction(false);
        setPlanExpired(false);
        setPollAttempt((n) => n + 1);
      }
    },
    [analysisPaused],
  );

  useEffect(() => {
    if (!submission || result) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    const bound = submission;
    async function poll() {
      try {
        const next = parseProgress(
          await acquisition(submissionPath(bound.id), { signal: abort.signal }),
          bound,
        );
        if (abort.signal.aborted) return;
        setProgress(next);
        if (next.has_report) {
          const transcript = parseTranscript(
            await acquisition(`${submissionPath(bound.id)}/transcript`, {
              signal: abort.signal,
            }),
            bound.sha,
          );
          const verified = parseAcquisitionReport(
            await acquisition(`${submissionPath(bound.id)}/report`, {
              signal: abort.signal,
            }),
            { submissionId: bound.id, recordingId: bound.recordingId },
            transcript,
          );
          if (!abort.signal.aborted) {
            setResult({ ...verified, transcript });
            setError("");
          }
          return;
        }
        if (
          next.local_state === "failed" ||
          next.local_state === "cancelled" ||
          ["held", "cancelled", "completed"].includes(next.state)
        ) {
          const paused =
            next.state === "held" ||
            next.stages.some((stage) => stage.state === "uncertain");
          if (paused) setError("");
          else
            setError(
              "This analysis needs attention. Your call is saved; completed work remains available.",
            );
          return;
        }
        if (
          next.local_state === "completed" &&
          !next.automatic_progression &&
          requestedPlan.current !== bound.id
        ) {
          requestedPlan.current = bound.id;
          try {
            const approved = await getPlan(bound, abort.signal);
            if (!abort.signal.aborted) {
              setPlan(approved);
              setPlanExpired(approved.expires_at_epoch * 1000 <= Date.now());
              const canAutoApprove =
                consentedSubmissionId === bound.id &&
                !planRequiresAction &&
                !analysisPaused &&
                approved.expires_at_epoch * 1000 > Date.now();
              if (canAutoApprove) {
                try {
                  await acceptPlanRequest(bound, approved, abort.signal);
                } catch (error) {
                  if (
                    error instanceof AcquisitionError &&
                    error.reason === "plan_stale"
                  ) {
                    if (!(await refreshStalePlan(bound, abort.signal))) {
                      setPlanRequiresAction(true);
                      throw error;
                    }
                  } else {
                    setPlanRequiresAction(true);
                    throw error;
                  }
                }
              } else {
                // A reloaded submission has no ephemeral upload consent and
                // must always stop at this explicit approval boundary.
                setPlanRequiresAction(true);
              }
            }
          } catch (error) {
            requestedPlan.current = "";
            throw error;
          }
        }
        failures = 0;
      } catch (error) {
        if (abort.signal.aborted) return;
        failures += 1;
        setError(message(error));
        if (
          failures >= 3 ||
          (error instanceof AcquisitionError &&
            [401, 403, 404, 409].includes(error.status))
        )
          return;
      }
      if (!abort.signal.aborted)
        timer = setTimeout(() => void poll(), failures ? 6000 : 3000);
    }
    void poll();
    return () => {
      abort.abort();
      if (timer) clearTimeout(timer);
    };
  }, [
    analysisPaused,
    acceptPlanRequest,
    getPlan,
    refreshStalePlan,
    consentedSubmissionId,
    planRequiresAction,
    submission,
    result,
    pollAttempt,
  ]);

  function choose(next: File | undefined) {
    if (!next || inFlight.current || submission) return;
    setError("");
    setDeleted(false);
    setConsent(false);
    setConsentedSubmissionId(null);
    setPlanRequiresAction(false);
    if (
      !policy ||
      !/\.(mp3|mpeg|wav|m4a|ogg|flac)$/i.test(next.name) ||
      !next.size ||
      next.size > policy.maximum_file_bytes
    ) {
      setError(
        "Choose an MP3, MPEG, WAV, M4A, OGG or FLAC within the displayed size limit.",
      );
      return;
    }
    chosenId.current = crypto.randomUUID();
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    previewUrl.current = URL.createObjectURL(next);
    setAudioUrl(previewUrl.current);
    setFile(next);
  }

  async function operation(
    label: string,
    task: (signal: AbortSignal) => Promise<void>,
  ) {
    if (inFlight.current) return;
    inFlight.current = true;
    controller.current = new AbortController();
    setBusy(label);
    setError("");
    try {
      await task(controller.current.signal);
    } catch (error) {
      if (active.current && !controller.current.signal.aborted)
        setError(message(error));
    } finally {
      inFlight.current = false;
      if (active.current) setBusy("");
    }
  }

  async function upload() {
    if (!file || !policy || !consent || (!session && !token)) return;
    if (embedded && !session) return;
    const selected = file;
    await operation("Uploading and checking your call…", async (signal) => {
      if (!session) {
        try {
          const issued = record(
            await acquisition("/session", {
              method: "POST",
              signal,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ challenge_token: token }),
            }),
          );
          if (signal.aborted) return;
          setSession(true);
          setAllowance(parseAllowance(issued.allowance));
          setAllowanceUnknown(false);
        } finally {
          if (!signal.aborted) {
            setToken("");
            setCheckKey((key) => key + 1);
          }
        }
      }
      const digest = await crypto.subtle.digest(
        "SHA-256",
        await selected.arrayBuffer(),
      );
      if (signal.aborted) return;
      const sha = Array.from(new Uint8Array(digest), (n) =>
        n.toString(16).padStart(2, "0"),
      ).join("");
      const id = chosenId.current;
      // Only an opaque selector is remembered. Cookies stay HttpOnly; no report,
      // transcript, filename, audio or credential is copied to browser storage.
      rememberSubmission(id);
      // Once a new upload starts, reload must recover that attempt normally.
      setNewCallRequested(false);
      const raw = record(
        await acquisition(`${submissionPath(id)}/source`, {
          method: "PUT",
          signal,
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Source-SHA256": sha,
            "X-Upload-Policy": policy.policy_sha256,
            "X-Upload-Consent": "accepted",
          },
          body: selected,
        }),
      );
      const bound = parseSubmission(raw);
      if (bound.id !== id || bound.sha !== sha)
        throw new Error("uploaded_source_mismatch");
      if (signal.aborted) return;
      setAllowance(parseAllowance(raw.allowance));
      setAllowanceUnknown(false);
      setSubmission(bound);
      setConsent(false);
      setConsentedSubmissionId(bound.id);
      setPlanRequiresAction(false);
    });
  }

  async function approvePlan() {
    if (
      analysisPaused ||
      !submission ||
      !plan ||
      plan.expires_at_epoch * 1000 <= Date.now()
    ) {
      if (plan && plan.expires_at_epoch * 1000 <= Date.now())
        setPlanExpired(true);
      return;
    }
    const bound = submission;
    const shown = plan;
    await operation("Starting your report…", async (signal) => {
      try {
        await acceptPlanRequest(bound, shown, signal);
      } catch (error) {
        if (
          error instanceof AcquisitionError &&
          error.reason === "plan_stale"
        ) {
          if (await refreshStalePlan(bound, signal)) return;
        }
        throw error;
      }
    });
  }

  async function freshPlan() {
    if (!submission || analysisPaused) return;
    const bound = submission;
    await operation("Checking available analysis…", async (signal) => {
      quoteKey.current = `report-plan:${crypto.randomUUID()}`;
      const next = await getPlan(bound, signal);
      if (!signal.aborted) {
        setPlan(next);
        setPlanExpired(next.expires_at_epoch * 1000 <= Date.now());
        setPlanRequiresAction(true);
        setPollAttempt((n) => n + 1);
      }
    });
  }

  function reset(options?: { preserveSavedSubmission?: boolean }) {
    if (inFlight.current) return;
    audio.current?.pause();
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    previewUrl.current = "";
    setFile(null);
    setAudioUrl("");
    setSubmission(null);
    setProgress(null);
    setPlan(null);
    setResult(null);
    setConsent(false);
    setConsentedSubmissionId(null);
    setPlanRequiresAction(false);
    setSavedCallNeedsSession(false);
    stalePlanRefresh.current = null;
    setMoment(null);
    setPlaybackMessage("");
    setError("");
    setDeleteConfirm(false);
    setDeletionOnlyId(null);
    chosenId.current = "";
    requestedPlan.current = "";
    quoteKey.current = "";
    clearRequestedSubmission();
    if (!options?.preserveSavedSubmission) rememberSubmission(null);
    if (input.current) input.current.value = "";
  }

  function startAnotherCall() {
    if (inFlight.current) return;
    reset({ preserveSavedSubmission: true });
    setNewCallRequested(true);
    // Re-read entry/session without racing an older saved-call lookup.
    setAttempt((n) => n + 1);
  }

  function forgetSavedCall() {
    if (inFlight.current) return;
    rememberSubmission(null);
    clearRequestedSubmission();
    setDeletionOnlyId(null);
    setDeleteConfirm(false);
    setError("");
    chosenId.current = "";
  }

  async function claim() {
    await operation("Saving with your account…", async (signal) => {
      const claimed = record(
        await acquisition("/claim", { method: "POST", signal }),
      );
      if (claimed.state !== "claimed") throw new Error("claim_unconfirmed");
      if (!signal.aborted) {
        setAllowance(parseAllowance(claimed.allowance));
        setAllowanceUnknown(false);
        setClaimAvailable(false);
        setSession(true);
        setResult(null);
        setAttempt((n) => n + 1);
      }
    });
  }

  async function erase() {
    const deletionId = submission?.id ?? deletionOnlyId;
    if (!deletionId || !deleteConfirm) return;
    await operation("Deleting this call…", async (signal) => {
      const deleted = record(
        await acquisition(submissionPath(deletionId), {
          method: "DELETE",
          signal,
          headers: { "Idempotency-Key": `delete:${deletionId}` },
        }),
      );
      if (
        typeof deleted.id !== "string" ||
        !["deleting", "deleted"].includes(String(deleted.state)) ||
        (submission !== null && deleted.id !== submission.recordingId)
      )
        throw new Error("delete_unconfirmed");
      if (!signal.aborted) {
        inFlight.current = false;
        reset();
        setDeleted(true);
      }
    });
  }

  async function downloadReport() {
    if (!submission) return;
    const bound = submission;
    await operation("Preparing your report download…", async (signal) => {
      const response = await fetch(
        `${ACQUISITION}${submissionPath(bound.id)}/report.docx`,
        {
          method: "GET",
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          signal,
          headers: {
            accept:
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          },
        },
      );
      if (!response.ok) throw new AcquisitionError(response.status);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `sales-xray-${bound.id}.docx`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    });
  }

  function seek(evidence: ReportEvidence) {
    if (!audio.current || !result) return;
    setMoment(evidence);
    setPlaybackMessage(
      `Selected ${time(evidence.start_ms)}–${time(evidence.end_ms)}`,
    );
    audio.current.currentTime = evidence.start_ms / 1000;
    void audio.current
      .play()
      .catch(() =>
        setPlaybackMessage(
          "Press play in the audio controls to hear this moment.",
        ),
      );
  }

  if (entry && !entry.enabled) {
    const fallback = <CallStudio variant="embedded" homeHref={homeHref} />;
    return embedded ? (
      fallback
    ) : (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        homeHref={homeHref}
      >
        {fallback}
      </AcquisitionShell>
    );
  }
  const report = result?.report;
  const reportReady = Boolean(report);
  const currentStage =
    progress?.stages.findLast((stage) => stage.state === "running") ??
    progress?.stages.find(
      (stage) => stage.state === "queued" || stage.state === "pending",
    ) ??
    progress?.stages.findLast((stage) => stage.state !== "completed");
  const uncertainStage = processingStages
    .map((stage) => latestStage(progress, stage))
    .find((stage) => stage?.state === "uncertain");
  const pausedStage = uncertainStage ?? currentStage;
  const processingPaused = Boolean(
    progress && (progress.state === "held" || uncertainStage),
  );
  const processingNeedsAttention = Boolean(
    processingPaused ||
      error ||
      (progress &&
        (["failed", "cancelled"].includes(progress.local_state ?? "") ||
          ["cancelled", "completed"].includes(progress.state))),
  );
  const quotePending = progress?.state === "quoted" && !plan;
  const showProcessingPanel =
    submission && !report && (!plan || plan.accepted) && !quotePending;
  const hasSavedTranscript = progress?.stages.some(
    (stage) => stage.stage === "C2" && stage.state === "completed",
  );
  const hasSavedAnalysis = progress?.stages.some(
    (stage) => stage.stage === "C4" && stage.state === "completed",
  );
  const canReviewHeldPlan =
    !error &&
    progress?.state === "held" &&
    progress.local_state === "completed" &&
    latestStage(progress, "C2")?.state === "completed";
  const source = submission
    ? `${ACQUISITION}${submissionPath(submission.id)}/source`
    : audioUrl;
  const audioPlayer = !reportReady ? (
    <audio
      ref={audio}
      src={source || undefined}
      controls
      preload="metadata"
      onError={() =>
        setPlaybackMessage(
          submission
            ? "Audio playback is unavailable. Your saved work is unchanged."
            : "Preview unavailable. You can still choose a different recording.",
        )
      }
      onTimeUpdate={() => {
        if (
          moment &&
          audio.current &&
          audio.current.currentTime >= moment.end_ms / 1000
        )
          audio.current.pause();
      }}
    />
  ) : null;

  const savedCallRecovery =
    savedCallNeedsSession && !submission && !deletionOnlyId ? (
      <div
        className={`notice ${styles.recoveryNotice} ${styles.recoveryError}`}
        role="status"
        aria-live="polite"
      >
        <p>
          That saved call belongs to another browser session. Start a new call
          with your available trial allowance, or sign in to recover it.
        </p>
        <div className={styles.errorActions}>
          <Link className="text-button" href="/login">
            Sign in to recover it
          </Link>
          <button
            className="secondary-button"
            type="button"
            disabled={!!busy}
            onClick={startAnotherCall}
          >
            <ArrowRight size={16} aria-hidden="true" />
            Start a new call
          </button>
        </div>
      </div>
    ) : null;

  const content = (
    <div
      className={`xray-app simple-app ${styles.app}`}
      data-theme="light"
      data-variant={variant}
      data-stage={
        report
          ? "report"
          : submission
            ? "processing"
            : busy
              ? "uploading"
              : "upload"
      }
      data-selected={file ? "true" : "false"}
    >
      <div className="studio-main">
        <AnalysisAvailability onChange={setAnalysisPaused} />
        <nav className="studio-steps" aria-label="Analysis steps">
          {[
            "Your call",
            "Your analysis",
            reportReady ? "Report ready" : "Your next step",
          ].map((label, index) => (
            <span
              key={label}
              aria-current={
                (report ? 2 : submission ? 1 : 0) === index ? "step" : undefined
              }
            >
              <b>{index + 1}</b>
              {label}
              {index < 2 && <ChevronDown size={15} />}
            </span>
          ))}
        </nav>
        {!submission && !report && (
          <div className="studio-intro">
            <p className="eyebrow">YOUR NEXT CALL CAN BE BETTER</p>
            <h1>
              {file ? "Turn your calls into clarity." : "Add a call to review."}
            </h1>
            <p>
              Upload a sales call and let Sales Xray find the insights, so you
              can coach, improve, and close more.
            </p>
          </div>
        )}
        {!file && !submission && !report && (
          <div className={styles.uploadAtmosphere} aria-hidden="true">
            <span className={styles.signalOrbit} />
            <span className={styles.signalWave} />
            <div className={styles.uploadAtmosphereSignals}>
              <span className={`${styles.signalChip} ${styles.signalUpload}`}>
                <Upload size={28} aria-hidden="true" />
                <span className={styles.signalCopy}>
                  <strong>Upload</strong>
                  <small>Add your call recording</small>
                </span>
              </span>
              <span className={styles.signalConnector} aria-hidden="true">
                →
              </span>
              <span
                className={`${styles.signalChip} ${styles.signalChipRaised} ${styles.signalEvidence}`}
              >
                <AudioLines size={28} aria-hidden="true" />
                <span className={styles.signalCopy}>
                  <strong>We analyse</strong>
                  <small>Find the key moments</small>
                </span>
              </span>
              <span className={styles.signalConnector} aria-hidden="true">
                →
              </span>
              <span
                className={`${styles.signalChip} ${styles.signalChipLower} ${styles.signalCoaching}`}
              >
                <Sparkles size={28} aria-hidden="true" />
                <span className={styles.signalCopy}>
                  <strong>Get your results</strong>
                  <small>Coach with clarity</small>
                </span>
              </span>
            </div>
          </div>
        )}
        {!entry && !error && (
          <p role="status" className="visually-hidden" aria-live="polite">
            Preparing the upload limits…
          </p>
        )}
        {deleted && (
          <p role="status" className="notice">
            Deletion requested. This call is no longer available here; private
            storage removal is queued.
          </p>
        )}
        {claimAvailable && (
          <aside className={`panel ${styles.claim}`}>
            <ShieldCheck size={22} />
            <div>
              <h2>Keep this call with your AC account</h2>
              <p>
                Save the recording and its report to the account you just signed
                in to.
              </p>
            </div>
            <button
              type="button"
              className="primary-button"
              disabled={!!busy}
              onClick={() => void claim()}
            >
              Save to my account
            </button>
          </aside>
        )}
        {savedCallRecovery}
        <div
          className={`${styles.layout} ${report ? styles.withReport : submission ? styles.withProcessing : busy && !submission ? styles.withBusy : ""}`}
        >
          <section
            className={`panel studio-upload ${styles.upload} ${dragActive ? styles.dragging : ""}`}
            aria-label="Your call"
            onDragEnter={(event) => {
              event.preventDefault();
              if (!busy && !submission && !deletionOnlyId) setDragActive(true);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node))
                setDragActive(false);
            }}
            onDrop={(event) => {
              event.preventDefault();
              setDragActive(false);
              if (!busy && !submission && !deletionOnlyId)
                choose(event.dataTransfer.files?.[0]);
            }}
          >
            <div
              className={styles.stepHeader}
              aria-label="Current analysis step"
            >
              <span className={styles.stepNumber}>
                {reportReady ? "03" : submission ? "02" : "01"}
              </span>
              <span>
                <strong>
                  {reportReady
                    ? "Report ready"
                    : submission
                      ? "Your analysis"
                      : "Your call"}
                </strong>
                <small>
                  {reportReady
                    ? "Explore your saved analysis"
                    : submission
                      ? "Saved work, processing privately"
                      : "Select a recording to begin"}
                </small>
              </span>
            </div>
            {busy && !submission ? (
              <div
                className={`studio-progress ${styles.processingPanel} ${styles.uploadProgress}`}
                role="status"
                aria-live="polite"
              >
                <ProcessingVisual phase="upload" paused={false} />
                <div className={styles.progressCopy}>
                  <p className={styles.progressKicker}>UPLOAD IN PROGRESS</p>
                  <h3>Your call is on its way.</h3>
                  <p>
                    We’re uploading your recording and checking its format and
                    duration. Keep this tab open until the upload finishes.
                  </p>
                </div>
                <div
                  className={styles.progressRail}
                  aria-label="Upload and analysis stages"
                >
                  <div data-state="running">
                    <span aria-hidden="true">1</span>
                    <p>
                      Upload + recording check
                      <small>In progress</small>
                    </p>
                  </div>
                  <div data-state="not-started">
                    <span aria-hidden="true">2</span>
                    <p>
                      Transcript
                      <small>Starts after the check</small>
                    </p>
                  </div>
                  <div data-state="not-started">
                    <span aria-hidden="true">3</span>
                    <p>
                      Coaching report
                      <small>Shown when ready</small>
                    </p>
                  </div>
                </div>
              </div>
            ) : deletionOnlyId && !file && !submission ? (
              <>
                <span className="studio-upload-icon">
                  <FileText size={30} />
                </span>
                <h2>Saved call unavailable</h2>
                <p>
                  This saved call cannot be opened here. If you own it, you can
                  permanently delete it.
                </p>
                <p className="small-text">
                  If deletion is denied, you can forget this selector on this
                  device. That does not delete the stored recording or report.
                </p>
                <button
                  type="button"
                  className="text-button"
                  disabled={!!busy}
                  onClick={forgetSavedCall}
                >
                  Forget this saved call on this device
                </button>
              </>
            ) : !file && !submission ? (
              <div className={styles.dropZone} data-upload-dropzone>
                <span className="studio-upload-icon">
                  <AudioLines className={styles.audioCue} size={30} />
                  <Upload className={styles.uploadCue} size={25} />
                </span>
                <h2>Start with your sales call</h2>
                <p className={styles.dropTitle}>
                  Drag and drop your audio file here
                </p>
                <label
                  className={`${styles.dropSelect} ${!policy ? styles.disabled : ""}`}
                  htmlFor="acquisition-file"
                >
                  or click to browse
                </label>
                <span className="visually-hidden">Choose audio file</span>
                <div className={styles.formatFacts}>
                  <span>
                    <FileAudio size={14} aria-hidden="true" />
                    MP3 · MPEG · WAV · M4A · OGG · FLAC
                  </span>
                  <span>
                    <HardDrive size={14} aria-hidden="true" />
                    Up to{" "}
                    {policy
                      ? Math.floor(policy.maximum_file_bytes / 1048576)
                      : "32"}{" "}
                    MB
                  </span>
                  <span>
                    <Clock3 size={14} aria-hidden="true" />
                    {policy
                      ? `${Math.floor(policy.maximum_call_seconds / 60)} min per call`
                      : "30 min per call"}
                  </span>
                </div>
                <p className="visually-hidden">
                  {policy
                    ? `Up to ${Math.floor(policy.maximum_file_bytes / 1048576)} MB · ${Math.floor(policy.maximum_call_seconds / 60)} minutes per call`
                    : "Checking file limits…"}
                </p>
              </div>
            ) : (
              <>
                {!submission && !result && (
                  <p className={styles.selectionHeading}>
                    <span>1</span> Select your call recording
                  </p>
                )}
                <div className="studio-file">
                  <span className="studio-upload-icon">
                    <AudioLines size={25} />
                  </span>
                  <div>
                    <h2>{file?.name || "Your saved sales call"}</h2>
                    <p>
                      {result
                        ? time(result.transcript.duration_ms)
                        : file
                          ? `Selected locally · ${(file.size / 1048576).toFixed(1)} MB`
                          : "Private original recording"}
                    </p>
                  </div>
                  {!submission && (
                    <button
                      type="button"
                      className="secondary-button"
                      aria-label="Change selected call"
                      disabled={!!busy}
                      onClick={() => reset()}
                    >
                      Change file
                    </button>
                  )}
                </div>
                {!submission && !result ? (
                  <details className={styles.previewDetails}>
                    <summary>Preview recording</summary>
                    {audioPlayer}
                  </details>
                ) : (
                  <div
                    className={styles.savedPlayback}
                    data-expanded={playbackExpanded}
                  >
                    <button
                      type="button"
                      className={styles.playbackToggle}
                      aria-expanded={playbackExpanded}
                      aria-controls="acquisition-saved-audio"
                      onClick={() => setPlaybackExpanded((value) => !value)}
                    >
                      {playbackExpanded ? "Hide player" : "Playback"}
                    </button>
                    <div id="acquisition-saved-audio">{audioPlayer}</div>
                  </div>
                )}
                <p className={`small-text ${styles.previewHint}`}>
                  {submission
                    ? "Select any timestamp to listen to that moment."
                    : "Listen to check this is the right call. Selecting a file does not upload it."}
                </p>
                {playbackMessage && (
                  <p role="status" className="small-text">
                    {playbackMessage}
                  </p>
                )}
              </>
            )}
            <input
              ref={input}
              className="visually-hidden"
              id="acquisition-file"
              type="file"
              accept=".mp3,.mpeg,.wav,.m4a,.ogg,.flac"
              aria-label="Choose sales call audio"
              disabled={!policy || !!busy || !!submission || !!deletionOnlyId}
              onChange={(event) => choose(event.target.files?.[0])}
            />
            {!deletionOnlyId && policy && (
              <div className={styles.allowance}>
                <ShieldCheck size={16} />
                <span>
                  {remainingAllowanceLabel(
                    allowance,
                    entry?.allowance_seconds ?? null,
                    allowanceUnknown,
                  )}
                </span>
              </div>
            )}
            {file && !busy && !deletionOnlyId && policy && !submission && (
              <div className="studio-consent">
                <p className={styles.verifyHeading}>
                  <span>2</span> Verify and continue
                </p>
                <h3>Upload privately</h3>
                <p className={styles.freeBadge}>
                  <span aria-hidden="true">
                    <Check size={13} />
                  </span>
                  Free analysis · included in your trial
                </p>
                <details className={styles.privacyDetails}>
                  <summary>Privacy details</summary>
                  <p>{policy.description}</p>
                  <p>
                    Your recording is retained for {policy.retention_days} days
                    so this review can finish and remain available. You can
                    request deletion from Privacy &amp; support.
                  </p>
                  <p>
                    {policy.privacy_details ||
                      "Approved service providers may process this recording to prepare the transcript and coaching report. The recording and report remain private for the retention period above."}
                  </p>
                </details>
                <label className={styles.consentLabel}>
                  <input
                    type="checkbox"
                    checked={consent}
                    disabled={!!busy}
                    onChange={(event) => setConsent(event.target.checked)}
                  />
                  <span>
                    I agree to the{" "}
                    <a href="https://app.authorityclosers.com/terms">Terms</a>{" "}
                    and{" "}
                    <a href="https://app.authorityclosers.com/privacy">
                      Privacy Policy
                    </a>
                    .
                  </span>
                </label>
                <div className={styles.uploadActions}>
                  {!embedded &&
                    !session &&
                    entry?.site_key &&
                    entry.challenge_action && (
                      <UploadCheck
                        key={checkKey}
                        siteKey={entry.site_key}
                        action={entry.challenge_action}
                        onToken={onToken}
                      />
                    )}
                  <button
                    type="button"
                    className="primary-button studio-wide"
                    disabled={
                      !consent ||
                      (!session && !token) ||
                      !!busy ||
                      (allowance?.available_seconds === 0 &&
                        !allowance?.unlimited)
                    }
                    onClick={() => void upload()}
                  >
                    {busy ? (
                      <LoaderCircle className="spin" size={17} />
                    ) : (
                      <ArrowRight size={17} aria-hidden="true" />
                    )}
                    {busy || "Analyse my call"}
                  </button>
                </div>
              </div>
            )}
            {submission && !report && plan && !plan.accepted && (
              <div className="studio-consent">
                <h3>Ready to continue</h3>
                <p>
                  Your saved call is ready for the next review step. Continue
                  with this same recording to start the analysis.
                </p>
                <p className="small-text">
                  This step is available until{" "}
                  {new Date(plan.expires_at_epoch * 1000).toLocaleString()}.
                </p>
                <details className={styles.privacyDetails}>
                  <summary>Privacy details</summary>
                  <ul>
                    {plan.stages.map((stage) => (
                      <li key={stage.stage}>{stage.privacy_notice}</li>
                    ))}
                  </ul>
                </details>
                <button
                  type="button"
                  className="primary-button studio-wide"
                  disabled={!!busy || planExpired || analysisPaused}
                  onClick={() => void approvePlan()}
                >
                  {busy ? (
                    <LoaderCircle className="spin" size={17} />
                  ) : (
                    <AudioLines size={17} />
                  )}
                  {busy || "Continue analysis"}
                </button>
                {planExpired && (
                  <button
                    className="text-button"
                    type="button"
                    disabled={!!busy || analysisPaused}
                    onClick={() => void freshPlan()}
                  >
                    Refresh expired plan
                  </button>
                )}
              </div>
            )}
            {showProcessingPanel && (
              <div
                className={`studio-progress ${styles.processingPanel}`}
                data-paused={processingNeedsAttention}
                role="status"
                aria-live="polite"
              >
                <ProcessingVisual
                  phase={
                    processingPaused
                      ? pausedStage?.stage === "C2" ||
                        pausedStage?.stage === "C4" ||
                        pausedStage?.stage === "C5"
                        ? pausedStage.stage
                        : "processing"
                      : currentStage?.stage === "C2" ||
                          currentStage?.stage === "C4" ||
                          currentStage?.stage === "C5"
                        ? currentStage.stage
                        : "processing"
                  }
                  paused={processingNeedsAttention}
                />
                <ProcessingStatusCopy
                  submissionId={submission.id}
                  progress={progress}
                  paused={processingPaused}
                  needsAttention={processingNeedsAttention}
                  title={
                    progress?.local_state !== "completed"
                      ? "Checking your recording"
                      : currentStage
                        ? stageNames[currentStage.stage]
                        : "Preparing your analysis"
                  }
                />
                <div
                  className={styles.progressRail}
                  aria-label="Processing stages"
                >
                  {processingStages.map((stage, index) => {
                    const latestStatus =
                      latestStage(progress, stage)?.state ?? null;
                    // C4 can have more chunks than the API currently exposes.
                    const status =
                      stage === "C4" &&
                      latestStatus === "completed" &&
                      !latestStage(progress, "C5")
                        ? "saved"
                        : latestStatus;
                    return (
                      <div
                        key={stage}
                        data-stage={stage}
                        data-state={status ?? "not-started"}
                        data-complete={status === "completed"}
                        aria-label={`${stageNames[stage]}: ${stageStatusLabel(status)}`}
                      >
                        <span aria-hidden="true">
                          {status === "completed" ? (
                            <Check size={13} />
                          ) : (
                            index + 1
                          )}
                        </span>
                        <p>
                          {stageLabels[stage]}
                          <small>{stageStatusLabel(status)}</small>
                        </p>
                      </div>
                    );
                  })}
                </div>
                <div className={styles.progressGuidance}>
                  <p className="eyebrow">
                    {processingNeedsAttention
                      ? "YOUR SAVED WORK"
                      : "WHILE YOU WAIT"}
                  </p>
                  <ul>
                    <li>
                      {processingNeedsAttention
                        ? hasSavedTranscript
                          ? "The completed transcript stays attached to this call."
                          : "A completed transcript has not been confirmed yet."
                        : "Keep this tab open or return later from this browser."}
                    </li>
                    {hasSavedAnalysis && (
                      <li>
                        Some conversation analysis is saved with this call.
                      </li>
                    )}
                    <li>
                      {processingNeedsAttention
                        ? "You do not need to upload the recording again."
                        : null}
                    </li>
                  </ul>
                  <div className={styles.progressActions}>
                    <Link
                      href={savedCallsHref(embedded)}
                      className="secondary-button"
                    >
                      <FolderOpen size={17} aria-hidden="true" />
                      Open saved calls
                    </Link>
                    {processingNeedsAttention && (
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={!!busy}
                        onClick={startAnotherCall}
                      >
                        <ArrowRight size={16} aria-hidden="true" />
                        Analyse another call
                      </button>
                    )}
                    {canReviewHeldPlan && (
                      <button
                        className="secondary-button"
                        type="button"
                        disabled={!!busy || analysisPaused}
                        onClick={() => void freshPlan()}
                      >
                        {busy ? (
                          <LoaderCircle className="spin" size={17} />
                        ) : (
                          <FileText size={17} />
                        )}
                        {busy || "Review and continue analysis"}
                      </button>
                    )}
                  </div>
                  {canReviewHeldPlan && (
                    <p className={styles.resumeNotice}>
                      Nothing restarts until you review and continue.
                    </p>
                  )}
                </div>
              </div>
            )}
            {(submission || deletionOnlyId) && (
              <div className={styles.callActions}>
                <details className={styles.privacyActions}>
                  <summary>Privacy &amp; support</summary>
                  <div>
                    <p>
                      Need this call removed?{" "}
                      <a href="mailto:admin@authorityclosers.com?subject=Sales%20Xray%20deletion%20request">
                        Email the AC team
                      </a>{" "}
                      or request deletion here.
                    </p>
                    {!deleteConfirm ? (
                      <button
                        className="text-button"
                        type="button"
                        disabled={!!busy}
                        onClick={() => setDeleteConfirm(true)}
                      >
                        Request deletion
                      </button>
                    ) : (
                      <>
                        <p>
                          Remove this recording and its report? This cannot be
                          undone.
                        </p>
                        <button
                          type="button"
                          className="secondary-button"
                          disabled={!!busy}
                          onClick={() => void erase()}
                        >
                          Request recording deletion
                        </button>
                        <button
                          type="button"
                          className="text-button"
                          disabled={!!busy}
                          onClick={() => setDeleteConfirm(false)}
                        >
                          Keep call
                        </button>
                      </>
                    )}
                  </div>
                </details>
              </div>
            )}
          </section>
          {!submission && !report && (
            <aside className={`panel ${styles.expect}`}>
              <p className="eyebrow">WHAT YOU’LL GET</p>
              <h2>What you’ll get</h2>
              <ol>
                <li>
                  <FileText size={22} aria-hidden="true" />
                  <div>
                    <h3>A clear call overview</h3>
                    <p>
                      Understand the outcome, your strengths and the most useful
                      improvements.
                    </p>
                  </div>
                </li>
                <li>
                  <ListChecks size={22} aria-hidden="true" />
                  <div>
                    <h3>Feedback you can hear</h3>
                    <p>
                      Jump from a finding to the exact moment in your recording.
                    </p>
                  </div>
                </li>
                <li>
                  <Sparkles size={22} aria-hidden="true" />
                  <div>
                    <h3>Your next-call focus</h3>
                    <p>Turn the feedback into one practical rehearsal.</p>
                  </div>
                </li>
              </ol>
              <p className={styles.draftNote}>
                AI-generated coaching based on Dipak’s principles. Each report
                remains a draft until reviewed.
              </p>
            </aside>
          )}
        </div>
        {error && !savedCallNeedsSession && (
          <div className={`notice error ${styles.error}`} role="alert">
            <p>{error instanceof AcquisitionError ? error.message : error}</p>
            <div className={styles.errorActions}>
              <button
                className="secondary-button"
                type="button"
                disabled={!!busy}
                onClick={() => {
                  setError("");
                  if (submission) {
                    if (
                      !plan &&
                      progress?.local_state === "completed" &&
                      !progress.automatic_progression
                    ) {
                      requestedPlan.current = "";
                      quoteKey.current = "";
                    }
                    setPollAttempt((n) => n + 1);
                  } else setAttempt((n) => n + 1);
                }}
              >
                Check again
              </button>
              {submission && progress?.local_state === "completed" && (
                <button
                  type="button"
                  className="secondary-button"
                  disabled={!!busy || analysisPaused}
                  onClick={() => void freshPlan()}
                >
                  Request a fresh plan
                </button>
              )}
              {(!submission || !progress || (plan && !plan.accepted)) && (
                <button
                  type="button"
                  className="secondary-button"
                  disabled={!!busy}
                  onClick={startAnotherCall}
                >
                  <ArrowRight size={16} aria-hidden="true" />
                  Analyse another call
                </button>
              )}
              {error instanceof AcquisitionError && error.status === 401 && (
                <Link className="text-button" href="/login">
                  Sign in
                </Link>
              )}
            </div>
          </div>
        )}
        {result && report && (
          <SourceWaveformProvider
            submissionId={submission?.id}
            audioRef={audio}
          >
            <section
              className={`studio-report panel ${styles.report}`}
              aria-label="Sales call report"
            >
              <div className={styles.reportHeader}>
                <div className={styles.reportHeading}>
                  <h1>Your call, clearly.</h1>
                  <p>
                    Actionable insights. Real conversations. A stronger you.
                  </p>
                </div>
                <details className={styles.reportMoreActions}>
                  <summary
                    aria-label="More report actions"
                    title="More report actions"
                  >
                    <MoreHorizontal size={19} aria-hidden="true" />
                  </summary>
                  <div className={styles.reportMoreMenu} role="menu">
                    {!result.claimed && (
                      <Link href="/login" role="menuitem">
                        Sign in to save this call
                      </Link>
                    )}
                    <button
                      type="button"
                      role="menuitem"
                      disabled={!!busy || !submission}
                      onClick={() => void downloadReport()}
                    >
                      <Download size={16} aria-hidden="true" />
                      Download report
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      disabled={!!busy}
                      onClick={() => reset()}
                    >
                      <ArrowRight size={16} aria-hidden="true" />
                      Analyse another call
                    </button>
                    <p className={styles.reportMetadata}>
                      Draft coaching; not adjudicated by Dipak. Speaker labels
                      are unverified.
                      {` Source: ${report.source_label}. Duration: ${time(result.transcript.duration_ms)}.`}
                    </p>
                    {submission && (
                      <div className={styles.reportPrivacyMenu}>
                        <strong>Privacy &amp; support</strong>
                        <p>
                          Need this call removed?{" "}
                          <a href="mailto:admin@authorityclosers.com?subject=Sales%20Xray%20deletion%20request">
                            Email the AC team
                          </a>{" "}
                          or request deletion here.
                        </p>
                        {!deleteConfirm ? (
                          <button
                            className={styles.reportMenuTextButton}
                            type="button"
                            disabled={!!busy}
                            onClick={() => setDeleteConfirm(true)}
                          >
                            Request deletion
                          </button>
                        ) : (
                          <>
                            <p>
                              Remove this recording and its report? This cannot
                              be undone.
                            </p>
                            <button
                              type="button"
                              disabled={!!busy}
                              onClick={() => void erase()}
                            >
                              Request recording deletion
                            </button>
                            <button
                              className={styles.reportMenuTextButton}
                              type="button"
                              disabled={!!busy}
                              onClick={() => setDeleteConfirm(false)}
                            >
                              Keep call
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                </details>
              </div>
              <ReportExplorer
                label="Explore your sales report"
                panels={[
                  {
                    id: "overview",
                    label: "Overview",
                    content: (
                      <DipakOverview
                        showHeading={false}
                        report={report}
                        onSelectEvidence={seek}
                        onUnlock={() => router.push("/login")}
                        durationMs={result.transcript.duration_ms}
                      />
                    ),
                  },
                  {
                    id: "moments",
                    label: "Moments",
                    content: (
                      <ReportMoments
                        report={report}
                        onSelectEvidence={seek}
                        transcriptSlot={
                          <ReportTranscript
                            transcript={result.transcript}
                            language="en"
                            onSelect={(segment) =>
                              seek({
                                segment_id: segment.id,
                                quote: segment.text,
                                start_ms: segment.start_ms,
                                end_ms: segment.end_ms,
                              })
                            }
                          />
                        }
                      />
                    ),
                  },
                  {
                    id: "skills",
                    label: "Sales skills",
                    content: <SalesSkills dimensions={report.dimensions} />,
                  },
                  {
                    id: "next-call-plan",
                    label: "Next-call plan",
                    content: (
                      <NextCallPlan
                        report={report}
                        onSelectEvidence={seek}
                        onUnlock={() => router.push("/login")}
                      />
                    ),
                  },
                ]}
              />
            </section>
            <CallAudioDock
              audioRef={audio}
              src={source}
              durationMs={result.transcript.duration_ms}
              title={file?.name ?? "Your saved sales call"}
              embedded={embedded}
              onTimeUpdate={() => {
                if (
                  moment &&
                  audio.current &&
                  audio.current.currentTime >= moment.end_ms / 1000
                ) {
                  audio.current.pause();
                }
              }}
              onSeek={() => setMoment(null)}
              onError={() =>
                setPlaybackMessage(
                  "Audio playback is unavailable. Your report remains below.",
                )
              }
            />
          </SourceWaveformProvider>
        )}
      </div>
    </div>
  );

  if (embedded) return content;
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      homeHref={homeHref}
      mobileFit
    >
      {content}
    </AcquisitionShell>
  );
}
