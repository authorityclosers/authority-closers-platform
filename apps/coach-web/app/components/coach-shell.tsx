"use client";
import Link from "next/link";
import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type ReactNode,
} from "react";
import { usePathname } from "next/navigation";
import { AcademyMark } from "@ac/ui";
import {
  BookOpen,
  ChevronRight,
  ClipboardCheck,
  ChevronDown,
  LogOut,
  LayoutDashboard,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Settings2,
  X,
} from "lucide-react";
import { CoachPreferencesProvider } from "./coach-preferences";
import {
  AdminSessionProvider,
  type AdminSessionState,
  useAdminSession,
} from "@ac/operations-web/session";
export const coachNavigation = [
  { href: "/studio", label: "Dashboard", icon: LayoutDashboard },
  { href: "/studio/programs", label: "Courses", icon: BookOpen },
  { href: "/studio/publication", label: "Publication", icon: ClipboardCheck },
  { href: "/studio/settings", label: "Settings", icon: Settings2 },
] as const;

const coachThemeBridge = {
  "--theme-action": "var(--signal)",
  "--theme-action-hover": "var(--signal-hover)",
  "--theme-action-text": "var(--signal-ink)",
  "--theme-surface": "var(--panel)",
  "--theme-surface-subtle": "var(--panel-soft)",
  "--theme-text": "var(--text)",
  "--theme-text-muted": "var(--muted)",
  "--theme-disabled-surface": "var(--disabled-surface)",
  "--theme-disabled-text": "var(--disabled-text)",
  "--theme-border": "var(--line)",
} as CSSProperties;

const SIDEBAR_PREFERENCE_KEY = "ac:coach-sidebar-collapsed";
const SIDEBAR_PREFERENCE_EVENT = "ac:coach-sidebar-preference";
function subscribeSidebar(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener(SIDEBAR_PREFERENCE_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(SIDEBAR_PREFERENCE_EVENT, callback);
  };
}
function readSidebar() {
  try {
    return window.localStorage.getItem(SIDEBAR_PREFERENCE_KEY) === "true";
  } catch {
    return false;
  }
}

export function isCoachRouteActive(pathname: string, href: string) {
  return (
    pathname === href || (href !== "/studio" && pathname.startsWith(href + "/"))
  );
}

