"use client";

import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  ChevronDown,
  PencilLine,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type Ref } from "react";

import { useAuthFlowProgress } from "./auth-flow-page";
import { courseIntentHref, type CourseIntent } from "../lib/course-intent";
import {
  ApiError,
  createLearnerApi,
  type LearnerApi,
  type OnboardingResponse,
} from "../lib/learner-api";
import {
  availableLocalStorage,
  clearOnboardingLocalDraftIfMatchesWithLock,
  purgeOnboardingLocalDraftIfMatchesWithLock,
  localDraftMatchesServer,
  mutationFailureKind,
  onboardingRecoveryText,
  onboardingServerFingerprint,
  peekOnboardingLocalDraftForCleanupWithLock,
  readOnboardingLocalDraftWithLock,
  registerBeforeUnloadGuard,
  registerHistoryNavigationGuard,
  registerInternalNavigationGuard,
  writeOnboardingLocalDraftWithLock,
  writeOnboardingLocalDraftWithLockAndEnvelope,
  type MutationFailureKind,
  type ConditionalLocalDraftStorageResult,
  type LocalDraftRawSnapshot,
  type OnboardingDraftScope,
  type OnboardingDraftEnvelope,
  type OnboardingLocalDraftCleanupTarget,
  type OnboardingLocalDraft,
  type OnboardingLocalStep,
  type OnboardingRecoveryLockManager,
} from "../lib/local-drafts";
import { ROUTES } from "../lib/routes";
import { userFacingRequestError } from "../lib/user-facing-error";

const contexts = [
  { value: "sales", label: "Sales" },
  { value: "founder", label: "Founder" },
  { value: "customer_success", label: "Customer success" },
  { value: "other", label: "Another context" },
] as const;

const goalChoices = [
  {
    value: "Handle objections with confidence",
    label: "Handle objections with confidence",
  },
  {
    value: "Run clearer discovery calls",
    label: "Run clearer discovery calls",
  },
  { value: "Close more consistently", label: "Close more consistently" },
  {
    value: "Build a repeatable sales process",
    label: "Build a repeatable sales process",
  },
] as const;

const situationChoices = [
  {
    value: "A real conversation coming up",
    label: "A real conversation coming up",
  },
  {
    value: "A discovery call to prepare for",
    label: "A discovery call to prepare for",
  },
  { value: "A process I want to repeat", label: "A process I want to repeat" },
] as const;

const weeklyTimeChoices = [
  { value: "15", label: "15 minutes" },
  { value: "30", label: "30 minutes" },
  { value: "45", label: "45 minutes" },
  { value: "60", label: "60 minutes" },
] as const;

type DetailQuestion = "situation" | "time" | "review";
type FocusTarget = "step" | "completion" | "conflict" | "error";

function hasChoiceValue(
  value: string,
  choices: ReadonlyArray<{ value: string }>,
): boolean {
  return choices.some((choice) => choice.value === value);
}

function detailQuestionFrom(draft: Draft): DetailQuestion {
  if (!draft.practiceSituation) return "situation";
  if (!draft.weeklyMinutes) return "time";
  return "review";
}

function onboardingProgressDetail(
  step: OnboardingLocalStep,
  detailQuestion: DetailQuestion,
): string {
  if (step === 1) return "Context: where you are practicing";
  if (step === 2) return "Goal: what you would most like to improve";
  if (detailQuestion === "situation") {
    return "Optional details: current situation";
  }
  if (detailQuestion === "time")
    return "Optional details: weekly learning time";
  return "Optional details: review your setup";
}

export function onboardingLocalDraftNeedsEditing(
  draft: Draft,
  serverDraft: Draft,
): boolean {
  return !draftsMatch(draft, serverDraft);
}

export function onboardingEditorStateFromLocalRecovery(
  draft: Draft,
  localStep: OnboardingLocalStep,
): { finished: false; draft: Draft; step: OnboardingLocalStep } {
  return { finished: false, draft, step: localStep };
}

export type OnboardingMutationLock = {
  activate: () => void;
  acquire: () => boolean;
  release: () => void;
  dispose: () => void;
  canCommit: () => boolean;
};

export function createOnboardingMutationLock(): OnboardingMutationLock {
  let mounted = false;
  let inFlight = false;
  return {
    activate() {
      mounted = true;
    },
    acquire() {
      if (!mounted || inFlight) return false;
      inFlight = true;
      return true;
    },
    release() {
      inFlight = false;
    },
    dispose() {
      mounted = false;
      inFlight = false;
    },
    canCommit() {
      return mounted;
    },
  };
}

type Draft = OnboardingLocalDraft;

export type OnboardingLocalCleanupResolution = {
  result: ConditionalLocalDraftStorageResult;
  envelope: OnboardingLocalDraftCleanupTarget | null;
  draft: OnboardingLocalDraft | null;
  rawSnapshot: LocalDraftRawSnapshot | null;
  newer: boolean;
};

export async function reconcileOnboardingLocalCleanup(
  storage: Storage | null,
  scope: OnboardingDraftScope,
  expected: OnboardingLocalDraftCleanupTarget | null,
  fallbackDraft: OnboardingLocalDraft,
  now = Date.now(),
  lockManager?: OnboardingRecoveryLockManager | null,
  expectedRaw?: LocalDraftRawSnapshot | null,
): Promise<OnboardingLocalCleanupResolution> {
  const result = expectedRaw
    ? await purgeOnboardingLocalDraftIfMatchesWithLock(
        storage,
        scope,
        expectedRaw,
        now,
        lockManager,
      )
    : await clearOnboardingLocalDraftIfMatchesWithLock(
        storage,
        scope,
        expected,
        now,
        lockManager,
      );
  if (result.ok) {
    return {
      result,
      envelope: null,
      draft: null,
      rawSnapshot: null,
      newer: false,
    };
  }
  if (result.reason !== "changed") {
    return {
      result,
      envelope: expected,
      draft: expected?.draft ?? fallbackDraft,
      rawSnapshot: expectedRaw ?? null,
      newer: false,
    };
  }

  const current = await peekOnboardingLocalDraftForCleanupWithLock(
    storage,
    scope,
    now,
    lockManager,
  );
  if (current.status === "missing") {
    return {
      result: { ok: true },
      envelope: null,
      draft: null,
      rawSnapshot: null,
      newer: false,
    };
  }
  if (current.status === "ready") {
    return {
      result,
      envelope: current.cleanupTarget,
      draft: current.envelope.draft,
      rawSnapshot: null,
      newer: true,
    };
  }
  if (current.status === "expired" || current.status === "invalid") {
    return {
      result: {
        ok: false,
        reason:
          current.cleanupStatus === "unavailable" ? "unavailable" : "changed",
      },
      envelope: null,
      draft: null,
      rawSnapshot: current.cleanupTarget,
      newer: false,
    };
  }
  return {
    result: { ok: false, reason: "unavailable" },
    envelope: null,
    draft: null,
    rawSnapshot: null,
    newer: false,
  };
}

export const ONBOARDING_USE_LOCAL_COPY_LABEL = "Use local copy in editor";
const ONBOARDING_NAVIGATION_CONFIRMATION =
  "You have unsaved onboarding answers. Leave this page?";

const defaultApi = createLearnerApi();

const emptyDraft: Draft = {
  experienceContext: "",
  learningGoal: "",
  practiceSituation: "",
  weeklyMinutes: "",
};

function draftFrom(profile: OnboardingResponse): Draft {
  return {
    experienceContext: profile.experience_context ?? "",
    learningGoal: profile.learning_goal ?? "",
    practiceSituation: profile.practice_situation ?? "",
    weeklyMinutes:
      profile.weekly_minutes === null ? "" : String(profile.weekly_minutes),
  };
}

