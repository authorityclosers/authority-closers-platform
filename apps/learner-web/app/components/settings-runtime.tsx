"use client";

import { ArrowRight, CheckCircle2, UserRound } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  ApiError,
  createLearnerApi,
  type LearnerApi,
  type MeResponse,
  type OnboardingResponse,
} from "../lib/learner-api";
import { ROUTES } from "../lib/routes";
import {
  hasMembershipRole,
  MembershipUnavailable,
} from "./membership-availability";
import { SignOutControl } from "./sign-out-control";
import { ThemeControl } from "./theme-control";

const defaultApi = createLearnerApi();

type SettingsState =
  | { status: "loading" }
  | {
      status: "ready";
      me: MeResponse;
      onboarding: OnboardingResponse | null;
    }
  | { status: "error"; error: unknown };

function settingsError(error: unknown): string {
  if (error instanceof ApiError && error.status === 401)
    return "Your session has expired. Sign in again to manage settings.";
  if (error instanceof TypeError)
    return "Settings could not load while the service is unreachable.";
  return "Settings could not load. Try again.";
}

function contextLabel(value: string | null): string {
  return (
    (
      {
        sales: "Sales",
        founder: "Founder",
        customer_success: "Customer success",
        other: "Another context",
      } as Record<string, string>
    )[value ?? ""] ?? "Not set"
  );
}

export function SettingsRuntime({
  api = defaultApi,
}: { api?: LearnerApi } = {}) {
  const [state, setState] = useState<SettingsState>({ status: "loading" });

  function load() {
    setState({ status: "loading" });
    void api
      .me()
      .then(async (me) => ({
        me,
        onboarding: hasMembershipRole(me) ? await api.onboarding() : null,
      }))
      .then(
        ({ me, onboarding }) => setState({ status: "ready", me, onboarding }),
        (error: unknown) => setState({ status: "error", error }),
      );
  }

  useEffect(() => {
    queueMicrotask(load);
    // The API instance is stable for this mounted settings surface.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (state.status === "loading") {
    return (
      <div
        className="settings-loading"
        role="status"
        aria-live="polite"
        aria-busy="true"
      >
        <header className="settings-heading">
          <p className="eyebrow">Profile &amp; settings</p>
          <h1>Settings</h1>
          <p>Preparing your account and learning preferences.</p>
        </header>
        <div className="settings-grid" aria-hidden="true">
          <section className="settings-card settings-card--skeleton">
            <span className="settings-skeleton-line is-short" />
            <span className="settings-skeleton-line is-title" />
            <span className="settings-skeleton-line" />
          </section>
          <section className="settings-card settings-card--skeleton">
            <span className="settings-skeleton-line is-short" />
            <span className="settings-skeleton-line is-title" />
            <span className="settings-skeleton-line" />
          </section>
          <section className="settings-card settings-card--wide settings-card--skeleton">
            <span className="settings-skeleton-line is-short" />
            <span className="settings-skeleton-line is-title" />
            <span className="settings-skeleton-line" />
          </section>
        </div>
        <p className="sr-only">Profile and settings are loading.</p>
      </div>
    );
  }

  if (state.status === "error") {
    const sessionExpired =
      state.error instanceof ApiError && state.error.status === 401;
    return (
      <div className="surface-state" role="alert">
        <h1>Settings could not open.</h1>
        <p>{settingsError(state.error)}</p>
        {sessionExpired ? (
          <Link className="button button--ink" href={ROUTES.sessionExpired}>
            Sign in again
          </Link>
        ) : (
          <button
            className="button button--outline"
            type="button"
            onClick={load}
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  if (!hasMembershipRole(state.me) || !state.onboarding) {
    return <MembershipUnavailable api={api} />;
  }

  const onboardingComplete =
    state.onboarding.status === "completed" ||
    state.onboarding.status === "skipped";

  return (
    <>
      <header className="settings-heading">
        <p className="eyebrow">Profile &amp; settings</p>
        <h1>Make the workspace yours.</h1>
        <p>
          Manage appearance, review your verified account, and update the
          learning context supported by your profile.
        </p>
      </header>
      <div className="settings-grid">
        <section className="settings-card" aria-labelledby="appearance-title">
          <p className="kicker">Appearance</p>
          <h2 id="appearance-title">Theme</h2>
          <p>Use light, dark, or follow this device.</p>
          <ThemeControl />
        </section>
        <section className="settings-card" aria-labelledby="account-title">
          <div className="settings-card__title-row">
            <span className="settings-card__icon" aria-hidden="true">
              <UserRound size={20} />
            </span>
            <div>
              <p className="kicker">Verified account</p>
              <h2 id="account-title">
                {state.me.display_name || "Learner profile"}
              </h2>
            </div>
          </div>
          <dl className="settings-facts">
            <div>
              <dt>Email</dt>
              <dd>{state.me.email}</dd>
            </div>
            <div>
              <dt>Role</dt>
              <dd>{state.me.membership_role}</dd>
            </div>
            <div>
              <dt>Email status</dt>
              <dd>
                <CheckCircle2 size={15} aria-hidden="true" /> Verified
              </dd>
            </div>
          </dl>
          <p className="settings-card__note">
            Name and email are managed by your verified account identity.
          </p>
        </section>
        <section
          className="settings-card settings-card--wide"
          aria-labelledby="learning-profile-title"
        >
          <div className="settings-card__title-row">
            <div>
              <p className="kicker">Learning profile</p>
              <h2 id="learning-profile-title">Your practice context</h2>
            </div>
            <span className="status-pill">
              {onboardingComplete ? "Saved" : "In progress"}
            </span>
          </div>
          <dl className="settings-facts settings-facts--columns">
            <div>
              <dt>Context</dt>
              <dd>{contextLabel(state.onboarding.experience_context)}</dd>
            </div>
            <div>
              <dt>Learning goal</dt>
              <dd>{state.onboarding.learning_goal || "Not set"}</dd>
            </div>
            <div>
              <dt>Current situation</dt>
              <dd>{state.onboarding.practice_situation || "Not set"}</dd>
            </div>
            <div>
              <dt>Weekly time</dt>
              <dd>
                {state.onboarding.weekly_minutes === null
                  ? "Not set"
                  : `${state.onboarding.weekly_minutes} minutes`}
              </dd>
            </div>
          </dl>
          <Link className="button button--outline" href={ROUTES.onboarding}>
            Update learning profile <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </section>
        <section
          className="settings-card settings-card--wide settings-card--session"
          aria-labelledby="session-title"
        >
          <div>
            <p className="kicker">Session</p>
            <h2 id="session-title">Sign out of this browser</h2>
            <p>
              Your saved server progress and drafts remain attached to your
              account.
            </p>
          </div>
          <SignOutControl api={api} />
        </section>
      </div>
    </>
  );
}
