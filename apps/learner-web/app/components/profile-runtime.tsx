"use client";

/* Avatar delivery URLs are server-owned and may be private signed origins. */
/* eslint-disable @next/next/no-img-element */

import {
  ArrowRight,
  CheckCircle2,
  GraduationCap,
  PencilLine,
  Settings,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createLearnerApi,
  isAbortError,
  type LearnerApi,
  type MeResponse,
  type OnboardingResponse,
} from "../lib/learner-api";
import {
  getEarliestOfflineReadMetadata,
  offlineReadNotice,
  type OfflineReadMetadata,
} from "../lib/offline-read-cache";
import { ROUTES } from "../lib/routes";
import { userFacingRequestError } from "../lib/user-facing-error";
import {
  unavailableAvatarUploadPort,
  type AvatarPresentation,
  type AvatarUploadPort,
} from "../lib/avatar-upload";
import { AvatarCropDialog } from "./avatar-crop-dialog";
import {
  hasMembershipRole,
  MembershipUnavailable,
} from "./membership-availability";
import { useInvalidateDraftsWithoutMembership } from "./learner-runtime";
import { SignOutControl } from "./sign-out-control";
import { ProfileSkeleton } from "./skeletons";

const defaultApi = createLearnerApi();

function contextLabel(value: string | null): string {
  if (!value) return "Not set";
  const map: Record<string, string> = {
    sales: "Sales Professional",
    founder: "Founder / Entrepreneur",
    customer_success: "Customer Success",
    other: "Other Context",
  };
  return map[value] ?? value;
}

function formatMinutes(value: number | null): string {
  if (value === null) return "Not set";
  return `${value} minutes / week`;
}

export async function loadProfileData(
  api: LearnerApi,
  signal?: AbortSignal,
): Promise<{
  me: MeResponse;
  onboarding: OnboardingResponse | null;
  onboardingError: unknown;
  offlineRead?: OfflineReadMetadata;
}> {
  const me = await api.me({ signal });
  if (!hasMembershipRole(me)) {
    return {
      me,
      onboarding: null,
      onboardingError: null,
      offlineRead: getEarliestOfflineReadMetadata(me) ?? undefined,
    };
  }
  try {
    const onboarding = await api.onboarding({ signal });
    return {
      me,
      onboarding,
      onboardingError: null,
      offlineRead: getEarliestOfflineReadMetadata(me, onboarding) ?? undefined,
    };
  } catch (onboardingError) {
    if (isAbortError(onboardingError)) throw onboardingError;
    return {
      me,
      onboarding: null,
      onboardingError,
      offlineRead: getEarliestOfflineReadMetadata(me) ?? undefined,
    };
  }
}

