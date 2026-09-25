"use client";
import { AnalysisAvailability } from "./analysis-availability";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  ShieldCheck,
} from "lucide-react";
import {
  CallStudio,
  parseProcessingPlan,
  type ProcessingPlan,
  type CallStudioVariant,
} from "./call-studio";
import { AcquisitionShell } from "./acquisition-shell";
import {
  AcquisitionGuideRail,
  AcquisitionLowerPanels,
} from "./acquisition-dashboard-panels";
import { AcquisitionFileStage } from "./acquisition-file-stage";
import { usePendingAnalysis } from "./pending-analysis";
import { DipakOverview } from "./dipak-overview";
import { ReportModes } from "./report-modes";
import { SalesSkills } from "./sales-skills";
import { ReportMoments } from "./report-moments";
import { NextCallPlan } from "./next-call-plan";
import { ProspectSnapshot } from "./prospect-snapshot";
import {
  ReportTranscript,
  formatTranscriptTime as time,
} from "./report-transcript";
import {
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
import { AcquisitionProcessingPanel } from "./acquisition-processing-panel";
import { useProcessingReview } from "./processing-review-port";
import { latestStage, projectProcessing } from "./processing-state";
import { observeSubmission, readProcessingPlan } from "./observe-submission";
import {
  parseReportLanguage,
  reportLanguageLabels,
  type ReportLanguage,
} from "./report-language";
import {
  isNewCallRequested,
  newCallHref,
  setNewCallRequested,
} from "./new-call-navigation";
import { UploadCheck } from "./upload-check";
import {
  UploadInProgressError,
  useUploadSession,
  useUploadSnapshot,
} from "./hooks/upload-session";
import { reconcileSource, sendSource } from "./new-analysis/source-upload";
import { useWorkspaceAccess } from "./workspace-access";
import { CallAudioDock } from "./call-audio-dock";
import { SourceWaveformProvider } from "./source-waveform";
import styles from "./acquisition-studio.module.css";

type Result = {
  report: SalesReport;
  transcript: Transcript;
  runId: string;
  claimed: boolean;
};
type ExistingCallEntryState = {
  submissionId: string;
  state: "opening" | "restored" | "failed";
};
function pausedFailureMessage(failureCode: string | null): string {
  if (
    failureCode === "conversation_broker_service_identity_unavailable" ||
    failureCode === "conversation_broker_service_identity_file_invalid" ||
    failureCode === "conversation_broker_service_identity_required"
  ) {
    return "The approved provider credentials are unavailable. Your recording is saved; ask the AC team to refresh the provider connection before continuing.";
  }
  if (failureCode?.startsWith("conversation_provider_http_")) {
    return "The approved provider returned an error. Your recording is saved; ask the AC team to check the provider connection before continuing.";
  }
  return "";
}

const message = (error: unknown) =>
  error instanceof AcquisitionError
    ? error
    : "This result could not be verified. Try again; your completed work stays saved.";

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
  requestedCallId,
  deferRouteSelection = false,
}: {
  variant?: CallStudioVariant;
  homeHref?: string;
  /** `undefined` is reserved for static export, where the query is client-only. */
  requestedCallId?: string | null;
  deferRouteSelection?: boolean;
}) {
  const embedded = variant === "embedded";
  // The standalone shell owns the page landmark; embedded mounts inherit one.
  const access = useWorkspaceAccess();
  const accessStatus = access?.status ?? null;
  const accessAuthenticated = access?.authenticated ?? null;
  const accessPersonId = access?.context?.personId ?? null;
  const accessSessionId = access?.context?.sessionId ?? null;
  const accessTenantId = access?.context?.tenantId ?? null;
  const accessObservation = useMemo(
    () =>
      accessStatus === null
        ? null
        : {
            status: accessStatus,
            authenticated: accessAuthenticated,
            context:
              accessPersonId && accessSessionId && accessTenantId
                ? {
                    personId: accessPersonId,
                    sessionId: accessSessionId,
                    tenantId: accessTenantId,
                  }
                : null,
          },
    [
      accessAuthenticated,
      accessPersonId,
      accessSessionId,
      accessStatus,
      accessTenantId,
    ],
  );
  const routeRequestedCallId =
    requestedCallId === undefined
      ? typeof window === "undefined"
        ? null
        : requestedSubmissionId()
      : requestedCallId;
  const routeHasSpecificCall = routeRequestedCallId !== null;
  const explicitNewIntake =
    typeof window !== "undefined" &&
    (isNewCallRequested() || savedSubmissionId() === null);
  const pending = usePendingAnalysis();
  const uploadStore = useUploadSession();
  const uploadSnapshot = useUploadSnapshot();
  const [entry, setEntry] = useState<Entry | null>(null);
  const router = useRouter();
  const [analysisPaused, setAnalysisPaused] = useState(false);
  const [policy, setPolicy] = useState<UploadPolicy | null>(null);
  const [allowance, setAllowance] = useState<Allowance | null>(null);
  const [allowanceUnknown, setAllowanceUnknown] = useState(false);
  const [session, setSession] = useState(false);
  const [claimAvailable, setClaimAvailable] = useState(false);
  const [savedCallNeedsSession, setSavedCallNeedsSession] = useState(false);
  const [localFile, setLocalFile] = useState<File | null>(null);
  const [localStagedFiles, setLocalStagedFiles] = useState<File[]>([]);
  const stagedFiles = pending?.stagedFiles ?? localStagedFiles;
  const retainedUploadFile =
    uploadStore &&
    !embedded &&
    (explicitNewIntake ||
      (uploadSnapshot.phase !== "idle" &&
        uploadSnapshot.phase !== "account_changed" &&
        uploadSnapshot.phase !== "saved" &&
        routeRequestedCallId === uploadSnapshot.intentId)) &&
    (uploadSnapshot.phase === "preparing" ||
      uploadSnapshot.phase === "uploading" ||
      uploadSnapshot.phase === "interrupted")
      ? uploadStore.fileFor(uploadSnapshot.intentId)
      : null;
  const file = pending
    ? (pending.selection?.file ?? retainedUploadFile)
    : (localFile ?? retainedUploadFile);
  const uploadPhaseUnresolved =
    uploadSnapshot.phase === "preparing" ||
    uploadSnapshot.phase === "uploading" ||
    uploadSnapshot.phase === "interrupted";
  const [reportLanguage, setReportLanguage] = useState<ReportLanguage>("en");
  const [privacyOpen, setPrivacyOpen] = useState(false);
  const [localValidationError, setLocalValidationError] = useState(false);
  const chosenReportLanguage = useRef<ReportLanguage | null>(null);
  const languageCapabilities = useRef(false);
  const [localAudioUrl, setLocalAudioUrl] = useState("");
  const audioUrl = pending
    ? (pending.selection?.audioUrl ?? "")
    : localAudioUrl;
  const [consent, setConsent] = useState(false);
  const [consentedPolicySha, setConsentedPolicySha] = useState<string | null>(
    null,
  );
  const consentCurrent = Boolean(
    consent &&
      policy?.policy_sha256 &&
      consentedPolicySha === policy.policy_sha256,
  );
  const clearConsent = useCallback(() => {
    setConsent(false);
    setConsentedPolicySha(null);
  }, []);
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
  const [statusIssue, setStatusIssue] = useState<string | AcquisitionError>("");
  const [checkingStatus, setCheckingStatus] = useState(false);
  const [moment, setMoment] = useState<ReportEvidence | null>(null);
  const [playbackMessage, setPlaybackMessage] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [deletionOnlyId, setDeletionOnlyId] = useState<string | null>(null);
  const [clientRouteResolved, setClientRouteResolved] =
    useState(!deferRouteSelection);
  const [clientRequestedCallId, setClientRequestedCallId] = useState<
    string | null
  >(null);
  const [dismissedCallId, setDismissedCallId] = useState<string | null>(null);
  const [existingCallEntry, setExistingCallEntry] =
    useState<ExistingCallEntryState | null>(null);
  const selectedRequestedCallId =
    requestedCallId === undefined ? clientRequestedCallId : requestedCallId;
  const activeRequestedCallId =
    selectedRequestedCallId && selectedRequestedCallId !== dismissedCallId
      ? selectedRequestedCallId
      : null;
  const routeSelectionPending = deferRouteSelection && !clientRouteResolved;
  const requestedCallEntryState = routeSelectionPending
    ? "opening"
    : activeRequestedCallId
      ? existingCallEntry?.submissionId === activeRequestedCallId
        ? existingCallEntry.state
        : "opening"
      : null;
  const [dragActive, setDragActive] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const controller = useRef<AbortController | null>(null);
  const active = useRef(true);
  const inFlight = useRef(false);
  const chosenId = useRef("");
  const quoteKey = useRef("");
  const requestedPlan = useRef("");
  const lastRequestedCallId = useRef<string | null>(null);
  const stalePlanRefresh = useRef<string | null>(null);
  const previewUrl = useRef("");
  const reconciliationAttempted = useRef("");
  const interruptedIntentId =
    uploadSnapshot.phase === "interrupted" ? uploadSnapshot.intentId : null;
  const interruptedSourceSha =
    uploadSnapshot.phase === "interrupted" ? uploadSnapshot.sourceSha256 : null;
  const activeUploadIntentId =
    uploadSnapshot.phase === "preparing" ||
    uploadSnapshot.phase === "uploading" ||
    uploadSnapshot.phase === "interrupted"
      ? uploadSnapshot.intentId
      : null;
  const uploadHomeHref =
    uploadSnapshot.phase !== "idle" &&
    uploadSnapshot.phase !== "account_changed"
      ? uploadSnapshot.homeHref
      : "/";
  const uploadHomeIsNewIntake = new URL(
    uploadHomeHref,
    "https://sales-xray.invalid",
  ).searchParams.has("new");
  const uploadMatchesCurrentView =
    !embedded &&
    (Boolean(
      activeUploadIntentId &&
        (routeRequestedCallId === activeUploadIntentId ||
          activeRequestedCallId === activeUploadIntentId ||
          (!routeHasSpecificCall &&
            (pending?.selection?.intentId === activeUploadIntentId ||
              explicitNewIntake ||
              uploadHomeIsNewIntake))),
    ) ||
      (uploadSnapshot.phase === "saved" &&
        (activeRequestedCallId === uploadSnapshot.submissionId ||
          routeRequestedCallId === uploadSnapshot.submissionId ||
          (!routeHasSpecificCall &&
            submission?.id === uploadSnapshot.submissionId))));
  const uploadUnresolved = uploadPhaseUnresolved && uploadMatchesCurrentView;
  const onToken = useCallback((value: string) => setToken(value), []);
  const review = useProcessingReview(
    activeRequestedCallId ?? submission?.id ?? null,
  );
  const reviewSelectionActive =
    review.requested ||
    review.localRequested ||
    Boolean(review.frame || review.localFrame);
  const analysisWriteBlocked =
    review.readOnly !== false || reviewSelectionActive;
  const localObservation = review.localFrame?.observation ?? null;
  const observedFileSelected = Boolean(
    localObservation?.file_name && localObservation.file_size_bytes,
  );
  const displayFileSelected = localObservation
    ? observedFileSelected
    : Boolean(file);
  const displayFileName = localObservation
    ? localObservation.file_name
    : (file?.name ?? null);
  const displayFileBytes = localObservation
    ? localObservation.file_size_bytes
    : (file?.size ?? null);
  const displayReportLanguage = localObservation
    ? localObservation.report_language
    : reportLanguage;
  const displayConsent = localObservation
    ? localObservation.consent_checked
    : consentCurrent;
  const displayPrivacyOpen = localObservation
    ? localObservation.privacy_open
    : privacyOpen;

  useEffect(() => {
    if (
      review.readOnly !== true ||
      review.requested ||
      review.localRequested ||
      !entry?.enabled ||
      submission ||
      result ||
      deletionOnlyId
    )
      return;
    review.captureLocal({
      phase: localValidationError
        ? "upload.validation.error"
        : file
          ? "upload.file.selected"
          : "upload.empty",
      privacy_open: privacyOpen,
      consent_checked: consentCurrent,
      report_language: entry.report_languages ? reportLanguage : null,
      verification: !policy
        ? "checking"
        : session
          ? "session-present"
          : token
            ? "guest-challenge-complete"
            : "guest-challenge-required",
      // choose() intentionally retains the previously selected valid File when
      // a replacement fails local validation. Keep that visible fact in the
      // observation while preserving the validation-error phase.
      file_name: file ? file.name.slice(0, 255) : null,
      file_size_bytes: file?.size ?? null,
    });
  }, [
    consentCurrent,
    deletionOnlyId,
    entry,
    file,
    localValidationError,
    policy,
    privacyOpen,
    reportLanguage,
    result,
    review,
    session,
    submission,
    token,
  ]);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      controller.current?.abort();
      if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    };
  }, []);

  useEffect(() => {
    if (!uploadStore || !uploadMatchesCurrentView) return;
    return uploadStore.view();
  }, [uploadMatchesCurrentView, uploadStore]);

  useEffect(() => {
    if (
      !uploadStore ||
      !uploadMatchesCurrentView ||
      !interruptedIntentId ||
      !interruptedSourceSha
    )
      return;
    if (accessObservation) uploadStore.observeAccount(accessObservation);
    const intentId = interruptedIntentId;
    const sourceSha256 = interruptedSourceSha;
    const recoveryKey = `${intentId}:${sourceSha256}`;
    if (
      reconciliationAttempted.current === recoveryKey ||
      !uploadStore.canReconcile(intentId)
    )
      return;
    reconciliationAttempted.current = recoveryKey;
    const abort = new AbortController();
    void reconcileSource({
      id: intentId,
      sha: sourceSha256,
      signal: abort.signal,
    })
      .then(async (outcome) => {
        if (abort.signal.aborted) return;
        if (outcome.kind === "missing") {
          uploadStore.markMissing(intentId);
          if (active.current) {
            clearConsent();
            setError(
              "The server did not find this upload. Review the current consent before trying again.",
            );
          }
          return;
        }
        uploadStore.markReconciled(intentId, outcome.submissionId);
        if (!active.current) return;
        setSubmission(outcome.bound);
        setProgress(parseProgress(outcome.raw, outcome.bound));
        clearConsent();
        setConsentedSubmissionId(outcome.bound.id);
        setPlanRequiresAction(false);
        setError("");
        try {
          const current = record(
            await acquisition("/session", { signal: abort.signal }),
          );
          if (abort.signal.aborted || !active.current) return;
          setAllowance(parseAllowance(current.allowance));
          setAllowanceUnknown(false);
        } catch {
          // The source is already bound. Allowance is refreshed by its normal
          // authority path when the page resumes.
        }
      })
      .catch(() => {
        if (!abort.signal.aborted && active.current)
          setError(
            "Upload status could not be checked. The selected recording remains in this tab.",
          );
      });
    return () => {
      abort.abort();
      if (reconciliationAttempted.current === recoveryKey)
        reconciliationAttempted.current = "";
    };
  }, [
    clearConsent,
    accessObservation,
    interruptedIntentId,
    interruptedSourceSha,
    uploadMatchesCurrentView,
    uploadStore,
  ]);

  useEffect(() => {
    const abort = new AbortController();
    const signal = abort.signal;
    // Capture this navigation before any awaits. A new upload can consume the
    // URL marker while entry/session reads are still in flight.
    const routeRequested =
      requestedCallId === undefined ? requestedSubmissionId() : requestedCallId;
    const requested =
      routeRequested && routeRequested !== dismissedCallId
        ? routeRequested
        : null;
    const newCall = !requested && isNewCallRequested();
    const saved = requested ?? (newCall ? null : savedSubmissionId());
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      abort.abort();
    }, 12_000);
    void (async () => {
      try {
        await Promise.resolve();
        if (signal.aborted) return;
        if (requestedCallId === undefined && deferRouteSelection) {
          setClientRequestedCallId(routeRequested);
          setClientRouteResolved(true);
        }
        if (requested !== lastRequestedCallId.current) {
          lastRequestedCallId.current = requested;
          if (requested) {
            setEntry(null);
            setPolicy(null);
            setAllowance(null);
            setAllowanceUnknown(true);
            setSession(false);
            setClaimAvailable(false);
            setSavedCallNeedsSession(false);
            setSubmission(null);
            setProgress(null);
            setPlan(null);
            setConsentedSubmissionId(null);
            setPlanRequiresAction(false);
            setResult(null);
            setError("");
            setStatusIssue("");
            setDeletionOnlyId(null);
            setExistingCallEntry({ submissionId: requested, state: "opening" });
            chosenId.current = "";
            quoteKey.current = "";
            requestedPlan.current = "";
            stalePlanRefresh.current = null;
          }
        }
        let config: Entry | null = null;
        try {
          config = parseEntry(await acquisition("/entry", { signal }));
        } catch (error) {
          if (!requested) throw error;
        }
        if (signal.aborted) return;
        if (config) {
          setEntry(config);
          languageCapabilities.current = config.report_languages !== undefined;
          if (
            !chosenReportLanguage.current ||
            !config.report_languages?.includes(chosenReportLanguage.current)
          ) {
            chosenReportLanguage.current =
              config.report_language_default ?? "en";
            setReportLanguage(chosenReportLanguage.current);
          }
        }
        if (!config?.enabled && !requested) return;
        const terms =
          config?.enabled && !requested
            ? parsePolicy(await acquisition("/upload-policy", { signal }))
            : null;
        let current: Record<string, unknown> | null = null;
        try {
          current = record(await acquisition("/session", { signal }));
        } catch (error) {
          if (!requested) {
            if (embedded) throw error;
            if (!(error instanceof AcquisitionError && error.status === 401))
              throw error;
          }
        }
        if (signal.aborted) return;
        if (!requested && embedded && (!current || current.state === "guest"))
          throw new AcquisitionError(401);
        if (terms) setPolicy(terms);
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
            const loadedProgress = parseProgress(loaded, bound);
            setProgress(loadedProgress);
            if (requested)
              setExistingCallEntry({
                submissionId: requested,
                state: loadedProgress.has_report ? "opening" : "restored",
              });
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
                "That saved call belongs to another browser session. Sign in to recover it, or start a new call.",
              );
              if (requested)
                setExistingCallEntry({
                  submissionId: requested,
                  state: "failed",
                });
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
              if (requested)
                setExistingCallEntry({
                  submissionId: requested,
                  state: "failed",
                });
              return;
            }
            throw error;
          }
        }
      } catch (error) {
        if (!signal.aborted) {
          setError(message(error));
          if (requested)
            setExistingCallEntry({
              submissionId: requested,
              state: "failed",
            });
        } else if (timedOut) {
          setError(
            "Sales Xray is taking longer than expected to load. Check again to continue your call.",
          );
          if (requested)
            setExistingCallEntry({
              submissionId: requested,
              state: "failed",
            });
        }
      } finally {
        window.clearTimeout(timeout);
      }
    })();
    return () => {
      window.clearTimeout(timeout);
      abort.abort();
    };
  }, [
    attempt,
    embedded,
    requestedCallId,
    deferRouteSelection,
    dismissedCallId,
  ]);

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
      if (analysisWriteBlocked)
        return Promise.reject(new Error("read_only_review"));
      const language = chosenReportLanguage.current ?? "en";
      const supportsLanguage = languageCapabilities.current;
      if (!quoteKey.current) {
        // Continuation keys permit letters, numbers, underscores, dots, colons
        // and hyphens. Keep each language distinct without sending its `+`.
        const languageKey = language.replaceAll("+", "_");
        quoteKey.current = `report-plan:${bound.id}${supportsLanguage ? `:${languageKey}` : ""}`;
      }
      const quoted = parseProcessingPlan(
        await acquisition(`${submissionPath(bound.id)}/plan/quote`, {
          method: "POST",
          signal,
          headers: {
            "Idempotency-Key": quoteKey.current,
            ...(supportsLanguage ? { "Content-Type": "application/json" } : {}),
          },
          ...(supportsLanguage
            ? { body: JSON.stringify({ report_language: language }) }
            : {}),
        }),
        bound.recordingId,
      );
      if (supportsLanguage && !quoted.report_language)
        throw new Error("plan_language_unconfirmed");
      return quoted;
    },
    [analysisWriteBlocked],
  );

  const refreshStalePlan = useCallback(
    async (bound: Submission, signal: AbortSignal) => {
      if (analysisWriteBlocked) return false;
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
    [getPlan, analysisWriteBlocked],
  );

  const acceptPlanRequest = useCallback(
    async (bound: Submission, shown: ProcessingPlan, signal: AbortSignal) => {
      if (analysisPaused || analysisWriteBlocked) {
        setPlanRequiresAction(true);
        return;
      }
      if (shown.expires_at_epoch * 1000 <= Date.now()) {
        setPlanExpired(true);
        setPlanRequiresAction(true);
        return;
      }
      let accepted: ProcessingPlan;
      try {
        accepted = parseProcessingPlan(
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
      } catch (error) {
        // A failed response can arrive after the server accepted this exact
        // plan. Reconcile with an owner read; never restart provider work.
        const mayHaveAccepted =
          error instanceof TypeError ||
          (error instanceof AcquisitionError &&
            error.status >= 500 &&
            error.reason !== "execution_paused");
        if (signal.aborted || !mayHaveAccepted) throw error;
        try {
          const saved = await readProcessingPlan(bound, signal);
          if (
            !saved.accepted ||
            saved.id !== shown.id ||
            saved.plan_fingerprint !== shown.plan_fingerprint
          )
            throw error;
          accepted = saved;
        } catch {
          throw error;
        }
      }
      if (!signal.aborted) {
        if (
          accepted.id !== shown.id ||
          accepted.plan_fingerprint !== shown.plan_fingerprint
        )
          throw new Error("accepted_plan_mismatch");
        setPlan({
          ...accepted,
          ...(shown.report_language
            ? {
                report_language: shown.report_language,
                coaching_prompt_revision: shown.coaching_prompt_revision,
              }
            : {}),
        });
        setPlanRequiresAction(false);
        setPlanExpired(false);
        setPollAttempt((n) => n + 1);
      }
    },
    [analysisPaused, analysisWriteBlocked],
  );

  // Recover the saved language from the immutable plan, never from today's
  // Admin default. This owner-read route cannot create a replacement quote.
  useEffect(() => {
    if (
      !submission ||
      !entry?.report_languages ||
      consentedSubmissionId === submission.id
    )
      return;
    const abort = new AbortController();
    const bound = submission;
    void (async () => {
      try {
        const saved = parseProcessingPlan(
          await acquisition(`${submissionPath(bound.id)}/plan`, {
            signal: abort.signal,
          }),
          bound.recordingId,
        );
        if (!abort.signal.aborted)
          setPlan((current) => {
            if (!current) return saved;
            // An owner read may confirm an acceptance whose response was lost.
            // Never overwrite a different plan, or demote known acceptance.
            return current.id === saved.id &&
              current.plan_fingerprint === saved.plan_fingerprint &&
              (!current.accepted || saved.accepted)
              ? saved
              : current;
          });
      } catch {
        // A legacy call may have no plan. Progress/report verification remains
        // authoritative, and no inferred language label is shown.
      }
    })();
    return () => abort.abort();
  }, [
    submission,
    entry?.report_languages,
    consentedSubmissionId,
    result?.runId,
  ]);

  useEffect(() => {
    if (!submission || result || review.requested) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    const bound = submission;
    async function poll() {
      try {
        setCheckingStatus(true);
        const observed = await observeSubmission(bound, abort.signal);
        if (abort.signal.aborted) return;
        const next = observed.progress;
        setProgress(next);
        setStatusIssue("");
        if (observed.result) {
          setResult(observed.result);
          setError("");
          setExistingCallEntry({
            submissionId: bound.id,
            state: "restored",
          });
          return;
        }
        if (!next.has_report)
          setExistingCallEntry({
            submissionId: bound.id,
            state: "restored",
          });
        if (
          next.local_state === "failed" ||
          next.local_state === "cancelled" ||
          ["held", "cancelled", "completed"].includes(next.state)
        ) {
          const paused =
            next.state === "held" ||
            next.stages.some((stage) => stage.state === "uncertain");
          if (paused) setError(pausedFailureMessage(next.failure_code));
          else
            setError(
              "This analysis needs attention. Your call is saved; completed work remains available.",
            );
          setExistingCallEntry({
            submissionId: bound.id,
            state: "restored",
          });
          return;
        }
        failures = 0;
      } catch (error) {
        if (abort.signal.aborted) return;
        failures += 1;
        setStatusIssue(message(error));
        if (
          failures >= 3 ||
          (error instanceof AcquisitionError &&
            [401, 403, 404, 409].includes(error.status))
        ) {
          setExistingCallEntry({
            submissionId: bound.id,
            state: "failed",
          });
          return;
        }
      } finally {
        if (!abort.signal.aborted) setCheckingStatus(false);
      }
      if (!abort.signal.aborted)
        timer = setTimeout(() => void poll(), failures ? 6000 : 3000);
    }
    void poll();
    return () => {
      abort.abort();
      if (timer) clearTimeout(timer);
    };
  }, [submission, result, pollAttempt, review.requested]);

  // Automatic acceptance is bound to the upload just consented to in this
  // mounted page. Restoring or refreshing a call never recreates that consent.
  const localProcessingState = progress?.local_state;
  const automaticProgression = progress?.automatic_progression;
  const publishedReport = progress?.has_report;
  const processingState = progress?.state;
  const processingTerminal = ["held", "cancelled", "completed"].includes(
    processingState ?? "",
  );
  useEffect(() => {
    if (
      !submission ||
      result ||
      publishedReport ||
      localProcessingState !== "completed" ||
      automaticProgression ||
      processingTerminal ||
      consentedSubmissionId !== submission.id ||
      planRequiresAction ||
      analysisPaused ||
      analysisWriteBlocked ||
      requestedPlan.current === submission.id
    )
      return;
    const abort = new AbortController();
    const bound = submission;
    requestedPlan.current = bound.id;
    void (async () => {
      try {
        const approved = await getPlan(bound, abort.signal);
        if (abort.signal.aborted) return;
        setPlan(approved);
        setPlanExpired(approved.expires_at_epoch * 1000 <= Date.now());
        if (
          approved.report_language &&
          approved.report_language !== chosenReportLanguage.current
        ) {
          setPlanRequiresAction(true);
          return;
        }
        await acceptPlanRequest(bound, approved, abort.signal);
      } catch (error) {
        if (abort.signal.aborted) return;
        if (
          error instanceof AcquisitionError &&
          error.reason === "plan_stale"
        ) {
          try {
            if (await refreshStalePlan(bound, abort.signal)) return;
          } catch (refreshError) {
            if (!abort.signal.aborted) {
              setPlanRequiresAction(true);
              setError(message(refreshError));
            }
            return;
          }
        }
        if (!abort.signal.aborted) {
          setPlanRequiresAction(true);
          setError(message(error));
        }
      }
    })();
    return () => {
      abort.abort();
      // A dependency change can interrupt an already-dispatched quote or
      // acceptance. Do not silently start it again or hide the review action.
      // Observation will reconcile any work the server has already accepted.
      if (active.current)
        setConsentedSubmissionId((current) =>
          current === bound.id ? null : current,
        );
    };
  }, [
    analysisPaused,
    analysisWriteBlocked,
    acceptPlanRequest,
    getPlan,
    refreshStalePlan,
    consentedSubmissionId,
    planRequiresAction,
    submission,
    result,
    localProcessingState,
    automaticProgression,
    publishedReport,
    processingTerminal,
  ]);

  function choose(next: File | undefined) {
    if (!next || inFlight.current || submission) return;
    if (uploadUnresolved && next !== file) {
      setError("Check the current upload before choosing another recording.");
      return;
    }
    setError("");
    setDeleted(false);
    clearConsent();
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
      setLocalValidationError(true);
      return;
    }
    setLocalValidationError(false);
    if (pending) pending.selectFile(next);
    else {
      chosenId.current = crypto.randomUUID();
      if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
      previewUrl.current = URL.createObjectURL(next);
      setLocalAudioUrl(previewUrl.current);
      setLocalFile(next);
      setLocalStagedFiles((current) =>
        current.some((candidate) => candidate === next)
          ? current
          : [...current, next],
      );
    }
  }

  function addFiles(nextFiles: FileList | File[]) {
    if (inFlight.current || submission || !policy || uploadUnresolved) return;
    const candidates = Array.from(nextFiles);
    const valid = candidates.filter(
      (candidate) =>
        /\.(mp3|mpeg|wav|m4a|ogg|flac)$/i.test(candidate.name) &&
        candidate.size > 0 &&
        candidate.size <= policy.maximum_file_bytes,
    );
    const hasInvalidFiles = valid.length !== candidates.length;
    if (valid.length === 0) {
      if (hasInvalidFiles) {
        setError(
          "Choose an MP3, MPEG, WAV, M4A, OGG or FLAC within the displayed size limit.",
        );
        setLocalValidationError(true);
      }
      return;
    }
    if (pending) pending.addFiles(valid);
    else
      setLocalStagedFiles((current) => [
        ...current,
        ...valid.filter((candidate) => !current.includes(candidate)),
      ]);
    if (!file) choose(valid[0]);
    if (hasInvalidFiles) {
      setError(
        "Choose an MP3, MPEG, WAV, M4A, OGG or FLAC within the displayed size limit.",
      );
      setLocalValidationError(true);
    }
  }

  function removeStagedFile(removed: File) {
    if (inFlight.current || submission || uploadUnresolved) return;
    const remaining = stagedFiles.filter((candidate) => candidate !== removed);
    if (file === removed) {
      if (remaining.length > 0) choose(remaining[0]);
      else reset();
    }
    if (pending) pending.removeFile(removed);
    else setLocalStagedFiles(remaining);
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
    if (analysisWriteBlocked || !file || !policy || !consentCurrent) return;
    if (access?.requestAnalysisAccess && !access.requestAnalysisAccess())
      return;
    if (!session && !token) return;
    if (embedded && !session) return;
    const selected = file;
    const resume =
      uploadSnapshot.phase === "interrupted" &&
      uploadStore?.fileFor(uploadSnapshot.intentId) === selected
        ? uploadSnapshot
        : null;
    const id =
      resume?.intentId ?? pending?.selection?.intentId ?? chosenId.current;
    if (!id) return;
    const uploadMeta = {
      intentId: id,
      fileName: selected.name,
      totalBytes: selected.size,
      reportLanguage:
        resume?.reportLanguage ??
        (entry?.report_languages ? reportLanguage : null),
      homeHref: resume?.homeHref ?? newCallHref(homeHref),
      sourceSha256: resume?.sourceSha256 ?? null,
    } as const;
    const send = async (signal: AbortSignal) => {
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
          if (signal.aborted) throw new Error("upload_cancelled");
          if (active.current) {
            setSession(true);
            setAllowance(parseAllowance(issued.allowance));
            setAllowanceUnknown(false);
          }
        } finally {
          if (!signal.aborted && active.current) {
            setToken("");
            setCheckKey((key) => key + 1);
          }
        }
      }
      const digest = await crypto.subtle.digest(
        "SHA-256",
        await selected.arrayBuffer(),
      );
      if (signal.aborted) throw new Error("upload_cancelled");
      const sha = Array.from(new Uint8Array(digest), (n) =>
        n.toString(16).padStart(2, "0"),
      ).join("");
      uploadStore?.sourceDigest(id, sha);
      setNewCallRequested(false);
      const outcome = await sendSource({
        id,
        file: selected,
        sha,
        policySha: policy.policy_sha256,
        uploadConsent: {
          accepted: consentCurrent,
          policySha256: consentedPolicySha ?? "",
        },
        signal,
        onPut: () => uploadStore?.markSending(id),
      });
      const bound = outcome.bound;
      const recoveredProgress = outcome.recovered
        ? parseProgress(outcome.raw, bound)
        : null;
      // GET progress does not include allowance. Refresh it from its authority,
      // never subtract an estimated duration locally or reuse a pre-upload value.
      const allowanceSource = outcome.recovered
        ? record(await acquisition("/session", { signal }))
        : outcome.raw;
      if (signal.aborted) throw new Error("upload_cancelled");
      if (active.current) {
        setAllowance(parseAllowance(allowanceSource.allowance));
        setAllowanceUnknown(false);
        if (recoveredProgress) setProgress(recoveredProgress);
        setSubmission(bound);
        clearConsent();
        setConsentedSubmissionId(bound.id);
        setPlanRequiresAction(false);
        setError("");
      }
      return outcome;
    };

    if (uploadStore && !embedded) {
      if (inFlight.current) return;
      if (access) uploadStore.observeAccount(access);
      inFlight.current = true;
      setBusy("Preparing private upload…");
      setError("");
      try {
        await uploadStore.run(uploadMeta, selected, send);
      } catch (error) {
        if (active.current) {
          setError(
            error instanceof UploadInProgressError
              ? "Another recording is still uploading. Check its upload status before continuing."
              : message(error),
          );
        }
      } finally {
        inFlight.current = false;
        if (active.current) setBusy("");
      }
      return;
    }

    await operation("Preparing private upload…", async (signal) => {
      await send(signal);
    });
  }

  async function approvePlan() {
    if (
      analysisWriteBlocked ||
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
    if (!submission || analysisPaused || analysisWriteBlocked) return;
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

  async function retryAnalysis() {
    if (
      !submission ||
      analysisPaused ||
      analysisWriteBlocked ||
      result ||
      progress?.local_state !== "completed" ||
      processingTerminal
    )
      return;
    const bound = submission;
    await operation("Starting your report…", async (signal) => {
      // Retry the same quote/acceptance identity. Creating a new attempt or
      // recovering held provider work remains a separate server decision.
      if (plan?.accepted) {
        setPollAttempt((n) => n + 1);
        return;
      }
      if (plan && plan.expires_at_epoch * 1000 <= Date.now())
        quoteKey.current = `report-plan:${crypto.randomUUID()}`;
      const shown =
        plan && plan.expires_at_epoch * 1000 > Date.now()
          ? plan
          : await getPlan(bound, signal);
      if (signal.aborted) return;
      setPlan(shown);
      setPlanExpired(shown.expires_at_epoch * 1000 <= Date.now());
      if (
        shown.report_language &&
        chosenReportLanguage.current &&
        shown.report_language !== chosenReportLanguage.current
      ) {
        setPlanRequiresAction(true);
        return;
      }
      try {
        await acceptPlanRequest(bound, shown, signal);
        if (!signal.aborted) setError("");
      } catch (error) {
        if (
          error instanceof AcquisitionError &&
          error.reason === "plan_stale"
        ) {
          if (await refreshStalePlan(bound, signal)) return;
        }
        setPlanRequiresAction(true);
        throw error;
      }
    });
  }

  function reset(options?: {
    preserveSavedSubmission?: boolean;
    preserveQueuedFiles?: boolean;
  }) {
    if (inFlight.current || uploadUnresolved) return;
    const queuedForNext = options?.preserveQueuedFiles
      ? stagedFiles.filter((candidate) => candidate !== file)
      : [];
    if (activeRequestedCallId) setDismissedCallId(activeRequestedCallId);
    setExistingCallEntry(null);
    audio.current?.pause();
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    previewUrl.current = "";
    setLocalFile(null);
    if (pending) pending.clearFiles();
    else setLocalStagedFiles([]);
    setPrivacyOpen(false);
    setLocalValidationError(false);
    setLocalAudioUrl("");
    setSubmission(null);
    setProgress(null);
    setStatusIssue("");
    setCheckingStatus(false);
    setPlan(null);
    setResult(null);
    clearConsent();
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
    if (queuedForNext.length > 0) {
      if (pending) pending.addFiles(queuedForNext);
      else {
        setLocalStagedFiles(queuedForNext);
        setLocalFile(queuedForNext[0]);
        previewUrl.current = URL.createObjectURL(queuedForNext[0]);
        setLocalAudioUrl(previewUrl.current);
        chosenId.current = crypto.randomUUID();
      }
    }
  }

  function startAnotherCall() {
    if (inFlight.current || uploadUnresolved) return;
    if (uploadSnapshot.phase === "saved")
      uploadStore?.settle(uploadSnapshot.intentId);
    reset({ preserveSavedSubmission: true, preserveQueuedFiles: true });
    setNewCallRequested(true);
    // Re-read entry/session without racing an older saved-call lookup.
    setAttempt((n) => n + 1);
  }

  function forgetSavedCall() {
    if (inFlight.current) return;
    if (activeRequestedCallId) setDismissedCallId(activeRequestedCallId);
    setExistingCallEntry(null);
    rememberSubmission(null);
    clearRequestedSubmission();
    setDeletionOnlyId(null);
    setDeleteConfirm(false);
    setError("");
    chosenId.current = "";
  }

  async function claim() {
    if (analysisWriteBlocked) return;
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
    if (analysisWriteBlocked || !deletionId || !deleteConfirm) return;
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

  if (
    (review.requested && !review.frame) ||
    (review.localRequested && !review.localFrame)
  ) {
    const reviewStatus = (
      <section className="panel" role="status">
        <h1>
          {review.localRequested
            ? "Opening browser-local state"
            : "Opening observed service state"}
        </h1>
        <p>{review.message || "Verifying live access…"}</p>
        <a href="/__review/">Review controls</a>
        {activeRequestedCallId && (
          <Link href={`?call=${activeRequestedCallId}`}>
            Open the live call
          </Link>
        )}
      </section>
    );
    return embedded ? (
      reviewStatus
    ) : (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        homeHref={homeHref}
      >
        {reviewStatus}
      </AcquisitionShell>
    );
  }
  // Only display inputs are substituted. Historical data never enters the
  // operational React state, consent, approval or job controller above.
  return renderWorkspace({
    submission: review.frame?.submission ?? submission,
    progress: review.frame?.progress ?? progress,
    result: review.frame ? null : result,
    plan: review.frame ? null : plan,
    busy: review.frame
      ? ""
      : uploadMatchesCurrentView && uploadSnapshot.phase === "preparing"
        ? "Preparing private upload…"
        : uploadMatchesCurrentView && uploadSnapshot.phase === "uploading"
          ? "Uploading privately…"
          : busy,
    error: review.frame
      ? pausedFailureMessage(review.frame.progress.failure_code)
      : localObservation?.phase === "upload.validation.error"
        ? "Choose an MP3, MPEG, WAV, M4A, OGG or FLAC within the displayed size limit."
        : error,
    statusIssue: review.frame ? "" : statusIssue,
    checkingStatus: review.frame ? false : checkingStatus,
    requestedCallEntryState: review.frame
      ? "restored"
      : requestedCallEntryState,
  });

  function renderWorkspace({
    submission,
    progress,
    result,
    plan,
    busy,
    error,
    statusIssue,
    checkingStatus,
    requestedCallEntryState,
  }: {
    submission: Submission | null;
    progress: Progress | null;
    result: Result | null;
    plan: ProcessingPlan | null;
    busy: string;
    error: string | AcquisitionError;
    statusIssue: string | AcquisitionError;
    checkingStatus: boolean;
    requestedCallEntryState: "opening" | "restored" | "failed" | null;
  }) {
    if (entry && !entry.enabled && requestedCallEntryState === null) {
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
    const processingNeedsAttention = projectProcessing(
      progress,
      false,
    ).attention;
    const canReviewHeldPlan =
      !error &&
      progress?.state === "held" &&
      progress.local_state === "completed" &&
      latestStage(progress, "C2")?.state === "completed";
    const waitingForApproval = Boolean(
      !plan?.accepted &&
        !progress?.automatic_progression &&
        progress?.local_state === "completed" &&
        !processingNeedsAttention &&
        !progress?.has_report &&
        consentedSubmissionId !== submission?.id,
    );
    const processingProjection = projectProcessing(
      progress,
      waitingForApproval,
    );
    const visibleError =
      error ||
      statusIssue ||
      (pending?.accountChanged
        ? "Your account or workspace changed. Choose your audio files again."
        : "");
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

    if (
      requestedCallEntryState === "opening" ||
      requestedCallEntryState === "failed"
    ) {
      const opening = requestedCallEntryState === "opening";
      const entryError = error || statusIssue;
      const needsSignIn =
        savedCallNeedsSession ||
        (entryError instanceof AcquisitionError && entryError.status === 401);
      const failedMessage = savedCallNeedsSession
        ? "That saved call belongs to another browser session. Sign in to recover it, or start a new call."
        : deletionOnlyId
          ? "This saved call cannot be opened here. If you own it, you can still request its deletion."
          : entryError instanceof AcquisitionError
            ? entryError.message
            : typeof entryError === "string" && entryError
              ? entryError
              : "Sales Xray could not verify this saved call. Try again; your saved work has not been changed.";
      const entryView = (
        <div
          className={`xray-app simple-app ${styles.app}`}
          data-theme="light"
          data-variant={variant}
          data-stage={opening ? "opening" : "recovery"}
          aria-busy={opening}
        >
          <div className="studio-main">
            <section
              className={`panel ${styles.processingPanel}`}
              role={opening ? "status" : "alert"}
              aria-live="polite"
              aria-labelledby="existing-call-entry-heading"
            >
              {opening ? (
                <LoaderCircle size={24} aria-hidden="true" />
              ) : (
                <FileText size={24} aria-hidden="true" />
              )}
              <div className={styles.progressCopy}>
                <p className={styles.progressKicker}>SAVED CALL</p>
                <h1 id="existing-call-entry-heading">
                  {opening
                    ? "Opening your saved call"
                    : deletionOnlyId
                      ? "Saved call unavailable"
                      : "Could not open your saved call"}
                </h1>
                <p>
                  {opening
                    ? "Checking your access and loading the saved call…"
                    : failedMessage}
                </p>
                {!opening && (
                  <div className={styles.errorActions}>
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={!!busy}
                      onClick={() => {
                        setError("");
                        setStatusIssue("");
                        if (activeRequestedCallId)
                          setExistingCallEntry({
                            submissionId: activeRequestedCallId,
                            state: "opening",
                          });
                        if (submission) {
                          setConsentedSubmissionId(null);
                          setPollAttempt((n) => n + 1);
                        } else setAttempt((n) => n + 1);
                      }}
                    >
                      Check again
                    </button>
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={!!busy}
                      onClick={startAnotherCall}
                    >
                      <ArrowRight size={16} aria-hidden="true" />
                      Start a new call
                    </button>
                    {needsSignIn && (
                      <Link className="text-button" href="/login">
                        Sign in to recover it
                      </Link>
                    )}
                  </div>
                )}
                {!opening && deletionOnlyId && (
                  <div className={styles.errorActions}>
                    {!deleteConfirm ? (
                      <button
                        className="text-button"
                        type="button"
                        disabled={!!busy || analysisWriteBlocked}
                        onClick={() => setDeleteConfirm(true)}
                      >
                        Request deletion
                      </button>
                    ) : (
                      <>
                        <button
                          className="secondary-button"
                          type="button"
                          disabled={!!busy || analysisWriteBlocked}
                          onClick={() => void erase()}
                        >
                          Request recording deletion
                        </button>
                        <button
                          className="text-button"
                          type="button"
                          disabled={!!busy || analysisWriteBlocked}
                          onClick={() => setDeleteConfirm(false)}
                        >
                          Keep call
                        </button>
                      </>
                    )}
                    <button
                      className="text-button"
                      type="button"
                      disabled={!!busy}
                      onClick={forgetSavedCall}
                    >
                      Forget this saved call on this device
                    </button>
                  </div>
                )}
              </div>
            </section>
          </div>
        </div>
      );
      if (embedded) return entryView;
      return (
        <AcquisitionShell
          authenticated={access?.authenticated === true}
          homeHref={homeHref}
          mobileFit
          allowance={allowance}
        >
          {entryView}
        </AcquisitionShell>
      );
    }

    const savedCallRecovery =
      savedCallNeedsSession && !submission && !deletionOnlyId ? (
        <div
          className={`notice ${styles.recoveryNotice} ${styles.recoveryError}`}
          role="status"
          aria-live="polite"
        >
          <p>
            That saved call belongs to another browser session. Sign in to
            recover it, or start a new call.
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
          localObservation?.phase === "upload.validation.error"
            ? "upload-error"
            : report
              ? "report"
              : submission
                ? "processing"
                : busy
                  ? "uploading"
                  : "upload"
        }
        data-selected={displayFileSelected ? "true" : "false"}
        onClickCapture={
          reviewSelectionActive
            ? (event) => {
                // Review allows native readers/details and navigation; buttons
                // cannot mutate the live controller from an observed frame.
                if (
                  event.target instanceof Element &&
                  event.target.closest("button")
                ) {
                  event.preventDefault();
                  event.stopPropagation();
                }
              }
            : undefined
        }
      >
        {(review.frame || review.localFrame) && (
          <nav
            className={styles.reviewNotice}
            aria-label="Observed state navigation"
          >
            <div>
              <strong>
                {review.localFrame?.label ??
                  `Observed processing · ${review.frame?.progress.state ?? "state"}`}
              </strong>
              {(() => {
                const navigation =
                  review.localFrame?.navigation ?? review.frame?.navigation;
                return (
                  <small>
                    {navigation
                      ? `Observed state ${navigation.position} of ${navigation.total}.`
                      : "Only states actually captured in this session can be visited."}
                    {review.localFrame
                      ? " Display only; the file and consent value are not restored or applied."
                      : " Live API data is rechecked before each state is opened."}
                  </small>
                );
              })()}
            </div>
            {(() => {
              const navigation =
                review.localFrame?.navigation ?? review.frame?.navigation;
              return (
                <div className={styles.reviewNavigationLinks}>
                  {navigation?.previousUrl ? (
                    <a href={navigation.previousUrl}>Previous state</a>
                  ) : (
                    <span aria-disabled="true">Previous state</span>
                  )}
                  {navigation?.nextUrl ? (
                    <a href={navigation.nextUrl}>Next state</a>
                  ) : (
                    <span aria-disabled="true">Next state</span>
                  )}
                  <a href="/__review/">All states</a>
                </div>
              );
            })()}
          </nav>
        )}
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
                  (report ? 2 : submission ? 1 : 0) === index
                    ? "step"
                    : undefined
                }
              >
                <b>{index + 1}</b>
                {label}
                {index < 2 && <ChevronDown size={15} />}
              </span>
            ))}
          </nav>
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
                  Save the recording and its report to the account you just
                  signed in to.
                </p>
              </div>
              <button
                type="button"
                className="primary-button"
                disabled={!!busy || analysisWriteBlocked}
                onClick={() => void claim()}
              >
                Save to my account
              </button>
            </aside>
          )}
          {savedCallRecovery}
          {visibleError && !savedCallNeedsSession && (
            <div className={`notice error ${styles.error}`} role="alert">
              {statusIssue && !error && (
                <p>
                  Status could not be refreshed. This does not mean analysis
                  failed.
                </p>
              )}
              <p>
                {visibleError instanceof AcquisitionError
                  ? visibleError.message
                  : visibleError}
              </p>
              <div className={styles.errorActions}>
                <button
                  className="secondary-button"
                  type="button"
                  disabled={!!busy}
                  onClick={() => {
                    setError("");
                    if (submission) {
                      setConsentedSubmissionId(null);
                      setPollAttempt((n) => n + 1);
                    } else setAttempt((n) => n + 1);
                  }}
                >
                  Check again
                </button>
                {error &&
                  submission &&
                  progress?.local_state === "completed" && (
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={
                        !!busy || analysisPaused || analysisWriteBlocked
                      }
                      onClick={() =>
                        void (processingTerminal
                          ? freshPlan()
                          : retryAnalysis())
                      }
                    >
                      {processingTerminal
                        ? "Request a fresh plan"
                        : "Retry analysis"}
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
                {visibleError instanceof AcquisitionError &&
                  visibleError.status === 401 && (
                    <Link className="text-button" href="/login">
                      Sign in
                    </Link>
                  )}
              </div>
            </div>
          )}
          <div
            className={`${styles.layout} ${!embedded && !report && !submission && !deletionOnlyId && stagedFiles.length < 2 ? styles.quietIntake : ""} ${report ? styles.withReport : submission ? styles.withProcessing : busy && !submission ? styles.withBusy : ""}`}
          >
            <div className={styles.primaryColumn}>
              <section
                className={`panel studio-upload ${styles.upload} ${dragActive ? styles.dragging : ""}`}
                aria-label="Your call"
                onDragEnter={(event) => {
                  event.preventDefault();
                  if (!busy && !submission && !deletionOnlyId)
                    setDragActive(true);
                }}
                onDragOver={(event) => event.preventDefault()}
                onDragLeave={(event) => {
                  if (
                    !event.currentTarget.contains(event.relatedTarget as Node)
                  )
                    setDragActive(false);
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  setDragActive(false);
                  if (!busy && !submission && !deletionOnlyId)
                    addFiles(event.dataTransfer.files);
                }}
              >
                {!submission && !deletionOnlyId && (
                  <div className={styles.uploadCardHeader}>
                    <div className={styles.uploadCardTitle}>
                      <svg
                        className={styles.animatedWaveMark}
                        viewBox="0 0 46 46"
                        fill="none"
                        aria-hidden="true"
                      >
                        <circle
                          cx="23"
                          cy="23"
                          r="19"
                          stroke="currentColor"
                          strokeOpacity=".12"
                          strokeDasharray="2 5"
                        />
                        <path
                          d="M3 23h5m30 0h5"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinecap="round"
                          strokeOpacity=".4"
                        />
                        <g className={styles.waveBars} fill="currentColor">
                          <rect x="9" y="18" width="2.8" height="10" rx="1.4" />
                          <rect
                            x="14.5"
                            y="12"
                            width="2.8"
                            height="22"
                            rx="1.4"
                          />
                          <rect x="20" y="6" width="2.8" height="34" rx="1.4" />
                          <rect
                            x="25.5"
                            y="14"
                            width="2.8"
                            height="18"
                            rx="1.4"
                          />
                          <rect
                            x="31"
                            y="10"
                            width="2.8"
                            height="26"
                            rx="1.4"
                          />
                          <rect
                            x="36.5"
                            y="18"
                            width="2.8"
                            height="10"
                            rx="1.4"
                          />
                        </g>
                      </svg>
                      <h2>Add a call to review</h2>
                    </div>
                    <span className={styles.allowanceBadge}>
                      <ShieldCheck size={19} aria-hidden="true" />
                      {remainingAllowanceLabel(
                        allowance,
                        entry?.allowance_seconds ?? null,
                        allowanceUnknown,
                      )}
                    </span>
                  </div>
                )}
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
                      <p className={styles.progressKicker}>
                        UPLOAD IN PROGRESS
                      </p>
                      <h3>Your call is on its way.</h3>
                      <p>
                        We’re uploading your recording and checking its format
                        and duration. Keep this tab open until the upload
                        finishes.
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
                ) : deletionOnlyId && !displayFileSelected && !submission ? (
                  <>
                    <span className="studio-upload-icon">
                      <FileText size={30} />
                    </span>
                    <h2>Saved call unavailable</h2>
                    <p>
                      This saved call cannot be opened here. If you own it, you
                      can permanently delete it.
                    </p>
                    <p className="small-text">
                      If deletion is denied, you can forget this selector on
                      this device. That does not delete the stored recording or
                      report.
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
                ) : !submission && !deletionOnlyId && !localObservation ? (
                  <AcquisitionFileStage
                    files={stagedFiles}
                    selectedFile={file}
                    onSelect={choose}
                    onRemove={removeStagedFile}
                    onClear={() => reset()}
                    onAddFiles={addFiles}
                    maxBytes={policy?.maximum_file_bytes}
                    maxMinutes={
                      policy
                        ? Math.floor(policy.maximum_call_seconds / 60)
                        : undefined
                    }
                    disabled={!policy || !!busy || reviewSelectionActive}
                  />
                ) : !displayFileSelected && !submission ? (
                  <div className={styles.dropZone} data-upload-dropzone>
                    <span className="studio-upload-icon">
                      <svg
                        className={styles.animatedUploadMark}
                        viewBox="0 0 64 64"
                        fill="none"
                        aria-hidden="true"
                      >
                        <circle
                          className={styles.uploadOrbit}
                          cx="32"
                          cy="32"
                          r="29"
                          stroke="currentColor"
                          strokeOpacity=".26"
                          strokeDasharray="2 7"
                        />
                        <path
                          className={styles.uploadCloud}
                          d="M18 44h27a10 10 0 0 0 2-19.8A16 16 0 0 0 16 28a8 8 0 0 0 2 16Z"
                          stroke="currentColor"
                          strokeWidth="2.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                        <g
                          className={styles.uploadArrow}
                          stroke="currentColor"
                          strokeWidth="2.7"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <path d="M32 48V28" />
                          <path d="m25 35 7-7 7 7" />
                        </g>
                        <circle
                          cx="11"
                          cy="16"
                          r="1.4"
                          fill="currentColor"
                          fillOpacity=".48"
                        />
                        <circle
                          cx="53"
                          cy="49"
                          r="1.4"
                          fill="currentColor"
                          fillOpacity=".48"
                        />
                      </svg>
                    </span>
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
                        <h2>{displayFileName || "Your saved sales call"}</h2>
                        <p>
                          {result
                            ? time(result.transcript.duration_ms)
                            : displayFileSelected
                              ? file
                                ? `Selected locally · ${(file.size / 1048576).toFixed(1)} MB`
                                : displayFileBytes !== null
                                  ? `Observed locally · ${(displayFileBytes / 1048576).toFixed(1)} MB`
                                  : "File selection observed locally"
                              : "Private original recording"}
                        </p>
                      </div>
                      {!submission && (
                        <button
                          type="button"
                          className="secondary-button"
                          aria-label="Change selected call"
                          disabled={!!busy || reviewSelectionActive}
                          onClick={() => reset()}
                        >
                          Change file
                        </button>
                      )}
                    </div>
                    {!submission && !result ? (
                      <details className={styles.previewDetails}>
                        <summary>Preview recording</summary>
                        {file ? (
                          audioPlayer
                        ) : (
                          <p className="small-text">
                            Audio playback is not part of this browser-local
                            observation. Select the actual file again to play
                            it.
                          </p>
                        )}
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
                  disabled={
                    !policy ||
                    !!busy ||
                    !!submission ||
                    !!deletionOnlyId ||
                    reviewSelectionActive
                  }
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
                {displayFileSelected &&
                  !busy &&
                  !deletionOnlyId &&
                  policy &&
                  !submission && (
                    <div className="studio-consent">
                      <p className={styles.verifyHeading}>
                        <span>2</span> Verify and continue
                      </p>
                      <h3>Upload privately</h3>
                      {entry?.report_languages && (
                        <div className={styles.reportLanguage}>
                          <label htmlFor="report-language">
                            Report language
                          </label>
                          <select
                            id="report-language"
                            value={displayReportLanguage ?? ""}
                            disabled={!!busy || reviewSelectionActive}
                            onChange={(event) => {
                              const selected = parseReportLanguage(
                                event.target.value,
                              );
                              chosenReportLanguage.current = selected;
                              setReportLanguage(selected);
                            }}
                          >
                            {localObservation && (
                              <option value="">
                                No language selection observed
                              </option>
                            )}
                            {displayReportLanguage &&
                              !entry.report_languages.includes(
                                displayReportLanguage,
                              ) && (
                                <option
                                  value={displayReportLanguage}
                                  key={displayReportLanguage}
                                >
                                  {reportLanguageLabels[displayReportLanguage]}{" "}
                                  (observed)
                                </option>
                              )}
                            {entry.report_languages.map((language) => (
                              <option key={language} value={language}>
                                {reportLanguageLabels[language]}
                              </option>
                            ))}
                          </select>
                          <p>
                            Hindi and Marathi use Devanagari with natural
                            English sales terms. Original transcript quotes stay
                            unchanged.
                          </p>
                        </div>
                      )}
                      <p className={styles.freeBadge}>
                        <span aria-hidden="true">
                          <Check size={13} />
                        </span>
                        Free analysis · included in your trial
                      </p>
                      <details
                        className={styles.privacyDetails}
                        open={displayPrivacyOpen}
                        onClick={(event) => {
                          if (reviewSelectionActive) event.preventDefault();
                        }}
                        onToggle={(event) => {
                          if (!reviewSelectionActive)
                            setPrivacyOpen(event.currentTarget.open);
                        }}
                      >
                        <summary>Privacy details</summary>
                        <p>{policy.description}</p>
                        <p>
                          Your recording is retained for {policy.retention_days}{" "}
                          days so this review can finish and remain available.
                          You can request deletion from Privacy &amp; support.
                        </p>
                        <p>
                          {policy.privacy_details ||
                            "Approved service providers may process this recording to prepare the transcript and coaching report. The recording and report remain private for the retention period above."}
                        </p>
                      </details>
                      <label className={styles.consentLabel}>
                        <input
                          type="checkbox"
                          checked={displayConsent}
                          disabled={!!busy || reviewSelectionActive}
                          aria-describedby={
                            localObservation
                              ? "observed-consent-note"
                              : undefined
                          }
                          onChange={(event) => {
                            const accepted = event.target.checked;
                            setConsent(accepted);
                            setConsentedPolicySha(
                              accepted ? (policy?.policy_sha256 ?? null) : null,
                            );
                          }}
                        />
                        <span>
                          I agree to the{" "}
                          <a href="https://app.authorityclosers.com/terms">
                            Terms
                          </a>{" "}
                          and{" "}
                          <a href="https://app.authorityclosers.com/privacy">
                            Privacy Policy
                          </a>
                          .
                        </span>
                      </label>
                      {localObservation && (
                        <p className="small-text" id="observed-consent-note">
                          Observed checkbox value only. This does not count as
                          consent or approval.
                        </p>
                      )}
                      <div className={styles.uploadActions}>
                        {localObservation ? (
                          <p className="small-text" role="status">
                            {localObservation.verification === "checking"
                              ? "Upload verification was still checking when this state was observed."
                              : localObservation.verification ===
                                  "session-present"
                                ? "An account or guest session was present at capture; no credentials were restored."
                                : localObservation.verification ===
                                    "guest-challenge-complete"
                                  ? "Guest verification was completed locally at capture. Its token is not restored or reused."
                                  : "Guest verification was required at capture. The challenge is not run in read-only review."}
                          </p>
                        ) : (
                          !analysisWriteBlocked &&
                          !embedded &&
                          !(
                            access?.authenticated === false &&
                            access.requestAnalysisAccess
                          ) &&
                          !session &&
                          entry?.site_key &&
                          entry.challenge_action && (
                            <UploadCheck
                              key={checkKey}
                              siteKey={entry.site_key}
                              action={entry.challenge_action}
                              onToken={onToken}
                            />
                          )
                        )}
                        <button
                          type="button"
                          className="primary-button studio-wide"
                          disabled={
                            analysisWriteBlocked ||
                            !consentCurrent ||
                            (!(
                              access?.authenticated === false &&
                              access.requestAnalysisAccess
                            ) &&
                              !session &&
                              !token) ||
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
                    {plan.report_language && (
                      <p>
                        Report language:{" "}
                        <strong>
                          {reportLanguageLabels[plan.report_language]}
                        </strong>
                        . This choice is saved with this analysis plan.
                      </p>
                    )}
                    <p>
                      Your saved call is ready for the next review step.
                      Continue with this same recording to start the analysis.
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
                      disabled={
                        !!busy ||
                        planExpired ||
                        analysisPaused ||
                        analysisWriteBlocked
                      }
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
                        disabled={
                          !!busy || analysisPaused || analysisWriteBlocked
                        }
                        onClick={() => void freshPlan()}
                      >
                        Refresh expired plan
                      </button>
                    )}
                  </div>
                )}
                {submission && !report && (!plan || plan.accepted) && (
                  <AcquisitionProcessingPanel
                    submissionId={submission.id}
                    progress={progress}
                    waitingForApproval={waitingForApproval}
                    accepted={plan?.accepted ?? false}
                    refreshProblem={!!statusIssue}
                    stageRows={processingProjection.rows}
                    statusText={processingProjection.title}
                    fileName={displayFileName ?? undefined}
                    fileMeta={
                      displayFileBytes !== null
                        ? `${(displayFileBytes / 1048576).toFixed(1)} MB`
                        : undefined
                    }
                    allowanceLabel={remainingAllowanceLabel(
                      allowance,
                      entry?.allowance_seconds ?? null,
                      allowanceUnknown,
                    )}
                    paused={processingProjection.attention}
                  >
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={!!busy || checkingStatus}
                      onClick={() => {
                        setConsentedSubmissionId(null);
                        setPollAttempt((n) => n + 1);
                      }}
                    >
                      {checkingStatus ? "Checking status…" : "Check status"}
                    </button>
                    <Link
                      href={`${embedded ? "/sales-xray" : "/"}?call=${submission.id}`}
                      className="secondary-button"
                    >
                      <FolderOpen size={17} aria-hidden="true" />
                      This call’s link
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
                        disabled={
                          !!busy || analysisPaused || analysisWriteBlocked
                        }
                        onClick={() => void freshPlan()}
                      >
                        <FileText size={17} aria-hidden="true" />
                        {busy || "Review and continue analysis"}
                      </button>
                    )}
                    {waitingForApproval && !plan && (
                      <button
                        type="button"
                        className="primary-button"
                        disabled={
                          !!busy || analysisPaused || analysisWriteBlocked
                        }
                        onClick={() => void retryAnalysis()}
                      >
                        Start analysis
                      </button>
                    )}
                  </AcquisitionProcessingPanel>
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
                            disabled={!!busy || analysisWriteBlocked}
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
                              className="secondary-button"
                              disabled={!!busy || analysisWriteBlocked}
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
              {embedded && !submission && !report && !deletionOnlyId && (
                <AcquisitionLowerPanels compact={displayFileSelected} />
              )}
            </div>
            {(embedded || stagedFiles.length >= 2) &&
              !report &&
              !deletionOnlyId &&
              !submission && (
                <AcquisitionGuideRail
                  stage={displayFileSelected ? "selected" : "empty"}
                  stagedFiles={stagedFiles}
                  maximumFileBytes={policy?.maximum_file_bytes}
                />
              )}
          </div>
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
                    {plan?.report_language &&
                      plan.report_run_id === result.runId && (
                        <p className={styles.reportMetadata}>
                          Report language:{" "}
                          {reportLanguageLabels[plan.report_language]} ·
                          Original quotes preserved
                        </p>
                      )}
                  </div>
                  <div
                    className={styles.reportActions}
                    role="group"
                    aria-label="Report actions"
                  >
                    {!result.claimed && (
                      <Link className={styles.reportAction} href="/login">
                        Sign in to save
                      </Link>
                    )}
                    <button
                      className={`${styles.reportAction} ${styles.reportActionPrimary}`}
                      type="button"
                      disabled={!!busy || !submission}
                      onClick={() => void downloadReport()}
                    >
                      <Download size={16} aria-hidden="true" />
                      Download report
                    </button>
                    <button
                      className={styles.reportAction}
                      type="button"
                      disabled={!!busy}
                      onClick={startAnotherCall}
                    >
                      <ArrowRight size={16} aria-hidden="true" />
                      Analyse another call
                    </button>
                    {submission && (
                      <button
                        className={`${styles.reportAction} ${styles.reportActionSupport}`}
                        type="button"
                        disabled={!!busy || analysisWriteBlocked}
                        onClick={() => setDeleteConfirm(true)}
                      >
                        Request deletion
                      </button>
                    )}
                  </div>
                </div>
                <p className={styles.reportDisclosure}>
                  Draft coaching; not adjudicated by Dipak. Speaker labels are
                  unverified. Source: {report.source_label}. Duration:{" "}
                  {time(result.transcript.duration_ms)}. Need the call removed?{" "}
                  <a href="mailto:admin@authorityclosers.com?subject=Sales%20Xray%20deletion%20request">
                    Contact the AC team.
                  </a>
                </p>
                {submission && deleteConfirm && (
                  <div className={styles.reportDeleteConfirm} role="alert">
                    <p>
                      Remove this recording and its report? This cannot be
                      undone.
                    </p>
                    <div>
                      <button
                        className={`${styles.reportAction} ${styles.reportActionDanger}`}
                        type="button"
                        disabled={!!busy || analysisWriteBlocked}
                        onClick={() => void erase()}
                      >
                        Request recording deletion
                      </button>
                      <button
                        className={styles.reportAction}
                        type="button"
                        disabled={!!busy}
                        onClick={() => setDeleteConfirm(false)}
                      >
                        Keep call
                      </button>
                    </div>
                  </div>
                )}
                <ReportModes
                  label="Explore your sales report"
                  boundCallId={submission?.id}
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
                      id: "prospect",
                      label: "Prospect",
                      content: (
                        <ProspectSnapshot
                          report={report}
                          onSelectEvidence={seek}
                          onUnlock={() => router.push("/login")}
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
                        />
                      ),
                    },
                    {
                      id: "skills",
                      label: "Sales skills",
                      compactLabel: "Skills",
                      content: (
                        <SalesSkills
                          dimensions={report.dimensions}
                          onSelectEvidence={seek}
                        />
                      ),
                    },
                    {
                      id: "next-call-plan",
                      label: "Next-call plan",
                      compactLabel: "Next-call",
                      content: (
                        <NextCallPlan
                          report={report}
                          onSelectEvidence={seek}
                          onUnlock={() => router.push("/login")}
                        />
                      ),
                    },
                    {
                      id: "transcript",
                      label: "Transcript",
                      content: (
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
                onPlay={() => setMoment(null)}
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
        allowance={allowance}
        heroStage={
          !result && !busy && !deletionOnlyId
            ? submission
              ? waitingForApproval && !plan?.accepted
                ? "ready"
                : "processing"
              : "welcome"
            : undefined
        }
      >
        {content}
      </AcquisitionShell>
    );
  }
}
