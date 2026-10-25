"use client";

import {
  AudioLines,
  BarChart3,
  Bell,
  Building2,
  ChevronDown,
  Contact,
  GraduationCap,
  Layers,
  LayoutGrid,
  LifeBuoy,
  LogIn,
  MessagesSquare,
  PanelLeftClose,
  PanelLeftOpen,
  PhoneCall,
  Plug,
  Plus,
  Rows3,
  Search,
  Settings,
  UserPlus,
  UserRound,
  Users,
  UsersRound,
} from "lucide-react";
import Form from "next/form";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type MouseEvent,
  type ReactNode,
} from "react";

import { useBranding } from "./branding-store";
import { AddSheet } from "./add-sheet";
import { useAppRouter } from "./app-router";
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
import { newCallHref } from "../new-call-navigation";
import { displayName as withCapitals } from "../display-name";
import { ProfileMenu } from "../profile-menu";
import { SettingsDialogHost } from "../settings-dialog";
import { notify } from "../notice-center";
import { opensInPlace } from "../settings-open";
import { useWorkspaceAccess } from "../workspace-access";
import { BrandLockup } from "./brand-lockup";
import { phoneTabFor, shellActiveFor, type PhoneTab } from "./phone-nav";
import { RailTip } from "./rail-tip";
import { usePlacePrefetch, useHoverPrefetch } from "./route-prefetch";
import { ScreenLink } from "./screen-link";
import { useGlide, useScreenMotion } from "./screen-transition";
import { warmCallsList } from "../calls-cache";
import { RouteLoading } from "./route-loading";
import {
  claimShell,
  releaseShell,
  shownClaim,
  type ShellClaim,
  type ShellClaims,
} from "./shell-claims";
import { SectionBoundary } from "../ui/section-boundary";
import {
  readAllowance,
  readCallSummary,
  readRecentCalls,
  type CallSummary,
} from "../dashboard/dashboard-data";
import {
  CREATE_ORGANISATION_EVENT,
  getShellState,
  markSidebar,
  OPEN_SWITCHER_EVENT,
  recentCallsForContext,
  RECENTS_CHANGED_EVENT,
  type ShellRecentCall,
  updateShellState,
} from "./shell-store";
import { ThemeToggle } from "./theme-toggle";
import { GuestSwitcher, WorkspaceSwitcher } from "./workspace-switcher";
import { WorkspacePicker } from "./workspace-picker";
import { Sheet } from "../ui/sheet";
import { allowEarlyConversationReads, dropEarlyReads } from "../early-reads";
import { dropInvite, refreshInvites, useInvites } from "./invites-store";
import {
  acceptInvite,
  OrgApiError,
  type PendingInvite,
} from "../organisation/organisation-api";
import { accountInitials } from "./account-initials";
import { useQuiet } from "./quiet";
import { useReportWaiting } from "../bug-report/open";
import { LocalSettingsButton } from "../live-data-banner";
import { AccountAvatarImage } from "../speaker-avatar";
import { useShellUpdates } from "./updates-store";
import { UpdatesBell } from "./updates-bell";
import { UpdateNotices } from "./update-notices";
import {
  isRelativeUpdateHref,
  type UpdateNotification,
} from "./updates-client";
import { ChatsTabIcon } from "../chats/chats-badge";
import type { Command } from "../ui/command-bar";
import { useRegisteredCommands } from "../ui/command-registry";
import { handOverLead } from "../leads/lead-handoff";
import { leavingOverlay } from "../ui/back-close";
import { tick } from "../ui/haptics";
import { LeadsTabIcon } from "../leads/leads-badge";
import { ReviewBarChip, ReviewRailLink } from "../review/review-badge";
import styles from "./lightbox-shell.module.css";

export type LightboxShellProps = {
  children: ReactNode;
  authenticated: boolean;
  /** The session is still being confirmed: show placeholders, never guest labels. */
  loading?: boolean;
  homeHref?: string;
  active?:
    | "dashboard"
    | "leads"
    | "chats"
    | "analyse"
    | "calls"
    | "account"
    | "organisation"
    | "prospects"
    | "coaching"
    | "insights"
    | "review";
  compactBusy?: boolean;
  mobileFit?: boolean;
  /**
   * Phones: the page takes the whole screen, without the top bar or the tab
   * bar (an open chat; owner, 22 Oct 2026). Its own header leads back.
   */
  immersive?: boolean;
  welcome?: boolean;
  heroStage?: "welcome" | "ready" | "processing" | "attention";
  /**
   * Names the page in the top bar when the content knows better than the
   * route, e.g. "Report" while a call's report is open.
   */
  pageName?: string;
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
      : // Short enough for a phone's bar; the panel says "Analysing your call".
        { title: "Analysing" };
  // The panel names what happened (failed, paused, needs attention).
  if (stage === "attention") return { title: "Your call" };
  if (stage === "welcome") return { title: "New analysis" };
  return null;
}

function resolvePageTitle(
  active: LightboxShellProps["active"],
  heading: PageHeading | null,
  pageName?: string,
): string | null {
  if (pageName) return pageName;
  if (active === "dashboard") return "Home";
  if (heading) return heading.title;
  if (active === "calls") return "Calls";
  if (active === "leads") return "Leads";
  if (active === "chats") return "Chats";
  if (active === "prospects") return "Prospects";
  if (active === "coaching") return "Coaching";
  if (active === "account") return "Account";
  if (active === "organisation") return "Organisation";
  if (active === "insights") return "Insights";
  if (active === "review") return "Review";
  // The studio names its stage once it loads; until then (and while a route
  // loads) the bar already says where you are, so nothing swaps in later.
  if (active === "analyse") return "New analysis";
  return null;
}

