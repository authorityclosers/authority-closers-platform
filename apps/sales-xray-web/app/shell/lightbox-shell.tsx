"use client";

import {
  Building2,
  ChevronDown,
  Ellipsis,
  FolderOpen,
  GraduationCap,
  LayoutGrid,
  LogIn,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  Settings,
  Users,
} from "lucide-react";
import Form from "next/form";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type MouseEvent,
  type ReactNode,
} from "react";

import { useBranding } from "./branding-store";
import { useShellProfile } from "./profile-store";
import { callHref, type Allowance } from "../acquisition-client";
import { CALLS_PATH } from "../analysis-routes";
import { callDate, callTone, submissionState } from "../call-status";
import { CALL_LABEL_EVENT, type CallLabelChange } from "../call-label-client";
import {
  ownerLabel,
  ownsCall,
  requestWorkspace,
  SELECT_WORKSPACE_EVENT,
} from "../call-ownership";
import { RecentCallItem } from "./recent-call-item";
import { LocalSettingsButton } from "../live-data-banner";
import { newCallHref } from "../new-call-navigation";
import { ProfileMenu } from "../profile-menu";
import { SettingsDialogHost } from "../settings-dialog";
import { notify } from "../notice-center";
import { opensInPlace } from "../settings-open";
import { useWorkspaceAccess } from "../workspace-access";
import { BrandLockup } from "./brand-lockup";
import { AllowanceRing } from "./allowance-ring";
import { MinutesMeter } from "./minutes-meter";
import { phoneTabFor, shellActiveFor } from "./phone-nav";
import { RailTip } from "./rail-tip";
import { SectionBoundary } from "../ui/section-boundary";
import {
  readAllowance,
  readCallSummary,
  readRecentCalls,
  type CallSummary,
} from "../dashboard/dashboard-data";
import {
  getShellState,
  OPEN_SWITCHER_EVENT,
  RECENTS_CHANGED_EVENT,
  recentCallsForContext,
  updateShellState,
  type ShellRecentCall,
} from "./shell-store";
import { ThemeToggle } from "./theme-toggle";
import { WorkspaceSwitcher } from "./workspace-switcher";
import { SettingsMenu } from "./settings-menu";
import { useShellUpdates } from "./updates-store";
import { UpdatesBell } from "./updates-bell";
import { UpdateNotices } from "./update-notices";
import {
  isRelativeUpdateHref,
  type UpdateNotification,
} from "./updates-client";
import styles from "./lightbox-shell.module.css";

export type LightboxShellProps = {
  children: ReactNode;
  authenticated: boolean;
  /** The session is still being confirmed: show placeholders, never guest labels. */
  loading?: boolean;
  homeHref?: string;
  active?:
    | "dashboard"
    | "analyse"
    | "calls"
    | "account"
    | "organisation"
    | "prospects"
    | "coaching";
  compactBusy?: boolean;
  mobileFit?: boolean;
  welcome?: boolean;
  heroStage?: "welcome" | "ready" | "processing";
  /** Kept for API compatibility; the shell shows no greeting banner. */
  displayName?: string | null;
  /** Label the explicit local review fixture without implying a real job. */
  previewHero?: boolean;
  /** A verified session allowance; the meter stays hidden without one. */
  allowance?: Allowance | null;
};

type PageHeading = { title: string; description?: string };

// Compact, truthful page headings. No greeting, slogan or estimated duration.
function pageHeading(
  stage: LightboxShellProps["heroStage"],
  previewHero: boolean,
): PageHeading | null {
  if (stage === "ready")
    return {
      title: "Ready to analyse",
      description: "Your call is saved. Start analysis to get your report.",
    };
  if (stage === "processing")
    return previewHero
      ? {
          title: "Example processing state",
          description:
            "A read-only preview of how your call moves from upload to report.",
        }
      : { title: "Analysing your call" };
  if (stage === "welcome") return { title: "New analysis" };
  return null;
}

function resolvePageTitle(
  active: LightboxShellProps["active"],
  heading: PageHeading | null,
): string | null {
  if (active === "dashboard") return "Dashboard";
  if (heading) return heading.title;
  if (active === "calls") return "Calls";
  if (active === "prospects") return "Prospects";
  if (active === "coaching") return "Coaching";
  if (active === "account") return "Account";
  if (active === "organisation") return "Organisation";
  return null;
}

const subscribeNothing = () => () => {};

// A rail icon's name for text readers and tests. Hidden inline, so it stays
// hidden even when the page draws before its stylesheet (dev recompiles);
// the visible label floats above every layer on hover or focus (rail-tip.tsx).
const RAIL_NAME_STYLE: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  margin: -1,
  padding: 0,
  border: 0,
  overflow: "hidden",
  clipPath: "inset(50%)",
  whiteSpace: "nowrap",
};

