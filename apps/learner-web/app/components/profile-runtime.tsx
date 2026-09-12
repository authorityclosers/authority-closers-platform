"use client";

/* Avatar delivery URLs are server-owned and may be private signed origins. */
/* eslint-disable @next/next/no-img-element */

import {
  ArrowRight,
  BookOpen,
  Camera,
  ChartNoAxesColumnIncreasing,
  CheckCircle2,
  CircleAlert,
  Clock3,
  PencilLine,
  Settings,
  Target,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  createLearnerApi,
  isAbortError,
  type LearnerApi,
  type MeResponse,
  type OnboardingResponse,
  type ProfileAvatarResponse,
} from "../lib/learner-api";
import {
  getEarliestOfflineReadMetadata,
  offlineReadNotice,
  type OfflineReadMetadata,
} from "../lib/offline-read-cache";
import { initialsForDisplayName } from "../lib/profile-identity";
import { ROUTES } from "../lib/routes";
import { userFacingRequestError } from "../lib/user-facing-error";
import {
  createApiAvatarUploadPort,
  type AvatarPresentation,
  type AvatarUploadPort,
} from "../lib/avatar-upload";
import { AvatarCropDialog } from "./avatar-crop-dialog";
import { CommunityIdentityCard } from "./community-identity-card";
import {
  hasMembershipRole,
  MembershipUnavailable,
} from "./membership-availability";
import { useInvalidateDraftsWithoutMembership } from "./learner-runtime";
import { SignOutControl } from "./sign-out-control";
import { ProfileSkeleton } from "./skeletons";
import styles from "./profile-runtime.module.css";

const defaultApi = createLearnerApi();
export const PROFILE_AVATAR_REFRESH_INTERVAL_MS = 4 * 60 * 1000;

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

function avatarPresentationFromResponse(
  response: ProfileAvatarResponse | null,
  displayName: string,
): AvatarPresentation | null {
  const avatar = response?.avatar;
  if (!avatar || avatar.state !== "ready" || !avatar.delivery_url) return null;
  return {
    assetId: avatar.asset_id,
    versionId: avatar.version_id,
    deliveryUrl: avatar.delivery_url,
    alt: `${displayName || "Learner"}'s profile photo`,
    revision: String(avatar.version_number),
  };
}

export async function loadProfileData(
  api: LearnerApi,
  signal?: AbortSignal,
): Promise<{
  me: MeResponse;
  onboarding: OnboardingResponse | null;
  onboardingError: unknown;
  avatar: ProfileAvatarResponse | null;
  avatarError: unknown;
  offlineRead?: OfflineReadMetadata;
}> {
  const me = await api.me({ signal });
  if (!hasMembershipRole(me)) {
    return {
      me,
      onboarding: null,
      onboardingError: null,
      avatar: null,
      avatarError: null,
      offlineRead: getEarliestOfflineReadMetadata(me) ?? undefined,
    };
  }
  let onboarding: OnboardingResponse | null = null;
  let onboardingError: unknown = null;
  try {
    onboarding = await api.onboarding({ signal });
  } catch (error) {
    if (isAbortError(error)) throw error;
    onboardingError = error;
  }

  let avatar: ProfileAvatarResponse | null = null;
  let avatarError: unknown = null;
  // Media delivery is a secondary read: a gated/private storage outage must
  // not hide the authenticated identity or learning preferences.
  if (typeof api.profileAvatar === "function") {
    try {
      avatar = await api.profileAvatar({ signal });
    } catch (error) {
      if (isAbortError(error)) throw error;
      avatarError = error;
    }
  }

  return {
    me,
    onboarding,
    onboardingError,
    avatar,
    avatarError,
    offlineRead:
      getEarliestOfflineReadMetadata(me, onboarding ?? undefined) ?? undefined,
  };
}

