"use client";

import {
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  GraduationCap,
  KeyRound,
  MonitorCog,
  PencilLine,
  RefreshCw,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type RefObject } from "react";

import {
  ApiError,
  createLearnerApi,
  type LearnerApi,
  type MeResponse,
  type OnboardingResponse,
} from "../lib/learner-api";
import { ROUTES } from "../lib/routes";
import { hasMembershipRole } from "./membership-availability";
import {
  availableLocalStorage,
  clearLearnerLocalDraftsForPersonWithLock,
  type LocalDraftStorageResult,
  type OnboardingRecoveryLockManager,
} from "../lib/local-drafts";
import { SignOutControl } from "./sign-out-control";
import { ThemeControl } from "./theme-control";
import styles from "./settings-clarity.module.css";

const defaultApi = createLearnerApi();

export type SettingsResource<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: unknown };

export type SettingsResources = {
  me: SettingsResource<MeResponse>;
  onboarding: SettingsResource<OnboardingResponse>;
};

export type SettingsResourceKey = keyof SettingsResources;

export type SettingsDraftCleanupState =
  | { status: "idle" }
  | { status: "pending" }
  | { status: "success" }
  | { status: "failure"; reason: "quota" | "unavailable" };

export type SettingsDraftCleanupController = {
  start: (personId: string | null | undefined) => void;
  retry: (personId: string | null | undefined) => void;
  invalidate: () => void;
  dispose: () => void;
};

export function createSettingsDraftCleanupController(
  cleanup: (personId: string) => Promise<LocalDraftStorageResult>,
  publish: (state: SettingsDraftCleanupState) => void,
): SettingsDraftCleanupController {
  let mounted = true;
  let generation = 0;
  let pending = false;

  function invalidate() {
    generation += 1;
    pending = false;
  }

  function start(personId: string | null | undefined) {
    if (!mounted || pending) return;
    const currentGeneration = ++generation;
    pending = true;
    publish({ status: "pending" });
    if (!personId) {
      pending = false;
      publish({ status: "failure", reason: "unavailable" });
      return;
    }
    void cleanup(personId).then(
      (result) => {
        if (!mounted || generation !== currentGeneration) return;
        pending = false;
        publish(
          result.ok
            ? { status: "success" }
            : { status: "failure", reason: result.reason },
        );
      },
      () => {
        if (!mounted || generation !== currentGeneration) return;
        pending = false;
        publish({ status: "failure", reason: "unavailable" });
      },
    );
  }

  return {
    start,
    retry: start,
    invalidate,
    dispose() {
      mounted = false;
      generation += 1;
      pending = false;
    },
  };
}

type SettingsHeadingRef = RefObject<HTMLHeadingElement | null>;

const initialSettingsResources: SettingsResources = {
  me: { status: "loading" },
  onboarding: { status: "loading" },
};

const settingsSections = [
  {
    id: "verified-account",
    label: "Verified account",
    detail: "Your identity and verification",
    icon: UserRound,
  },
  {
    id: "learning-setup",
    label: "Learning setup",
    detail: "Your learning preferences",
    icon: GraduationCap,
  },
  {
    id: "appearance",
    label: "Appearance",
    detail: "Theme and display",
    icon: MonitorCog,
  },
  {
    id: "security-privacy",
    label: "Security & privacy",
    detail: "Account and privacy",
    icon: ShieldCheck,
  },
  {
    id: "session",
    label: "Session",
    detail: "Sign out",
    icon: KeyRound,
  },
] as const;

