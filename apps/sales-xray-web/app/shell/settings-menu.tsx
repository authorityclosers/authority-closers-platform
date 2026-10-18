"use client";

import {
  BarChart3,
  Building2,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleUserRound,
  Clock3,
  Compass,
  CreditCard,
  Gem,
  Globe,
  GraduationCap,
  LifeBuoy,
  LogOut,
  MailOpen,
  Plus,
  Settings2,
  Smartphone,
  Sparkles,
  Users,
} from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { usePathname } from "next/navigation";

import type { Allowance } from "../acquisition-client";
import { useSalesXraySignOut } from "../account-navigation";
import { formatAnalysisTime } from "../analysis-time";
import { useFirstCallGuideSwitch } from "../guide-toggle";
import { phoneCallsOpener, useInApp } from "../in-app-client";
import { when } from "../leads/leads-client";
import {
  ANDROID_DOWNLOAD_READY,
  PHONE_APP_HREF,
} from "../leads/phone-app-flag";
import { useTakingLeads } from "../leads/taking-account";
import { notify } from "../notice-center";
import { openSettings } from "../settings-open";
import { AccountAvatarImage } from "../speaker-avatar";
import { useShellUpdates } from "./updates-store";
import styles from "./settings-menu.module.css";

type View = "main" | "language" | "news";

/** The badge follows the account's canonical receipt count. */
export function useUnseenNews(authenticated = true, enabled = true): number {
  return useShellUpdates(authenticated, enabled).unseen_count;
}

const DAY = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

export function accountInitials(name: string | null, email: string | null) {
  const source = name?.trim() || email?.split("@")[0] || "";
  const parts = source.split(/\s+/).filter(Boolean);
  const letters =
    parts.length > 1 ? parts[0][0] + parts[1][0] : source.slice(0, 2);
  return letters.toUpperCase() || "·";
}

function minutesLine(allowance: Allowance | null) {
  if (!allowance || allowance.unlimited) return null;
  const left = formatAnalysisTime(allowance.available_seconds);
  const total = formatAnalysisTime(allowance.allowance_seconds);
  const share =
    allowance.allowance_seconds > 0
      ? Math.min(1, allowance.available_seconds / allowance.allowance_seconds)
      : 0;
  return { text: `${left} of ${total} left`, share };
}

function Row({
  icon,
  label,
  value,
  badge,
  next,
  checked,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  value?: string;
  badge?: string;
  next?: boolean;
  /** Renders the row as an on/off switch. */
  checked?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={styles.row}
      onClick={onClick}
      {...(checked === undefined
        ? {}
        : { role: "switch", "aria-checked": checked })}
    >
      <span className={styles.rowIcon} aria-hidden="true">
        {icon}
      </span>
      <span className={styles.rowLabel}>{label}</span>
      {badge ? <span className={styles.badge}>{badge}</span> : null}
      {value ? <span className={styles.rowValue}>{value}</span> : null}
      {next ? (
        <ChevronRight size={15} className={styles.chev} aria-hidden="true" />
      ) : null}
    </button>
  );
}

function Back({ label, onBack }: { label: string; onBack: () => void }) {
  return (
    <button type="button" className={styles.back} onClick={onBack}>
      <ChevronLeft size={16} aria-hidden="true" />
      {label}
    </button>
  );
}

/**
 * The account card that opens from the gear: who is signed in, the minutes
 * left, and one list for settings, language, usage, plans and what's new.
 */