function failureMessage(
  error: unknown,
  online: boolean,
  locallyStored: boolean,
): string {
  if (error instanceof ApiError && error.status === 401) {
    return "Your session is no longer available. Sign in to continue.";
  }
  if (error instanceof ApiError && error.status === 409) {
    return locallyStored
      ? "This profile changed elsewhere. Compare your recovery copy with the latest server profile before saving again."
      : "This profile changed elsewhere, and this browser could not retain a recovery copy. Keep this page open or copy/export your answers before reloading.";
  }
  const fallback = online
    ? locallyStored
      ? "The profile was not saved to the server. A bounded recovery copy is stored on this device."
      : "The profile was not saved, and this browser could not retain a recovery copy. Keep this page open or copy/export your answers."
    : locallyStored
      ? "You are offline. A bounded recovery copy is stored on this device; reconnect and retry the save."
      : "You are offline, and this browser could not retain a recovery copy. Keep this page open or copy/export your answers.";
  return userFacingRequestError(error, fallback);
}

export function isOnboardingSessionExpired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

function draftsMatch(left: Draft, right: Draft): boolean {
  return (
    left.experienceContext === right.experienceContext &&
    left.learningGoal === right.learningGoal &&
    left.practiceSituation === right.practiceSituation &&
    left.weeklyMinutes === right.weeklyMinutes
  );
}

function onboardingScope(personId: string): OnboardingDraftScope {
  return { kind: "onboarding", personId };
}

function editorEnvelopeFromCleanupTarget(
  target: OnboardingLocalDraftCleanupTarget,
  localStep: OnboardingLocalStep,
): OnboardingDraftEnvelope {
  return target.version === 2 ? { ...target, version: 3, localStep } : target;
}

function onboardingStepFromServer(value: number): OnboardingLocalStep {
  if (!Number.isInteger(value)) return 1;
  return Math.min(3, Math.max(1, value)) as OnboardingLocalStep;
}

async function copyRecoveryText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function downloadRecoveryText(text: string, filename: string): void {
  const href = URL.createObjectURL(
    new Blob([text], { type: "text/plain;charset=utf-8" }),
  );
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(href);
}

export type OnboardingFormProps = {
  api?: LearnerApi;
  initialProfile?: OnboardingResponse;
  returnHref?: string;
  courseIntent?: CourseIntent;
};

export type OnboardingCompletionStateProps = {
  status: "completed" | "skipped";
  returnHref: string;
  cleanupPending: boolean;
  cleanupAcknowledged: boolean;
  recoveryMessage?: string | null;
  completionRef?: Ref<HTMLDivElement>;
  onRetryLocalCleanup: () => void;
  onCopyRecovery: () => void;
  onExportRecovery: () => void;
  onAcknowledgeRemainingCopy: () => void;
  onEdit: () => void;
};

