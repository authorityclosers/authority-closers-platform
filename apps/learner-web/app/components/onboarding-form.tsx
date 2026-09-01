"use client";

import { ArrowLeft, ArrowRight, CheckCircle2, UserRound } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  ApiError,
  createLearnerApi,
  type LearnerApi,
  type OnboardingResponse,
} from "../lib/learner-api";
import {
  clearOnboardingLocalDraft,
  localDraftMatchesServer,
  mutationFailureKind,
  onboardingRecoveryText,
  onboardingServerFingerprint,
  readOnboardingLocalDraft,
  registerBeforeUnloadGuard,
  writeOnboardingLocalDraft,
  type MutationFailureKind,
  type OnboardingDraftEnvelope,
  type OnboardingDraftScope,
  type OnboardingLocalDraft,
} from "../lib/local-drafts";
import { ROUTES } from "../lib/routes";
import { userFacingRequestError } from "../lib/user-facing-error";

const contexts = [
  { value: "sales", label: "Sales" },
  { value: "founder", label: "Founder" },
  { value: "customer_success", label: "Customer success" },
  { value: "other", label: "Another context" },
] as const;

type Draft = OnboardingLocalDraft;

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

export function OnboardingForm({
  api = defaultApi,
}: { api?: LearnerApi } = {}) {
  const [profile, setProfile] = useState<OnboardingResponse | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [step, setStep] = useState(1);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [finished, setFinished] = useState(false);
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
  const [localPersistence, setLocalPersistence] = useState<
    "idle" | "saved" | "failed"
  >("idle");
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null);
  const dirty = profile !== null && !draftsMatch(draft, draftFrom(profile));

  function online(): boolean {
    return typeof navigator === "undefined" ? true : navigator.onLine;
  }

  function load() {
    setPending(true);
    setError(null);
    setSessionExpired(false);
    setFailureKind(null);
    void api.onboarding().then(
      (loaded) => {
        const serverDraft = draftFrom(loaded);
        const scope = onboardingScope(loaded.person_id);
        const localDraft = readOnboardingLocalDraft(window.localStorage, scope);
        setProfile(loaded);
        setDraft(serverDraft);
        setStaleLocalDraft(null);
        setLocalDraftRestored(false);
        if (localDraft.status === "ready") {
          if (
            localDraftMatchesServer(
              localDraft.envelope,
              loaded.revision,
              onboardingServerFingerprint(serverDraft),
            )
          ) {
            setDraft(localDraft.envelope.draft);
            setLocalDraftRestored(true);
            setLocalPersistence("saved");
          } else {
            setStaleLocalDraft(localDraft.envelope);
          }
        } else if (localDraft.status === "unavailable") {
          setLocalPersistence("failed");
        } else {
          setLocalPersistence("idle");
        }
        setStep(Math.max(1, Math.min(3, loaded.current_step)));
        setFinished(
          loaded.status === "completed" || loaded.status === "skipped",
        );
        setPending(false);
      },
      (requestError: unknown) => {
        setError(failureMessage(requestError, online(), false));
        setSessionExpired(isOnboardingSessionExpired(requestError));
        setFailureKind(mutationFailureKind(requestError, online()));
        setPending(false);
      },
    );
  }

  useEffect(() => {
    queueMicrotask(load);
    // The API instance is stable for one mounted form and its retries.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!profile) return;
    if (staleLocalDraft) return;
    let active = true;
    const scope = onboardingScope(profile.person_id);
    if (dirty) {
      const result = writeOnboardingLocalDraft(window.localStorage, {
        scope,
        draft,
        baseRevision: profile.revision,
        serverFingerprint: onboardingServerFingerprint(draftFrom(profile)),
      });
      queueMicrotask(() => {
        if (active) setLocalPersistence(result.ok ? "saved" : "failed");
      });
    } else {
      clearOnboardingLocalDraft(window.localStorage, scope);
      queueMicrotask(() => {
        if (active) setLocalPersistence("idle");
      });
    }
    return () => {
      active = false;
    };
  }, [dirty, draft, profile, staleLocalDraft]);

  useEffect(() => registerBeforeUnloadGuard(window, dirty), [dirty]);

  async function save(
    status: "in_progress" | "completed" | "skipped",
    currentStep: number,
  ) {
    if (!profile) return;
    setLastSave({ status, currentStep });
    setPending(true);
    setError(null);
    setSessionExpired(false);
    setFailureKind(null);
    let locallyStored = localPersistence === "saved";
    if (dirty) {
      const result = writeOnboardingLocalDraft(window.localStorage, {
        scope: onboardingScope(profile.person_id),
        draft,
        baseRevision: profile.revision,
        serverFingerprint: onboardingServerFingerprint(draftFrom(profile)),
      });
      locallyStored = result.ok;
      setLocalPersistence(result.ok ? "saved" : "failed");
    }
    try {
      const weeklyMinutes =
        draft.weeklyMinutes.trim() === ""
          ? null
          : Number.parseInt(draft.weeklyMinutes, 10);
      const saved = await api.saveOnboarding(
        {
          experienceContext: draft.experienceContext || null,
          learningGoal: draft.learningGoal || null,
          practiceSituation: draft.practiceSituation || null,
          weeklyMinutes,
          status,
          currentStep,
        },
        profile.revision,
      );
      setProfile(saved);
      setDraft(draftFrom(saved));
      setStep(currentStep);
      setFinished(status === "completed" || status === "skipped");
      clearOnboardingLocalDraft(
        window.localStorage,
        onboardingScope(saved.person_id),
      );
      setLocalDraftRestored(false);
      setStaleLocalDraft(null);
      setLocalPersistence("idle");
      setLastSave(null);
    } catch (requestError) {
      setError(failureMessage(requestError, online(), locallyStored));
      setSessionExpired(isOnboardingSessionExpired(requestError));
      setFailureKind(mutationFailureKind(requestError, online()));
    } finally {
      setPending(false);
    }
  }

  function keepServerDraft() {
    if (!profile) return;
    clearOnboardingLocalDraft(
      window.localStorage,
      onboardingScope(profile.person_id),
    );
    setDraft(draftFrom(profile));
    setStaleLocalDraft(null);
    setLocalDraftRestored(false);
    setLocalPersistence("idle");
    setRecoveryMessage("The local recovery copy was discarded.");
  }

  function mergeLocalDraftIntoEditor() {
    if (!staleLocalDraft) return;
    setDraft(staleLocalDraft.draft);
    setStaleLocalDraft(null);
    setLocalDraftRestored(true);
    setRecoveryMessage(
      "The local recovery copy is now in the editor. Review it before saving against the latest server revision.",
    );
  }

  const recoveryDraft = staleLocalDraft?.draft ?? (dirty ? draft : null);

  async function copyRecovery() {
    if (!recoveryDraft) return;
    const copied = await copyRecoveryText(
      onboardingRecoveryText(recoveryDraft),
    );
    setRecoveryMessage(
      copied
        ? "Recovery copy copied to the clipboard."
        : "Clipboard access was blocked. Download the recovery file instead.",
    );
  }

  function exportRecovery() {
    if (!recoveryDraft) return;
    downloadRecoveryText(
      onboardingRecoveryText(recoveryDraft),
      "authority-closers-profile-recovery.txt",
    );
    setRecoveryMessage("Recovery file downloaded on this device.");
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
      <div className="onboarding-form clarity-onboarding-form" role="alert">
        <p className="form-message form-message--error">{error}</p>
        <button className="button button--outline button--full" onClick={load}>
          Retry profile
        </button>
        {sessionExpired ? (
          <Link className="text-link" href={ROUTES.sessionExpired}>
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
          <h2 id="profile-draft-conflict-title">
            A newer profile exists on the server.
          </h2>
          <p>
            This device has answers based on revision{" "}
            {staleLocalDraft.baseRevision}, while the server is now at revision{" "}
            {profile.revision}. Nothing has been placed into the editor. Compare
            the copies and choose what to keep.
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
            onClick={keepServerDraft}
          >
            Keep server and discard local
          </button>
          <button
            className="button button--ink"
            type="button"
            onClick={mergeLocalDraftIntoEditor}
          >
            Merge local copy into editor
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
      <div
        className="onboarding-form clarity-onboarding-form onboarding-complete"
        role="status"
      >
        <CheckCircle2 size={34} aria-hidden="true" />
        <div>
          <p className="eyebrow">
            <span aria-hidden="true" /> Profile saved
          </p>
          <h2>
            {profile.status === "skipped"
              ? "Continue without personalization."
              : "Your starting context is ready."}
          </h2>
        </div>
        <Link
          className="button button--ink button--full"
          href={ROUTES.learnerHome}
        >
          Open learner home <ArrowRight size={17} aria-hidden="true" />
        </Link>
        <button
          className="button button--quiet button--full"
          type="button"
          onClick={() => {
            setFinished(false);
            setStep(profile.current_step);
          }}
        >
          Edit profile
        </button>
      </div>
    );
  }

  return (
    <form
      className="onboarding-form clarity-onboarding-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (step < 3) {
          void save("in_progress", step + 1);
        } else {
          void save("completed", 3);
        }
      }}
    >
      <div
        className="onboarding-progress clarity-onboarding-progress"
        aria-label={`Step ${step} of 3`}
      >
        <span>0{step}</span>
        <div>
          <i style={{ width: `${(step / 3) * 100}%` }} />
        </div>
        <span>03</span>
      </div>

      {step === 1 ? (
        <>
          <div className="form-step clarity-form-step">
            <span className="form-step__number">01</span>
            <div>
              <h2>Where are you practicing?</h2>
              <p>Choose the context closest to your next real conversation.</p>
            </div>
          </div>
          <fieldset className="choice-fieldset">
            <legend className="sr-only">Experience context</legend>
            <div className="choice-grid">
              {contexts.map((option) => (
                <button
                  className={`choice-card${
                    draft.experienceContext === option.value
                      ? " is-selected"
                      : ""
                  }`}
                  key={option.value}
                  type="button"
                  aria-pressed={draft.experienceContext === option.value}
                  disabled={pending}
                  onClick={() =>
                    setDraft((current) => ({
                      ...current,
                      experienceContext: option.value,
                    }))
                  }
                >
                  <span>{option.label}</span>
                </button>
              ))}
            </div>
          </fieldset>
        </>
      ) : null}

      {step === 2 ? (
        <>
          <div className="form-step clarity-form-step">
            <span className="form-step__number">02</span>
            <div>
              <h2>Name the change you want.</h2>
              <p>Use your own words so you can return to this goal later.</p>
            </div>
          </div>
          <div className="field-group">
            <label htmlFor="learning-goal">Learning goal</label>
            <div className="input-with-icon">
              <UserRound size={17} aria-hidden="true" />
              <input
                id="learning-goal"
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
        </>
      ) : null}

      {step === 3 ? (
        <>
          <div className="form-step clarity-form-step">
            <span className="form-step__number">03</span>
            <div>
              <h2>Make the plan realistic.</h2>
              <p>These details are optional and can be changed later.</p>
            </div>
          </div>
          <div className="field-group">
            <label htmlFor="practice-situation">Current situation</label>
            <textarea
              id="practice-situation"
              value={draft.practiceSituation}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  practiceSituation: event.target.value,
                }))
              }
              maxLength={500}
              disabled={pending}
              placeholder="What conversation is coming up?"
            />
          </div>
          <div className="field-group">
            <label htmlFor="weekly-minutes">Minutes available each week</label>
            <input
              id="weekly-minutes"
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
        </>
      ) : null}

      {error ? (
        <div role="alert">
          <p className="form-message form-message--error">{error}</p>
          {sessionExpired ? (
            <Link className="text-link" href={ROUTES.sessionExpired}>
              Sign in again
            </Link>
          ) : null}
          {failureKind === "conflict" ? (
            <button
              className="text-button"
              type="button"
              disabled={pending}
              onClick={load}
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
          {dirty && localPersistence === "saved" ? (
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

      {dirty && localPersistence === "failed" ? (
        <div className="form-message form-message--error" role="alert">
          <p>
            This browser could not save a recovery copy. Keep this page open or
            copy/download your answers before leaving.
          </p>
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

      <div className="onboarding-actions clarity-onboarding-actions">
        {step > 1 ? (
          <button
            className="button button--quiet"
            type="button"
            disabled={pending}
            onClick={() => setStep((current) => current - 1)}
          >
            <ArrowLeft size={16} aria-hidden="true" /> Back
          </button>
        ) : (
          <button
            className="button button--quiet"
            type="button"
            disabled={pending}
            onClick={() => void save("skipped", step)}
          >
            Skip for now
          </button>
        )}
        <button
          className="button button--ink"
          type="submit"
          disabled={
            pending ||
            (step === 1 && !draft.experienceContext) ||
            (step === 2 && !draft.learningGoal.trim())
          }
        >
          {pending
            ? "Saving…"
            : step === 3
              ? "Finish profile"
              : "Save & continue"}
          <ArrowRight size={16} aria-hidden="true" />
        </button>
      </div>
    </form>
  );
}
