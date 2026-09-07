"use client";

import {
  ArrowRight,
  ArrowLeft,
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
  Info,
  Search,
  X,
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
import {
  getEarliestOfflineReadMetadata,
  offlineReadNotice,
} from "../lib/offline-read-cache";
import { ROUTES } from "../lib/routes";
import {
  getSettingsSectionByAnchor,
  SETTINGS_SECTION_GROUPS,
  SETTINGS_SECTIONS,
  type SettingsSection,
  type SettingsSectionIconName,
  type SettingsSectionId,
} from "../lib/settings-registry";
import { hasMembershipRole } from "./membership-availability";
import {
  availableLocalStorage,
  clearLearnerLocalDraftsForPersonWithLock,
  type LocalDraftStorageResult,
  type OnboardingRecoveryLockManager,
} from "../lib/local-drafts";
import { SignOutControl } from "./sign-out-control";
import { AppearanceControl } from "./theme-control";
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

type SettingsFocusTargets = {
  identity?: SettingsHeadingRef;
  learningSetup?: SettingsHeadingRef;
  routeEntry?: SettingsHeadingRef;
};

const initialSettingsResources: SettingsResources = {
  me: { status: "loading" },
  onboarding: { status: "loading" },
};

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

const settingsSectionIcons: Record<SettingsSectionIconName, typeof UserRound> =
  {
    account: UserRound,
    appearance: MonitorCog,
    learning: GraduationCap,
    security: ShieldCheck,
    session: KeyRound,
  };

function SectionIcon({ icon }: { icon: SettingsSectionIconName }) {
  const Icon = settingsSectionIcons[icon];
  return (
    <span className={styles.cardIcon} aria-hidden="true">
      <Icon size={20} strokeWidth={1.8} />
    </span>
  );
}

function SectionHeader({
  section,
  headingRef,
}: {
  section: SettingsSection;
  headingRef?: SettingsHeadingRef;
}) {
  return (
    <div className={styles.cardHeader}>
      <SectionIcon icon={section.icon} />
      <div className={styles.cardHeaderCopy}>
        <h2 ref={headingRef} id={section.headingId} tabIndex={-1}>
          {section.title}
        </h2>
        <p>{section.description}</p>
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
  section,
  resource,
  onRetry,
  headingRef,
}: {
  section: Extract<SettingsSection, { id: "verified-account" }>;
  resource: SettingsResource<MeResponse>;
  onRetry: () => void;
  headingRef?: SettingsHeadingRef;
}) {
  return (
    <section
      className={styles.card}
      id={section.anchor}
      aria-labelledby={section.headingId}
    >
      {resource.status === "loading" ? (
        <div
          className={styles.cardLoading}
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          <SectionHeader section={section} headingRef={headingRef} />
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
          title={section.title}
          headingId={section.headingId}
          resource="identity"
          error={resource.error}
          onRetry={onRetry}
          headingRef={headingRef}
        />
      ) : (
        <>
          <SectionHeader section={section} headingRef={headingRef} />
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
  section,
  resource,
  onRetry,
  headingRef,
}: {
  section: Extract<SettingsSection, { id: "learning-setup" }>;
  resource: SettingsResource<OnboardingResponse>;
  onRetry: () => void;
  headingRef?: SettingsHeadingRef;
}) {
  return (
    <section
      className={`${styles.card} ${styles.cardWide}`}
      id={section.anchor}
      aria-labelledby={section.headingId}
    >
      {resource.status === "loading" ? (
        <div
          className={styles.cardLoading}
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          <SectionHeader section={section} headingRef={headingRef} />
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
          title={section.title}
          headingId={section.headingId}
          resource="learning setup"
          error={resource.error}
          onRetry={onRetry}
          headingRef={headingRef}
        />
      ) : (
        <>
          <SectionHeader section={section} headingRef={headingRef} />
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
            className={`${styles.outlineAction}${getEarliestOfflineReadMetadata(resource.data) ? " is-disabled" : ""}`}
            href={ROUTES.onboarding + "?return=settings"}
            aria-disabled={
              getEarliestOfflineReadMetadata(resource.data) ? "true" : undefined
            }
            tabIndex={
              getEarliestOfflineReadMetadata(resource.data) ? -1 : undefined
            }
            onClick={(event) => {
              if (getEarliestOfflineReadMetadata(resource.data)) {
                event.preventDefault();
              }
            }}
          >
            <PencilLine size={17} aria-hidden="true" />
            {getEarliestOfflineReadMetadata(resource.data)
              ? "Reconnect to edit learning setup"
              : "Edit learning setup"}
          </Link>
        </>
      )}
    </section>
  );
}

function LearningSetupGate({
  section,
  headingRef,
}: {
  section: Extract<SettingsSection, { id: "learning-setup" }>;
  headingRef?: SettingsHeadingRef;
}) {
  return (
    <section
      className={styles.card + " " + styles.cardWide}
      id={section.anchor}
      aria-labelledby={section.headingId}
    >
      <SectionHeader section={section} headingRef={headingRef} />
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

function AppearanceCard({
  section,
}: {
  section: Extract<SettingsSection, { id: "appearance" }>;
}) {
  return (
    <section
      className={`${styles.card} ${styles.cardWide}`}
      id={section.anchor}
      aria-labelledby={section.headingId}
    >
      <SectionHeader section={section} />
      <div className={styles.localScopeNote} role="note">
        <Info size={17} aria-hidden="true" />
        <div>
          <strong>Browser-local appearance</strong>
          <p>
            Preferences apply to this browser, not your account or learning
            progress.
          </p>
        </div>
      </div>
      <AppearanceControl compact />
    </section>
  );
}

function SecurityPrivacyCard({
  section,
}: {
  section: Extract<SettingsSection, { id: "security-privacy" }>;
}) {
  const links = [
    { href: ROUTES.forgotPassword, label: "Password recovery" },
    { href: ROUTES.terms, label: "Terms" },
    { href: ROUTES.privacy, label: "Privacy" },
  ];

  return (
    <section
      className={`${styles.card} ${styles.cardWide}`}
      id={section.anchor}
      aria-labelledby={section.headingId}
    >
      <SectionHeader section={section} />
      <p className={styles.boundaryNote}>
        Recover your password or review how your information is handled.
      </p>
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

function SessionCard({
  api,
  section,
}: {
  api: LearnerApi;
  section: Extract<SettingsSection, { id: "session" }>;
}) {
  return (
    <section
      className={`${styles.card} ${styles.cardWide} ${styles.sessionCard}`}
      id={section.anchor}
      aria-labelledby={section.headingId}
    >
      <div className={styles.sessionCopy}>
        <SectionHeader section={section} />
      </div>
      <SignOutControl api={api} className={styles.signOutButton} />
    </section>
  );
}

function SettingsSectionCard({
  section,
  resources,
  api,
  onRetry,
  learnerAccessConfirmed,
  focusTargets,
}: {
  section: SettingsSection;
  resources: SettingsResources;
  api: LearnerApi;
  onRetry: (resource: SettingsResourceKey) => void;
  learnerAccessConfirmed: boolean;
  focusTargets?: SettingsFocusTargets;
}) {
  switch (section.id) {
    case "verified-account":
      return (
        <IdentityCard
          section={section}
          resource={resources.me}
          onRetry={() => onRetry("me")}
          headingRef={focusTargets?.identity}
        />
      );
    case "appearance":
      return <AppearanceCard section={section} />;
    case "learning-setup":
      return learnerAccessConfirmed ? (
        <LearningSetupCard
          section={section}
          resource={resources.onboarding}
          onRetry={() => onRetry("onboarding")}
          headingRef={focusTargets?.learningSetup}
        />
      ) : (
        <LearningSetupGate
          section={section}
          headingRef={focusTargets?.learningSetup}
        />
      );
    case "security-privacy":
      return <SecurityPrivacyCard section={section} />;
    case "session":
      return <SessionCard section={section} api={api} />;
  }
}

const settingsKeywords: Record<SettingsSectionId, string> = {
  "verified-account": "name email identity verification account role",
  appearance:
    "theme light dark system color accent density display motion animation preset",
  "learning-setup": "goal context weekly time practice preferences onboarding",
  "security-privacy": "password recovery terms policies privacy security",
  session: "logout log out sign out device session",
};

export function searchSettingsSections(
  query: string,
): readonly SettingsSection[] {
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return SETTINGS_SECTIONS.filter((section) => {
    const text =
      `${section.label} ${section.detail} ${settingsKeywords[section.id]}`.toLocaleLowerCase();
    return words.every((word) => text.includes(word));
  });
}

export function SettingsView({
  resources,
  api = defaultApi,
  onRetry,
  draftCleanup = { status: "idle" },
  onRetryCleanup,
  focusTargets,
  initialSection = null,
}: {
  resources: SettingsResources;
  api?: LearnerApi;
  onRetry: (resource: SettingsResourceKey) => void;
  draftCleanup?: SettingsDraftCleanupState;
  onRetryCleanup?: () => void;
  focusTargets?: SettingsFocusTargets;
  initialSection?: SettingsSectionId | null;
}) {
  const [selectedSection, setSelectedSection] =
    useState<SettingsSectionId | null>(initialSection);
  const [search, setSearch] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const syncLocation = (event?: Event) => {
      const section = getSettingsSectionByAnchor(window.location.hash.slice(1));
      setSelectedSection(section?.id ?? null);
      setSearch("");
      if (event && !section) {
        window.requestAnimationFrame(() => searchRef.current?.focus());
      }
    };
    syncLocation();
    window.addEventListener("hashchange", syncLocation);
    window.addEventListener("popstate", syncLocation);
    return () => {
      window.removeEventListener("hashchange", syncLocation);
      window.removeEventListener("popstate", syncLocation);
    };
  }, []);

  useEffect(() => {
    if (!selectedSection) return;
    const section = getSettingsSectionByAnchor(selectedSection);
    if (section)
      document
        .getElementById(section.headingId)
        ?.focus({ preventScroll: true });
  }, [selectedSection]);

  function navigateSection(section: SettingsSectionId | null) {
    const href = `${window.location.pathname}${window.location.search}${section ? `#${section}` : ""}`;
    if (window.location.hash !== (section ? `#${section}` : "")) {
      window.history.pushState(null, "", href);
    }
    setSelectedSection(section);
    setSearch("");
    if (!section)
      window.requestAnimationFrame(() => searchRef.current?.focus());
  }

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
  const offlineRead = getEarliestOfflineReadMetadata(
    resources.me.status === "ready" ? resources.me.data : null,
    resources.onboarding.status === "ready" ? resources.onboarding.data : null,
  );
  const activeSection =
    SETTINGS_SECTIONS.find((section) => section.id === selectedSection) ??
    SETTINGS_SECTIONS[0];
  const visibleSections = searchSettingsSections(search);

  return (
    <div
      className={styles.settingsLedger}
      data-detail-open={selectedSection ? "true" : "false"}
    >
      {offlineRead ? (
        <div
          className={`${styles.settingsOfflineNotice} offline-read-notice`}
          id="settings-offline-read"
          role="status"
        >
          {offlineReadNotice(offlineRead)}
        </div>
      ) : null}
      <aside className={styles.settingsIndex} aria-label="Settings sections">
        <div className={styles.indexHeadingRow}>
          <h1
            className={styles.routeEntryHeading}
            ref={focusTargets?.routeEntry}
            id="settings-title"
            tabIndex={-1}
          >
            Settings
          </h1>
        </div>
        <p className={styles.indexDescription}>Make yourself at home.</p>
        <div className={styles.searchField}>
          <Search size={17} aria-hidden="true" />
          <input
            ref={searchRef}
            type="search"
            aria-label="Search settings"
            placeholder="Search settings"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          {search ? (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => {
                setSearch("");
                searchRef.current?.focus();
              }}
            >
              <X size={16} aria-hidden="true" />
            </button>
          ) : null}
        </div>
        <nav className={styles.indexNav} aria-label="Settings sections">
          <div className={styles.indexGroups}>
            {SETTINGS_SECTION_GROUPS.filter((group) =>
              visibleSections.some((section) => section.groupId === group.id),
            ).map((group) => (
              <section
                className={styles.indexGroup}
                key={group.id}
                aria-labelledby={`settings-group-${group.id}`}
              >
                <div className={styles.indexGroupHeader}>
                  <h2 id={`settings-group-${group.id}`}>{group.label}</h2>
                </div>
                <div className={styles.indexGroupLinks}>
                  {visibleSections
                    .filter((section) => section.groupId === group.id)
                    .map((section) => {
                      const Icon = settingsSectionIcons[section.icon];
                      return (
                        <a
                          className={`${styles.indexLink} ${activeSection.id === section.id ? styles.indexLinkCurrent : ""}`}
                          href={`#${section.anchor}`}
                          aria-current={
                            activeSection.id === section.id
                              ? "location"
                              : undefined
                          }
                          key={section.id}
                          onClick={(event) => {
                            if (
                              event.button !== 0 ||
                              event.metaKey ||
                              event.ctrlKey ||
                              event.altKey ||
                              event.shiftKey
                            )
                              return;
                            event.preventDefault();
                            navigateSection(section.id);
                          }}
                        >
                          <Icon
                            size={19}
                            strokeWidth={1.8}
                            aria-hidden="true"
                          />
                          <span className={styles.indexLinkCopy}>
                            <strong>{section.label}</strong>
                            <small>{section.detail}</small>
                          </span>
                          <ChevronRight
                            className={styles.indexChevron}
                            size={16}
                            aria-hidden="true"
                          />
                        </a>
                      );
                    })}
                </div>
              </section>
            ))}
            {visibleSections.length === 0 ? (
              <div className={styles.noResults} role="status">
                <strong>No settings found</strong>
                <p>Try “theme”, “password”, or “learning”.</p>
              </div>
            ) : null}
          </div>
        </nav>
      </aside>

      <div className={styles.settingsContent} data-settings-panel>
        <button
          className={styles.backToCategories}
          type="button"
          onClick={() => navigateSection(null)}
        >
          <ArrowLeft size={17} aria-hidden="true" /> All settings
        </button>
        {/* Keep each operation owner mounted through category changes. Native hidden
            exposes one panel without losing pending logout or local-save recovery. */}
        {SETTINGS_SECTIONS.map((section) => (
          <div
            key={section.id}
            hidden={activeSection.id !== section.id}
            data-settings-category
          >
            <SettingsSectionCard
              section={section}
              resources={resources}
              api={api}
              onRetry={onRetry}
              learnerAccessConfirmed={learnerAccessConfirmed}
              focusTargets={focusTargets}
            />
          </div>
        ))}
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
  const controller = new AbortController();

  function publish<K extends SettingsResourceKey>(
    resource: K,
    result: SettingsResources[K],
  ) {
    if (active) onUpdate(resource, result);
  }

  function loadOnboarding() {
    let request: Promise<OnboardingResponse>;
    try {
      request = api.onboarding({ signal: controller.signal });
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
    identityRequest = api.me({ signal: controller.signal });
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
    controller.abort();
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
  const retryAbortRef = useRef<AbortController | null>(null);
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
      const section = getSettingsSectionByAnchor(window.location.hash.slice(1));
      if (section) {
        document.getElementById(section.headingId)?.focus();
        return;
      }
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
      retryAbortRef.current?.abort();
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

  function loadOnboardingForGeneration(
    generation: number,
    controller: AbortController,
  ) {
    let request: Promise<OnboardingResponse>;
    try {
      request = api.onboarding({ signal: controller.signal });
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
    retryAbortRef.current?.abort();
    const controller = new AbortController();
    retryAbortRef.current = controller;
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
      loadOnboardingForGeneration(generation, controller);
      return;
    }

    let request: Promise<MeResponse>;
    try {
      request = api.me({ signal: controller.signal });
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
          loadOnboardingForGeneration(generation, controller);
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
