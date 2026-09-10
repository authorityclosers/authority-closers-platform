"use client";
import Link from "next/link";
import { type CSSProperties, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { AcademyMark } from "@ac/ui";
import {
  BookOpen,
  ChevronRight,
  ClipboardCheck,
  LayoutDashboard,
  Settings2,
} from "lucide-react";
import { CoachPreferencesProvider } from "./coach-preferences";
import {
  AdminSessionProvider,
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

export function isCoachRouteActive(pathname: string, href: string) {
  return (
    pathname === href || (href !== "/studio" && pathname.startsWith(href + "/"))
  );
}

function Workspace({ children }: { children: ReactNode }) {
  const state = useAdminSession();
  const pathname = usePathname();
  const active = coachNavigation.find((item) =>
    isCoachRouteActive(pathname, item.href),
  );
  const name =
    state.status === "ready"
      ? state.session.displayName || state.session.email
      : "Your account";
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
  return (
    <div className="coach-workspace" style={coachThemeBridge}>
      <aside className="coach-sidebar">
        <Link href="/studio" className="coach-brand">
          <AcademyMark width={40} height={40} aria-hidden="true" />
          <span>
            Academy Studio<small>by Cohorva</small>
          </span>
        </Link>
        <div className="coach-sidebar-label">YOUR WORKSPACE</div>
        <nav aria-label="Coach workspace">
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
        <div className="coach-sidebar-bottom">
          <div className="coach-sidebar-note">
            <BookOpen size={20} aria-hidden="true" />
            <p>
              Your courses.
              <br />
              <strong>Your way of teaching.</strong>
            </p>
          </div>
          <Link href="/studio/settings" className="coach-account-link">
            <span className="coach-avatar" aria-hidden="true">
              {initials}
            </span>
            <span>
              {name}
              <small>Account & preferences</small>
            </span>
            <Settings2 size={17} aria-hidden="true" />
          </Link>
        </div>
      </aside>
      <div className="coach-stage">
        <header className="coach-topbar">
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
          <Link
            href="/studio/settings"
            className="coach-top-account"
            aria-label={`Account settings for ${name}`}
          >
            <span>{name}</span>
            <span className="coach-avatar" aria-hidden="true">
              {initials}
            </span>
          </Link>
        </header>
        <main id="admin-content" className="coach-content" tabIndex={-1}>
          {state.status === "denied" ? (
            <section className="coach-session-message" role="alert">
              <h1>Let’s get you into Studio.</h1>
              <p>Sign in with the account assigned to your academy.</p>
              <Link href="/login" className="button button-primary">
                Sign in
              </Link>
            </section>
          ) : (
            children
          )}
        </main>
      </div>
      <nav className="coach-mobile-nav" aria-label="Coach mobile navigation">
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
      <AdminSessionProvider refreshKey={pathname} revalidateOnFocus>
        <Workspace>{children}</Workspace>
      </AdminSessionProvider>
    </CoachPreferencesProvider>
  );
}