export function ProfileRuntime({
  api = defaultApi,
  avatarUpload = unavailableAvatarUploadPort,
}: {
  api?: LearnerApi;
  avatarUpload?: AvatarUploadPort;
}) {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [onboarding, setOnboarding] = useState<OnboardingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [onboardingError, setOnboardingError] = useState<unknown>(null);
  const [offlineRead, setOfflineRead] = useState<
    OfflineReadMetadata | undefined
  >();
  const [avatarDialogOpen, setAvatarDialogOpen] = useState(false);
  const [currentAvatar, setCurrentAvatar] =
    useState<AvatarPresentation | null>(null);
  const avatarButtonRef = useRef<HTMLButtonElement>(null);
  const generationRef = useRef(0);
  const mountedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const membershipKnown = me !== null;
  const membershipAvailable = me !== null && hasMembershipRole(me);
  const draftCleanup = useInvalidateDraftsWithoutMembership(
    membershipKnown,
    membershipAvailable,
    me?.person_id ?? null,
  );

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const generation = ++generationRef.current;
    const isCurrent = () =>
      mountedRef.current &&
      generationRef.current === generation &&
      !controller.signal.aborted;

    setLoading(true);
    setError(null);
    setOnboardingError(null);
    setOnboarding(null);
    setOfflineRead(undefined);
    try {
      const result = await loadProfileData(api, controller.signal);
      if (!isCurrent()) return;
      setMe(result.me);
      setCurrentAvatar(result.me.avatar ?? null);
      setOnboarding(result.onboarding);
      setOnboardingError(result.onboardingError);
      setOfflineRead(result.offlineRead);
    } catch (err) {
      if (isAbortError(err) || !isCurrent()) return;
      setError(err);
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    mountedRef.current = true;
    void Promise.resolve().then(() => {
      if (mountedRef.current) void load();
    });
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      abortRef.current?.abort();
    };
  }, [load]);

  if (loading) {
    return <ProfileSkeleton />;
  }

  if (error) {
    const is401 = error instanceof ApiError && error.status === 401;
    const is403 = error instanceof ApiError && error.status === 403;
    return (
      <div className="surface-state surface-state--error-terminal" role="alert">
        <h1>
          {is401
            ? "Sign in to view your profile"
            : is403
              ? "Profile access is unavailable"
              : "Profile could not load"}
        </h1>
        <p>
          {is401
            ? "Your session has expired. Sign in again to view your profile."
            : is403
              ? "This account is not authorized to view this learner profile."
              : userFacingRequestError(
                  error,
                  "The profile service could not be reached. Try again.",
                )}
        </p>
        {is401 ? (
          <Link className="button button--ink" href={ROUTES.sessionExpired}>
            Sign in again
          </Link>
        ) : (
          <button
            className="button button--outline"
            type="button"
            onClick={() => void load()}
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  if (!me || !hasMembershipRole(me)) {
    return <MembershipUnavailable api={api} draftCleanup={draftCleanup} />;
  }

  const displayName = me.display_name || "Learner";
  const initials =
    displayName
      .split(" ")
      .map((p) => p[0])
      .filter(Boolean)
      .slice(0, 2)
      .join("")
      .toUpperCase() || "AC";

  return (
    <div className="profile-view">
      <header className="profile-header" aria-labelledby="profile-heading">
        <div className="learning-breadcrumbs" aria-label="Breadcrumb">
          <Link href={ROUTES.dashboard}>Dashboard</Link>
          <span aria-hidden="true">/</span>
          <span>Profile</span>
        </div>
        <h1 id="profile-heading" className="profile-title">
          Learner Profile
        </h1>
        <p className="profile-subhead">
          Your account identity and learning preferences.
        </p>
      </header>

      {offlineRead ? (
        <div
          className="offline-read-notice"
          id="profile-offline-read"
          role="status"
        >
          {offlineReadNotice(offlineRead)}
        </div>
      ) : null}

      <div className="profile-grid">
        {/* Identity & Account Card */}
        <section
          className="card profile-card"
          aria-labelledby="identity-card-title"
        >
          <div className="profile-card__hero profile-card__hero--avatar">
            <div className="profile-avatar-panel">
              <div className="profile-avatar-large">
                {currentAvatar ? (
                  <img
                    className="profile-avatar-large__image"
                    src={currentAvatar.deliveryUrl}
                    alt={currentAvatar.alt || `${displayName}'s profile photo`}
                  />
                ) : (
                  <span aria-hidden="true">{initials}</span>
                )}
              </div>
              <div className="profile-avatar-panel__copy">
                <span className="profile-avatar-panel__label">
                  Profile photo
                </span>
                <p>
                  Optional. Preview a crop locally before any server-backed
                  profile update.
                </p>
                <button
                  ref={avatarButtonRef}
                  className="button button--small button--outline profile-avatar-panel__button"
                  type="button"
                  onClick={() => setAvatarDialogOpen(true)}
                  aria-haspopup="dialog"
                >
                  <PencilLine size={15} aria-hidden="true" />
                  Change photo
                </button>
              </div>
            </div>
            <div className="profile-hero-copy">
              <h2 id="identity-card-title" className="profile-name">
                {displayName}
              </h2>
              <span className="profile-email">{me.email}</span>
              <div className="profile-badges">
                <span className="card-badge card-badge--success">
                  <CheckCircle2 size={13} aria-hidden="true" />
                  {me.email_verified_at
                    ? "Email verified"
                    : "Email verification pending"}
                </span>
                <span className="card-badge card-badge--primary">
                  {me.membership_role ? "Active Learner" : "Learner"}
                </span>
              </div>
            </div>
          </div>

          <div className="profile-facts-list">
            <div className="fact-row">
              <span className="fact-label">Account Role</span>
              <strong className="fact-value">
                {me.membership_role || "Learner"}
              </strong>
            </div>
            <div className="fact-row">
              <span className="fact-label">Verification Status</span>
              <strong className="fact-value">
                {me.email_verified_at ? "Verified" : "Pending"}
              </strong>
            </div>
          </div>
        </section>

        {/* Learning Preferences Card */}
        <section
          className="card setup-card"
          aria-labelledby="learning-setup-title"
        >
          <div className="card-header">
            <div className="card-header-icon" aria-hidden="true">
              <GraduationCap size={20} />
            </div>
            <div>
              <h2 id="learning-setup-title" className="card-title">
                Learning Preferences
              </h2>
              <p className="card-description">
                Your personalized setup from onboarding.
              </p>
            </div>
          </div>

          {onboardingError ? (
            <div className="alert-box alert-box--error" role="alert">
              <p>
                {userFacingRequestError(
                  onboardingError,
                  "Learning preferences could not be loaded. The rest of your profile is still available.",
                )}
              </p>
              <button
                className="text-button"
                type="button"
                onClick={() => void load()}
              >
                Retry preferences
              </button>
            </div>
          ) : onboarding ? (
            <div className="profile-facts-list">
              <div className="fact-row">
                <span className="fact-label">Experience Context</span>
                <strong className="fact-value">
                  {contextLabel(onboarding.experience_context)}
                </strong>
              </div>
              <div className="fact-row">
                <span className="fact-label">Primary Goal</span>
                <strong className="fact-value">
                  {onboarding.learning_goal || "Not set"}
                </strong>
              </div>
              <div className="fact-row">
                <span className="fact-label">Current Situation</span>
                <strong className="fact-value">
                  {onboarding.practice_situation || "Not set"}
                </strong>
              </div>
              <div className="fact-row">
                <span className="fact-label">Weekly Commitment</span>
                <strong className="fact-value">
                  {formatMinutes(onboarding.weekly_minutes)}
                </strong>
              </div>
            </div>
          ) : (
            <p className="empty-copy">
              No onboarding preferences have been recorded yet.
            </p>
          )}

          <div className="card-footer-actions">
            {offlineRead ? (
              <span
                className="button button--small button--outline is-disabled"
                aria-disabled="true"
              >
                <PencilLine size={16} aria-hidden="true" /> Reconnect to edit
              </span>
            ) : (
              <Link
                className="button button--small button--outline"
                href={`${ROUTES.onboarding}?return=profile`}
              >
                <PencilLine size={16} aria-hidden="true" /> Edit learning setup
              </Link>
            )}
          </div>
        </section>

        {/* Quick Settings & Navigation Card */}
        <section
          className="card quick-actions-card"
          aria-labelledby="account-actions-title"
        >
          <div className="card-header">
            <div className="card-header-icon" aria-hidden="true">
              <Settings size={20} />
            </div>
            <div>
              <h2 id="account-actions-title" className="card-title">
                Account & Appearance
              </h2>
              <p className="card-description">
                Manage theme and account security.
              </p>
            </div>
          </div>

          <div className="quick-actions-links">
            <Link className="quick-action-row" href={ROUTES.settings}>
              <div>
                <strong>Theme & Display Settings</strong>
                <span>Switch between Light, Dark, and System appearance</span>
              </div>
              <ArrowRight size={16} aria-hidden="true" />
            </Link>

            <Link className="quick-action-row" href={ROUTES.progress}>
              <div>
                <strong>Progress</strong>
                <span>View course completion and activity locks</span>
              </div>
              <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </div>

          <div className="card-footer-actions">
            <SignOutControl
              api={api}
              className="button button--small button--outline button--danger"
            />
          </div>
        </section>
      </div>

      {avatarDialogOpen ? (
        <AvatarCropDialog
          displayName={displayName}
          profileRevision={me.profile_revision}
          currentAvatar={currentAvatar}
          adapter={avatarUpload}
          onClose={() => {
            setAvatarDialogOpen(false);
            window.requestAnimationFrame(() =>
              avatarButtonRef.current?.focus(),
            );
          }}
          onSuccess={(avatar) => {
            setCurrentAvatar(avatar);
            setAvatarDialogOpen(false);
            window.requestAnimationFrame(() => avatarButtonRef.current?.focus());
          }}
        />
      ) : null}
    </div>
  );
}