const inSettings = (pathname: string | null) =>
  pathname === "/settings" || (pathname?.startsWith("/settings/") ?? false);

const subscribeNothing = () => () => {};

// A rail icon's name for text readers and tests. Hidden inline, so it stays
// hidden even when the page draws before its stylesheet (dev recompiles);
// the visible label floats above every layer on hover or focus (rail-tip.tsx).
/** Every open lead (owner, 23 Oct 2026: "All leads one tap from anywhere"). */
const ALL_LEADS_HREF = "/leads?tab=all&stage=open";
/** The organisation hub's Team tab: members, invites and roles. */
const TEAM_HREF = "/organisation?tab=team";
/** Where each organisation setting lives in the hub (org-hub.tsx). */
const HUB = {
  rules: "/organisation?tab=leads&part=rules",
  stages: "/organisation?tab=leads&part=stages",
  apps: "/organisation?tab=connections&part=apps",
  callAi: "/organisation?tab=call-ai",
};

/**
 * Add lead (about 1,000 lines with the pipelines it reads) loads when it is
 * first wanted, not with every page (launch readiness, 23 Oct 2026); opening
 * + or choosing "Add a lead" fetches it first, so the form still opens at once.
 */
// Out of the start: each loads once the page is quiet, or when first opened
// (orchestrator, 24 Oct 2026: mid-tier phones took ~4.7 s to show Home).
const BugReportHost = dynamic(
  () =>
    import("../bug-report/bug-report-sheet").then(
      (module) => module.BugReportHost,
    ),
  { ssr: false },
);
const FeedbackHost = dynamic(
  () =>
    import("../feedback/feedback-prompt").then((module) => module.FeedbackHost),
  { ssr: false },
);
const SettingsMenu = dynamic(
  () => import("./settings-menu").then((module) => module.SettingsMenu),
  { ssr: false },
);
const CommandBar = dynamic(
  () => import("../ui/command-bar").then((module) => module.CommandBar),
  { ssr: false },
);
const CreateOrganisationDialog = dynamic(
  () =>
    import("./create-organisation-dialog").then(
      (module) => module.CreateOrganisationDialog,
    ),
  { ssr: false },
);