export function SettingsMenu({
  open,
  anchorRef,
  onClose,
  name,
  email,
  photoUrl,
  allowance,
  organisation = false,
  insights = false,
  workspaces = [],
  currentWorkspaceId = null,
  onSelectWorkspace,
  invitesWaiting = 0,
  onCreateOrganisation,
  initialView = "main",
}: {
  initialView?: View;
  /** An organisation is selected: phones reach its page from here. */
  organisation?: boolean;
  /** The selected organisation's owner or admin: phones reach Insights here. */
  insights?: boolean;
  /** Where your calls live; phones switch here (desktop also has the sidebar). */
  workspaces?: readonly { tenant_id: string; kind: string; name: string }[];
  currentWorkspaceId?: string | null;
  onSelectWorkspace?: (tenantId: string) => void;
  /** Invitations waiting for you: one row to the Invitations page. */
  invitesWaiting?: number;
  /** Offered only where the server can create organisations. */
  onCreateOrganisation?: () => void;
  open: boolean;
  anchorRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  name: string | null;
  email: string | null;
  photoUrl?: string | null;
  allowance: Allowance | null;
}) {
  const [view, setView] = useState<View>(initialView);
  const [place, setPlace] = useState<{ left: number; bottom: number } | null>(
    null,
  );
  const card = useRef<HTMLDivElement>(null);
  const updates = useShellUpdates();
  const { markSeen } = updates;
  const unseen = updates.unseen_count;
  const displayedKeys = useMemo(
    () => updates.notes.filter((note) => !note.seen).map((note) => note.key),
    [updates.notes],
  );
  const minutes = minutesLine(allowance);
  const guide = useFirstCallGuideSwitch();
  // The seller's own "Taking new leads", in an organisation only (UX study item 8);
  // a live read, so not under test (like the Leads tab badge).
  const taking = useTakingLeads(
    open && organisation && process.env.NODE_ENV !== "test",
  );
  const pathname = usePathname();
  const inApp = useInApp();
  const { signOut, signingOut, error: signOutError } = useSalesXraySignOut();

  // A sign out that could not be confirmed says so in the corner.
  useEffect(() => {
    if (!signOutError) return;
    notify({
      id: "sign-out",
      tone: "error",
      title: "Couldn’t log out",
      message: signOutError,
      action: { label: "Try again", run: () => void signOut() },
    });
    // signOut is recreated each render; the message is what changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signOutError]);

  useLayoutEffect(() => {
    if (!open) return;
    const measure = () => {
      const rect = anchorRef.current?.getBoundingClientRect();
      const mobile = window.innerWidth < 900;
      const width = Math.min(300, window.innerWidth - 16);
      const anchorVisible = Boolean(
        rect &&
          rect.width > 0 &&
          rect.height > 0 &&
          rect.right > 0 &&
          rect.left < window.innerWidth &&
          rect.bottom > 0 &&
          rect.top < window.innerHeight,
      );
      if (!rect || !anchorVisible) {
        setPlace({
          left: Math.max(8, Math.round((window.innerWidth - width) / 2)),
          bottom: 16,
        });
        return;
      }
      if (mobile) {
        const height =
          card.current?.getBoundingClientRect().height ??
          Math.min(620, window.innerHeight - 32);
        const maxBottom = Math.max(8, window.innerHeight - height - 8);
        setPlace({
          left: Math.max(8, Math.round((window.innerWidth - width) / 2)),
          bottom: Math.min(
            Math.max(8, Math.round(window.innerHeight - rect.top + 8)),
            maxBottom,
          ),
        });
        return;
      }
      const right = rect.right + 10;
      const left =
        right + width <= window.innerWidth - 8
          ? right
          : Math.max(8, rect.left - width - 10);
      setPlace({
        left: Math.round(left),
        bottom: Math.max(8, Math.round(window.innerHeight - rect.bottom)),
      });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [anchorRef, open]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        !card.current?.contains(target) &&
        !anchorRef.current?.contains(target)
      )
        onClose();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      onClose();
      anchorRef.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    // Focus starts on the first visible item, never on Log out.
    [...(card.current?.querySelectorAll<HTMLElement>("button, a[href]") ?? [])]
      .find((item) => !item.hasAttribute("data-log-out") && item.offsetParent)
      ?.focus();
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [anchorRef, onClose, open]);

  useEffect(() => {
    // The shell mounts the card only while open, so each open starts at main.
    if (open && view === "news" && displayedKeys.length)
      void markSeen(displayedKeys).catch(() => {});
  }, [open, view, displayedKeys, markSeen]);

  if (!open || typeof document === "undefined") return null;

  const settings = (section: string) => {
    onClose();
    openSettings(section);
  };

  // Phones: the pages that are not tabs, as one tap each. Desktop has them
  // in the rail, so the sheet's CSS shows this block on phones only.
  const openPhoneCalls = inApp ? phoneCallsOpener() : null;
  const goTo = [
    { href: "/prospects", label: "Prospects", icon: <Users size={20} /> },
    { href: "/coaching", label: "Coaching", icon: <GraduationCap size={20} /> },
    ...(organisation
      ? [
          {
            href: "/organisation",
            label: "Organisation",
            icon: <Building2 size={20} />,
          },
        ]
      : []),
    ...(organisation && insights
      ? [
          {
            href: "/organisation/insights",
            label: "Insights",
            icon: <BarChart3 size={20} />,
          },
        ]
      : []),
  ];
  const here = (href: string) =>
    pathname === href ||
    (href !== "/organisation" && Boolean(pathname?.startsWith(`${href}/`)));

  return createPortal(
    <>
      {/* Phones: the sheet dims the screen; a tap on it closes the sheet
          without reaching the page underneath. */}
      <div className={styles.scrim} aria-hidden="true" />
      <div
        ref={card}
        className={styles.card}
        role="dialog"
        aria-label="Account menu"
        // Variables, not left/bottom: the phone sheet's own CSS then wins
        // without !important (r17 S8).
        style={
          place
            ? ({
                "--card-left": `${place.left}px`,
                "--card-bottom": `${place.bottom}px`,
              } as CSSProperties)
            : undefined
        }
      >
        {/* Empty, so nothing to announce: the sheet handle is drawn only. */}
        <span className={styles.grip} />
        <div key={view} className={styles.view}>
          {view === "main" && (
            <>
              <div className={styles.who}>
                <span className={styles.avatar} aria-hidden="true">
                  <AccountAvatarImage key={email} photoUrl={photoUrl}>
                    {accountInitials(name, email)}
                  </AccountAvatarImage>
                </span>
                <span className={styles.whoText}>
                  <b>{name || "Your account"}</b>
                  {email ? <small>{email}</small> : null}
                </span>
                {/* Owner, 17 Oct: logging out is never more than one tap
                  away once this menu is open. */}
                <button
                  type="button"
                  className={styles.logOut}
                  data-log-out=""
                  onClick={() => void signOut()}
                  disabled={signingOut}
                >
                  <LogOut size={15} aria-hidden="true" />
                  {signingOut ? "Logging out…" : "Log out"}
                </button>
              </div>
              <nav className={styles.goTo} aria-label="More pages">
                {goTo.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={styles.tile}
                    aria-current={here(item.href) ? "page" : undefined}
                    onClick={onClose}
                  >
                    <span aria-hidden="true">{item.icon}</span>
                    {item.label}
                  </Link>
                ))}
                {openPhoneCalls ? (
                  <button
                    type="button"
                    className={styles.tile}
                    onClick={() => {
                      onClose();
                      openPhoneCalls();
                    }}
                  >
                    <span aria-hidden="true">
                      <Smartphone size={20} />
                    </span>
                    Calls on this phone
                  </button>
                ) : null}
              </nav>
              {minutes ? (
                <button
                  type="button"
                  className={styles.usage}
                  onClick={() => settings("usage")}
                >
                  <span className={styles.usageTop}>
                    <span>Analysis time</span>
                    <b>{minutes.text}</b>
                  </span>
                  {minutes.share !== null ? (
                    <span className={styles.meter} aria-hidden="true">
                      <i style={{ width: `${minutes.share * 100}%` }} />
                    </span>
                  ) : null}
                </button>
              ) : null}
              {(workspaces.length > 1 && onSelectWorkspace) ||
              invitesWaiting > 0 ||
              onCreateOrganisation ? (
                <div
                  className={styles.list}
                  role="group"
                  aria-label="Workspace"
                >
                  <p className={styles.note}>Workspace</p>
                  {(onSelectWorkspace && workspaces.length > 1
                    ? workspaces
                    : []
                  ).map((workspace) => {
                    const current = workspace.tenant_id === currentWorkspaceId;
                    const name =
                      workspace.kind === "personal"
                        ? "Personal"
                        : workspace.name;
                    return (
                      <button
                        key={workspace.tenant_id}
                        type="button"
                        className={styles.row}
                        aria-current={current ? "true" : undefined}
                        onClick={() => {
                          if (current) return;
                          onClose();
                          onSelectWorkspace?.(workspace.tenant_id);
                        }}
                      >
                        <span className={styles.rowIcon} aria-hidden="true">
                          {workspace.kind === "organisation" ? (
                            <Building2 size={16} />
                          ) : (
                            <CircleUserRound size={16} />
                          )}
                        </span>
                        <span className={styles.rowLabel}>{name}</span>
                        {current ? (
                          <Check
                            size={15}
                            className={styles.chev}
                            aria-label="Current"
                          />
                        ) : null}
                      </button>
                    );
                  })}
                  {invitesWaiting > 0 ? (
                    <Link
                      href="/organisation/invites"
                      className={styles.row}
                      onClick={onClose}
                    >
                      <span className={styles.rowIcon} aria-hidden="true">
                        <MailOpen size={16} />
                      </span>
                      <span className={styles.rowLabel}>Invitations</span>
                      <span className={styles.badge}>{invitesWaiting}</span>
                    </Link>
                  ) : null}
                  {onCreateOrganisation ? (
                    <button
                      type="button"
                      className={styles.row}
                      onClick={() => {
                        onClose();
                        onCreateOrganisation();
                      }}
                    >
                      <span className={styles.rowIcon} aria-hidden="true">
                        <Plus size={16} />
                      </span>
                      <span className={styles.rowLabel}>
                        Create an organisation
                      </span>
                    </button>
                  ) : null}
                  <span className={styles.divider} />
                </div>
              ) : null}
              <div className={styles.list}>
                {taking ? (
                  <Row
                    icon={<Users size={16} />}
                    label="Taking new leads"
                    value={
                      !taking.taking
                        ? "Off"
                        : taking.pausedUntil
                          ? `Waits until ${when(taking.pausedUntil)}`
                          : "On"
                    }
                    checked={taking.taking}
                    onClick={taking.toggle}
                  />
                ) : null}
                <Row
                  icon={<Settings2 size={16} />}
                  label="Settings"
                  onClick={() => settings("general")}
                />
                <Row
                  icon={<CircleUserRound size={16} />}
                  label="Profile"
                  onClick={() => settings("profile")}
                />
                <Row
                  icon={<Globe size={16} />}
                  label="Language"
                  value="English"
                  next
                  onClick={() => setView("language")}
                />
                <Row
                  icon={<Clock3 size={16} />}
                  label="Usage"
                  value={
                    minutes && minutes.share !== null
                      ? `${Math.round(minutes.share * 100)}% left`
                      : undefined
                  }
                  onClick={() => settings("usage")}
                />
                <Link href="/plans" className={styles.row} onClick={onClose}>
                  <span className={styles.rowIcon} aria-hidden="true">
                    <Gem size={16} />
                  </span>
                  <span className={styles.rowLabel}>Plans</span>
                  <ChevronRight
                    size={15}
                    className={styles.chev}
                    aria-hidden="true"
                  />
                </Link>
                <Row
                  icon={<CreditCard size={16} />}
                  label="Plan & billing"
                  onClick={() => settings("billing")}
                />
                <Row
                  icon={<Sparkles size={16} />}
                  label="What's new"
                  badge={unseen > 0 ? `${unseen} new` : undefined}
                  next
                  onClick={() => setView("news")}
                />
                <span className={styles.divider} />
                {/* The phone app lives here, not in the Leads header (owner,
                    18 Oct), and only once its download is on. */}
                {ANDROID_DOWNLOAD_READY && !inApp ? (
                  <Link
                    href={PHONE_APP_HREF}
                    className={styles.row}
                    onClick={onClose}
                  >
                    <span className={styles.rowIcon} aria-hidden="true">
                      <Smartphone size={16} />
                    </span>
                    <span className={styles.rowLabel}>Phone app</span>
                    <ChevronRight
                      size={15}
                      className={styles.chev}
                      aria-hidden="true"
                    />
                  </Link>
                ) : null}
                <Row
                  icon={<LifeBuoy size={16} />}
                  label="Help & support"
                  onClick={() => settings("help")}
                />
                {guide ? (
                  <Row
                    icon={<Compass size={16} />}
                    label="First call guide"
                    value={guide.on ? "On" : "Off"}
                    checked={guide.on}
                    onClick={() => {
                      guide.set(!guide.on);
                      // Turning it on closes the menu so the guide is in view.
                      if (!guide.on) onClose();
                    }}
                  />
                ) : null}
              </div>
            </>
          )}

          {view === "language" && (
            <>
              <Back label="Language" onBack={() => setView("main")} />
              <p className={styles.note}>App language</p>
              <div className={styles.choices}>
                <span className={styles.choice} data-on="">
                  <i aria-hidden="true" />
                  English
                </span>
                <span className={styles.choice} aria-disabled="true">
                  <i aria-hidden="true" />
                  हिन्दी
                  <small>Coming soon</small>
                </span>
                <span className={styles.choice} aria-disabled="true">
                  <i aria-hidden="true" />
                  मराठी
                  <small>Coming soon</small>
                </span>
              </div>
              <p className={styles.note}>
                Reports: pick English, Hindi + English or Marathi + English when
                you start an analysis.
              </p>
            </>
          )}

          {view === "news" && (
            <>
              <Back label="What's new" onBack={() => setView("main")} />
              {!updates.notes.length ? (
                <p className={styles.note}>
                  {updates.status === "error"
                    ? "Updates could not load. Try again when you return."
                    : updates.status === "loading"
                      ? "Loading updates…"
                      : "You're up to date."}
                </p>
              ) : null}
              <ol className={styles.news}>
                {updates.notes.map((entry, index) => (
                  <li
                    key={entry.key}
                    style={{ animationDelay: `${index * 50}ms` }}
                  >
                    <time dateTime={entry.date}>
                      {DAY.format(new Date(`${entry.date}T00:00:00Z`))}
                    </time>
                    <b>
                      {entry.title}
                      {entry.draft ? (
                        <span className={styles.draft}>Draft</span>
                      ) : null}
                      {!entry.seen ? (
                        <span className={styles.dot} aria-label="New" />
                      ) : null}
                    </b>
                    <ul>
                      {entry.items.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>
      </div>
    </>,
    document.body,
  );
}