export function ProfileRuntime({
  api = defaultApi,
  avatarUpload,
}: {
  api?: LearnerApi;
  avatarUpload?: AvatarUploadPort;
}) {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [onboarding, setOnboarding] = useState<OnboardingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [onboardingError, setOnboardingError] = useState<unknown>(null);
  const [avatarError, setAvatarError] = useState<unknown>(null);
  const [offlineRead, setOfflineRead] = useState<
    OfflineReadMetadata | undefined
  >();
  const [avatarDialogOpen, setAvatarDialogOpen] = useState(false);
  const [currentAvatar, setCurrentAvatar] = useState<AvatarPresentation | null>(
    null,
  );
  const [failedAvatarUrl, setFailedAvatarUrl] = useState<string | null>(null);
  const [avatarSuccessMessage, setAvatarSuccessMessage] = useState<
    string | null
  >(null);
  const avatarButtonRef = useRef<HTMLButtonElement>(null);
  const generationRef = useRef(0);
  const mountedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const avatarRefreshGenerationRef = useRef(0);
  const avatarRefreshAbortRef = useRef<AbortController | null>(null);
  const effectiveAvatarUpload = useMemo(
    () => avatarUpload ?? createApiAvatarUploadPort(api),
    [api, avatarUpload],
  );
  const membershipKnown = me !== null;
  const membershipAvailable = me !== null && hasMembershipRole(me);
  const draftCleanup = useInvalidateDraftsWithoutMembership(
    membershipKnown,
    membershipAvailable,
    me?.person_id ?? null,
  );

  const refreshAvatar = useCallback(async () => {
    avatarRefreshAbortRef.current?.abort();
    const controller = new AbortController();
    avatarRefreshAbortRef.current = controller;
    const generation = ++avatarRefreshGenerationRef.current;

    try {
      const response = await api.profileAvatar({ signal: controller.signal });
      if (
        controller.signal.aborted ||
        !mountedRef.current ||
        generation !== avatarRefreshGenerationRef.current
      ) {
        return;
      }

      const refreshedAvatar = avatarPresentationFromResponse(
        response,
        me?.display_name?.trim() || "Learner",
      );
      if (refreshedAvatar) {
        setCurrentAvatar(refreshedAvatar);
        setFailedAvatarUrl((failedUrl) =>
          failedUrl === refreshedAvatar.deliveryUrl ? failedUrl : null,
        );
        setAvatarError(null);
      } else if (!response.avatar) {
        setCurrentAvatar(null);
        setFailedAvatarUrl(null);
        setAvatarError(null);
      } else if (response.avatar.state === "ready") {
        setAvatarError(new Error("avatar_delivery_unavailable"));
      }
    } catch (error) {
      if (
        isAbortError(error) ||
        controller.signal.aborted ||
        !mountedRef.current ||
        generation !== avatarRefreshGenerationRef.current
      ) {
        return;
      }
      setAvatarError(error);
    } finally {
      if (avatarRefreshAbortRef.current === controller) {
        avatarRefreshAbortRef.current = null;
      }
    }
  }, [api, me]);

  const load = useCallback(async () => {
    avatarRefreshGenerationRef.current += 1;
    avatarRefreshAbortRef.current?.abort();
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
    setAvatarError(null);
    setOfflineRead(undefined);
    try {
      const result = await loadProfileData(api, controller.signal);
      if (!isCurrent()) return;
      setMe(result.me);
      const nextAvatar =
        avatarPresentationFromResponse(
          result.avatar,
          result.me.display_name?.trim() || "Learner",
        ) ??
        result.me.avatar ??
        null;
      setCurrentAvatar(nextAvatar);
      setFailedAvatarUrl((failedUrl) =>
        failedUrl === nextAvatar?.deliveryUrl ? failedUrl : null,
      );
      setOnboarding(result.onboarding);
      setOnboardingError(result.onboardingError);
      setAvatarError(result.avatarError);
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
      avatarRefreshGenerationRef.current += 1;
      avatarRefreshAbortRef.current?.abort();
    };
  }, [load]);

  useEffect(() => {
    if (!me || !hasMembershipRole(me)) return;
    const refreshTimer = window.setInterval(
      () => void refreshAvatar(),
      PROFILE_AVATAR_REFRESH_INTERVAL_MS,
    );
    return () => {
      window.clearInterval(refreshTimer);
      avatarRefreshGenerationRef.current += 1;
      avatarRefreshAbortRef.current?.abort();
    };
  }, [me, refreshAvatar]);

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
  const initials = initialsForDisplayName(displayName);
  const displayAvatar =
    currentAvatar && currentAvatar.deliveryUrl !== failedAvatarUrl
      ? currentAvatar
      : null;

  return (
    <div className={styles.profile}>
      <header className={styles.header} aria-labelledby="profile-heading">
        <nav className={styles.breadcrumbs} aria-label="Breadcrumb">
          <Link href={ROUTES.dashboard}>Dashboard</Link>
          <span aria-hidden="true">/</span>
          <span aria-current="page">Profile</span>
        </nav>
        <h1 id="profile-heading" className={styles.title}>
          Your profile
        </h1>
        <p className={styles.subtitle}>
          Make it yours. Keep your learning in focus.
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

      <section
        className={styles.identity}
        aria-labelledby="identity-card-title"
      >
        <div className={styles.identityRow}>
          <div className={styles.avatar}>
            {displayAvatar ? (
              <img
                className={styles.avatarImage}
                src={displayAvatar.deliveryUrl}
                alt={displayAvatar.alt || `${displayName}'s profile photo`}
                width={96}
                height={96}
                decoding="async"
                onError={() => {
                  setFailedAvatarUrl(displayAvatar.deliveryUrl);
                  void refreshAvatar();
                }}
              />
            ) : (
              <span aria-hidden="true">{initials}</span>
            )}
          </div>
          <div className={styles.identityCopy}>
            <h2 id="identity-card-title" className={styles.name}>
              {displayName}
            </h2>
            <p className={styles.email}>{me.email}</p>
            <span
              className={
                me.email_verified_at ? styles.verified : styles.pending
              }
            >
              {me.email_verified_at ? (
                <CheckCircle2 size={14} aria-hidden="true" />
              ) : (
                <CircleAlert size={14} aria-hidden="true" />
              )}
              {me.email_verified_at
                ? "Email verified"
                : "Email verification pending"}
            </span>
          </div>
          <div className={styles.photoAction}>
            <button
              ref={avatarButtonRef}
              className={styles.outlineButton}
              type="button"
              onClick={() => {
                setAvatarSuccessMessage(null);
                setAvatarDialogOpen(true);
              }}
              aria-haspopup="dialog"
            >
              <Camera size={16} aria-hidden="true" />
              Change photo
            </button>
            <span className={styles.photoHint}>
              Choose a photo, then crop to fit.
            </span>
          </div>
        </div>
        {avatarSuccessMessage ? (
          <div
            className={styles.photoSuccess}
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            <CheckCircle2 size={14} aria-hidden="true" />
            {avatarSuccessMessage}
          </div>
        ) : null}
        {avatarError ? (
          <div className={styles.photoNotice} role="status">
            <span>
              Your photo couldn’t load. Your account details are still here.
            </span>
            <button
              className={styles.inlineButton}
              type="button"
              onClick={() => void refreshAvatar()}
            >
              Retry photo
            </button>
          </div>
        ) : null}
      </section>

      {!offlineRead ? (
        <CommunityIdentityCard
          key={`${me.person_id}:${me.selected_tenant_id ?? "none"}`}
          api={api}
          showLeaderboard={false}
        />
      ) : null}

      <div className={styles.contentGrid}>
        <section
          className={styles.focusCard}
          aria-labelledby="learning-setup-title"
        >
          <header className={styles.sectionHeader}>
            <h2 id="learning-setup-title">Your learning focus</h2>
            <p>Your saved goals and learning routine.</p>
          </header>

          {onboardingError ? (
            <div className={styles.setupError} role="alert">
              <p>
                {userFacingRequestError(
                  onboardingError,
                  "Your learning setup couldn’t load. Please try again.",
                )}
              </p>
              <button
                className={styles.inlineButton}
                type="button"
                onClick={() => void load()}
              >
                Retry learning setup
              </button>
            </div>
          ) : onboarding ? (
            <>
              <div className={styles.goal}>
                <Target size={22} aria-hidden="true" />
                <div>
                  <span className={styles.label}>
                    What you’re working toward
                  </span>
                  <p className={styles.goalText}>
                    {onboarding.learning_goal ||
                      "Choose a goal to give your learning direction."}
                  </p>
                </div>
              </div>
              <dl className={styles.facts}>
                <div>
                  <dt>Experience</dt>
                  <dd>{contextLabel(onboarding.experience_context)}</dd>
                </div>
                <div>
                  <dt>
                    <Clock3 size={14} aria-hidden="true" /> Weekly commitment
                  </dt>
                  <dd>{formatMinutes(onboarding.weekly_minutes)}</dd>
                </div>
                <div className={styles.practice}>
                  <dt>Where you’ll put it into practice</dt>
                  <dd>{onboarding.practice_situation || "Not set"}</dd>
                </div>
              </dl>
            </>
          ) : (
            <p className={styles.emptyCopy}>
              What would you like to get better at? Add a goal and a weekly
              commitment to make this space yours.
            </p>
          )}

          <footer className={styles.setupFooter}>
            {offlineRead ? (
              <span className={styles.disabledButton} aria-disabled="true">
                <PencilLine size={16} aria-hidden="true" /> Reconnect to edit
              </span>
            ) : (
              <Link
                className={styles.outlineButton}
                href={`${ROUTES.onboarding}?return=profile`}
              >
                <PencilLine size={16} aria-hidden="true" /> Edit learning setup
              </Link>
            )}
          </footer>
        </section>

        <nav className={styles.nextSteps} aria-label="Profile shortcuts">
          <h2>Keep moving forward</h2>
          <Link
            className={`${styles.shortcut} ${styles.primaryShortcut}`}
            href={ROUTES.learning}
          >
            <BookOpen size={20} aria-hidden="true" />
            <span>
              <strong>Continue learning</strong>
              <span>Pick up your next activity</span>
            </span>
            <ArrowRight size={18} aria-hidden="true" />
          </Link>
          <Link className={styles.shortcut} href={ROUTES.progress}>
            <ChartNoAxesColumnIncreasing size={20} aria-hidden="true" />
            <span>
              <strong>Your progress</strong>
              <span>See the steps you’ve completed</span>
            </span>
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
          <Link className={styles.shortcut} href={ROUTES.settings}>
            <Settings size={20} aria-hidden="true" />
            <span>
              <strong>Settings</strong>
              <span>Appearance, privacy, and your account</span>
            </span>
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
          <div className={styles.sessionAction}>
            <SignOutControl api={api} className={styles.signOut} />
          </div>
        </nav>
      </div>

      {avatarDialogOpen ? (
        <AvatarCropDialog
          displayName={displayName}
          profileRevision={me.profile_revision}
          currentAvatar={currentAvatar}
          adapter={effectiveAvatarUpload}
          onClose={(result) => {
            setAvatarDialogOpen(false);
            // Aborting the wait cannot roll back a save already accepted by
            // the service. Reconcile the displayed photo through its normal
            // authenticated read, without manufacturing a success notice.
            if (result?.saveMayBePending) void refreshAvatar();
            window.requestAnimationFrame(() =>
              avatarButtonRef.current?.focus(),
            );
          }}
          onSuccess={(avatar) => {
            // A read started before this save must not replace the newer photo.
            avatarRefreshGenerationRef.current += 1;
            avatarRefreshAbortRef.current?.abort();
            setCurrentAvatar(avatar);
            setFailedAvatarUrl(null);
            setAvatarSuccessMessage("Profile photo updated.");
            window.dispatchEvent(
              new CustomEvent("ac-profile-avatar-updated", {
                detail: {
                  deliveryUrl: avatar.deliveryUrl,
                  alt: avatar.alt,
                  revision: avatar.revision,
                },
              }),
            );
            setAvatarDialogOpen(false);
            window.requestAnimationFrame(() =>
              avatarButtonRef.current?.focus(),
            );
          }}
        />
      ) : null}
    </div>
  );
}