function Workspace({
  children,
  sessionState,
  boundary,
}: {
  children: ReactNode;
  sessionState?: AdminSessionState;
  boundary?: ReactNode;
}) {
  const contextState = useAdminSession();
  const state = sessionState ?? contextState;
  const pathname = usePathname();
  const storedCollapsed = useSyncExternalStore(
    subscribeSidebar,
    readSidebar,
    () => false,
  );
  const [temporaryCollapsed, setTemporaryCollapsed] = useState<boolean | null>(
    null,
  );
  const sidebarCollapsed = temporaryCollapsed ?? storedCollapsed;
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState("");
  const mobileToggleRef = useRef<HTMLButtonElement>(null);
  const mobileCloseRef = useRef<HTMLButtonElement>(null);
  const firstNavRef = useRef<HTMLAnchorElement>(null);
  const accountTriggerRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const accountMenuRef = useRef<HTMLDivElement>(null);
  const active = coachNavigation.find((item) =>
    isCoachRouteActive(pathname, item.href),
  );
  const name =
    state.status === "ready"
      ? state.session.displayName || state.session.email
      : "Your account";
  const email = state.status === "ready" ? state.session.email : "";
  const initials =
    state.status === "ready"
      ? (state.session.displayName || state.session.email)
          .trim()
          .split(/\s+/)
          .slice(0, 2)
          .map((part) => part[0])
          .join("")
          .toUpperCase()
      : "";

  function toggleSidebar() {
    const next = !sidebarCollapsed;
    try {
      window.localStorage.setItem(SIDEBAR_PREFERENCE_KEY, String(next));
      window.dispatchEvent(new Event(SIDEBAR_PREFERENCE_EVENT));
      setTemporaryCollapsed(null);
    } catch {
      setTemporaryCollapsed(next);
    }
  }

  useEffect(() => {
    if (!mobileNavOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusTimer = window.setTimeout(() => firstNavRef.current?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMobileNavOpen(false);
        window.setTimeout(() => mobileToggleRef.current?.focus(), 0);
      }
      if (event.key === "Tab") {
        const controls = Array.from(
          sidebarRef.current?.querySelectorAll<HTMLElement>(
            "a[href], button:not(:disabled)",
          ) ?? [],
        ).filter((node) => node.getClientRects().length > 0);
        const first = controls[0];
        const last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        }
        if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [mobileNavOpen]);

  useEffect(() => {
    if (!accountOpen) return;
    accountMenuRef.current
      ?.querySelector<HTMLElement>('[role="menuitem"]')
      ?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setAccountOpen(false);
        window.setTimeout(() => accountTriggerRef.current?.focus(), 0);
      }
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        const items = Array.from(
          accountMenuRef.current?.querySelectorAll<HTMLElement>(
            '[role="menuitem"]:not(:disabled)',
          ) ?? [],
        );
        if (!items.length) return;
        event.preventDefault();
        const index = items.indexOf(document.activeElement as HTMLElement);
        const next =
          event.key === "Home"
            ? 0
            : event.key === "End"
              ? items.length - 1
              : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) %
                items.length;
        items[next]?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [accountOpen]);

  function closeMobileNav() {
    setMobileNavOpen(false);
    window.setTimeout(() => mobileToggleRef.current?.focus(), 0);
  }

  function requestSignOut() {
    const proceed = () => void signOut();
    const request = new CustomEvent("ac:studio-before-leave", {
      cancelable: true,
      detail: { proceed },
    });
    // Ask the current editor before invalidating its session, not afterwards.
    if (document.dispatchEvent(request)) proceed();
  }

  async function signOut() {
    if (signingOut) return;
    setSigningOut(true);
    setSignOutError("");
    try {
      const response = await fetch("/v1/auth/logout", {
        method: "POST",
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error();
      // The editor guard has already settled. Discard private route state.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- Confirmed sign-out must discard the privileged document and route cache.
      window.location.assign("/login");
    } catch {
      setSignOutError("We couldn’t confirm sign-out. Please try again.");
      setSigningOut(false);
    }
  }

  const workspaceClassName = [
    "coach-workspace",
    sidebarCollapsed ? "is-sidebar-collapsed" : "",
    mobileNavOpen ? "is-mobile-nav-open" : "",
  ]
    .filter(Boolean)
    .join(" ");

  function sessionMessage() {
    if (boundary) return boundary;
    if (state.status === "loading") {
      return (
        <section
          className="coach-session-message"
          role="status"
          aria-busy="true"
        >
          <div className="coach-session-loading-mark" aria-hidden="true" />
          <h1>Opening your workspace…</h1>
          <p>
            We’re checking your Studio access. Your courses will appear here in
            a moment.
          </p>
        </section>
      );
    }
    if (state.status === "error") {
      return (
        <section className="coach-session-message" role="alert">
          <h1>We couldn’t check your account</h1>
          <p>
            Your workspace is still protected. Reload this page to reconnect,
            then try again.
          </p>
          <Link href="/login" className="button button-primary">
            Sign in again
          </Link>
        </section>
      );
    }
    return (
      <section className="coach-session-message" role="alert">
        <h1>Let’s get you into Studio.</h1>
        <p>Sign in with the account assigned to your academy.</p>
        <Link href="/login" className="button button-primary">
          Sign in
        </Link>
      </section>
    );
  }

  return (
    <div className={workspaceClassName} style={coachThemeBridge}>
      <aside
        ref={sidebarRef}
        className="coach-sidebar"
        id="coach-sidebar"
        aria-label="Studio workspace navigation"
      >
        <div className="coach-sidebar-head">
          <Link
            href="/studio"
            className="coach-brand"
            aria-label="Academy Studio home"
          >
            <AcademyMark width={40} height={40} aria-hidden="true" />
            <span>
              Academy Studio<small>by Cohorva</small>
            </span>
          </Link>
          <button
            ref={mobileCloseRef}
            className="coach-mobile-close"
            type="button"
            aria-label="Close Studio navigation"
            onClick={closeMobileNav}
          >
            <X size={20} aria-hidden="true" />
          </button>
          <button
            className="coach-sidebar-toggle"
            type="button"
            aria-label={
              sidebarCollapsed
                ? "Expand Studio navigation"
                : "Collapse Studio navigation"
            }
            aria-expanded={!sidebarCollapsed}
            aria-controls="coach-sidebar"
            title={
              sidebarCollapsed ? "Expand navigation" : "Collapse navigation"
            }
            onClick={toggleSidebar}
          >
            {sidebarCollapsed ? (
              <PanelLeftOpen size={19} aria-hidden="true" />
            ) : (
              <PanelLeftClose size={19} aria-hidden="true" />
            )}
          </button>
        </div>
        <div className="coach-sidebar-label">YOUR WORKSPACE</div>
        <nav aria-label="Coach workspace">
          {coachNavigation.map(({ href, label, icon: Icon }, index) => (
            <Link
              key={href}
              href={href}
              ref={index === 0 ? firstNavRef : undefined}
              title={label}
              aria-current={
                isCoachRouteActive(pathname, href) ? "page" : undefined
              }
              onClick={() => {
                if (mobileNavOpen) closeMobileNav();
              }}
            >
              <Icon size={20} aria-hidden="true" />
              <span>{label}</span>
            </Link>
          ))}
        </nav>
        <div className="coach-sidebar-bottom">
          <div className="coach-sidebar-note">
            <BookOpen size={20} aria-hidden="true" />
            <p>
              Your courses.
              <br />
              <strong>Your way of teaching.</strong>
            </p>
          </div>
          {state.status === "ready" ? (
            <div className="coach-account-wrap">
              <button
                ref={accountTriggerRef}
                className="coach-account-link"
                type="button"
                aria-expanded={accountOpen}
                aria-haspopup="menu"
                aria-controls="coach-account-menu"
                onClick={() => {
                  setSignOutError("");
                  setAccountOpen((current) => !current);
                }}
              >
                <span className="coach-avatar" aria-hidden="true">
                  {initials}
                </span>
                <span className="coach-account-copy">
                  <strong>{name}</strong>
                  <small title={email}>{email}</small>
                </span>
                <ChevronDown
                  className="coach-account-chevron"
                  size={17}
                  aria-hidden="true"
                />
              </button>
              {accountOpen && (
                <div
                  ref={accountMenuRef}
                  className="coach-account-menu"
                  id="coach-account-menu"
                  role="menu"
                  aria-label="Account actions"
                >
                  <div className="coach-account-menu-heading">
                    <strong>{name}</strong>
                    <span title={email}>{email}</span>
                  </div>
                  <Link
                    href="/studio/settings"
                    role="menuitem"
                    onClick={() => setAccountOpen(false)}
                  >
                    <Settings2 size={16} aria-hidden="true" />
                    Account & preferences
                  </Link>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={requestSignOut}
                    disabled={signingOut}
                  >
                    <LogOut size={16} aria-hidden="true" />
                    {signingOut ? "Signing out…" : "Sign out"}
                  </button>
                  {signOutError && (
                    <p className="coach-signout-error" role="alert">
                      {signOutError}
                    </p>
                  )}
                </div>
              )}
            </div>
          ) : state.status === "denied" ? (
            <Link className="coach-account-signin" href="/login">
              <span className="coach-avatar" aria-hidden="true">
                ?
              </span>
              <span>Sign in</span>
            </Link>
          ) : (
            <div className="coach-account-pending" role="status">
              <span className="coach-avatar" aria-hidden="true">
                …
              </span>
              <span>
                {state.status === "error"
                  ? "Access needs checking"
                  : "Checking access…"}
              </span>
            </div>
          )}
        </div>
      </aside>
      <button
        className="coach-nav-scrim"
        type="button"
        aria-label="Close Studio navigation"
        onClick={closeMobileNav}
      />
      <div className="coach-stage" inert={mobileNavOpen}>
        <header className="coach-topbar">
          <button
            ref={mobileToggleRef}
            className="coach-mobile-toggle"
            type="button"
            aria-label="Open Studio navigation"
            aria-expanded={mobileNavOpen}
            aria-controls="coach-sidebar"
            onClick={() => {
              setAccountOpen(false);
              setMobileNavOpen(true);
            }}
          >
            <Menu size={20} aria-hidden="true" />
            <span>Menu</span>
          </button>
          <Link className="coach-mobile-brand" href="/studio">
            <AcademyMark width={32} height={32} aria-hidden="true" />
            <span>Academy Studio</span>
          </Link>
          <nav className="coach-breadcrumb" aria-label="Breadcrumb">
            <Link href="/studio">Studio</Link>
            {active && active.href !== "/studio" && (
              <>
                <ChevronRight size={14} aria-hidden="true" />
                <span>{active.label}</span>
              </>
            )}
            {pathname.startsWith("/studio/programs/") && (
              <>
                <ChevronRight size={14} aria-hidden="true" />
                <span>Course editor</span>
              </>
            )}
          </nav>
          {state.status === "ready" ? (
            <Link
              href="/studio/settings"
              className="coach-top-account"
              aria-label={`Account settings for ${name}`}
            >
              <span title={email}>{name}</span>
              <span className="coach-avatar" aria-hidden="true">
                {initials}
              </span>
            </Link>
          ) : state.status === "denied" ? (
            <Link href="/login" className="coach-top-signin">
              Sign in
            </Link>
          ) : (
            <span className="coach-top-account-pending" role="status">
              Checking access…
            </span>
          )}
        </header>
        <main id="admin-content" className="coach-content" tabIndex={-1}>
          {state.status === "ready" ? children : sessionMessage()}
        </main>
      </div>
      <nav
        className="coach-mobile-nav"
        aria-label="Coach mobile navigation"
        inert={mobileNavOpen}
      >
        {coachNavigation.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            aria-current={
              isCoachRouteActive(pathname, href) ? "page" : undefined
            }
          >
            <Icon size={20} aria-hidden="true" />
            <span>{label}</span>
          </Link>
        ))}
      </nav>
    </div>
  );
}
export function CoachShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <CoachPreferencesProvider>
      <AdminSessionProvider
        refreshKey={pathname}
        revalidateOnFocus
        renderBoundary={(boundary, state) => (
          <Workspace sessionState={state} boundary={boundary}>
            {null}
          </Workspace>
        )}
      >
        <Workspace>{children}</Workspace>
      </AdminSessionProvider>
    </CoachPreferencesProvider>
  );
}