export function OnboardingCompletionState({
  status,
  returnHref,
  cleanupPending,
  cleanupAcknowledged,
  recoveryMessage,
  completionRef,
  onRetryLocalCleanup,
  onCopyRecovery,
  onExportRecovery,
  onAcknowledgeRemainingCopy,
  onEdit,
}: OnboardingCompletionStateProps) {
  const returningToSettings = returnHref === ROUTES.settings;

  return (
    <div
      className="onboarding-form clarity-onboarding-form onboarding-complete"
      role="status"
      aria-live="polite"
      aria-labelledby="onboarding-completion-title"
      tabIndex={-1}
      ref={completionRef}
    >
      <CheckCircle2 size={34} aria-hidden="true" />
      <div className="onboarding-complete__copy">
        <p className="eyebrow">
          <span aria-hidden="true" />{" "}
          {cleanupPending ? "Saved on server" : "Profile saved"}
        </p>
        <h2 id="onboarding-completion-title">
          {cleanupPending
            ? "Saved on the server; local cleanup is pending."
            : status === "skipped"
              ? "Continue without personalization."
              : "Your starting context is ready."}
        </h2>
        {cleanupPending ? (
          <div
            className="onboarding-cleanup-pending"
            aria-labelledby="onboarding-cleanup-title"
          >
            <h3 id="onboarding-cleanup-title">
              Your recovery copy may still be on this device.
            </h3>
            <p>
              The server save succeeded. This browser could not verify or remove
              the local recovery copy, so you can retry cleanup or keep a copy
              before leaving.
            </p>
            <div className="onboarding-cleanup-actions">
              <button
                className="button button--outline"
                type="button"
                onClick={onRetryLocalCleanup}
              >
                Retry local cleanup
              </button>
              <button
                className="text-button"
                type="button"
                onClick={onCopyRecovery}
              >
                Copy recovery text
              </button>
              <button
                className="text-button"
                type="button"
                onClick={onExportRecovery}
              >
                Download recovery file
              </button>
            </div>
            {cleanupAcknowledged ? (
              <p className="onboarding-cleanup-acknowledged">
                You acknowledged that a local recovery copy may remain on this
                device.
              </p>
            ) : (
              <button
                className="text-button onboarding-cleanup-acknowledge"
                type="button"
                onClick={onAcknowledgeRemainingCopy}
              >
                Acknowledge remaining copy
              </button>
            )}
            {recoveryMessage ? (
              <p className="onboarding-cleanup-message" role="status">
                {recoveryMessage}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
      {!cleanupPending && recoveryMessage ? (
        <p className="onboarding-cleanup-message" role="status">
          {recoveryMessage}
        </p>
      ) : null}
      <Link className="button button--ink button--full" href={returnHref}>
        {returningToSettings ? "Return to settings" : "Open learner home"}{" "}
        <ArrowRight size={17} aria-hidden="true" />
      </Link>
      <button
        className="button button--quiet button--full"
        type="button"
        onClick={onEdit}
      >
        Edit profile
      </button>
    </div>
  );
}

export function OnboardingForm(props: OnboardingFormProps = {}) {
  const {
    api = defaultApi,
    initialProfile,
    courseIntent = null,
    returnHref = courseIntentHref(ROUTES.learnerHome, courseIntent),
  } = props;
  const initialDraft = initialProfile ? draftFrom(initialProfile) : emptyDraft;
  const [profile, setProfile] = useState<OnboardingResponse | null>(
    initialProfile ?? null,
  );
  const [draft, setDraft] = useState<Draft>(initialDraft);
  const [step, setStep] = useState<OnboardingLocalStep>(() =>
    initialProfile ? onboardingStepFromServer(initialProfile.current_step) : 1,
  );
  const [detailQuestion, setDetailQuestion] = useState<DetailQuestion>(() =>
    detailQuestionFrom(initialDraft),
  );
  const [goalCustomOpen, setGoalCustomOpen] = useState(
    () =>
      Boolean(initialDraft.learningGoal) &&
      !hasChoiceValue(initialDraft.learningGoal, goalChoices),
  );
  const [contextCustomOpen, setContextCustomOpen] = useState(
    () =>
      Boolean(initialDraft.experienceContext) &&
      !hasChoiceValue(initialDraft.experienceContext, contexts),
  );
  const [situationCustomOpen, setSituationCustomOpen] = useState(
    () =>
      Boolean(initialDraft.practiceSituation) &&
      !hasChoiceValue(initialDraft.practiceSituation, situationChoices),
  );
  const [timeCustomOpen, setTimeCustomOpen] = useState(
    () =>
      Boolean(initialDraft.weeklyMinutes) &&
      !hasChoiceValue(initialDraft.weeklyMinutes, weeklyTimeChoices),
  );
  const [pending, setPending] = useState(!initialProfile);
  const [error, setError] = useState<string | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [finished, setFinished] = useState(
    initialProfile?.status === "completed" ||
      initialProfile?.status === "skipped",
  );
  const [failureKind, setFailureKind] = useState<MutationFailureKind | null>(
    null,
  );
  const [lastSave, setLastSave] = useState<{
    status: "in_progress" | "completed" | "skipped";
    currentStep: number;
  } | null>(null);
  const [localDraftRestored, setLocalDraftRestored] = useState(false);
  const [staleLocalDraft, setStaleLocalDraft] =
    useState<OnboardingDraftEnvelope | null>(null);
  const [staleLocalDraftCleanupTarget, setStaleLocalDraftCleanupTarget] =
    useState<OnboardingLocalDraftCleanupTarget | null>(null);
  const [localPersistence, setLocalPersistence] = useState<
    "idle" | "saved" | "failed"
  >("idle");
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null);
  const [cleanupPending, setCleanupPending] = useState(false);
  const [cleanupAcknowledged, setCleanupAcknowledged] = useState(false);
  const [cleanupRecoveryDraft, setCleanupRecoveryDraft] =
    useState<Draft | null>(null);
  const [cleanupEnvelope, setCleanupEnvelope] =
    useState<OnboardingLocalDraftCleanupTarget | null>(null);
  const [cleanupRawSnapshot, setCleanupRawSnapshot] =
    useState<LocalDraftRawSnapshot | null>(null);
  const [cleanupConflict, setCleanupConflict] = useState(false);
  const [focusTarget, setFocusTarget] = useState<FocusTarget | null>(null);
  const mutationLockRef = useRef(createOnboardingMutationLock());
  const stepHeadingRef = useRef<HTMLHeadingElement>(null);
  const previousStepRef = useRef<OnboardingLocalStep>(
    initialProfile ? onboardingStepFromServer(initialProfile.current_step) : 1,
  );
  const previousDetailQuestionRef = useRef<DetailQuestion>(detailQuestion);
  const errorRef = useRef<HTMLDivElement>(null);
  const conflictHeadingRef = useRef<HTMLHeadingElement>(null);
  const completionRef = useRef<HTMLDivElement>(null);
  const loadGenerationRef = useRef(0);
  const authFlowProgress = useAuthFlowProgress();
  const setAuthFlowStep = authFlowProgress?.setCurrentStep;
  const setAuthFlowDetail = authFlowProgress?.setCurrentDetail;
  const dirty = profile !== null && !draftsMatch(draft, draftFrom(profile));
  const navigationDirty =
    dirty ||
    staleLocalDraft !== null ||
    (cleanupPending && !cleanupAcknowledged);

  useEffect(() => {
    const mutationLock = mutationLockRef.current;
    mutationLock.activate();
    return () => mutationLock.dispose();
  }, []);

  useEffect(() => {
    if (!profile) {
      setAuthFlowStep?.(null);
      setAuthFlowDetail?.("Loading setup");
      return;
    }
    setAuthFlowStep?.(step);
    setAuthFlowDetail?.(onboardingProgressDetail(step, detailQuestion));
  }, [detailQuestion, profile, setAuthFlowDetail, setAuthFlowStep, step]);

  function requestFocus(target: FocusTarget) {
    setFocusTarget(target);
  }

  useEffect(() => {
    if (!focusTarget) return;
    const element =
      focusTarget === "step"
        ? stepHeadingRef.current
        : focusTarget === "completion"
          ? completionRef.current
          : focusTarget === "conflict"
            ? conflictHeadingRef.current
            : errorRef.current;
    if (!element) return;
    element.focus();
    setFocusTarget(null);
  }, [
    cleanupPending,
    detailQuestion,
    error,
    focusTarget,
    finished,
    profile,
    staleLocalDraft,
    step,
  ]);

  function online(): boolean {
    return typeof navigator === "undefined" ? true : navigator.onLine;
  }

  function load(restoreFocus = false) {
    const generation = ++loadGenerationRef.current;
    setPending(true);
    setError(null);
    setSessionExpired(false);
    setFailureKind(null);
    void api.onboarding().then(
      async (loaded) => {
        if (generation !== loadGenerationRef.current) return;
        const serverDraft = draftFrom(loaded);
        const scope = onboardingScope(loaded.person_id);
        const serverStep = onboardingStepFromServer(loaded.current_step);
        const localDraft = await readOnboardingLocalDraftWithLock(
          availableLocalStorage(window),
          scope,
          Date.now(),
          serverStep,
        );
        if (generation !== loadGenerationRef.current) return;
        setProfile(loaded);
        setDraft(serverDraft);
        setStaleLocalDraft(null);
        setStaleLocalDraftCleanupTarget(null);
        setCleanupPending(false);
        setCleanupAcknowledged(false);
        setCleanupEnvelope(null);
        setCleanupRawSnapshot(null);
        setCleanupRecoveryDraft(null);
        setCleanupConflict(false);
        setRecoveryMessage(null);
        setLocalDraftRestored(false);
        setStep(serverStep);
        setDetailQuestion(detailQuestionFrom(serverDraft));
        setContextCustomOpen(
          Boolean(serverDraft.experienceContext) &&
            !hasChoiceValue(serverDraft.experienceContext, contexts),
        );
        setGoalCustomOpen(
          Boolean(serverDraft.learningGoal) &&
            !hasChoiceValue(serverDraft.learningGoal, goalChoices),
        );
        setSituationCustomOpen(
          Boolean(serverDraft.practiceSituation) &&
            !hasChoiceValue(serverDraft.practiceSituation, situationChoices),
        );
        setTimeCustomOpen(
          Boolean(serverDraft.weeklyMinutes) &&
            !hasChoiceValue(serverDraft.weeklyMinutes, weeklyTimeChoices),
        );
        let localDraftNeedsEditing = false;
        if (localDraft.status === "ready") {
          if (
            localDraftMatchesServer(
              localDraft.envelope,
              loaded.revision,
              onboardingServerFingerprint(serverDraft),
            )
          ) {
            localDraftNeedsEditing = onboardingLocalDraftNeedsEditing(
              localDraft.envelope.draft,
              serverDraft,
            );
            setDraft(localDraft.envelope.draft);
            setStep(localDraft.envelope.localStep);
            setDetailQuestion(detailQuestionFrom(localDraft.envelope.draft));
            setContextCustomOpen(
              Boolean(localDraft.envelope.draft.experienceContext) &&
                !hasChoiceValue(
                  localDraft.envelope.draft.experienceContext,
                  contexts,
                ),
            );
            setGoalCustomOpen(
              Boolean(localDraft.envelope.draft.learningGoal) &&
                !hasChoiceValue(
                  localDraft.envelope.draft.learningGoal,
                  goalChoices,
                ),
            );
            setSituationCustomOpen(
              Boolean(localDraft.envelope.draft.practiceSituation) &&
                !hasChoiceValue(
                  localDraft.envelope.draft.practiceSituation,
                  situationChoices,
                ),
            );
            setTimeCustomOpen(
              Boolean(localDraft.envelope.draft.weeklyMinutes) &&
                !hasChoiceValue(
                  localDraft.envelope.draft.weeklyMinutes,
                  weeklyTimeChoices,
                ),
            );
            setLocalDraftRestored(true);
            setLocalPersistence("saved");
          } else {
            setStaleLocalDraft(localDraft.envelope);
            setStaleLocalDraftCleanupTarget(localDraft.cleanupTarget);
          }
        } else if (localDraft.status === "unavailable") {
          setLocalPersistence("failed");
          setRecoveryMessage(
            "This browser could not verify its local recovery copy. The server profile remains authoritative; keep a copy of any answers before leaving.",
          );
        } else if (
          localDraft.status === "expired" ||
          localDraft.status === "invalid"
        ) {
          setLocalPersistence("failed");
          setCleanupPending(true);
          setCleanupAcknowledged(false);
          setCleanupRawSnapshot(localDraft.cleanupTarget);
          setRecoveryMessage(
            localDraft.status === "expired"
              ? "An expired local recovery record remains because this browser could not complete locked cleanup. Retry cleanup before leaving."
              : "An invalid local recovery record remains because this browser could not complete locked cleanup. Retry cleanup before leaving.",
          );
        } else {
          setLocalPersistence("idle");
        }
        const loadedFinished =
          loaded.status === "completed" || loaded.status === "skipped";
        setFinished(loadedFinished && !localDraftNeedsEditing);
        if (restoreFocus) {
          requestFocus(
            loadedFinished &&
              localDraft.status === "ready" &&
              !localDraftNeedsEditing
              ? "completion"
              : localDraft.status === "ready" &&
                  !localDraftMatchesServer(
                    localDraft.envelope,
                    loaded.revision,
                    onboardingServerFingerprint(serverDraft),
                  )
                ? "conflict"
                : "step",
          );
        }
        setPending(false);
      },
      (requestError: unknown) => {
        if (generation !== loadGenerationRef.current) return;
        setError(
          requestError instanceof ApiError && requestError.status === 401
            ? "Your session is no longer available. Sign in to continue."
            : userFacingRequestError(
                requestError,
                online()
                  ? "We could not load your learning profile. Try again."
                  : "You are offline. Reconnect to load your learning profile.",
              ),
        );
        setSessionExpired(isOnboardingSessionExpired(requestError));
        setFailureKind(mutationFailureKind(requestError, online()));
        setPending(false);
        requestFocus("error");
      },
    );
  }

  useEffect(() => {
    if (initialProfile) return;
    let active = true;
    queueMicrotask(() => {
      if (active) load();
    });
    return () => {
      active = false;
      loadGenerationRef.current += 1;
    };
    // The API instance is stable for one mounted form and its retries.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialProfile]);

  useEffect(() => {
    if (!profile) return;
    if (staleLocalDraft) return;
    let active = true;
    const scope = onboardingScope(profile.person_id);
    const storage = availableLocalStorage(window);
    void (async () => {
      if (dirty) {
        const result = await writeOnboardingLocalDraftWithLock(storage, {
          scope,
          draft,
          baseRevision: profile.revision,
          serverFingerprint: onboardingServerFingerprint(draftFrom(profile)),
          localStep: step,
        });
        if (active) setLocalPersistence(result.ok ? "saved" : "failed");
        return;
      }
      if (cleanupPending) return;
      const localDraft = await peekOnboardingLocalDraftForCleanupWithLock(
        storage,
        scope,
        Date.now(),
      );
      if (!active) return;
      const expected =
        localDraft.status === "ready" ? localDraft.envelope : null;
      const resolution = await reconcileOnboardingLocalCleanup(
        storage,
        scope,
        expected,
        draft,
        Date.now(),
        undefined,
        localDraft.status === "expired" || localDraft.status === "invalid"
          ? localDraft.cleanupTarget
          : null,
      );
      if (!active) return;
      if (resolution.newer && resolution.envelope) {
        const editor = editorEnvelopeFromCleanupTarget(
          resolution.envelope,
          step,
        );
        setStaleLocalDraft(editor);
        setStaleLocalDraftCleanupTarget(resolution.envelope);
        setCleanupConflict(true);
        setCleanupPending(false);
        setCleanupAcknowledged(false);
        setCleanupEnvelope(null);
        setCleanupRawSnapshot(null);
        setCleanupRecoveryDraft(null);
        setLocalPersistence("failed");
        setRecoveryMessage(
          "A newer local recovery copy appeared while cleanup was in progress. Compare it with the server profile before choosing what to keep.",
        );
        return;
      }
      if (!resolution.result.ok) {
        setRecoveryMessage(
          resolution.result.reason === "changed"
            ? "The local recovery copy changed, so cleanup was not completed. Review or keep the current copy before leaving."
            : "The browser could not clear or verify the local recovery copy. Retry cleanup before leaving.",
        );
        setCleanupPending(true);
        setCleanupAcknowledged(false);
        setCleanupEnvelope(resolution.envelope);
        setCleanupRawSnapshot(resolution.rawSnapshot);
        setCleanupRecoveryDraft(resolution.draft);
      }
      setLocalPersistence(resolution.result.ok ? "idle" : "failed");
      if (resolution.result.ok) {
        setCleanupPending(false);
        setCleanupEnvelope(null);
        setCleanupRawSnapshot(null);
        setCleanupRecoveryDraft(null);
        setCleanupConflict(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [cleanupPending, dirty, draft, profile, staleLocalDraft, step]);

  useEffect(
    () => registerBeforeUnloadGuard(window, navigationDirty),
    [navigationDirty],
  );

  useEffect(
    () =>
      registerInternalNavigationGuard(window, navigationDirty, () =>
        window.confirm(ONBOARDING_NAVIGATION_CONFIRMATION),
      ),
    [navigationDirty],
  );

  useEffect(
    () =>
      registerHistoryNavigationGuard(window, navigationDirty, () =>
        window.confirm(ONBOARDING_NAVIGATION_CONFIRMATION),
      ),
    [navigationDirty],
  );

  useEffect(() => {
    if (!profile) return;
    if (
      previousStepRef.current === step &&
      previousDetailQuestionRef.current === detailQuestion
    ) {
      return;
    }
    previousStepRef.current = step;
    previousDetailQuestionRef.current = detailQuestion;
    stepHeadingRef.current?.focus();
  }, [detailQuestion, profile, step]);

  async function save(
    status: "in_progress" | "completed" | "skipped",
    currentStep: number,
  ) {
    const mutationLock = mutationLockRef.current;
    if (!profile || !mutationLock?.acquire()) return;
    const submittedDraft = draft;
    const nextServerStep = onboardingStepFromServer(currentStep);
    setLastSave({ status, currentStep: nextServerStep });
    setPending(true);
    setError(null);
    setSessionExpired(false);
    setFailureKind(null);
    let locallyStored = localPersistence === "saved";
    const storage = availableLocalStorage(window);
    const scope = onboardingScope(profile.person_id);
    let cleanupTarget: OnboardingLocalDraftCleanupTarget | null = null;
    let cleanupRawSnapshot: LocalDraftRawSnapshot | null = null;
    try {
      if (dirty) {
        const localWrite = await writeOnboardingLocalDraftWithLockAndEnvelope(
          storage,
          {
            scope,
            draft: submittedDraft,
            baseRevision: profile.revision,
            serverFingerprint: onboardingServerFingerprint(draftFrom(profile)),
            localStep: step,
          },
        );
        if (!mutationLock.canCommit()) return;
        locallyStored = localWrite.result.ok;
        setLocalPersistence(localWrite.result.ok ? "saved" : "failed");
        // The writer returns the exact envelope created in its lock section.
        // Do not peek in a later section: another tab may have replaced it.
        if (localWrite.result.ok) cleanupTarget = localWrite.envelope;
      } else {
        const localDraft = await peekOnboardingLocalDraftForCleanupWithLock(
          storage,
          scope,
          Date.now(),
        );
        if (!mutationLock.canCommit()) return;
        if (localDraft.status === "ready") {
          cleanupTarget = localDraft.envelope;
        } else if (
          localDraft.status === "expired" ||
          localDraft.status === "invalid"
        ) {
          cleanupRawSnapshot = localDraft.cleanupTarget;
        }
      }
      const weeklyMinutes =
        submittedDraft.weeklyMinutes.trim() === ""
          ? null
          : Number.parseInt(submittedDraft.weeklyMinutes, 10);
      const saved = await api.saveOnboarding(
        {
          experienceContext: submittedDraft.experienceContext || null,
          learningGoal: submittedDraft.learningGoal || null,
          practiceSituation: submittedDraft.practiceSituation || null,
          weeklyMinutes,
          status,
          currentStep: nextServerStep,
        },
        profile.revision,
      );
      if (!mutationLock.canCommit()) return;
      setProfile(saved);
      const savedDraft = draftFrom(saved);
      setDraft(savedDraft);
      setStep(onboardingStepFromServer(saved.current_step));
      setDetailQuestion(detailQuestionFrom(savedDraft));
      const savedFinished =
        saved.status === "completed" || saved.status === "skipped";
      setFinished(savedFinished);
      const cleanup = await reconcileOnboardingLocalCleanup(
        storage,
        onboardingScope(saved.person_id),
        cleanupTarget,
        submittedDraft,
        Date.now(),
        undefined,
        cleanupRawSnapshot,
      );
      if (!mutationLock.canCommit()) return;
      setLocalDraftRestored(false);
      setLocalPersistence(cleanup.result.ok ? "idle" : "failed");
      setCleanupAcknowledged(false);
      if (cleanup.newer && cleanup.envelope) {
        setStaleLocalDraft(
          editorEnvelopeFromCleanupTarget(
            cleanup.envelope,
            onboardingStepFromServer(saved.current_step),
          ),
        );
        setStaleLocalDraftCleanupTarget(cleanup.envelope);
        setCleanupConflict(true);
        setCleanupPending(false);
        setCleanupEnvelope(null);
        setCleanupRawSnapshot(null);
        setCleanupRecoveryDraft(null);
        setRecoveryMessage(
          "The profile was saved to the server, but a newer local recovery copy appeared during cleanup. Compare it with the saved server profile before choosing what to keep.",
        );
      } else {
        setStaleLocalDraft(null);
        setStaleLocalDraftCleanupTarget(null);
        setCleanupConflict(false);
        setCleanupPending(!cleanup.result.ok);
        setCleanupEnvelope(cleanup.result.ok ? null : cleanup.envelope);
        setCleanupRawSnapshot(cleanup.result.ok ? null : cleanup.rawSnapshot);
        setCleanupRecoveryDraft(cleanup.result.ok ? null : cleanup.draft);
      }
      if (!cleanup.result.ok && !cleanup.newer) {
        setRecoveryMessage(
          cleanup.result.reason === "changed"
            ? "The profile was saved to the server, but the current local recovery copy could not be verified. Review or copy it before retrying cleanup."
            : "The profile was saved to the server, but this browser could not verify or clear its local recovery copy. Retry cleanup or acknowledge that the copy may remain.",
        );
      } else if (cleanup.result.ok) {
        setRecoveryMessage(null);
      }
      setLastSave(null);
      requestFocus(savedFinished ? "completion" : "step");
    } catch (requestError) {
      if (!mutationLock.canCommit()) return;
      setError(failureMessage(requestError, online(), locallyStored));
      setSessionExpired(isOnboardingSessionExpired(requestError));
      setFailureKind(mutationFailureKind(requestError, online()));
      requestFocus("error");
    } finally {
      mutationLock.release();
      if (mutationLock.canCommit()) setPending(false);
    }
  }

  async function keepServerDraft() {
    const mutationLock = mutationLockRef.current;
    if (!profile || !staleLocalDraft || !mutationLock?.acquire()) {
      return;
    }
    try {
      const expected = staleLocalDraftCleanupTarget ?? staleLocalDraft;
      const cleanup = await reconcileOnboardingLocalCleanup(
        availableLocalStorage(window),
        onboardingScope(profile.person_id),
        expected,
        draftFrom(profile),
        Date.now(),
      );
      if (!mutationLock.canCommit()) return;
      if (cleanup.newer && cleanup.envelope) {
        setStaleLocalDraft(
          editorEnvelopeFromCleanupTarget(
            cleanup.envelope,
            onboardingStepFromServer(profile.current_step),
          ),
        );
        setStaleLocalDraftCleanupTarget(cleanup.envelope);
        setCleanupConflict(true);
        setCleanupPending(false);
        setCleanupAcknowledged(false);
        setCleanupEnvelope(null);
        setCleanupRawSnapshot(null);
        setCleanupRecoveryDraft(null);
        setLocalPersistence("failed");
        setRecoveryMessage(
          "A newer local recovery copy appeared while discarding the previous copy. Compare the current copy with the server profile before choosing what to keep.",
        );
        requestFocus("conflict");
        return;
      }
      const serverDraft = draftFrom(profile);
      setDraft(serverDraft);
      setStep(onboardingStepFromServer(profile.current_step));
      setDetailQuestion(detailQuestionFrom(serverDraft));
      setStaleLocalDraft(null);
      setStaleLocalDraftCleanupTarget(null);
      setCleanupConflict(false);
      setLocalDraftRestored(false);
      setLocalPersistence(cleanup.result.ok ? "idle" : "failed");
      setCleanupPending(!cleanup.result.ok);
      setCleanupAcknowledged(false);
      setCleanupEnvelope(cleanup.result.ok ? null : cleanup.envelope);
      setCleanupRawSnapshot(cleanup.result.ok ? null : cleanup.rawSnapshot);
      setCleanupRecoveryDraft(cleanup.result.ok ? null : cleanup.draft);
      setRecoveryMessage(
        cleanup.result.ok
          ? "The local recovery copy was discarded."
          : cleanup.result.reason === "changed"
            ? "The server profile is now in the editor, but the current local recovery copy could not be verified, so it was left in place."
            : "The server profile is now in the editor, but this browser could not verify or clear the local recovery copy.",
      );
      requestFocus("step");
    } finally {
      mutationLock.release();
    }
  }

  function mergeLocalDraftIntoEditor() {
    if (!staleLocalDraft) return;
    const restored = onboardingEditorStateFromLocalRecovery(
      staleLocalDraft.draft,
      staleLocalDraft.localStep,
    );
    setFinished(restored.finished);
    setDraft(restored.draft);
    setStep(restored.step);
    setDetailQuestion(detailQuestionFrom(restored.draft));
    setStaleLocalDraft(null);
    setStaleLocalDraftCleanupTarget(null);
    setCleanupConflict(false);
    setLocalDraftRestored(true);
    setRecoveryMessage(
      "The local recovery copy is now in the editor. Review it before saving against the latest server revision.",
    );
    requestFocus("step");
  }

  const recoveryDraft =
    staleLocalDraft?.draft ?? (dirty ? draft : null) ?? cleanupRecoveryDraft;

  function recoveryText(): string | null {
    if (recoveryDraft) return onboardingRecoveryText(recoveryDraft);
    return cleanupRawSnapshot?.raw ?? null;
  }

  async function copyRecovery() {
    const text = recoveryText();
    if (!text) return;
    const copied = await copyRecoveryText(text);
    setRecoveryMessage(
      copied
        ? "Recovery copy copied to the clipboard."
        : "Clipboard access was blocked. Download the recovery file instead.",
    );
  }

  function exportRecovery() {
    const text = recoveryText();
    if (!text) return;
    downloadRecoveryText(text, "authority-closers-profile-recovery.txt");
    setRecoveryMessage("Recovery file downloaded on this device.");
  }

  async function retryLocalCleanup() {
    const mutationLock = mutationLockRef.current;
    if (!profile || !mutationLock?.acquire()) return;
    try {
      const cleanup = await reconcileOnboardingLocalCleanup(
        availableLocalStorage(window),
        onboardingScope(profile.person_id),
        cleanupEnvelope,
        draftFrom(profile),
        Date.now(),
        undefined,
        cleanupRawSnapshot,
      );
      if (!mutationLock.canCommit()) return;
      if (cleanup.newer && cleanup.envelope) {
        setStaleLocalDraft(
          editorEnvelopeFromCleanupTarget(
            cleanup.envelope,
            onboardingStepFromServer(profile.current_step),
          ),
        );
        setStaleLocalDraftCleanupTarget(cleanup.envelope);
        setCleanupConflict(true);
        setCleanupPending(false);
        setCleanupAcknowledged(false);
        setCleanupEnvelope(null);
        setCleanupRawSnapshot(null);
        setCleanupRecoveryDraft(null);
        setLocalPersistence("failed");
        setRecoveryMessage(
          "A newer local recovery copy appeared during cleanup. Compare it with the saved server profile before choosing what to keep.",
        );
        requestFocus("conflict");
        return;
      }
      if (cleanup.result.ok) {
        setCleanupPending(false);
        setCleanupAcknowledged(false);
        setCleanupEnvelope(null);
        setCleanupRawSnapshot(null);
        setCleanupRecoveryDraft(null);
        setCleanupConflict(false);
        setLocalPersistence("idle");
        setRecoveryMessage("The local recovery copy was cleared.");
      } else {
        setCleanupPending(true);
        setCleanupEnvelope(cleanup.envelope);
        setCleanupRawSnapshot(cleanup.rawSnapshot);
        setCleanupRecoveryDraft(cleanup.draft);
        setRecoveryMessage(
          cleanup.result.reason === "changed"
            ? "The profile was saved to the server, but the current local recovery copy could not be verified, so it was left in place."
            : "The profile was saved to the server, but this browser still could not verify or clear its local recovery copy.",
        );
      }
      requestFocus(finished ? "completion" : "step");
    } finally {
      mutationLock.release();
    }
  }

  function acknowledgeRemainingCopy() {
    setCleanupAcknowledged(true);
    setRecoveryMessage(
      "You acknowledged that a local recovery copy may remain on this device.",
    );
    requestFocus(finished ? "completion" : "step");
  }

  function editProfile() {
    if (!profile) return;
    setFinished(false);
    setStep(onboardingStepFromServer(profile.current_step));
    setDetailQuestion(detailQuestionFrom(draft));
    requestFocus("step");
  }

  function goBack() {
    if (step === 3 && detailQuestion === "review") {
      setDetailQuestion("time");
      return;
    }
    if (step === 3 && detailQuestion === "time") {
      setDetailQuestion("situation");
      return;
    }
    if (step === 3 && detailQuestion === "situation") {
      setStep(2);
      return;
    }
    setStep(onboardingStepFromServer(step - 1));
  }

  if (pending && !profile) {
    return (
      <div
        className="onboarding-form clarity-onboarding-form"
        role="status"
        aria-live="polite"
      >
        <div className="skeleton-block" />
        <p>Loading your saved profile…</p>
      </div>
    );
  }

  if (error && !profile) {
    return (
      <div
        className="onboarding-form clarity-onboarding-form"
        role="alert"
        tabIndex={-1}
        ref={errorRef}
      >
        <p className="form-message form-message--error">{error}</p>
        <button
          className="button button--outline button--full"
          onClick={() => load(true)}
        >
          Retry profile
        </button>
        {sessionExpired ? (
          <Link
            className="text-link"
            href={courseIntentHref(ROUTES.sessionExpired, courseIntent)}
          >
            Sign in again
          </Link>
        ) : null}
      </div>
    );
  }

  if (!profile) return null;

  if (staleLocalDraft) {
    const serverDraft = draftFrom(profile);
    return (
      <section
        className="onboarding-form clarity-onboarding-form"
        aria-labelledby="profile-draft-conflict-title"
      >
        <div role="alert">
          <p className="eyebrow">Recovery decision required</p>
          <h2
            id="profile-draft-conflict-title"
            ref={conflictHeadingRef}
            tabIndex={-1}
          >
            {cleanupConflict
              ? "A newer local recovery copy needs your decision."
              : "A newer profile exists on the server."}
          </h2>
          <p>
            {cleanupConflict
              ? "A newer answer was written on this device while cleanup was in progress. Nothing has been placed into the editor. Compare the current copy with the saved server profile and choose what to keep."
              : `This device has answers based on revision ${staleLocalDraft.baseRevision}, while the server is now at revision ${profile.revision}. Nothing has been placed into the editor. Compare the copies and choose what to keep.`}
          </p>
        </div>
        <details>
          <summary>Compare server and local answers</summary>
          <dl>
            <div>
              <dt>Experience context on the server</dt>
              <dd>{serverDraft.experienceContext || "Not provided"}</dd>
            </div>
            <div>
              <dt>Experience context in this device recovery copy</dt>
              <dd>
                {staleLocalDraft.draft.experienceContext || "Not provided"}
              </dd>
            </div>
            <div>
              <dt>Learning goal on the server</dt>
              <dd>{serverDraft.learningGoal || "Not provided"}</dd>
            </div>
            <div>
              <dt>Learning goal in this device recovery copy</dt>
              <dd>{staleLocalDraft.draft.learningGoal || "Not provided"}</dd>
            </div>
            <div>
              <dt>Practice situation on the server</dt>
              <dd>{serverDraft.practiceSituation || "Not provided"}</dd>
            </div>
            <div>
              <dt>Practice situation in this device recovery copy</dt>
              <dd>
                {staleLocalDraft.draft.practiceSituation || "Not provided"}
              </dd>
            </div>
            <div>
              <dt>Weekly minutes on the server</dt>
              <dd>{serverDraft.weeklyMinutes || "Not provided"}</dd>
            </div>
            <div>
              <dt>Weekly minutes in this device recovery copy</dt>
              <dd>{staleLocalDraft.draft.weeklyMinutes || "Not provided"}</dd>
            </div>
          </dl>
        </details>
        <div className="onboarding-actions clarity-onboarding-actions">
          <button
            className="button button--outline"
            type="button"
            onClick={() => void keepServerDraft()}
          >
            Keep server and discard local
          </button>
          <button
            className="button button--ink"
            type="button"
            onClick={mergeLocalDraftIntoEditor}
          >
            {ONBOARDING_USE_LOCAL_COPY_LABEL}
          </button>
        </div>
        <div className="onboarding-actions clarity-onboarding-actions">
          <button
            className="text-button"
            type="button"
            onClick={() => void copyRecovery()}
          >
            Copy local recovery text
          </button>
          <button
            className="text-button"
            type="button"
            onClick={exportRecovery}
          >
            Download local recovery file
          </button>
        </div>
        {recoveryMessage ? <p role="status">{recoveryMessage}</p> : null}
      </section>
    );
  }

  if (finished) {
    return (
      <OnboardingCompletionState
        status={profile.status === "skipped" ? "skipped" : "completed"}
        returnHref={returnHref}
        cleanupPending={cleanupPending}
        cleanupAcknowledged={cleanupAcknowledged}
        recoveryMessage={recoveryMessage}
        completionRef={completionRef}
        onRetryLocalCleanup={retryLocalCleanup}
        onCopyRecovery={() => void copyRecovery()}
        onExportRecovery={exportRecovery}
        onAcknowledgeRemainingCopy={acknowledgeRemainingCopy}
        onEdit={editProfile}
      />
    );
  }

  return (
    <form
      className="onboarding-form clarity-onboarding-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (step < 3) {
          void save("in_progress", step + 1);
        } else if (detailQuestion === "situation") {
          setDetailQuestion("time");
        } else if (detailQuestion === "time") {
          setDetailQuestion("review");
        } else {
          void save("completed", 3);
        }
      }}
    >
      {step === 1 ? (
        <>
          <div className="form-step clarity-form-step">
            <span className="form-step__number">01</span>
            <div>
              <h2 ref={stepHeadingRef} tabIndex={-1}>
                Where are you practicing?
              </h2>
              <p>Choose the context closest to your next real conversation.</p>
            </div>
          </div>
          <fieldset
            className="choice-fieldset"
            aria-required="true"
            aria-describedby="experience-context-help"
          >
            <legend className="sr-only">Experience context</legend>
            <div className="choice-grid">
              {contexts.map((option) => (
                <label
                  className={`choice-card${
                    !contextCustomOpen &&
                    draft.experienceContext === option.value
                      ? " is-selected"
                      : ""
                  }`}
                  key={option.value}
                >
                  <input
                    type="radio"
                    name="experience-context"
                    value={option.value}
                    checked={
                      !contextCustomOpen &&
                      draft.experienceContext === option.value
                    }
                    disabled={pending}
                    onChange={() => {
                      setContextCustomOpen(false);
                      setDraft((current) => ({
                        ...current,
                        experienceContext: option.value,
                      }));
                    }}
                  />
                  <span>{option.label}</span>
                </label>
              ))}
              <label
                className={`choice-card${contextCustomOpen ? " is-selected" : ""}`}
              >
                <input
                  type="radio"
                  name="experience-context"
                  value="custom"
                  checked={contextCustomOpen}
                  disabled={pending}
                  onChange={() => {
                    setContextCustomOpen(true);
                    setDraft((current) => ({
                      ...current,
                      experienceContext: hasChoiceValue(
                        current.experienceContext,
                        contexts,
                      )
                        ? ""
                        : current.experienceContext,
                    }));
                  }}
                />
                <span>Write a different context</span>
              </label>
            </div>
            <p id="experience-context-help" className="choice-help">
              Choose one to continue, or describe a different context.
            </p>
          </fieldset>
          {contextCustomOpen ? (
            <div className="field-group clarity-custom-answer">
              <label htmlFor="experience-context-custom">Your context</label>
              <div className="input-with-icon">
                <PencilLine size={17} aria-hidden="true" />
                <input
                  id="experience-context-custom"
                  value={draft.experienceContext}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      experienceContext: event.target.value,
                    }))
                  }
                  maxLength={64}
                  required
                  disabled={pending}
                  placeholder="For example: leading a small sales team"
                />
              </div>
            </div>
          ) : null}
        </>
      ) : null}

      {step === 2 ? (
        <>
          <div className="form-step clarity-form-step">
            <span className="form-step__number">02</span>
            <div>
              <h2 ref={stepHeadingRef} tabIndex={-1}>
                What would you most like to improve?
              </h2>
              <p>Choose the closest fit. You can change this later.</p>
            </div>
          </div>
          <fieldset
            className="choice-fieldset"
            aria-required="true"
            aria-describedby="learning-goal-help"
          >
            <legend className="sr-only">Learning goal</legend>
            <div className="choice-grid choice-grid--stacked">
              {goalChoices.map((option) => (
                <label
                  className={`choice-card${
                    !goalCustomOpen && draft.learningGoal === option.value
                      ? " is-selected"
                      : ""
                  }`}
                  key={option.value}
                >
                  <input
                    type="radio"
                    name="learning-goal"
                    value={option.value}
                    checked={
                      !goalCustomOpen && draft.learningGoal === option.value
                    }
                    disabled={pending}
                    onChange={() => {
                      setGoalCustomOpen(false);
                      setDraft((current) => ({
                        ...current,
                        learningGoal: option.value,
                      }));
                    }}
                  />
                  <span>{option.label}</span>
                </label>
              ))}
              <label
                className={`choice-card clarity-choice-card--secondary${
                  goalCustomOpen ? " is-selected" : ""
                }`}
              >
                <input
                  type="radio"
                  name="learning-goal"
                  value="custom"
                  checked={goalCustomOpen}
                  disabled={pending}
                  onChange={() => {
                    setGoalCustomOpen(true);
                    setDraft((current) => ({
                      ...current,
                      learningGoal: hasChoiceValue(
                        current.learningGoal,
                        goalChoices,
                      )
                        ? ""
                        : current.learningGoal,
                    }));
                  }}
                />
                <ChevronDown size={16} aria-hidden="true" />
                <span>Write a different goal</span>
              </label>
            </div>
            <p id="learning-goal-help" className="choice-help">
              A goal is required for this step. Skip setup is still available.
            </p>
          </fieldset>
          {goalCustomOpen ? (
            <div className="field-group clarity-custom-answer">
              <label htmlFor="learning-goal-custom">Your goal</label>
              <div className="input-with-icon">
                <UserRound size={17} aria-hidden="true" />
                <input
                  id="learning-goal-custom"
                  value={draft.learningGoal}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      learningGoal: event.target.value,
                    }))
                  }
                  maxLength={240}
                  required
                  disabled={pending}
                  placeholder="For example: ask a clear next-step question"
                />
              </div>
            </div>
          ) : null}
        </>
      ) : null}

      {step === 3 && detailQuestion === "situation" ? (
        <>
          <div className="form-step clarity-form-step">
            <span className="form-step__number">03</span>
            <div>
              <h2 ref={stepHeadingRef} tabIndex={-1}>
                What situation are you working through?
              </h2>
              <p>This detail is optional and can be changed later.</p>
            </div>
          </div>
          <fieldset
            className="choice-fieldset"
            aria-describedby="situation-help"
          >
            <legend className="sr-only">Current situation</legend>
            <div className="choice-grid choice-grid--stacked">
              {situationChoices.map((option) => (
                <label
                  className={`choice-card${
                    !situationCustomOpen &&
                    draft.practiceSituation === option.value
                      ? " is-selected"
                      : ""
                  }`}
                  key={option.value}
                >
                  <input
                    type="radio"
                    name="practice-situation"
                    value={option.value}
                    checked={
                      !situationCustomOpen &&
                      draft.practiceSituation === option.value
                    }
                    disabled={pending}
                    onChange={() => {
                      setSituationCustomOpen(false);
                      setDraft((current) => ({
                        ...current,
                        practiceSituation: option.value,
                      }));
                    }}
                  />
                  <span>{option.label}</span>
                </label>
              ))}
              <label
                className={`choice-card${situationCustomOpen ? " is-selected" : ""}`}
              >
                <input
                  type="radio"
                  name="practice-situation"
                  value="custom"
                  checked={situationCustomOpen}
                  disabled={pending}
                  onChange={() => {
                    setSituationCustomOpen(true);
                    setDraft((current) => ({
                      ...current,
                      practiceSituation: hasChoiceValue(
                        current.practiceSituation,
                        situationChoices,
                      )
                        ? ""
                        : current.practiceSituation,
                    }));
                  }}
                />
                <span>Describe a different situation</span>
              </label>
            </div>
            <p id="situation-help" className="choice-help">
              Optional · You can continue without adding a situation.
            </p>
          </fieldset>
          {situationCustomOpen ? (
            <div className="field-group clarity-custom-answer">
              <label htmlFor="practice-situation-custom">Your situation</label>
              <div className="input-with-icon">
                <PencilLine size={17} aria-hidden="true" />
                <textarea
                  id="practice-situation-custom"
                  value={draft.practiceSituation}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      practiceSituation: event.target.value,
                    }))
                  }
                  maxLength={500}
                  disabled={pending}
                  placeholder="For example: a first call with a new buyer"
                />
              </div>
            </div>
          ) : null}
        </>
      ) : null}

      {step === 3 && detailQuestion === "time" ? (
        <>
          <div className="form-step clarity-form-step">
            <span className="form-step__number">03</span>
            <div>
              <h2 ref={stepHeadingRef} tabIndex={-1}>
                How much time can you make each week?
              </h2>
              <p>Pick a useful starting point. You can change it later.</p>
            </div>
          </div>
          <fieldset
            className="choice-fieldset"
            aria-describedby="weekly-time-help"
          >
            <legend className="sr-only">Weekly learning time</legend>
            <div className="choice-grid choice-grid--stacked">
              {weeklyTimeChoices.map((option) => (
                <label
                  className={`choice-card${
                    !timeCustomOpen && draft.weeklyMinutes === option.value
                      ? " is-selected"
                      : ""
                  }`}
                  key={option.value}
                >
                  <input
                    type="radio"
                    name="weekly-time"
                    value={option.value}
                    checked={
                      !timeCustomOpen && draft.weeklyMinutes === option.value
                    }
                    disabled={pending}
                    onChange={() => {
                      setTimeCustomOpen(false);
                      setDraft((current) => ({
                        ...current,
                        weeklyMinutes: option.value,
                      }));
                    }}
                  />
                  <Clock3 size={17} aria-hidden="true" />
                  <span>{option.label}</span>
                </label>
              ))}
              <label
                className={`choice-card${timeCustomOpen ? " is-selected" : ""}`}
              >
                <input
                  type="radio"
                  name="weekly-time"
                  value="custom"
                  checked={timeCustomOpen}
                  disabled={pending}
                  onChange={() => {
                    setTimeCustomOpen(true);
                    setDraft((current) => ({
                      ...current,
                      weeklyMinutes: hasChoiceValue(
                        current.weeklyMinutes,
                        weeklyTimeChoices,
                      )
                        ? ""
                        : current.weeklyMinutes,
                    }));
                  }}
                />
                <PencilLine size={17} aria-hidden="true" />
                <span>Choose another amount</span>
              </label>
            </div>
            <p id="weekly-time-help" className="choice-help">
              Optional · You can continue without adding weekly time.
            </p>
          </fieldset>
          {timeCustomOpen ? (
            <div className="field-group clarity-custom-answer">
              <label htmlFor="weekly-minutes-custom">Minutes each week</label>
              <div className="input-with-icon">
                <Clock3 size={17} aria-hidden="true" />
                <input
                  id="weekly-minutes-custom"
                  type="number"
                  inputMode="numeric"
                  min={15}
                  max={1200}
                  step={5}
                  value={draft.weeklyMinutes}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      weeklyMinutes: event.target.value,
                    }))
                  }
                  disabled={pending}
                  placeholder="30"
                />
              </div>
              <p className="field-help">Enter a number from 15 to 1200.</p>
            </div>
          ) : null}
        </>
      ) : null}

      {step === 3 && detailQuestion === "review" ? (
        <>
          <div className="form-step clarity-form-step">
            <span className="form-step__number">03</span>
            <div>
              <h2 ref={stepHeadingRef} tabIndex={-1}>
                Review your setup.
              </h2>
              <p>One final check before these details are saved.</p>
            </div>
          </div>
          <div className="clarity-review-list" aria-label="Setup answers">
            <div className="clarity-review-row">
              <div>
                <span>Context</span>
                <strong>{draft.experienceContext || "Not provided"}</strong>
              </div>
              <button
                className="text-button clarity-review-edit"
                type="button"
                disabled={pending}
                onClick={() => {
                  setStep(1);
                }}
              >
                <PencilLine size={15} aria-hidden="true" /> Edit
              </button>
            </div>
            <div className="clarity-review-row">
              <div>
                <span>Goal</span>
                <strong>{draft.learningGoal || "Not provided"}</strong>
              </div>
              <button
                className="text-button clarity-review-edit"
                type="button"
                disabled={pending}
                onClick={() => {
                  setStep(2);
                }}
              >
                <PencilLine size={15} aria-hidden="true" /> Edit
              </button>
            </div>
            <div className="clarity-review-row">
              <div>
                <span>Situation</span>
                <strong>{draft.practiceSituation || "Not provided"}</strong>
              </div>
              <button
                className="text-button clarity-review-edit"
                type="button"
                disabled={pending}
                onClick={() => {
                  setDetailQuestion("situation");
                }}
              >
                <PencilLine size={15} aria-hidden="true" /> Edit
              </button>
            </div>
            <div className="clarity-review-row">
              <div>
                <span>Weekly time</span>
                <strong>
                  {draft.weeklyMinutes
                    ? `${draft.weeklyMinutes} minutes`
                    : "Not provided"}
                </strong>
              </div>
              <button
                className="text-button clarity-review-edit"
                type="button"
                disabled={pending}
                onClick={() => {
                  setDetailQuestion("time");
                }}
              >
                <PencilLine size={15} aria-hidden="true" /> Edit
              </button>
            </div>
          </div>
          <p className="clarity-onboarding-step-note">
            Final check · still step 3 of 3. Saving records your answers only;
            it does not change course access.
          </p>
        </>
      ) : null}

      {error ? (
        <div
          className="auth-error-summary"
          role="alert"
          tabIndex={-1}
          ref={errorRef}
        >
          <strong>Profile save could not be completed</strong>
          <p>{error}</p>
          {sessionExpired ? (
            <Link
              className="text-link"
              href={courseIntentHref(ROUTES.sessionExpired, courseIntent)}
            >
              Sign in again
            </Link>
          ) : null}
          {failureKind === "conflict" ? (
            <button
              className="text-button"
              type="button"
              disabled={pending}
              onClick={() => load(true)}
            >
              Reload latest profile
            </button>
          ) : null}
          {(failureKind === "offline" || failureKind === "retry") &&
          lastSave ? (
            <button
              className="text-button"
              type="button"
              disabled={pending}
              onClick={() => void save(lastSave.status, lastSave.currentStep)}
            >
              Retry save
            </button>
          ) : null}
          {dirty && (recoveryDraft || cleanupRawSnapshot) ? (
            <div>
              <button
                className="text-button"
                type="button"
                onClick={() => void copyRecovery()}
              >
                Copy recovery text
              </button>
              <button
                className="text-button"
                type="button"
                onClick={exportRecovery}
              >
                Download recovery file
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {localDraftRestored && dirty && !error ? (
        <p className="form-message" role="status">
          A matching recovery copy was restored from this device. It expires
          after seven days unless saved or removed sooner.
        </p>
      ) : null}

      {localPersistence === "failed" ? (
        <div className="form-message form-message--error" role="alert">
          <p>
            {cleanupPending
              ? "The profile was saved to the server, but this browser could not verify or clear its local recovery copy. Retry cleanup or copy/download it before leaving."
              : "This browser could not provide local recovery storage. Your current answers are not saved locally; save to the server before leaving or copy/download them now."}
          </p>
          {recoveryDraft || cleanupRawSnapshot ? (
            <>
              <button
                className="text-button"
                type="button"
                onClick={() => void copyRecovery()}
              >
                Copy recovery text
              </button>
              <button
                className="text-button"
                type="button"
                onClick={exportRecovery}
              >
                Download recovery file
              </button>
            </>
          ) : null}
        </div>
      ) : null}

      {(dirty || cleanupPending) &&
      !error &&
      localPersistence !== "failed" &&
      (recoveryDraft || cleanupRawSnapshot) ? (
        <div
          className="onboarding-recovery-actions"
          aria-label="Recovery copy actions"
        >
          <span>Recovery copy available on this device.</span>
          <button
            className="text-button"
            type="button"
            onClick={() => void copyRecovery()}
          >
            Copy recovery text
          </button>
          <button
            className="text-button"
            type="button"
            onClick={exportRecovery}
          >
            Download recovery file
          </button>
        </div>
      ) : null}

      {recoveryMessage ? <p role="status">{recoveryMessage}</p> : null}

      {cleanupPending && !error ? (
        <div className="onboarding-cleanup-actions">
          <button
            className="button button--outline"
            type="button"
            onClick={retryLocalCleanup}
          >
            Retry local cleanup
          </button>
          {!cleanupAcknowledged ? (
            <button
              className="text-button"
              type="button"
              onClick={acknowledgeRemainingCopy}
            >
              Acknowledge remaining copy
            </button>
          ) : null}
        </div>
      ) : null}

      <p className="clarity-onboarding-safety-note">
        Optional setup. You can skip and update later; these answers never
        control course access.
      </p>

      <div className="onboarding-actions clarity-onboarding-actions">
        {step > 1 ? (
          <button
            className="button button--outline clarity-onboarding-back"
            type="button"
            disabled={pending}
            onClick={goBack}
          >
            <ArrowLeft size={16} aria-hidden="true" /> Back
          </button>
        ) : (
          <span aria-hidden="true" />
        )}
        <div className="clarity-onboarding-actions__primary">
          <button
            className="button button--ink"
            type="submit"
            disabled={
              pending ||
              (step === 1 && !draft.experienceContext.trim()) ||
              (step === 2 && !draft.learningGoal.trim())
            }
          >
            {pending
              ? "Saving…"
              : step === 3
                ? detailQuestion === "review"
                  ? "Save profile"
                  : "Continue"
                : "Continue"}
            <ArrowRight size={16} aria-hidden="true" />
          </button>
          <button
            className="button button--quiet clarity-onboarding-skip"
            type="button"
            disabled={pending}
            onClick={() => void save("skipped", step)}
          >
            Skip setup
          </button>
        </div>
      </div>
    </form>
  );
}