function isSessionExpired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export async function clearUnavailableMembershipLearnerLocalDrafts(
  owner: {
    readonly localStorage: Storage;
  },
  personId: string | null | undefined,
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<LocalDraftStorageResult> {
  if (!personId) return { ok: false, reason: "unavailable" };
  return clearLearnerLocalDraftsForPersonWithLock(
    availableLocalStorage(owner),
    personId,
    lockManager,
  );
}

export function settingsResourceErrorMessage(
  error: unknown,
  resource: "identity" | "learning setup",
): string {
  if (isSessionExpired(error)) {
    return `Your session has expired. Sign in again to view ${resource}.`;
  }
  if (error instanceof TypeError) {
    return `We couldn't reach the service. Your other settings remain available while ${resource} is unavailable.`;
  }
  return `We couldn't load ${resource}. Your other settings remain available; try this section again.`;
}

function contextLabel(value: string | null): string {
  if (!value) return "Not set";
  return (
    (
      {
        sales: "Sales",
        founder: "Founder",
        customer_success: "Customer success",
        other: "Another context",
      } as Record<string, string>
    )[value] ?? value
  );
}

function formatWeeklyTime(value: number | null): string {
  if (value === null) return "Not set";
  return `${value} minute${value === 1 ? "" : "s"}`;
}

function SectionIcon({ icon: Icon }: { icon: typeof UserRound }) {
  return (
    <span className={styles.cardIcon} aria-hidden="true">
      <Icon size={20} strokeWidth={1.8} />
    </span>
  );
}

function SectionHeader({
  id,
  icon,
  title,
  description,
  headingRef,
}: {
  id: string;
  icon: typeof UserRound;
  title: string;
  description: string;
  headingRef?: SettingsHeadingRef;
}) {
  return (
    <div className={styles.cardHeader}>
      <SectionIcon icon={icon} />
      <div className={styles.cardHeaderCopy}>
        <h2 ref={headingRef} id={id} tabIndex={-1}>
          {title}
        </h2>
        <p>{description}</p>
      </div>
    </div>
  );
}

function Facts({
  facts,
  className = "",
}: {
  facts: Array<{ label: string; value: React.ReactNode }>;
  className?: string;
}) {
  return (
    <dl className={`${styles.facts} ${className}`}>
      {facts.map((fact) => (
        <div key={fact.label}>
          <dt>{fact.label}</dt>
          <dd>{fact.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ResourceErrorCard({
  title,
  headingId,
  resource,
  error,
  onRetry,
  headingRef,
}: {
  title: string;
  headingId: string;
  resource: "identity" | "learning setup";
  error: unknown;
  onRetry: () => void;
  headingRef?: SettingsHeadingRef;
}) {
  return (
    <div className={styles.resourceError} role="alert">
      <CircleAlert size={20} aria-hidden="true" />
      <div className={styles.resourceErrorCopy}>
        <h2 ref={headingRef} id={headingId} tabIndex={-1}>
          {title} unavailable
        </h2>
        <p>{settingsResourceErrorMessage(error, resource)}</p>
        {isSessionExpired(error) ? (
          <Link className={styles.actionLink} href={ROUTES.sessionExpired}>
            Sign in again <ArrowRight size={15} aria-hidden="true" />
          </Link>
        ) : (
          <button
            className={styles.inlineAction}
            type="button"
            onClick={onRetry}
          >
            <RefreshCw size={15} aria-hidden="true" />
            Retry {resource}
          </button>
        )}
      </div>
    </div>
  );
}

function IdentityCard({
  resource,
  onRetry,
  headingRef,
}: {
  resource: SettingsResource<MeResponse>;
  onRetry: () => void;
  headingRef?: SettingsHeadingRef;
}) {
  return (
    <section
      className={styles.card}
      id="verified-account"
      aria-labelledby="verified-account-title"
    >
      {resource.status === "loading" ? (
        <div
          className={styles.cardLoading}
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          <SectionHeader
            id="verified-account-title"
            icon={UserRound}
            title="Verified account"
            description="Your identity and verification details."
            headingRef={headingRef}
          />
          <span className={styles.srOnly}>Verified account loading</span>
          <div className={styles.loadingFacts} aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </div>
        </div>
      ) : resource.status === "error" ? (
        <ResourceErrorCard
          title="Verified account"
          headingId="verified-account-title"
          resource="identity"
          error={resource.error}
          onRetry={onRetry}
          headingRef={headingRef}
        />
      ) : (
        <>
          <SectionHeader
            id="verified-account-title"
            icon={UserRound}
            title="Verified account"
            description="Your identity and verification details."
            headingRef={headingRef}
          />
          <Facts
            facts={[
              {
                label: "Name",
                value: resource.data.display_name || "Learner profile",
              },
              { label: "Email", value: resource.data.email },
              {
                label: "Role",
                value: resource.data.membership_role || "Not set",
              },
              {
                label: "Verification status",
                value: (
                  <span className={styles.verifiedValue}>
                    <CheckCircle2 size={15} aria-hidden="true" />
                    {resource.data.email_verified_at
                      ? "Verified"
                      : "Not verified"}
                  </span>
                ),
              },
            ]}
          />
        </>
      )}
    </section>
  );
}

function LearningSetupCard({
  resource,
  onRetry,
  headingRef,
}: {
  resource: SettingsResource<OnboardingResponse>;
  onRetry: () => void;
  headingRef?: SettingsHeadingRef;
}) {
  return (
    <section
      className={`${styles.card} ${styles.cardWide}`}
      id="learning-setup"
      aria-labelledby="learning-setup-title"
    >
      {resource.status === "loading" ? (
        <div
          className={styles.cardLoading}
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          <SectionHeader
            id="learning-setup-title"
            icon={GraduationCap}
            title="Learning setup"
            description="Your learning preferences."
            headingRef={headingRef}
          />
          <span className={styles.srOnly}>Learning setup loading</span>
          <div className={styles.loadingFacts} aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </div>
        </div>
      ) : resource.status === "error" ? (
        <ResourceErrorCard
          title="Learning setup"
          headingId="learning-setup-title"
          resource="learning setup"
          error={resource.error}
          onRetry={onRetry}
          headingRef={headingRef}
        />
      ) : (
        <>
          <SectionHeader
            id="learning-setup-title"
            icon={GraduationCap}
            title="Learning setup"
            description="Your learning preferences."
            headingRef={headingRef}
          />
          <Facts
            className={styles.learningFacts}
            facts={[
              {
                label: "Context",
                value: contextLabel(resource.data.experience_context),
              },
              {
                label: "Learning goal",
                value: resource.data.learning_goal || "Not set",
              },
              {
                label: "Situation (optional)",
                value: resource.data.practice_situation || "Not set",
              },
              {
                label: "Weekly time (optional)",
                value: formatWeeklyTime(resource.data.weekly_minutes),
              },
            ]}
          />
          <Link
            className={styles.outlineAction}
            href={ROUTES.onboarding + "?return=settings"}
          >
            <PencilLine size={17} aria-hidden="true" />
            Edit learning setup
          </Link>
        </>
      )}
    </section>
  );
}

function LearningSetupGate({
  headingRef,
}: {
  headingRef?: SettingsHeadingRef;
}) {
  return (
    <section
      className={styles.card + " " + styles.cardWide}
      id="learning-setup"
      aria-labelledby="learning-setup-title"
    >
      <SectionHeader
        id="learning-setup-title"
        icon={GraduationCap}
        title="Learning setup"
        description="Your learning preferences."
        headingRef={headingRef}
      />
      <p className={styles.gatedCopy}>
        Learning setup will appear after learner access is confirmed.
      </p>
    </section>
  );
}

function ReauthenticationBoundary({
  headingRef,
}: {
  headingRef?: SettingsHeadingRef;
}) {
  return (
    <section
      className={styles.accessBoundary}
      role="alert"
      aria-labelledby="settings-reauthentication-title"
    >
      <h1 ref={headingRef} id="settings-reauthentication-title" tabIndex={-1}>
        Sign in to continue.
      </h1>
      <p>Your session has expired. Sign in again to view your settings.</p>
      <Link className={styles.outlineAction} href={ROUTES.sessionExpired}>
        Sign in again <ArrowRight size={15} aria-hidden="true" />
      </Link>
    </section>
  );
}

function MembershipBoundary({
  api,
  cleanup,
  onRetryCleanup,
  headingRef,
}: {
  api: LearnerApi;
  cleanup: SettingsDraftCleanupState;
  onRetryCleanup?: () => void;
  headingRef?: SettingsHeadingRef;
}) {
  return (
    <section
      className={styles.accessBoundary}
      role="alert"
      aria-labelledby="settings-membership-title"
    >
      <h1 ref={headingRef} id="settings-membership-title" tabIndex={-1}>
        Learner membership is unavailable.
      </h1>
      <p>
        This signed-in identity does not have the exact learner membership role.
        Protected learner content remains unavailable until learner access is
        authorized.
      </p>
      {cleanup.status === "pending" ? (
        <p className={styles.gatedCopy} role="status">
          Removing this person&apos;s local recovery copies…
        </p>
      ) : null}
      {cleanup.status === "failure" ? (
        <div className={styles.cleanupFailure}>
          <p>
            We could not remove this browser&apos;s bounded learner recovery
            copies.{" "}
            {cleanup.reason === "quota"
              ? "The browser reported a storage quota problem."
              : "This browser did not make local storage available."}{" "}
            Retry cleanup before another person uses this device.
          </p>
          {onRetryCleanup ? (
            <button
              className={styles.cleanupRetry}
              type="button"
              onClick={onRetryCleanup}
            >
              Retry cleanup
            </button>
          ) : null}
        </div>
      ) : null}
      <SignOutControl api={api} className={styles.signOutButton} />
    </section>
  );
}

function AppearanceCard() {
  return (
    <section
      className={`${styles.card} ${styles.cardWide}`}
      id="appearance"
      aria-labelledby="appearance-title"
    >
      <SectionHeader
        id="appearance-title"
        icon={MonitorCog}
        title="Appearance"
        description="Choose how Authority Closers LMS looks."
      />
      <ThemeControl />
    </section>
  );
}

function SecurityPrivacyCard() {
  const links = [
    { href: ROUTES.forgotPassword, label: "Password recovery" },
    { href: ROUTES.terms, label: "Terms" },
    { href: ROUTES.privacy, label: "Privacy" },
  ];

  return (
    <section
      className={`${styles.card} ${styles.cardWide}`}
      id="security-privacy"
      aria-labelledby="security-privacy-title"
    >
      <SectionHeader
        id="security-privacy-title"
        icon={ShieldCheck}
        title="Security & privacy"
        description="Review important policies and account support."
      />
      <nav
        className={styles.policyLinks}
        aria-label="Security and privacy links"
      >
        {links.map((link) => (
          <Link key={link.href} href={link.href}>
            <span>{link.label}</span>
            <ChevronRight size={17} aria-hidden="true" />
          </Link>
        ))}
      </nav>
    </section>
  );
}

function SessionCard({ api }: { api: LearnerApi }) {
  return (
    <section
      className={`${styles.card} ${styles.cardWide} ${styles.sessionCard}`}
      id="session"
      aria-labelledby="session-title"
    >
      <div className={styles.sessionCopy}>
        <SectionHeader
          id="session-title"
          icon={KeyRound}
          title="Session"
          description="Sign out of your account on this device."
        />
      </div>
      <SignOutControl api={api} className={styles.signOutButton} />
    </section>
  );
}

export function SettingsView({
  resources,
  api = defaultApi,
  onRetry,
  draftCleanup = { status: "idle" },
  onRetryCleanup,
  focusTargets,
}: {
  resources: SettingsResources;
  api?: LearnerApi;
  onRetry: (resource: SettingsResourceKey) => void;
  draftCleanup?: SettingsDraftCleanupState;
  onRetryCleanup?: () => void;
  focusTargets?: {
    identity?: SettingsHeadingRef;
    learningSetup?: SettingsHeadingRef;
    routeEntry?: SettingsHeadingRef;
  };
}) {
  if (resources.me.status === "error" && isSessionExpired(resources.me.error)) {
    return (
      <ReauthenticationBoundary
        headingRef={focusTargets?.routeEntry ?? focusTargets?.identity}
      />
    );
  }

  if (
    resources.me.status === "ready" &&
    !hasMembershipRole(resources.me.data)
  ) {
    return (
      <MembershipBoundary
        api={api}
        cleanup={draftCleanup}
        onRetryCleanup={onRetryCleanup}
        headingRef={focusTargets?.routeEntry ?? focusTargets?.identity}
      />
    );
  }

  const learnerAccessConfirmed =
    resources.me.status === "ready" && hasMembershipRole(resources.me.data);

  return (
    <div className={styles.settingsLedger}>
      <aside className={styles.settingsIndex} aria-label="Settings sections">
        <p className={styles.indexEyebrow}>Account control surface</p>
        <h1
          className={styles.routeEntryHeading}
          ref={focusTargets?.routeEntry}
          id="settings-title"
          tabIndex={-1}
        >
          Settings
        </h1>
        <p className={styles.indexDescription}>
          Manage your account, learning setup, and preferences.
        </p>
        <nav className={styles.indexNav}>
          {settingsSections.map((section) => {
            const Icon = section.icon;
            return (
              <a
                className={styles.indexLink}
                href={`#${section.id}`}
                key={section.id}
              >
                <Icon size={20} strokeWidth={1.8} aria-hidden="true" />
                <span>
                  <strong>{section.label}</strong>
                  <small>{section.detail}</small>
                </span>
              </a>
            );
          })}
        </nav>
      </aside>

      <div className={styles.settingsContent}>
        <IdentityCard
          resource={resources.me}
          onRetry={() => onRetry("me")}
          headingRef={focusTargets?.identity}
        />
        {learnerAccessConfirmed ? (
          <LearningSetupCard
            resource={resources.onboarding}
            onRetry={() => onRetry("onboarding")}
            headingRef={focusTargets?.learningSetup}
          />
        ) : (
          <LearningSetupGate headingRef={focusTargets?.learningSetup} />
        )}
        <AppearanceCard />
        <SecurityPrivacyCard />
        <SessionCard api={api} />
      </div>
    </div>
  );
}

export function startSettingsResourceLoad(
  api: Pick<LearnerApi, "me" | "onboarding">,
  onUpdate: <K extends SettingsResourceKey>(
    resource: K,
    result: SettingsResources[K],
  ) => void,
): () => void {
  let active = true;

  function publish<K extends SettingsResourceKey>(
    resource: K,
    result: SettingsResources[K],
  ) {
    if (active) onUpdate(resource, result);
  }

  function loadOnboarding() {
    let request: Promise<OnboardingResponse>;
    try {
      request = api.onboarding();
    } catch (error) {
      publish("onboarding", { status: "error", error });
      return;
    }
    void Promise.resolve(request).then(
      (data) => publish("onboarding", { status: "ready", data }),
      (error: unknown) => publish("onboarding", { status: "error", error }),
    );
  }

  let identityRequest: Promise<MeResponse>;
  try {
    identityRequest = api.me();
  } catch (error) {
    publish("me", { status: "error", error });
    return () => {
      active = false;
    };
  }
  void Promise.resolve(identityRequest).then(
    (data) => {
      publish("me", { status: "ready", data });
      if (hasMembershipRole(data)) loadOnboarding();
    },
    (error: unknown) => publish("me", { status: "error", error }),
  );

  return () => {
    active = false;
  };
}

export function SettingsRuntime({
  api = defaultApi,
}: { api?: LearnerApi } = {}) {
  const [resources, setResources] = useState<SettingsResources>(
    initialSettingsResources,
  );
  const [draftCleanup, setDraftCleanup] = useState<SettingsDraftCleanupState>({
    status: "idle",
  });
  const requestGeneration = useRef(0);
  const activeLoadCleanup = useRef<(() => void) | null>(null);
  const draftCleanupController = useRef<SettingsDraftCleanupController | null>(
    null,
  );
  const pendingFocus = useRef<SettingsResourceKey | null>(null);
  const identityHeadingRef = useRef<HTMLHeadingElement>(null);
  const learningSetupHeadingRef = useRef<HTMLHeadingElement>(null);
  const routeEntryHeadingRef = useRef<HTMLHeadingElement>(null);
  const previousStatuses = useRef({
    me: initialSettingsResources.me.status,
    onboarding: initialSettingsResources.onboarding.status,
  });

  useEffect(() => {
    if (document.activeElement === document.body) {
      routeEntryHeadingRef.current?.focus();
    }
  }, []);

  useEffect(() => {
    const controller = createSettingsDraftCleanupController(
      (personId) =>
        typeof window === "undefined"
          ? Promise.resolve({
              ok: false as const,
              reason: "unavailable" as const,
            })
          : clearUnavailableMembershipLearnerLocalDrafts(window, personId),
      setDraftCleanup,
    );
    draftCleanupController.current = controller;
    return () => {
      controller.dispose();
      if (draftCleanupController.current === controller) {
        draftCleanupController.current = null;
      }
    };
  }, []);

  useEffect(() => {
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    draftCleanupController.current?.invalidate();
    setResources(initialSettingsResources);
    setDraftCleanup({ status: "idle" });
    const stop = startSettingsResourceLoad(api, (resource, result) => {
      if (requestGeneration.current !== generation) return;
      setResources((current) => ({ ...current, [resource]: result }));
    });
    activeLoadCleanup.current = stop;
    return () => {
      stop();
      if (activeLoadCleanup.current === stop) activeLoadCleanup.current = null;
      requestGeneration.current += 1;
    };
  }, [api]);

  const cleanupPersonId =
    resources.me.status === "ready" ? resources.me.data.person_id : null;
  const cleanupMembershipAvailable =
    resources.me.status === "ready" && hasMembershipRole(resources.me.data);

  useEffect(() => {
    draftCleanupController.current?.invalidate();
    if (resources.me.status !== "ready" || cleanupMembershipAvailable) {
      setDraftCleanup({ status: "idle" });
      return;
    }
    draftCleanupController.current?.start(cleanupPersonId);
  }, [cleanupMembershipAvailable, cleanupPersonId, resources.me.status]);

  useEffect(() => {
    const currentStatuses = {
      me: resources.me.status,
      onboarding: resources.onboarding.status,
    };
    const resource = pendingFocus.current;
    if (
      resource &&
      previousStatuses.current[resource] !== currentStatuses[resource]
    ) {
      const headingRef =
        resource === "me" ? identityHeadingRef : learningSetupHeadingRef;
      headingRef.current?.focus();
      if (
        currentStatuses[resource] === "ready" ||
        currentStatuses[resource] === "error"
      ) {
        pendingFocus.current = null;
      }
    }
    previousStatuses.current = currentStatuses;
  }, [resources.me.status, resources.onboarding.status]);

  function loadOnboardingForGeneration(generation: number) {
    let request: Promise<OnboardingResponse>;
    try {
      request = api.onboarding();
    } catch (error) {
      if (requestGeneration.current === generation) {
        setResources((current) => ({
          ...current,
          onboarding: { status: "error", error },
        }));
      }
      return;
    }
    void Promise.resolve(request).then(
      (data) => {
        if (requestGeneration.current !== generation) return;
        setResources((current) => ({
          ...current,
          onboarding: { status: "ready", data },
        }));
      },
      (error: unknown) => {
        if (requestGeneration.current !== generation) return;
        setResources((current) => ({
          ...current,
          onboarding: { status: "error", error },
        }));
      },
    );
  }

  function retry(resource: SettingsResourceKey) {
    pendingFocus.current = resource;
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    activeLoadCleanup.current?.();
    activeLoadCleanup.current = null;
    setResources((current) => ({
      ...current,
      ...(resource === "me"
        ? {
            me: { status: "loading" as const },
            onboarding: { status: "loading" as const },
          }
        : { [resource]: { status: "loading" as const } }),
    }));

    if (resource === "onboarding") {
      loadOnboardingForGeneration(generation);
      return;
    }

    let request: Promise<MeResponse>;
    try {
      request = api.me();
    } catch (error) {
      setResources((current) => ({
        ...current,
        me: { status: "error", error },
      }));
      return;
    }
    void Promise.resolve(request).then(
      (data) => {
        if (requestGeneration.current !== generation) return;
        setResources((current) => ({
          ...current,
          me: { status: "ready", data },
          onboarding: { status: "loading" },
        }));
        if (hasMembershipRole(data)) {
          loadOnboardingForGeneration(generation);
        }
      },
      (error: unknown) => {
        if (requestGeneration.current !== generation) return;
        setResources((current) => ({
          ...current,
          me: { status: "error", error },
        }));
      },
    );
  }

  function retryDraftCleanup() {
    draftCleanupController.current?.retry(cleanupPersonId);
  }

  return (
    <SettingsView
      resources={resources}
      api={api}
      onRetry={retry}
      draftCleanup={draftCleanup}
      onRetryCleanup={retryDraftCleanup}
      focusTargets={{
        identity: identityHeadingRef,
        learningSetup: learningSetupHeadingRef,
        routeEntry: routeEntryHeadingRef,
      }}
    />
  );
}