// Apple keyboards show ⌘; everyone else presses Ctrl (the server assumes Ctrl).
const shortcutLabel = () =>
  /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
    ? "⌘K"
    : "Ctrl K";

function LightboxShellFrame({
  children,
  authenticated,
  homeHref = "/",
  active = "analyse",
  compactBusy = false,
  mobileFit = false,
  welcome = false,
  heroStage,
  previewHero = false,
  allowance = null,
  displayName = null,
  loading = false,
}: LightboxShellProps) {
  const access = useWorkspaceAccess();
  const cached = getShellState();
  // Until the server answers, the session is unknown: keep the signed-in
  // frame with placeholders instead of flashing guest labels.
  const sessionPending =
    access !== null &&
    (access.status === "loading" || access.authenticated === null);
  const accountKey = access?.context
    ? JSON.stringify([access.context.personId, access.context.sessionId])
    : null;
  const [savedCollapsed, setCollapsed] = useState(cached.collapsed);
  // The server cannot read the saved sidebar state: match it while
  // hydrating, then apply the saved state (no hydration mismatch).
  const hydrated = useSyncExternalStore(
    subscribeNothing,
    () => true,
    () => false,
  );
  const collapsed = hydrated && savedCollapsed;
  const shortcut = useSyncExternalStore(
    subscribeNothing,
    shortcutLabel,
    () => "Ctrl K",
  );
  const [, setCounts] = useState<CallSummary | null>(cached.counts);
  const workspaces = access?.workspaces ?? [];
  const workspacesSettled = access?.status === "ready";
  const [workspaceReloadPending, setWorkspaceReloadPending] = useState(false);
  // The confirmed server context owns selection across mounts and sessions.
  const effectiveTenantId = access?.context?.tenantId ?? null;
  const salesXrayEnabled =
    workspaces.find((workspace) => workspace.tenant_id === effectiveTenantId)
      ?.sales_xray_enabled !== false;
  const recentContextKey =
    authenticated &&
    salesXrayEnabled &&
    !workspaceReloadPending &&
    access?.context &&
    effectiveTenantId
      ? JSON.stringify([
          access.context.personId,
          access.context.sessionId,
          effectiveTenantId,
        ])
      : null;
  const [switcherOpen, setSwitcherOpen] = useState(false);
  useEffect(() => {
    const open = () => setSwitcherOpen(true);
    window.addEventListener(OPEN_SWITCHER_EVENT, open);
    return () => window.removeEventListener(OPEN_SWITCHER_EVENT, open);
  }, []);
  // The gear opens the account card; the card opens settings sections.
  const [accountCardOpen, setAccountCardOpen] = useState(false);
  const [accountView, setAccountView] = useState<"main" | "news">("main");
  const closeAccountCard = useCallback(() => setAccountCardOpen(false), []);
  const accountAnchorRef = useRef<HTMLElement | null>(null);
  const railRef = useRef<HTMLDivElement | null>(null);
  const updates = useShellUpdates(
    authenticated,
    process.env.NODE_ENV !== "test",
  );
  const unseenNews = updates.unseen_count;
  const { markRead } = updates;
  const updatesContextKey =
    authenticated && access?.authenticated === true ? recentContextKey : null;
  const openNews = useCallback((anchor: HTMLElement | null = null) => {
    accountAnchorRef.current = anchor;
    setAccountView("news");
    setAccountCardOpen(true);
  }, []);
  const navigateEvent = useCallback((href: string) => {
    if (isRelativeUpdateHref(href)) window.location.assign(href);
  }, []);
  const navigationContext = useRef(updatesContextKey);
  useEffect(() => {
    navigationContext.current = updatesContextKey;
  }, [updatesContextKey]);
  const openEvent = useCallback(
    async (entry: UpdateNotification) => {
      if (!isRelativeUpdateHref(entry.href)) return;
      await markRead([entry.id]);
      if (navigationContext.current === updatesContextKey)
        navigateEvent(entry.href);
    },
    [markRead, navigateEvent, updatesContextKey],
  );
  const bell = updatesContextKey ? (
    <UpdatesBell
      key={updatesContextKey}
      notifications={updates.notifications}
      unreadCount={updates.unread_count}
      status={updates.notifications_status}
      openNews={openNews}
      openEvent={openEvent}
    />
  ) : null;
  const profile = useShellProfile(
    authenticated,
    process.env.NODE_ENV !== "test",
  );
  const profileName = profile?.name?.trim() || null;
  const [recentCalls, setRecentCalls] = useState(() =>
    recentCallsForContext(cached, recentContextKey),
  );
  const [recentCallsContextKey, setRecentCallsContextKey] = useState(
    cached.recentCallsContextKey,
  );
  const [recentsOpen, setRecentsOpen] = useState(cached.recentsOpen);

  const switcherRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const collapseButtonRef = useRef<HTMLButtonElement>(null);
  const expandButtonRef = useRef<HTMLButtonElement>(null);
  const focusTogglePendingRef = useRef(false);
  const accountHref = authenticated ? "/account" : "/login";
  const accountLabel = authenticated ? "Account" : "Profile & account";
  const visibleHero = heroStage ?? (welcome ? "welcome" : undefined);
  const heading = compactBusy ? null : pageHeading(visibleHero, previewHero);
  const pathname = usePathname();
  const place = shellActiveFor(pathname, active);
  const pageTitle = resolvePageTitle(place, heading);
  const phoneTab = phoneTabFor(pathname, active);

  const toggleCollapsed = () => {
    const next = !collapsed;
    focusTogglePendingRef.current = true;
    setCollapsed(next);
    updateShellState({ collapsed: next });
    try {
      localStorage.setItem("sx.sidebar.collapsed", String(next));
    } catch {}
  };

  useLayoutEffect(() => {
    // Only a toggle action moves focus, after the visible control is ready.
    if (!focusTogglePendingRef.current) return;
    focusTogglePendingRef.current = false;
    const target = collapsed ? expandButtonRef : collapseButtonRef;
    target.current?.focus({ preventScroll: true });
  }, [collapsed]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        // Search lives in the sidebar: open it first when it is collapsed.
        if (expandButtonRef.current) {
          expandButtonRef.current.click();
          window.setTimeout(() => searchInputRef.current?.focus(), 80);
        } else searchInputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // Recents refetch when a call is created or finishes, and when the tab
  // comes back into view.
  const [recentsNudge, setRecentsNudge] = useState(0);
  useEffect(() => {
    const nudge = () => setRecentsNudge((count) => count + 1);
    const onVisible = () => {
      if (document.visibilityState === "visible") nudge();
    };
    window.addEventListener(RECENTS_CHANGED_EVENT, nudge);
    window.addEventListener("focus", nudge);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener(RECENTS_CHANGED_EVENT, nudge);
      window.removeEventListener("focus", nudge);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  useEffect(() => {
    if (
      !authenticated ||
      recentContextKey === null ||
      process.env.NODE_ENV === "test"
    ) {
      updateShellState({
        recentCalls: [],
        recentCallsContextKey: null,
        recentFetchedAt: null,
      });
      return;
    }
    const cached = getShellState();
    const sameContext = cached.recentCallsContextKey === recentContextKey;
    if (
      sameContext &&
      cached.recentFetchedAt !== null &&
      Date.now() - cached.recentFetchedAt < (recentsNudge ? 3_000 : 60_000)
    ) {
      return;
    }
    const controller = new AbortController();
    // Keep the list on screen while refreshing the same account's Recents.
    if (!sameContext)
      updateShellState({
        recentCalls: [],
        recentCallsContextKey: null,
        recentFetchedAt: null,
      });
    readRecentCalls(controller.signal, 5, true)
      .then((submissions) => {
        if (controller.signal.aborted) return;
        const mapped = submissions.map((call) => ({
          id: call.id,
          name: call.label?.displayName ?? "Untitled call",
          revision: call.label?.revision ?? 0,
          date: callDate(call.createdAt),
          tone: callTone(call),
          status: submissionState(call),
          ...(call.owner ? { owner: call.owner } : {}),
        }));
        setRecentCalls(mapped);
        setRecentCallsContextKey(recentContextKey);
        updateShellState({
          recentCalls: mapped,
          recentCallsContextKey: recentContextKey,
          recentFetchedAt: Date.now(),
        });
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setRecentCalls([]);
        setRecentCallsContextKey(recentContextKey);
        updateShellState({
          recentCalls: [],
          recentCallsContextKey: recentContextKey,
          recentFetchedAt: null,
        });
      });
    return () => controller.abort();
  }, [authenticated, recentContextKey, recentsNudge]);

  // The minutes pill reads the account's own allowance when the page has none.
  const [shellAllowance, setShellAllowance] = useState<{
    key: string | null;
    value: Allowance | null;
  } | null>(() =>
    cached.allowance
      ? { key: cached.allowanceContextKey, value: cached.allowance }
      : null,
  );
  const hasPageAllowance = allowance !== null;
  useEffect(() => {
    if (
      !authenticated ||
      recentContextKey === null ||
      hasPageAllowance ||
      process.env.NODE_ENV === "test"
    )
      return;
    const controller = new AbortController();
    readAllowance(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setShellAllowance({ key: recentContextKey, value });
        updateShellState({
          allowance: value,
          allowanceContextKey: recentContextKey,
        });
      })
      .catch(() => {
        // No minutes in this workspace: settle, so the pill never shimmers on.
        if (!controller.signal.aborted)
          setShellAllowance({ key: recentContextKey, value: null });
      });
    return () => controller.abort();
  }, [authenticated, recentContextKey, hasPageAllowance, recentsNudge]);

  useEffect(() => {
    if (
      !authenticated ||
      recentContextKey === null ||
      process.env.NODE_ENV === "test"
    ) {
      return;
    }
    const controller = new AbortController();
    readCallSummary(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setCounts(data);
        updateShellState({ counts: data });
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setCounts(null);
        updateShellState({ counts: null });
      });
    return () => controller.abort();
  }, [authenticated, recentContextKey]);

  useEffect(() => {
    if (!accountKey || !access?.workspaces) return;
    updateShellState({
      workspaces: [...access.workspaces],
      selectedTenantId: access.context?.tenantId ?? null,
      selectedTenantAccountKey: accountKey,
      fetchedAt: Date.now(),
    });
  }, [accountKey, access?.workspaces, access?.context?.tenantId]);

  useEffect(() => {
    if (!switcherOpen) return;
    const closeOutside = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !switcherRef.current?.contains(event.target)
      ) {
        setSwitcherOpen(false);
      }
    };
    const closeEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setSwitcherOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeEscape);
    };
  }, [switcherOpen]);

  async function handleSelectWorkspace(tenantId: string) {
    if (tenantId === effectiveTenantId) {
      setSwitcherOpen(false);
      return;
    }
    try {
      const res = await fetch("/v1/context", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenantId }),
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
      });
      if (res.ok) {
        const selected: unknown = await res.json();
        if (
          typeof selected !== "object" ||
          selected === null ||
          !("tenant_id" in selected) ||
          selected.tenant_id !== tenantId
        )
          throw new Error("workspace_not_selected");
        // The next document reads the new context. Do not start reads here
        // between the successful context change and its reload.
        setWorkspaceReloadPending(true);
        setSwitcherOpen(false);
        setRecentCalls([]);
        setRecentCallsContextKey(null);
        updateShellState({
          selectedTenantId: tenantId,
          selectedTenantAccountKey: accountKey,
          recentCalls: [],
          recentCallsContextKey: null,
          recentFetchedAt: null,
        });
        // Every list on the page belongs to the workspace: reload into it.
        window.location.reload();
        return;
      }
    } catch {}
    // Nothing changed: say so in the corner, never fail silently.
    notify({
      id: "workspace-switch",
      tone: "error",
      title: "Couldn’t switch workspace",
      message: "Try again in a moment.",
      action: {
        label: "Try again",
        run: () => void handleSelectWorkspace(tenantId),
      },
    });
  }

  function openAccount(event: MouseEvent<HTMLAnchorElement>) {
    if (!authenticated && access?.requestAccountSignIn) {
      event.preventDefault();
      access.requestAccountSignIn();
      return;
    }
    // The account card floats over the current screen instead of leaving it.
    if (authenticated && active !== "account" && opensInPlace(event)) {
      event.preventDefault();
      accountAnchorRef.current = event.currentTarget;
      setAccountView("main");
      setAccountCardOpen((open) => !open);
    }
  }

  // Organisation tools appear only while an organisation is selected.
  const inOrganisation = workspaces.some(
    (workspace) =>
      workspace.tenant_id === effectiveTenantId &&
      workspace.kind === "organisation",
  );
  const branding = useBranding(inOrganisation);
  // Signed in but names not fetched yet: placeholders, never a guest-looking
  // "Workspace". A failed fetch settles too, so this cannot shimmer forever.
  const chromePending =
    loading ||
    sessionPending ||
    (authenticated && !workspacesSettled && !profileName && !displayName);
  // Recents show skeleton rows until this account's list has arrived.
  const recentsReady =
    recentContextKey !== null &&
    (recentCallsContextKey === recentContextKey ||
      getShellState().recentCallsContextKey === recentContextKey);
  const recentsPending =
    process.env.NODE_ENV !== "test" &&
    (sessionPending || (authenticated && !recentsReady));
  const shownAllowance =
    allowance ??
    (shellAllowance && shellAllowance.key === recentContextKey
      ? shellAllowance.value
      : null);
  const visibleRecentCalls =
    recentCallsContextKey === recentContextKey &&
    getShellState().recentCallsContextKey === recentContextKey
      ? recentCalls
      : recentCallsForContext(getShellState(), recentContextKey);
  const newAnalysisHref = newCallHref(homeHref);
  const viewerId = access?.context?.personId ?? null;
  // A list with owners can mix people: then every row says whose it is.
  const recentsShowOwners = visibleRecentCalls.some((call) => call.owner);
  // The workspace is named wherever you are, so work never looks lost.
  const currentWorkspace = workspaces.find(
    (workspace) => workspace.tenant_id === effectiveTenantId,
  );
  const workspaceLabel = currentWorkspace
    ? currentWorkspace.kind === "personal"
      ? "Personal"
      : currentWorkspace.name
    : null;
  const personalWorkspace = workspaces.find(
    (workspace) =>
      workspace.kind === "personal" && workspace.sales_xray_enabled,
  );
  const recentsElsewhere =
    recentsShowOwners &&
    currentWorkspace?.kind === "organisation" &&
    personalWorkspace &&
    !visibleRecentCalls.some((call) => ownsCall(call.owner, viewerId))
      ? personalWorkspace
      : null;

  // Apply a rename or deletion to the sidebar list and its shared cache.
  function updateRecentCall(id: string, next: ShellRecentCall | null) {
    const apply = (calls: ShellRecentCall[]) =>
      next === null
        ? calls.filter((call) => call.id !== id)
        : calls.map((call) => (call.id === id ? next : call));
    setRecentCalls(apply);
    updateShellState({ recentCalls: apply(getShellState().recentCalls) });
  }

  // A rename anywhere (report header, Calls, sidebar) updates Recents at once.
  useEffect(() => {
    const onLabel = (event: Event) => {
      const { submissionId, label } = (event as CustomEvent<CallLabelChange>)
        .detail;
      const rename = (calls: ShellRecentCall[]) =>
        calls.map((call) =>
          call.id === submissionId
            ? {
                ...call,
                name: label.displayName ?? "Untitled call",
                revision: label.revision,
              }
            : call,
        );
      setRecentCalls(rename);
      updateShellState({ recentCalls: rename(getShellState().recentCalls) });
    };
    window.addEventListener(CALL_LABEL_EVENT, onLabel);
    return () => window.removeEventListener(CALL_LABEL_EVENT, onLabel);
  }, []);

  // Pages ask the shell to switch workspace ("Switch to Personal").
  const selectWorkspaceRef = useRef(handleSelectWorkspace);
  useEffect(() => {
    selectWorkspaceRef.current = handleSelectWorkspace;
  });
  useEffect(() => {
    const onSelect = (event: Event) => {
      const tenantId = (event as CustomEvent<string>).detail;
      if (typeof tenantId === "string")
        void selectWorkspaceRef.current(tenantId);
    };
    window.addEventListener(SELECT_WORKSPACE_EVENT, onSelect);
    return () => window.removeEventListener(SELECT_WORKSPACE_EVENT, onSelect);
  }, []);

  return (
    <div
      className={`${styles.shell} ${collapsed ? styles.collapsed : ""}`}
      data-lightbox-shell
      data-authenticated={authenticated}
      data-loading={chromePending || undefined}
      data-sidebar-collapsed={collapsed}
      data-compact-busy={compactBusy}
      data-mobile-fit={mobileFit}
      data-welcome={Boolean(visibleHero)}
      data-hero-stage={visibleHero}
    >
      <a className={styles.skip} href="#main-content">
        Skip to workspace
      </a>
      <aside
        id="sales-xray-sidebar"
        className={styles.sidebar}
        aria-label="Sales Xray navigation"
      >
        {/* 64px Icon Strip */}
        <div className={styles.iconStrip} ref={railRef}>
          <div className={styles.stripTop}>
            <div className={styles.logoSlot}>
              <BrandLockup href={homeHref} markOnly={true} />
              {collapsed && (
                <button
                  type="button"
                  ref={expandButtonRef}
                  className={styles.logoExpandBtn}
                  onClick={toggleCollapsed}
                  aria-label="Expand sidebar navigation"
                  aria-expanded={false}
                  aria-controls="sales-xray-sidebar-panel"
                  title="Expand navigation"
                >
                  <PanelLeftOpen size={18} aria-hidden="true" />
                </button>
              )}
            </div>
          </div>
          <div className={styles.stripNav}>
            <Link
              className={`${styles.stripBtn}${place === "dashboard" ? ` ${styles.stripBtnActive}` : ""}`}
              href="/dashboard"
              aria-label="Dashboard"
              data-rail-tip="Dashboard"
              aria-current={place === "dashboard" ? "page" : undefined}
            >
              <LayoutGrid size={20} strokeWidth={1.75} aria-hidden="true" />
              <span style={RAIL_NAME_STYLE}>Dashboard</span>
            </Link>
            <Link
              className={`${styles.stripBtn}${place === "analyse" ? ` ${styles.stripBtnActive}` : ""}`}
              href={newAnalysisHref}
              aria-label="New analysis"
              data-rail-tip="New analysis"
              aria-current={place === "analyse" ? "page" : undefined}
            >
              <Plus size={20} strokeWidth={1.75} aria-hidden="true" />
              <span style={RAIL_NAME_STYLE}>New analysis</span>
            </Link>
            <Link
              className={`${styles.stripBtn}${place === "calls" ? ` ${styles.stripBtnActive}` : ""}`}
              href="/analysis/calls"
              aria-label="Calls"
              data-rail-tip="Calls"
              aria-current={place === "calls" ? "page" : undefined}
            >
              <FolderOpen size={20} strokeWidth={1.75} aria-hidden="true" />
              <span style={RAIL_NAME_STYLE}>Calls</span>
            </Link>
            <Link
              className={`${styles.stripBtn}${place === "prospects" ? ` ${styles.stripBtnActive}` : ""}`}
              href="/prospects"
              aria-label="Prospects"
              data-rail-tip="Prospects"
              aria-current={place === "prospects" ? "page" : undefined}
            >
              <Users size={20} strokeWidth={1.75} aria-hidden="true" />
              <span style={RAIL_NAME_STYLE}>Prospects</span>
            </Link>
            <Link
              className={`${styles.stripBtn}${place === "coaching" ? ` ${styles.stripBtnActive}` : ""}`}
              href="/coaching"
              aria-label="Coaching"
              data-rail-tip="Coaching"
              aria-current={place === "coaching" ? "page" : undefined}
            >
              <GraduationCap size={20} strokeWidth={1.75} aria-hidden="true" />
              <span style={RAIL_NAME_STYLE}>Coaching</span>
            </Link>
            {inOrganisation || place === "organisation" ? (
              <Link
                className={`${styles.stripBtn}${place === "organisation" ? ` ${styles.stripBtnActive}` : ""}`}
                href="/organisation"
                prefetch={false}
                aria-label="Organisation"
                data-rail-tip="Organisation"
                aria-current={place === "organisation" ? "page" : undefined}
              >
                <Building2 size={20} strokeWidth={1.75} aria-hidden="true" />
                <span style={RAIL_NAME_STYLE}>Organisation</span>
              </Link>
            ) : null}
          </div>
          <div className={styles.stripBottom}>
            {bell}
            <Link
              className={`${styles.stripBtn}${place === "account" ? ` ${styles.stripBtnActive}` : ""}`}
              href={accountHref}
              onClick={openAccount}
              aria-label={accountLabel}
              data-rail-tip={accountLabel}
              aria-haspopup={authenticated ? "dialog" : undefined}
              aria-expanded={authenticated ? accountCardOpen : undefined}
              aria-current={place === "account" ? "page" : undefined}
              data-news={authenticated && unseenNews > 0 ? "" : undefined}
            >
              <Settings size={20} strokeWidth={1.75} aria-hidden="true" />
              <span style={RAIL_NAME_STYLE}>{accountLabel}</span>
            </Link>
          </div>
        </div>

        <RailTip rail={railRef} />

        {/* 248px Panel */}
        <div
          id="sales-xray-sidebar-panel"
          className={styles.panel}
          inert={collapsed}
        >
          <div className={styles.panelHeader}>
            <WorkspaceSwitcher
              workspaces={workspaces}
              currentId={effectiveTenantId}
              personName={profileName}
              branding={branding}
              pending={chromePending}
              open={switcherOpen}
              setOpen={setSwitcherOpen}
              containerRef={switcherRef}
              onSelect={(tenantId) => void handleSelectWorkspace(tenantId)}
            />
            <button
              type="button"
              ref={collapseButtonRef}
              className={styles.collapseBtn}
              onClick={toggleCollapsed}
              aria-label="Collapse sidebar navigation"
              aria-expanded={!collapsed}
              aria-controls="sales-xray-sidebar-panel"
              title="Collapse navigation"
            >
              <PanelLeftClose size={16} aria-hidden="true" />
            </button>
          </div>

          {/* Enter opens Calls filtered by the text; the box then clears. */}
          <Form
            action={CALLS_PATH}
            role="search"
            className={`${styles.searchBox} ${styles.panelSearch}`}
            onSubmit={(event) => {
              const form = event.currentTarget;
              window.setTimeout(() => {
                form.reset();
                searchInputRef.current?.blur();
              }, 0);
            }}
          >
            <Search
              size={15}
              className={styles.searchIcon}
              aria-hidden="true"
            />
            <input
              ref={searchInputRef}
              type="search"
              name="q"
              className={styles.searchInput}
              placeholder="Search calls…"
              aria-label="Search calls"
              enterKeyHint="search"
            />
            <kbd className={styles.searchKbd} aria-hidden="true">
              {shortcut}
            </kbd>
          </Form>

          {/* Recents Section */}
          {salesXrayEnabled && (
            <div className={styles.recentsSection}>
              <div className={styles.recentsHeader}>
                <button
                  type="button"
                  className={styles.recentsToggleBtn}
                  onClick={() => {
                    setRecentsOpen((prev) => {
                      const next = !prev;
                      updateShellState({ recentsOpen: next });
                      return next;
                    });
                  }}
                  aria-expanded={recentsOpen}
                  title={recentsOpen ? "Collapse recents" : "Expand recents"}
                >
                  <ChevronDown
                    size={14}
                    className={`${styles.recentsChevron}${recentsOpen ? "" : ` ${styles.recentsChevronCollapsed}`}`}
                    aria-hidden="true"
                  />
                  <span className={styles.recentsTitle}>Recents</span>
                </button>
                <Link
                  href="/analysis/calls"
                  className={styles.recentsViewAll}
                  title="View all calls"
                >
                  View all
                </Link>
              </div>
              {recentsOpen && (
                <SectionBoundary name="Recents">
                  <div className={styles.recentsList}>
                    {recentsPending && visibleRecentCalls.length === 0
                      ? [62, 44, 72].map((width, index) => (
                          <div
                            key={width}
                            className={styles.recentSkeleton}
                            style={
                              {
                                "--i": index,
                                "--w": `${width}%`,
                              } as CSSProperties
                            }
                            aria-hidden="true"
                          >
                            <i />
                            <span />
                            <em />
                          </div>
                        ))
                      : null}
                    {!recentsPending &&
                    recentsReady &&
                    visibleRecentCalls.length === 0 ? (
                      <p className={styles.recentsEmpty}>No calls here yet</p>
                    ) : null}
                    {visibleRecentCalls.map((call, index) => (
                      <RecentCallItem
                        key={call.id}
                        index={index}
                        call={call}
                        href={callHref(call.id)}
                        mine={ownsCall(call.owner, viewerId)}
                        owner={
                          recentsShowOwners
                            ? call.owner
                              ? ownerLabel(call.owner, viewerId)
                              : "You"
                            : null
                        }
                        onChange={(next) => updateRecentCall(call.id, next)}
                      />
                    ))}
                    {recentsElsewhere ? (
                      <p className={styles.recentsElsewhere}>
                        None of these are yours.{" "}
                        <button
                          type="button"
                          onClick={() =>
                            requestWorkspace(recentsElsewhere.tenant_id)
                          }
                        >
                          Switch to Personal
                        </button>
                      </p>
                    ) : null}
                  </div>
                </SectionBoundary>
              )}
            </div>
          )}

          <div className={styles.panelSpacer} />
        </div>
      </aside>
      <div className={styles.content}>
        <header className={styles.mobileBar}>
          {/* r17: the lens, then where you are: workspace over page title. */}
          {workspaceLabel || pageTitle ? (
            <div className={styles.mobileWorkspace}>
              <BrandLockup href={homeHref} markOnly />
              <span
                title={
                  workspaceLabel ? `Workspace: ${workspaceLabel}` : undefined
                }
              >
                {workspaceLabel ? (
                  <small>{pageTitle ? workspaceLabel : "Workspace"}</small>
                ) : null}
                <b>{pageTitle ?? workspaceLabel}</b>
              </span>
            </div>
          ) : (
            <BrandLockup href={homeHref} />
          )}
          {/* The account lives under More in the tab bar, not here too. */}
          <div className={styles.barActions}>
            {bell}
            <MinutesMeter allowance={allowance} variant="pill" />
          </div>
        </header>
        <header className={styles.topBar}>
          <div className={styles.topBarLeft}>
            {pageTitle && (
              <div className={styles.titleWrap}>
                <div className={styles.topBarTitle}>
                  <span
                    className={styles.titleContext}
                    title={
                      workspaceLabel
                        ? `Workspace: ${workspaceLabel}`
                        : undefined
                    }
                  >
                    {workspaceLabel ?? "Sales Xray"}
                  </span>
                  {heading ? (
                    <h1 key={heading.title} className={styles.titleText}>
                      {heading.title}
                    </h1>
                  ) : (
                    <span key={pageTitle} className={styles.titleText}>
                      {pageTitle}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
          {/* Pages can host their own toolbar here (the report's sections). */}
          <div className={styles.topBarCenter} data-shell-toolbar />
          <div className={styles.topBarRight}>
            {/* First, so its arrival (or absence) moves nothing else. */}
            <AllowanceRing allowance={shownAllowance} />
            {(authenticated || sessionPending) && place !== "analyse" ? (
              <Link className={styles.newAnalysisButton} href={newAnalysisHref}>
                <Plus size={15} aria-hidden="true" />
                New analysis
              </Link>
            ) : null}
            <ThemeToggle />
            <ProfileMenu
              authenticated={authenticated}
              accountHref={accountHref}
              variant="header"
              pending={chromePending}
            />
          </div>
        </header>
        {heading?.description ? (
          <div className={styles.pageDescription}>
            <p>{heading.description}</p>
          </div>
        ) : null}
        <main id="main-content" className={styles.main}>
          {/* A page that fails leaves the shell working: navigation, Recents. */}
          <SectionBoundary
            name="This screen"
            note="Your calls and reports are safe."
            resetKey={pathname}
          >
            {children}
          </SectionBoundary>
        </main>
      </div>
      <nav
        className={styles.bottomNav}
        aria-label="Mobile Sales Xray navigation"
      >
        <Link
          className={styles.bottomLink}
          href="/dashboard"
          aria-current={phoneTab === "dashboard" ? "page" : undefined}
        >
          <LayoutGrid size={20} aria-hidden="true" />
          <span>Dashboard</span>
        </Link>
        <Link
          className={styles.bottomLink}
          href="/analysis/calls"
          aria-current={phoneTab === "calls" ? "page" : undefined}
        >
          <FolderOpen size={20} aria-hidden="true" />
          <span>Calls</span>
        </Link>
        <Link
          className={`${styles.bottomLink} ${styles.bottomNew}`}
          href={newAnalysisHref}
          aria-label="New analysis"
          aria-current={phoneTab === "new" ? "page" : undefined}
        >
          <span className={styles.newMark} aria-hidden="true">
            <Plus size={18} strokeWidth={2.25} />
          </span>
          <span>New</span>
        </Link>
        <Link
          className={styles.bottomLink}
          href="/prospects"
          aria-current={phoneTab === "prospects" ? "page" : undefined}
        >
          <Users size={20} aria-hidden="true" />
          <span>Prospects</span>
        </Link>
        <Link
          className={styles.bottomLink}
          href="/coaching"
          aria-current={phoneTab === "coaching" ? "page" : undefined}
        >
          <GraduationCap size={20} aria-hidden="true" />
          <span>Coaching</span>
        </Link>
        {/* Signed out shows Sign in; an unconfirmed session keeps More. */}
        {!authenticated && !sessionPending && !loading ? (
          <Link
            className={styles.bottomLink}
            href={accountHref}
            onClick={openAccount}
          >
            <LogIn size={20} aria-hidden="true" />
            <span>Sign in</span>
          </Link>
        ) : (
          <button
            type="button"
            className={styles.bottomLink}
            onClick={(event) => {
              if (!authenticated) return;
              accountAnchorRef.current = event.currentTarget;
              setAccountView("main");
              setAccountCardOpen((open) => !open);
            }}
            aria-haspopup="dialog"
            aria-expanded={accountCardOpen && authenticated}
            aria-current={phoneTab === "more" ? "page" : undefined}
          >
            <Ellipsis size={20} aria-hidden="true" />
            <span>More</span>
          </button>
        )}
        <LocalSettingsButton className={styles.bottomLink} />
      </nav>
      <SettingsDialogHost />
      <UpdateNotices
        updates={updates}
        contextKey={updatesContextKey}
        openNews={openNews}
        openEvent={navigateEvent}
      />
      {accountCardOpen && authenticated ? (
        <SettingsMenu
          key={accountView}
          initialView={accountView}
          open
          anchorRef={accountAnchorRef}
          onClose={closeAccountCard}
          name={profileName}
          email={profile?.email ?? null}
          photoUrl={profile?.photo_url}
          allowance={shownAllowance}
          organisation={inOrganisation}
          workspaces={workspaces.filter(
            (workspace) => workspace.sales_xray_enabled,
          )}
          currentWorkspaceId={effectiveTenantId}
          onSelectWorkspace={(tenantId) => void handleSelectWorkspace(tenantId)}
        />
      ) : null}
    </div>
  );
}

type ShellPage = Omit<LightboxShellProps, "children">;

const PersistentShellContext = createContext<
  ((page: ShellPage) => void) | null
>(null);

/**
 * One app frame (sidebar, top bar, page area) that stays mounted while the
 * person moves between app pages, so navigation swaps only the page content.
 * Pages keep rendering <LightboxShell>; inside this frame it describes the
 * chrome (active item, heading, allowance) instead of drawing a second one.
 */
export function PersistentShell({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<ShellPage>({
    authenticated: false,
    loading: true,
  });
  return (
    <PersistentShellContext.Provider value={setPage}>
      <LightboxShellFrame {...page}>{children}</LightboxShellFrame>
    </PersistentShellContext.Provider>
  );
}

function ShellPageSettings({
  setPage,
  children,
  ...page
}: LightboxShellProps & { setPage: (page: ShellPage) => void }) {
  // The chrome settings are plain data, so their serialised form is both the
  // change signal and the value handed to the frame.
  const settings = JSON.stringify(page);
  // Before paint, so the frame never shows the previous page's chrome.
  useLayoutEffect(() => {
    setPage(JSON.parse(settings) as ShellPage);
  }, [setPage, settings]);
  return children;
}

export function LightboxShell(props: LightboxShellProps) {
  const setPage = useContext(PersistentShellContext);
  if (!setPage) return <LightboxShellFrame {...props} />;
  return <ShellPageSettings setPage={setPage} {...props} />;
}
