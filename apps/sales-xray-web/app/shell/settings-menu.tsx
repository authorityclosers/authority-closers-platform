"use client";

/**
 * You: the account menu (design system v2; the new map, owner, 22 Oct 2026:
 * "Approved: the new map"). There is no More tab: on phones your face in the
 * top bar opens this sheet, which follows the finger and closes on a swipe
 * down. Computers (the gear in the rail): a glass card beside the rail.
 *
 * It lists only what a person needs, in this order:
 * 1. who is signed in, with Log out one tap away (owner, 17 Oct);
 * 2. phones: your settings (Profile, Selling, Notifications), then, for the
 *    organisation's owners and admins, its settings (Team & roles, Lead
 *    stages, Connected apps, AI on calls): each two taps from anywhere;
 * 3. phones: the pages that are not tabs, then where you work (current
 *    first, others one tap away, Create an organisation apart);
 * 4. Settings, Plan & usage, What's new, Help & support;
 * 5. the phone app download (website only) and the first-call guide.
 */
import {
  AudioLines,
  BarChart3,
  Bell,
  Building2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Compass,
  GraduationCap,
  Layers,
  LifeBuoy,
  ListChecks,
  LogOut,
  MailOpen,
  PhoneCall,
  Plug,
  Settings2,
  Smartphone,
  Sparkles,
  UserRound,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

import type { Allowance } from "../acquisition-client";
import { useSalesXraySignOut } from "../account-navigation";
import { useFirstCallGuideSwitch } from "../guide-toggle";
import { phoneCallsOpener, useInApp } from "../in-app-client";
import { inPhoneApp } from "../leads/native-phone";
import { PHONE_SETUP_HASH } from "../leads/phone-setup";
import {
  ANDROID_DOWNLOAD_READY,
  PHONE_APP_HREF,
} from "../leads/phone-app-flag";
import { notify } from "../notice-center";
import { AccountAvatarImage } from "../speaker-avatar";
import { sectionById } from "../settings/settings-sections";
import { ActionList, ActionRow } from "../ui/kit";
import { Sheet, SHEET_PHONE_QUERY } from "../ui/sheet";
import { useShellUpdates } from "./updates-store";
import { WorkspacePicker, type PickerWorkspace } from "./workspace-picker";
import styles from "./settings-menu.module.css";
import { useBackClose } from "../ui/back-close";

type View = "main" | "news";

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

const noSubscription = () => () => {};
const subscribePhone = (change: () => void) => {
  const query = window.matchMedia?.(SHEET_PHONE_QUERY);
  query?.addEventListener?.("change", change);
  return () => query?.removeEventListener?.("change", change);
};
const isPhone = () => window.matchMedia?.(SHEET_PHONE_QUERY).matches === true;

function Row({
  icon,
  label,
  value,
  badge,
  href,
  checked,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  value?: string;
  badge?: string;
  /** A page: a link that closes the menu. */
  href?: string;
  /** Renders the row as an on/off switch. */
  checked?: boolean;
  onClick?: () => void;
}) {
  const inside = (
    <>
      <span className={styles.rowIcon} aria-hidden="true">
        {icon}
      </span>
      <span className={styles.rowLabel}>{label}</span>
      {badge ? <span className={styles.badge}>{badge}</span> : null}
      {value ? <span className={styles.rowValue}>{value}</span> : null}
      {checked !== undefined ? (
        <span className={styles.switch} data-on={checked || undefined} />
      ) : (
        <ChevronRight size={16} className={styles.chev} aria-hidden="true" />
      )}
    </>
  );
  if (href)
    return (
      <Link href={href} className={styles.row} onClick={onClick}>
        {inside}
      </Link>
    );
  return (
    <button
      type="button"
      className={styles.row}
      onClick={onClick}
      {...(checked === undefined
        ? {}
        : { role: "switch", "aria-checked": checked })}
    >
      {inside}
    </button>
  );
}

export function SettingsMenu({
  open,
  anchorRef,
  onClose,
  name,
  email,
  photoUrl,
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
  /** Where your calls live; phones switch here (computers use the sidebar). */
  workspaces?: readonly PickerWorkspace[];
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
  /** Not shown: end users never see minutes (owner, 19 Oct 2026). */
  allowance?: Allowance | null;
}) {
  const [view, setView] = useState<View>(initialView);
  // Each opening starts at the view the opener asked for.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setView(initialView);
  }
  const phone = useSyncExternalStore(subscribePhone, isPhone, () => false);
  // Phones: the sheet closes on Back by itself; computers: the card does.
  useBackClose(open && !phone, onClose);
  const [place, setPlace] = useState<{ left: number; bottom: number } | null>(
    null,
  );
  const card = useRef<HTMLDivElement>(null);
  // Read only while open: the menu stays mounted (so its sheet can slide
  // away), and a closed menu must not ask the server for anything.
  const updates = useShellUpdates(true, open);
  const { markSeen } = updates;
  const unseen = updates.unseen_count;
  const displayedKeys = useMemo(
    () => updates.notes.filter((note) => !note.seen).map((note) => note.key),
    [updates.notes],
  );
  const guide = useFirstCallGuideSwitch();
  const pathname = usePathname();
  const inApp = useInApp();
  // The phone app's own setup checklist (calls, alerts, recordings), once its
  // first run has taken the bar off Leads (owner, 19 Oct). Read after
  // hydration, so the first paint matches the server's.
  const phoneApp = useSyncExternalStore(
    noSubscription,
    inPhoneApp,
    () => false,
  );
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

  // Computers: the card sits beside the gear, inside the window.
  useLayoutEffect(() => {
    if (!open || phone) return;
    const measure = () => {
      const rect = anchorRef.current?.getBoundingClientRect();
      const width = Math.min(320, window.innerWidth - 16);
      const visible = Boolean(
        rect &&
          rect.width > 0 &&
          rect.height > 0 &&
          rect.right > 0 &&
          rect.left < window.innerWidth &&
          rect.bottom > 0 &&
          rect.top < window.innerHeight,
      );
      if (!rect || !visible) {
        setPlace({
          left: Math.max(8, Math.round((window.innerWidth - width) / 2)),
          bottom: 16,
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
  }, [anchorRef, open, phone]);

  useEffect(() => {
    if (!open || phone) return;
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
    // Focus starts on the first item, never on Log out.
    [...(card.current?.querySelectorAll<HTMLElement>("button, a[href]") ?? [])]
      .find((item) => !item.hasAttribute("data-log-out"))
      ?.focus();
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [anchorRef, onClose, open, phone]);

  useEffect(() => {
    if (open && view === "news" && displayedKeys.length)
      void markSeen(displayedKeys).catch(() => {});
  }, [open, view, displayedKeys, markSeen]);

  if (typeof document === "undefined") return null;

  // Phones: the pages that are not tabs, one tap each (computers have them
  // in the rail).
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

  // Your settings and, for owners and admins, the organisation's: the
  // sections' own names and hints (settings/settings-sections.ts).
  const yours = (
    [
      ["profile", <UserRound key="i" size={18} />],
      ["selling", <PhoneCall key="i" size={18} />],
      ["notifications", <Bell key="i" size={18} />],
    ] as const
  ).map(([id, icon]) => ({
    ...sectionById(id),
    href: `/settings/${id}`,
    icon,
  }));
  // Leads' settings have one home in Settings since slice 5 (22 Oct 2026).
  const theirs = [
    {
      ...sectionById("team"),
      href: "/settings/team",
      icon: <Users size={18} />,
    },
    {
      ...sectionById("lead-rules"),
      href: "/settings/lead-rules",
      icon: <ListChecks size={18} />,
    },
    {
      ...sectionById("stages"),
      href: "/settings/stages",
      icon: <Layers size={18} />,
    },
    {
      ...sectionById("apps"),
      href: "/settings/apps",
      icon: <Plug size={18} />,
    },
    {
      ...sectionById("call-ai"),
      href: "/settings/call-ai",
      icon: <AudioLines size={18} />,
    },
  ];

  const choose = (tenantId: string) => {
    if (tenantId === currentWorkspaceId) return;
    onClose();
    onSelectWorkspace?.(tenantId);
  };
  const canSwitch = Boolean(onSelectWorkspace) && workspaces.length > 1;

  const goToNav = (
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
      {phoneApp ? (
        <Link
          href={`/leads${PHONE_SETUP_HASH}`}
          className={styles.tile}
          onClick={onClose}
        >
          <span aria-hidden="true">
            <ListChecks size={20} />
          </span>
          Phone setup
        </Link>
      ) : null}
    </nav>
  );

  const main = (
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
        {/* Owner, 17 Oct: logging out is never more than one tap away
            once this menu is open. */}
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

      {phone ? (
        <section className={styles.group} aria-label="Your settings">
          <h3 className={styles.heading}>You</h3>
          <ActionList label="Your settings">
            {yours.map((item) => (
              <ActionRow
                key={item.href}
                icon={item.icon}
                title={item.label}
                note={item.hint}
                href={item.href}
                onClick={onClose}
              />
            ))}
          </ActionList>
        </section>
      ) : null}

      {phone && organisation && insights ? (
        <section className={styles.group} aria-label="Organisation settings">
          <h3 className={styles.heading}>Organisation</h3>
          <ActionList label="Organisation settings">
            {theirs.map((item) => (
              <ActionRow
                key={item.href}
                icon={item.icon}
                title={item.label}
                note={item.hint}
                href={item.href}
                onClick={onClose}
              />
            ))}
          </ActionList>
        </section>
      ) : null}

      {phone ? goToNav : null}

      {phone && (canSwitch || invitesWaiting > 0 || onCreateOrganisation) ? (
        <section className={styles.section} aria-label="Workspace">
          <h3 className={styles.heading}>Workspace</h3>
          <WorkspacePicker
            workspaces={canSwitch ? workspaces : []}
            currentId={currentWorkspaceId}
            onSelect={choose}
            personName={name}
            onCreate={
              onCreateOrganisation
                ? () => {
                    onClose();
                    onCreateOrganisation();
                  }
                : undefined
            }
          />
          {invitesWaiting > 0 ? (
            <Row
              icon={<MailOpen size={17} />}
              label="Invitations"
              badge={String(invitesWaiting)}
              href="/organisation/invites"
              onClick={onClose}
            />
          ) : null}
        </section>
      ) : null}

      <div className={styles.list}>
        <Row
          icon={<Settings2 size={17} />}
          label="Settings"
          href="/settings"
          onClick={onClose}
        />
        <Row
          icon={<Clock3 size={17} />}
          label="Plan & usage"
          href="/settings/plan"
          onClick={onClose}
        />
        <Row
          icon={<Sparkles size={17} />}
          label="What's new"
          badge={unseen > 0 ? `${unseen} new` : undefined}
          onClick={() => setView("news")}
        />
        <Row
          icon={<LifeBuoy size={17} />}
          label="Help & support"
          href="/settings/help"
          onClick={onClose}
        />
      </div>

      {(ANDROID_DOWNLOAD_READY && !inApp) || guide ? (
        <div className={styles.list}>
          {/* The phone app lives here, not in the Leads header (owner,
              18 Oct), and only once its download is on. */}
          {ANDROID_DOWNLOAD_READY && !inApp ? (
            <Row
              icon={<Smartphone size={17} />}
              label="Phone app"
              href={PHONE_APP_HREF}
              onClick={onClose}
            />
          ) : null}
          {guide ? (
            <Row
              icon={<Compass size={17} />}
              label="First call guide"
              checked={guide.on}
              onClick={() => {
                guide.set(!guide.on);
                // Turning it on closes the menu so the guide is in view.
                if (!guide.on) onClose();
              }}
            />
          ) : null}
        </div>
      ) : null}
    </>
  );

  const news = (
    <>
      <button
        type="button"
        className={styles.back}
        onClick={() => setView("main")}
      >
        <ChevronLeft size={16} aria-hidden="true" />
        What&apos;s new
      </button>
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
          <li key={entry.key} style={{ animationDelay: `${index * 50}ms` }}>
            <time dateTime={entry.date}>
              {DAY.format(new Date(`${entry.date}T00:00:00Z`))}
            </time>
            <b>
              {entry.title}
              {entry.draft ? <span className={styles.draft}>Draft</span> : null}
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
  );

  const content = (
    <div key={view} className={styles.view}>
      {view === "main" ? main : news}
    </div>
  );

  if (phone)
    return (
      <Sheet
        open={open}
        onClose={onClose}
        title="You"
        hideTitle
        closeButton={false}
        className={styles.sheet}
      >
        {content}
      </Sheet>
    );

  if (!open) return null;
  return createPortal(
    <div
      ref={card}
      className={styles.card}
      role="dialog"
      aria-label="Account menu"
      style={
        place
          ? ({
              "--card-left": `${place.left}px`,
              "--card-bottom": `${place.bottom}px`,
            } as CSSProperties)
          : undefined
      }
    >
      {content}
    </div>,
    document.body,
  );
}
