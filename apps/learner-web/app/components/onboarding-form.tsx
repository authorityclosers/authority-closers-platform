"use client";

import { ArrowLeft, ArrowRight, CheckCircle2, UserRound } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  ApiError,
  createLearnerApi,
  type OnboardingResponse,
} from "../lib/learner-api";
import { ROUTES } from "../lib/routes";

const contexts = [
  { value: "sales", label: "Sales" },
  { value: "founder", label: "Founder" },
  { value: "customer_success", label: "Customer success" },
  { value: "other", label: "Another context" },
] as const;

type Draft = {
  experienceContext: string;
  learningGoal: string;
  practiceSituation: string;
  weeklyMinutes: string;
};

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

function failureMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) {
    return "Your session is no longer available. Sign in to continue.";
  }
  if (error instanceof ApiError && error.status === 409) {
    return "This profile changed in another tab. Reload it before saving again.";
  }
  if (error instanceof ApiError) return error.message;
  return navigator.onLine
    ? "The profile did not finish loading. Try again."
    : "You are offline. Reconnect before saving this profile.";
}

export function isOnboardingSessionExpired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export function OnboardingForm() {
  const [profile, setProfile] = useState<OnboardingResponse | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [step, setStep] = useState(1);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [finished, setFinished] = useState(false);

  function load() {
    setPending(true);
    setError(null);
    setSessionExpired(false);
    void createLearnerApi()
      .onboarding()
      .then(
        (loaded) => {
          setProfile(loaded);
          setDraft(draftFrom(loaded));
          setStep(Math.max(1, Math.min(3, loaded.current_step)));
          setFinished(
            loaded.status === "completed" || loaded.status === "skipped",
          );
          setPending(false);
        },
        (requestError: unknown) => {
          setError(failureMessage(requestError));
          setSessionExpired(isOnboardingSessionExpired(requestError));
          setPending(false);
        },
      );
  }

  useEffect(() => {
    queueMicrotask(load);
  }, []);

  async function save(
    status: "in_progress" | "completed" | "skipped",
    currentStep: number,
  ) {
    if (!profile) return;
    setPending(true);
    setError(null);
    setSessionExpired(false);
    try {
      const weeklyMinutes =
        draft.weeklyMinutes.trim() === ""
          ? null
          : Number.parseInt(draft.weeklyMinutes, 10);
      const saved = await createLearnerApi().saveOnboarding(
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
      setStep(currentStep);
      setFinished(status === "completed" || status === "skipped");
    } catch (requestError) {
      setError(failureMessage(requestError));
      setSessionExpired(isOnboardingSessionExpired(requestError));
    } finally {
      setPending(false);
    }
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
        <p>{profile.next_action_reason}</p>
        <Link
          className="button button--ink button--full"
          href={profile.next_action_href}
        >
          Open published programs <ArrowRight size={17} aria-hidden="true" />
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
              <p>
                Use your own words. This does not trigger automated scoring.
              </p>
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
        </div>
      ) : null}

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