const loadCaptureDialogs = () => import("../leads/capture-dialogs");
const AddLeadDialog = dynamic(
  () => loadCaptureDialogs().then((module) => module.AddLeadDialog),
  { ssr: false },
);

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
  immersive = false,
  welcome = false,
  heroStage,
  pageName,
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
  // Phones: the tab bar's + opens Add (a lead or a call), and Add lead its
  // quick form over the current screen (owner, 22 Oct). Each opening of the
  // form is a new round, so it always starts empty.
  const [addOpen, setAddOpen] = useState(false);
  const [leadForm, setLeadForm] = useState({ open: false, round: 0 });
  const router = useAppRouter();
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
      markRead={markRead}
    />
  ) : null;
  const profile = useShellProfile(
    authenticated,
    process.env.NODE_ENV !== "test",
  );
  // Your own name with capitals too (owner, 22 Oct).
  const profileName = profile?.name?.trim() ? withCapitals(profile.name) : null;
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
  // Moving between places animates the page area; the places one tap away
  // are made ready while the app is quiet (owner, 20 Oct).
  const pageRef = useRef<HTMLElement | null>(null);
  const standIn = useScreenMotion(pageRef, pathname);
  // While a tapped place's outline stands in, the rail, tab bar and title
  // already show that place, so their highlight glides with the move.
  const shownPath = standIn ?? pathname;
  const place = shellActiveFor(shownPath, active);
  // Every Settings page says Settings, even while its section loads.
  const pageTitle = resolvePageTitle(
    place,
    heading,
    pageName ?? (inSettings(shownPath) ? "Settings" : undefined),
  );
  const phoneTab = phoneTabFor(shownPath, active);
  // Phones: the large title shrinks once the page scrolls and the bar's
  // hairline appears, as iOS does. The bar keeps its height, so nothing
  // under it moves; an attribute, not state, so scrolling never re-renders.
  const shellRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const shell = shellRef.current;
    if (!shell) return;
    shell.removeAttribute("data-scrolled");
    const onScroll = (event: Event) => {
      const target = event.target;
      const top =
        target === document
          ? window.scrollY
          : target instanceof HTMLElement && target.matches(".studio-main")
            ? target.scrollTop
            : null;
      if (top !== null) shell.toggleAttribute("data-scrolled", top > 8);
    };
    document.addEventListener("scroll", onScroll, {
      capture: true,
      passive: true,
    });
    return () =>
      document.removeEventListener("scroll", onScroll, { capture: true });
  }, [pathname]);
  // A light tap in the hand when the phone's tab changes, as iOS does.
  const tapTab = (tab: PhoneTab) => () => {
    if (tab !== phoneTab) tick();
  };
  // Phones call the dashboard Home, as its tab does (owner, 17 Oct).
  const barTitle = place === "dashboard" && !pageName ? "Home" : pageTitle;
  // The selected capsule glides to the new place, on the rail and the tabs.
  const tabBarRef = useRef<HTMLElement | null>(null);
  useGlide(railRef, `.${styles.stripBtnActive} .${styles.railPill}`, place);
  useGlide(tabBarRef, `[aria-current="page"] .${styles.tabPill}`, phoneTab);
  // ...and, once quiet, the calls list Home and Calls open with.
  usePlacePrefetch(authenticated && !loading, () => {
    void warmCallsList(recentContextKey);
  });
  useHoverPrefetch(authenticated);

  const toggleCollapsed = () => {
    const next = !collapsed;
    focusTogglePendingRef.current = true;
    setCollapsed(next);
    updateShellState({ collapsed: next });
    markSidebar(next);
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

  // Ctrl K or ⌘K opens the command bar from anywhere (slice 9 of the new
  // map): places, actions, settings, leads and calls in one search.
  const [commandOpen, setCommandOpen] = useState(false);
  const quiet = useQuiet();
  // Report a problem before the reporter loaded: load it now.
  const reportWaiting = useReportWaiting();
  const signedIn = authenticated && !loading;
  useEffect(() => {
    if (!signedIn) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [signedIn]);

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

  /** True once the page is moving into the workspace. */
  async function handleSelectWorkspace(
    tenantId: string,
    next?: string,
  ): Promise<boolean> {
    if (tenantId === effectiveTenantId) {
      setSwitcherOpen(false);
      if (next) window.location.assign(next);
      return Boolean(next);
    }
    // Nothing read for the old workspace may answer a read for the new one,
    // and the next page reads conversations only once Sales Xray is known on.
    dropEarlyReads();
    allowEarlyConversationReads(false);
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
        if (next) window.location.assign(next);
        else window.location.reload();
        return true;
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
        run: () => void handleSelectWorkspace(tenantId, next),
      },
    });
    return false;
  }

  // Joining from the menu: accept (one key per invitation, so a retry is
  // safe), then move into the organisation.
  const [joining, setJoining] = useState<string | null>(null);
  const joinKeys = useRef(new Map<string, string>());
  async function joinInvite(invite: PendingInvite) {
    if (joining) return;
    setJoining(invite.inviteId);
    const key = joinKeys.current.get(invite.inviteId) ?? crypto.randomUUID();
    joinKeys.current.set(invite.inviteId, key);
    try {
      const joined = await acceptInvite(invite.inviteId, key);
      dropInvite(invite.inviteId);
      if (await handleSelectWorkspace(joined.tenantId)) return;
    } catch (error) {
      // Used, expired or withdrawn: the list is read again.
      const closed =
        error instanceof OrgApiError && [404, 409].includes(error.status);
      if (closed) refreshInvites();
      notify({
        id: "invite-join",
        tone: "error",
        title: `Couldn’t join ${invite.organisationName}`,
        message:
          error instanceof OrgApiError
            ? error.message
            : "Check your connection and try again.",
        action: closed
          ? undefined
          : { label: "Try again", run: () => void joinInvite(invite) },
      });
    }
    setJoining(null);
  }
  const [createOpen, setCreateOpen] = useState(false);
  const [workspaceSheetOpen, setWorkspaceSheetOpen] = useState(false);

  // Phones: the avatar in the top bar opens You (there is no More tab).
  function toggleAccountSheet(event: MouseEvent<HTMLElement>) {
    if (!authenticated) return;
    accountAnchorRef.current = event.currentTarget;
    setAccountView("main");
    setAccountCardOpen((open) => !open);
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
  // The company view (Insights) is for the organisation's owners and admins.
  const orgAdmin = workspaces.some(
    (workspace) =>
      workspace.tenant_id === effectiveTenantId &&
      workspace.kind === "organisation" &&
      (workspace.role === "owner" || workspace.role === "admin"),
  );
  // One way into the organisation: its hub, every area a tab (owner, 23 Oct
  // 2026: "if organisation is clicked there should be clearly visible all
  // management options").
  const orgHere = place === "organisation";
  const branding = useBranding(inOrganisation);
  // Confirmed signed out (not merely unknown yet): nothing personal to show.
  const guest = !authenticated && !sessionPending && !loading;
  // Like the updates and allowance reads, off under test (pages count reads).
  const invites = useInvites(
    authenticated && !loading && process.env.NODE_ENV !== "test",
  );
  // The Leads tab badge reads on the same terms.
  const leadsBadgeLive =
    authenticated && !loading && process.env.NODE_ENV !== "test";
  useEffect(() => {
    if (!invites.live) return;
    const open = () => setCreateOpen(true);
    window.addEventListener(CREATE_ORGANISATION_EVENT, open);
    return () => window.removeEventListener(CREATE_ORGANISATION_EVENT, open);
  }, [invites.live]);
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

  const go = useCallback(
    (href: string) => {
      if (router) router.push(href);
      else window.location.assign(href);
    },
    [router],
  );
  const openLeadForm = useCallback(() => {
    void loadCaptureDialogs();
    setLeadForm((form) => ({ open: true, round: form.round + 1 }));
  }, []);
  // Add lead is one tap away while + is open: fetch the form then.
  useEffect(() => {
    if (addOpen) void loadCaptureDialogs();
  }, [addOpen]);
  const commands = useMemo<Command[]>(() => {
    const place = (
      label: string,
      href: string,
      icon: ReactNode,
      keywords?: string,
    ): Command => ({
      id: `go:${href}`,
      group: "Go to",
      label,
      keywords,
      icon,
      run: () => go(href),
    });
    const setting = (
      label: string,
      href: string,
      icon: ReactNode,
      hint: string,
    ): Command => ({
      id: `settings:${href}`,
      group: "Settings",
      label,
      hint,
      icon,
      run: () => go(href),
    });
    return [
      place("Home", "/dashboard", <LayoutGrid size={17} />, "dashboard sales"),
      place("Leads", "/leads", <Contact size={17} />, "pipeline stages"),
      place("Chats", "/chats", <MessagesSquare size={17} />, "whatsapp inbox"),
      place("Calls", "/analysis/calls", <AudioLines size={17} />, "reports"),
      place("Coaching", "/coaching", <GraduationCap size={17} />),
      place("Prospects", "/prospects", <Users size={17} />),
      ...(inOrganisation
        ? [
            place(
              "All leads",
              ALL_LEADS_HREF,
              <Rows3 size={17} />,
              "every open lead list",
            ),
            place(
              "Team",
              TEAM_HREF,
              <UsersRound size={17} />,
              "members invites roles organisation",
            ),
            place(
              "Organisation",
              "/organisation",
              <Building2 size={17} />,
              "team analytics insights company settings",
            ),
          ]
        : []),
      ...(orgAdmin
        ? [
            place(
              "Insights",
              "/organisation/insights",
              <BarChart3 size={17} />,
              "company",
            ),
          ]
        : []),
      ...(inOrganisation
        ? [
            {
              id: "add:lead",
              group: "Actions",
              label: "Add a lead",
              hint: "A name and a number is enough",
              icon: <UserPlus size={17} />,
              run: openLeadForm,
            },
          ]
        : []),
      {
        id: "add:call",
        group: "Actions",
        label: "Analyse a call",
        hint: "Record or upload a call for its report",
        icon: <AudioLines size={17} />,
        keywords: "new analysis upload recording",
        run: () => go(newAnalysisHref),
      },
      setting(
        "Profile",
        "/settings/profile",
        <UserRound size={17} />,
        "Your name, photo, phone and theme",
      ),
      setting(
        "Selling",
        "/settings/selling",
        <PhoneCall size={17} />,
        "Taking new leads, calling from your phone, alerts",
      ),
      setting(
        "Phone & alerts",
        "/settings/notifications",
        <Bell size={17} />,
        "Phone setup, alerts, vibration and usage analytics",
      ),
      ...(orgAdmin
        ? [
            setting(
              "Team & roles",
              TEAM_HREF,
              <Users size={17} />,
              "Members, invites and who can do what",
            ),
            setting(
              "Lead rules",
              HUB.rules,
              <Users size={17} />,
              "Who gets new leads, limits and work hours",
            ),
            setting(
              "Lead stages",
              HUB.stages,
              <Layers size={17} />,
              "Stages and pipelines",
            ),
            setting(
              "Connected apps",
              HUB.apps,
              <Plug size={17} />,
              "Lead ads, WhatsApp, Messenger and Instagram",
            ),
            setting(
              "AI on calls",
              HUB.callAi,
              <AudioLines size={17} />,
              "How much AI reads each seller's calls",
            ),
          ]
        : []),
      setting(
        "All settings",
        "/settings",
        <Settings size={17} />,
        "Account, organisation, connections, this device",
      ),
      setting(
        "Help & support",
        "/settings/help",
        <LifeBuoy size={17} />,
        "First call guide and support",
      ),
    ];
  }, [go, inOrganisation, newAnalysisHref, openLeadForm, orgAdmin]);
  // Screens add their own commands and searches while they are on screen
  // (ui/command-registry.ts).
  const registered = useRegisteredCommands();
  const allCommands = useMemo(
    () => [...commands, ...registered.commands],
    [commands, registered.commands],
  );
  const leadsSearchedElsewhere = registered.keys.includes("leads");
  // Leads that match (the team's for owners and admins, your own for
  // sellers), recent calls by name, and a step that searches every call;
  // then whatever the screens on show find.
  const searchEverything = useCallback(
    async (text: string, signal: AbortSignal): Promise<Command[]> => {
      const lower = text.toLocaleLowerCase();
      const calls = visibleRecentCalls
        .filter((call) => call.name.toLocaleLowerCase().includes(lower))
        .slice(0, 3)
        .map<Command>((call) => ({
          id: `call:${call.id}`,
          group: "Calls",
          label: call.name,
          hint: call.date,
          icon: <AudioLines size={17} />,
          run: () => go(callHref(call.id)),
        }));
      const everyCall: Command = {
        id: "calls:search",
        group: "Calls",
        label: `Search calls for “${text}”`,
        icon: <Search size={17} />,
        run: () => go(`${CALLS_PATH}?q=${encodeURIComponent(text)}`),
      };
      let leads: Command[] = [];
      if (inOrganisation && !leadsSearchedElsewhere)
        try {
          // Loaded on the first search, not with every page.
          const { leadLink, readLeads } = await import("../leads/leads-client");
          const page = await readLeads(
            { scope: orgAdmin ? "team" : "mine", search: text },
            signal,
          );
          leads = page.leads.slice(0, 5).map((lead) => ({
            id: `lead:${lead.lead_id}`,
            group: "Leads",
            label: withCapitals(lead.name),
            hint: [lead.stage_label, lead.company ?? lead.city]
              .filter(Boolean)
              .join(" · "),
            icon: <UserRound size={17} />,
            // The lead's own address: Leads with its sheet up.
            run: () => go(leadLink(lead.lead_id)),
          }));
        } catch {
          // A failed read shows the calls only.
        }
      const found = await Promise.allSettled(
        registered.searches.map((search) => search(text, signal)),
      );
      const theirs = found.flatMap((result) =>
        result.status === "fulfilled" ? result.value : [],
      );
      return [...leads, ...theirs, ...calls, everyCall];
    },
    [
      go,
      inOrganisation,
      leadsSearchedElsewhere,
      orgAdmin,
      registered.searches,
      visibleRecentCalls,
    ],
  );
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
  // Phones: the bar's workspace name opens the Workspace sheet when there
  // is another workspace, an invitation or Create to offer.
  const switchable = workspaces.filter(
    (workspace) => workspace.sales_xray_enabled,
  );
  const canSwitchHere =
    authenticated &&
    !chromePending &&
    Boolean(workspaceLabel) &&
    (switchable.length > 1 || invites.invites.length > 0 || invites.live);
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
      // A tenant id, or { tenantId, next } to land on a given page.
      const detail = (event as CustomEvent<unknown>).detail;
      const target =
        typeof detail === "string"
          ? { tenantId: detail, next: undefined }
          : detail && typeof detail === "object"
            ? (detail as { tenantId?: unknown; next?: unknown })
            : null;
      if (typeof target?.tenantId === "string")
        void selectWorkspaceRef.current(
          target.tenantId,
          typeof target.next === "string" && /^\/(?!\/)/.test(target.next)
            ? target.next
            : undefined,
        );
    };
    window.addEventListener(SELECT_WORKSPACE_EVENT, onSelect);
    return () => window.removeEventListener(SELECT_WORKSPACE_EVENT, onSelect);
  }, []);

  return (
    <div
      ref={shellRef}
      className={`${styles.shell} ${collapsed ? styles.collapsed : ""}`}
      data-lightbox-shell
      data-authenticated={authenticated}
      data-loading={chromePending || undefined}
      data-sidebar-collapsed={collapsed}
      data-compact-busy={compactBusy}
      data-mobile-fit={mobileFit}
      data-immersive={immersive || undefined}
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
            <ScreenLink
              className={`${styles.stripBtn}${place === "dashboard" ? ` ${styles.stripBtnActive}` : ""}`}
              href="/dashboard"
              aria-label="Home"
              data-rail-tip="Home"
              aria-current={place === "dashboard" ? "page" : undefined}
            >
              <LayoutGrid size={20} strokeWidth={1.75} aria-hidden="true" />
              <span className={styles.railPill} aria-hidden="true" />
              <span style={RAIL_NAME_STYLE}>Home</span>
            </ScreenLink>
            <ScreenLink
              className={`${styles.stripBtn}${place === "leads" ? ` ${styles.stripBtnActive}` : ""}`}
              href="/leads"
              aria-label="Leads"
              data-rail-tip="Leads"
              aria-current={place === "leads" ? "page" : undefined}
            >
              <LeadsTabIcon
                size={20}
                strokeWidth={1.75}
                live={leadsBadgeLive}
              />
              <span className={styles.railPill} aria-hidden="true" />
              <span style={RAIL_NAME_STYLE}>Leads</span>
            </ScreenLink>
            {/* Every open lead, one click from anywhere; the open sidebar only. */}
            {inOrganisation ? (
              <ScreenLink
                className={`${styles.stripBtn} ${styles.stripSub}`}
                href={ALL_LEADS_HREF}
              >
                <Rows3 size={16} strokeWidth={1.75} aria-hidden="true" />
                All leads
              </ScreenLink>
            ) : null}
            <ScreenLink
              className={`${styles.stripBtn}${place === "chats" ? ` ${styles.stripBtnActive}` : ""}`}
              href="/chats"
              aria-label="Chats"
              data-rail-tip="Chats"
              aria-current={place === "chats" ? "page" : undefined}
            >
              <ChatsTabIcon
                size={20}
                strokeWidth={1.75}
                live={leadsBadgeLive}
              />
              <span className={styles.railPill} aria-hidden="true" />
              <span style={RAIL_NAME_STYLE}>Chats</span>
            </ScreenLink>
            <ScreenLink
              className={`${styles.stripBtn}${place === "analyse" ? ` ${styles.stripBtnActive}` : ""}`}
              href={newAnalysisHref}
              aria-label="New analysis"
              data-rail-tip="New analysis"
              aria-current={place === "analyse" ? "page" : undefined}
            >
              <Plus size={20} strokeWidth={1.75} aria-hidden="true" />
              <span className={styles.railPill} aria-hidden="true" />
              <span style={RAIL_NAME_STYLE}>New analysis</span>
            </ScreenLink>
            <ScreenLink
              className={`${styles.stripBtn}${place === "calls" ? ` ${styles.stripBtnActive}` : ""}`}
              href="/analysis/calls"
              aria-label="Calls"
              data-rail-tip="Calls"
              aria-current={place === "calls" ? "page" : undefined}
            >
              <AudioLines size={20} strokeWidth={1.75} aria-hidden="true" />
              <span className={styles.railPill} aria-hidden="true" />
              <span style={RAIL_NAME_STYLE}>Calls</span>
            </ScreenLink>
            {/* Owner, 23 Oct 2026: team and organisation were "too hidden";
                the hub sits right after the daily places. */}
            {inOrganisation || place === "organisation" ? (
              <ScreenLink
                className={`${styles.stripBtn}${orgHere ? ` ${styles.stripBtnActive}` : ""}`}
                href="/organisation"
                aria-label="Organisation"
                data-rail-tip="Organisation"
                aria-current={orgHere ? "page" : undefined}
              >
                <Building2 size={20} strokeWidth={1.75} aria-hidden="true" />
                <span className={styles.railPill} aria-hidden="true" />
                <span style={RAIL_NAME_STYLE}>Organisation</span>
              </ScreenLink>
            ) : null}
            <ScreenLink
              className={`${styles.stripBtn}${place === "prospects" ? ` ${styles.stripBtnActive}` : ""}`}
              href="/prospects"
              aria-label="Prospects"
              data-rail-tip="Prospects"
              aria-current={place === "prospects" ? "page" : undefined}
            >
              <Users size={20} strokeWidth={1.75} aria-hidden="true" />
              <span className={styles.railPill} aria-hidden="true" />
              <span style={RAIL_NAME_STYLE}>Prospects</span>
            </ScreenLink>
            <ScreenLink
              className={`${styles.stripBtn}${place === "coaching" ? ` ${styles.stripBtnActive}` : ""}`}
              href="/coaching"
              aria-label="Coaching"
              data-rail-tip="Coaching"
              aria-current={place === "coaching" ? "page" : undefined}
            >
              <GraduationCap size={20} strokeWidth={1.75} aria-hidden="true" />
              <span className={styles.railPill} aria-hidden="true" />
              <span style={RAIL_NAME_STYLE}>Coaching</span>
            </ScreenLink>
            {orgAdmin || place === "insights" ? (
              <ScreenLink
                className={`${styles.stripBtn}${place === "insights" ? ` ${styles.stripBtnActive}` : ""}`}
                href="/organisation/insights"
                aria-label="Insights"
                data-rail-tip="Insights"
                aria-current={place === "insights" ? "page" : undefined}
              >
                <BarChart3 size={20} strokeWidth={1.75} aria-hidden="true" />
                <span className={styles.railPill} aria-hidden="true" />
                <span style={RAIL_NAME_STYLE}>Insights</span>
              </ScreenLink>
            ) : null}
            {/* Gold reviewers (owner, 19 Oct); nothing for anyone else. */}
            <ReviewRailLink
              live={leadsBadgeLive}
              className={styles.stripBtn}
              activeClassName={styles.stripBtnActive}
              nameStyle={RAIL_NAME_STYLE}
            />
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

        {/* Open, the sidebar names every place: no hover labels then. */}
        <RailTip rail={railRef} off={!collapsed} />

        {/* 248px Panel */}
        <div
          id="sales-xray-sidebar-panel"
          className={styles.panel}
          inert={collapsed}
        >
          <div className={styles.panelHeader}>
            {guest ? (
              <GuestSwitcher href={accountHref} onSignIn={openAccount} />
            ) : (
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
                invites={invites.invites}
                joining={joining}
                onJoin={(invite) => void joinInvite(invite)}
                onCreate={
                  invites.live
                    ? () => {
                        setSwitcherOpen(false);
                        setCreateOpen(true);
                      }
                    : undefined
                }
              />
            )}
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

          {/* Enter opens Calls filtered by the text; the box then clears.
              Signed out there are no calls to search. */}
          {!guest && (
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
            </Form>
          )}

          {/* Recents Section */}
          {salesXrayEnabled && !guest && (
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
      <div className={styles.content} data-shell-content="">
        <header className={styles.mobileBar}>
          {/* r17: the lens, then where you are: workspace over page title. */}
          {workspaceLabel || pageTitle ? (
            <div className={styles.mobileWorkspace}>
              {/* Signed in, your own face opens the account menu (Log out)
                  from every screen; signed out, the brand mark goes home. */}
              {guest ? (
                <BrandLockup href={homeHref} markOnly />
              ) : (
                <button
                  type="button"
                  className={styles.mobileAvatar}
                  onClick={toggleAccountSheet}
                  aria-label="Account and log out"
                  aria-haspopup="dialog"
                  aria-expanded={accountCardOpen && authenticated}
                  data-pending={chromePending ? "" : undefined}
                >
                  <span aria-hidden="true">
                    {/* Until the profile arrives: the circle only, never a stray dot. */}
                    {chromePending || !profile ? null : (
                      <AccountAvatarImage
                        key={profile?.email ?? ""}
                        photoUrl={profile?.photo_url}
                      >
                        {accountInitials(
                          profileName,
                          profile?.email ?? null,
                        ) || <UserRound size={16} />}
                      </AccountAvatarImage>
                    )}
                  </span>
                </button>
              )}
              {/* Where you are. Tapping it switches workspace in one
                  step when there is anywhere else to go (owner, 20 Oct:
                  "workspaces shifter needs to be made in a far better way"). */}
              {canSwitchHere ? (
                <button
                  type="button"
                  className={styles.mobilePlace}
                  onClick={() => setWorkspaceSheetOpen(true)}
                  aria-haspopup="dialog"
                  aria-expanded={workspaceSheetOpen}
                  aria-label={`Workspace: ${workspaceLabel}. Switch workspace`}
                  title={`Workspace: ${workspaceLabel}`}
                >
                  <small className={styles.mobileContext}>
                    {workspaceLabel}
                    <ChevronDown
                      size={12}
                      strokeWidth={2.5}
                      aria-hidden="true"
                    />
                  </small>
                  <b>{barTitle ?? workspaceLabel}</b>
                </button>
              ) : (
                <span
                  title={
                    workspaceLabel ? `Workspace: ${workspaceLabel}` : undefined
                  }
                >
                  {/* Two lines from the first paint: the workspace line is a
                      placeholder while it loads, so the title never drops. */}
                  <small className={styles.mobileContext}>
                    {pageTitle
                      ? (workspaceLabel ?? "Sales X-Ray")
                      : "Workspace"}
                  </small>
                  <b>{barTitle ?? workspaceLabel}</b>
                </span>
              )}
            </div>
          ) : (
            <BrandLockup href={homeHref} />
          )}
          {/* You opens from the avatar on the left, not from here too. */}
          <div className={styles.barActions}>
            <ReviewBarChip live={leadsBadgeLive} />
            {guest ? null : (
              <button
                type="button"
                className={styles.barSearch}
                onClick={() => setCommandOpen(true)}
                aria-label="Search"
                aria-haspopup="dialog"
                aria-expanded={commandOpen}
              >
                <Search size={20} aria-hidden="true" />
              </button>
            )}
            {bell}
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
                    {workspaceLabel ?? "Sales X-Ray"}
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
            {guest ? null : (
              <button
                type="button"
                className={styles.commandButton}
                onClick={() => setCommandOpen(true)}
                aria-haspopup="dialog"
                aria-expanded={commandOpen}
                aria-keyshortcuts="Control+K Meta+K"
              >
                <Search size={15} aria-hidden="true" />
                Search
                <kbd aria-hidden="true">{shortcut}</kbd>
              </button>
            )}
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
        <main id="main-content" ref={pageRef} className={styles.main}>
          {/* A page that fails leaves the shell working: navigation, Recents. */}
          <SectionBoundary
            name="This screen"
            note="Your calls and reports are safe."
            resetKey={pathname}
          >
            {/* A tapped place shows its outline at once, while the router
                fetches it; the page underneath stays mounted until then. */}
            {standIn ? (
              <StandInContext.Provider value>
                <RouteLoading pathname={standIn} />
              </StandInContext.Provider>
            ) : null}
            <div
              className={styles.pageSlot}
              data-page-slot=""
              data-standing-in={standIn ? "" : undefined}
            >
              {children}
            </div>
          </SectionBoundary>
        </main>
      </div>
      {/* The new map (owner, 22 Oct 2026): five tabs on phones, Home, Leads,
          + (Add), Chats and Calls. Your avatar in the top bar opens You (your
          settings, the organisation's, the other places, Log out), so there
          is no More tab. */}
      <nav
        ref={tabBarRef}
        className={styles.bottomNav}
        aria-label="Mobile Sales Xray navigation"
      >
        <ScreenLink
          className={styles.bottomLink}
          href="/dashboard"
          onClick={tapTab("dashboard")}
          aria-current={phoneTab === "dashboard" ? "page" : undefined}
        >
          <LayoutGrid size={20} aria-hidden="true" />
          <span className={styles.tabPill} aria-hidden="true" />
          <span>Home</span>
        </ScreenLink>
        {/* Signed out, Leads and Calls only lead to a sign-in prompt (B22). */}
        {guest ? null : (
          <ScreenLink
            className={styles.bottomLink}
            href="/leads"
            onClick={tapTab("leads")}
            aria-current={phoneTab === "leads" ? "page" : undefined}
          >
            <LeadsTabIcon size={20} live={leadsBadgeLive} />
            <span className={styles.tabPill} aria-hidden="true" />
            <span>Leads</span>
          </ScreenLink>
        )}
        {/* Owner, 22 Oct: the + asks what to add (a lead or a call) instead
            of jumping straight to call analysis. A visitor can only analyse
            a call, so theirs still goes straight there. */}
        {guest ? (
          <ScreenLink
            className={`${styles.bottomLink} ${styles.bottomNew}`}
            href={newAnalysisHref}
            aria-label="New analysis"
            aria-current={phoneTab === "new" ? "page" : undefined}
          >
            <span className={styles.newMark} aria-hidden="true">
              <Plus size={18} strokeWidth={2.25} />
            </span>
            <span className={styles.tabPill} aria-hidden="true" />
            <span>New</span>
          </ScreenLink>
        ) : (
          <button
            type="button"
            className={`${styles.bottomLink} ${styles.bottomNew}`}
            onClick={() => {
              tick();
              setAddOpen(true);
            }}
            aria-label="Add a lead or a call"
            aria-haspopup="dialog"
            aria-expanded={addOpen}
            aria-current={phoneTab === "new" ? "page" : undefined}
          >
            <span className={styles.newMark} aria-hidden="true">
              <Plus size={18} strokeWidth={2.25} />
            </span>
            <span className={styles.tabPill} aria-hidden="true" />
            <span>Add</span>
          </button>
        )}
        {/* Chats has its own tab and its own unread count. */}
        {guest ? null : (
          <ScreenLink
            className={styles.bottomLink}
            href="/chats"
            onClick={tapTab("chats")}
            aria-current={phoneTab === "chats" ? "page" : undefined}
          >
            <ChatsTabIcon size={20} live={leadsBadgeLive} />
            <span className={styles.tabPill} aria-hidden="true" />
            <span>Chats</span>
          </ScreenLink>
        )}
        {guest ? null : (
          <ScreenLink
            className={styles.bottomLink}
            href="/analysis/calls"
            onClick={tapTab("calls")}
            aria-current={phoneTab === "calls" ? "page" : undefined}
          >
            <AudioLines size={20} aria-hidden="true" />
            <span className={styles.tabPill} aria-hidden="true" />
            <span>Calls</span>
          </ScreenLink>
        )}
        {/* Signed out shows Sign in (the phone app has its own sign-in
            screen, so it hides this). */}
        {guest ? (
          <ScreenLink
            className={`${styles.bottomLink} sx-web-only`}
            href={accountHref}
            onClick={openAccount}
          >
            <LogIn size={20} aria-hidden="true" />
            <span className={styles.tabPill} aria-hidden="true" />
            <span>Sign in</span>
          </ScreenLink>
        ) : null}
        {/* Local live-data development only; never on a served site. */}
        <LocalSettingsButton className={styles.bottomLink} />
      </nav>
      <SettingsDialogHost />
      {/* Mounted only while open, so each opening starts fresh. */}
      {invites.live && createOpen ? (
        <CreateOrganisationDialog
          open
          onClose={() => setCreateOpen(false)}
          onCreated={(tenantId) =>
            void handleSelectWorkspace(
              tenantId,
              "/organisation?tab=members",
            ).then((moving) => {
              // Created, but the switch failed: its corner card offers a retry.
              if (!moving) setCreateOpen(false);
            })
          }
        />
      ) : null}
      <UpdateNotices
        updates={updates}
        contextKey={updatesContextKey}
        openNews={openNews}
        openEvent={navigateEvent}
      />
      {authenticated ? (
        <Sheet
          open={workspaceSheetOpen}
          onClose={() => setWorkspaceSheetOpen(false)}
          title="Workspace"
          description="Where your calls, leads and reports live."
        >
          <WorkspacePicker
            workspaces={switchable}
            currentId={effectiveTenantId}
            branding={branding}
            personName={profileName}
            onSelect={(tenantId) => {
              setWorkspaceSheetOpen(false);
              void handleSelectWorkspace(tenantId);
            }}
            onKeep={() => setWorkspaceSheetOpen(false)}
            invites={invites.invites}
            joining={joining}
            onJoin={(invite) => void joinInvite(invite)}
            onCreate={
              invites.live
                ? () => {
                    setWorkspaceSheetOpen(false);
                    setCreateOpen(true);
                  }
                : undefined
            }
          />
        </Sheet>
      ) : null}
      {/* Mounted while signed in (once quiet, or at the first open), so
          the phone sheet can slide away. */}
      {authenticated && (quiet || accountCardOpen) ? (
        <SettingsMenu
          initialView={accountView}
          open={accountCardOpen}
          anchorRef={accountAnchorRef}
          onClose={closeAccountCard}
          name={profileName}
          email={profile?.email ?? null}
          photoUrl={profile?.photo_url}
          allowance={shownAllowance}
          organisation={inOrganisation}
          insights={orgAdmin}
          workspaces={workspaces.filter(
            (workspace) => workspace.sales_xray_enabled,
          )}
          currentWorkspaceId={effectiveTenantId}
          onSelectWorkspace={(tenantId) => void handleSelectWorkspace(tenantId)}
          invitesWaiting={invites.invites.length}
          onCreateOrganisation={
            invites.live ? () => setCreateOpen(true) : undefined
          }
        />
      ) : null}
      {guest || !(quiet || commandOpen) ? null : (
        <CommandBar
          open={commandOpen}
          onClose={() => setCommandOpen(false)}
          commands={allCommands}
          search={searchEverything}
        />
      )}
      {guest || !(quiet || reportWaiting) ? null : <BugReportHost />}
      {guest || !quiet ? null : <FeedbackHost />}
      {guest ? null : (
        <AddSheet
          open={addOpen}
          onClose={() => setAddOpen(false)}
          leadsHere={inOrganisation}
          callHref={newAnalysisHref}
          onAddLead={() => {
            setAddOpen(false);
            setLeadForm((form) => ({ open: true, round: form.round + 1 }));
          }}
        />
      )}
      {/* Mounted from the first Add lead on, so it can slide away. */}
      {leadForm.round > 0 ? (
        <AddLeadDialog
          key={leadForm.round}
          open={leadForm.open}
          canManage={orgAdmin}
          onClose={() => setLeadForm((form) => ({ ...form, open: false }))}
          onAdded={(leadId) => {
            setLeadForm((form) => ({ ...form, open: false }));
            // The new lead opens on Leads, ready to call.
            handOverLead(leadId);
            if (shownPath !== "/leads" && !shownPath?.startsWith("/leads/")) {
              leavingOverlay();
              router?.push("/leads");
            }
          }}
        />
      ) : null}
    </div>
  );
}

type ShellPage = Omit<LightboxShellProps, "children">;

type ShellRegistry = {
  claim: (id: string, claim: ShellClaim<ShellPage>) => void;
  release: (id: string) => void;
};

const PersistentShellContext = createContext<ShellRegistry | null>(null);

/** True inside the outline standing in for a tapped place. */
const StandInContext = createContext(false);

/**
 * One app frame (sidebar, top bar, page area) that stays mounted while the
 * person moves between app pages, so navigation swaps only the page content.
 * Pages keep rendering <LightboxShell>; inside this frame it describes the
 * chrome (active item, heading, allowance) instead of drawing a second one.
 */
export function PersistentShell({ children }: { children: ReactNode }) {
  // Pages hand the frame their settings before paint; until then it starts
  // from what the session already knows, so a page drawn on the server with
  // its session (dev) arrives with its full bar, not loading placeholders.
  const access = useWorkspaceAccess();
  const [first] = useState<ShellPage>(() => ({
    authenticated: access?.authenticated === true,
    loading: !access || access.status === "loading",
  }));
  // Every mounted page and stand-in outline claims the frame; see
  // shell-claims.ts for which one it shows.
  const [claims, setClaims] = useState<ShellClaims<ShellPage>>([]);
  const registry = useMemo<ShellRegistry>(
    () => ({
      claim: (id, claim) => setClaims((list) => claimShell(list, id, claim)),
      release: (id) => setClaims((list) => releaseShell(list, id)),
    }),
    [],
  );
  const page = shownClaim(claims)?.page ?? first;
  // A loading screen can't know the session, but the frame does: once the
  // session is confirmed, a screen that is still loading never turns the
  // bar back into placeholders (no flicker between pages, owner 20 Oct).
  const signedIn =
    access?.authenticated === true && access.status !== "loading";
  const shown =
    page.loading && signedIn
      ? { ...page, loading: false, authenticated: true }
      : page;
  return (
    <PersistentShellContext.Provider value={registry}>
      <LightboxShellFrame {...shown}>{children}</LightboxShellFrame>
    </PersistentShellContext.Provider>
  );
}

function ShellPageSettings({
  registry,
  children,
  ...page
}: LightboxShellProps & { registry: ShellRegistry }) {
  const id = useId();
  const standIn = useContext(StandInContext);
  // The chrome settings are plain data, so their serialised form is both the
  // change signal and the value handed to the frame.
  const settings = JSON.stringify(page);
  // Before paint, so the frame never shows the previous page's chrome.
  useLayoutEffect(() => {
    registry.claim(id, { page: JSON.parse(settings) as ShellPage, standIn });
  }, [registry, id, settings, standIn]);
  // Only on leaving: a settings change updates the claim in its place.
  useLayoutEffect(() => () => registry.release(id), [registry, id]);
  return children;
}

export function LightboxShell(props: LightboxShellProps) {
  const registry = useContext(PersistentShellContext);
  if (!registry) return <LightboxShellFrame {...props} />;
  return <ShellPageSettings registry={registry} {...props} />;
}
