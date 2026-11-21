"use client";

/**
 * Notifications (owner program, 25 Oct 2026, item 5: "ugly and stupid";
 * rebuild it with a strong core and some personality). A sheet from the bell:
 * what needs you first, then what is new, then what you have read; each line
 * in its kind's colour with its one action, unread lines marked, and Mark all
 * read. Nothing waiting: a calm line that says what lands here.
 *
 * sx-redesign board pick A "grouped cards" (owner, 21 Nov 2026): a small
 * All / Leads / Reports switch, one white card per day (Today, Yesterday,
 * Earlier), each row a dark ink icon in its meaning's soft tile, a word chip,
 * the title, one line and one button; only the top-most row's button is
 * solid green. No chevrons: the button says where the row goes.
 */

import {
  BadgeCheck,
  Bell,
  BellRing,
  CheckCheck,
  FileCheck2,
  PauseCircle,
  Sparkles,
  UserPlus,
  UserRoundPlus,
  type LucideIcon,
} from "lucide-react";
import { useRef, useState } from "react";

import { Sheet } from "../ui/sheet";
import { leadName, leadSource } from "./missed-alert-rules";
import {
  isRelativeUpdateHref,
  type UpdateNotification,
} from "./updates-client";
import styles from "./updates-bell.module.css";

type Kind = UpdateNotification["kind"];

/**
 * sx-redesign board pick (owner, 21 Nov 2026): each kind has a word chip, a
 * dark ink icon in a soft tile of its meaning's colour and one short button.
 */
const KINDS: Record<
  Kind,
  {
    icon: LucideIcon;
    tone: string;
    chip: string;
    button: string;
    verb: string;
    filter: Filter;
  }
> = {
  report_ready: {
    icon: FileCheck2,
    tone: "report",
    chip: "Report",
    button: "Open",
    verb: "Open report",
    filter: "reports",
  },
  analysis_paused: {
    icon: PauseCircle,
    tone: "paused",
    chip: "Paused",
    button: "See why",
    verb: "See why",
    filter: "reports",
  },
  invite_received: {
    icon: UserPlus,
    tone: "invite",
    chip: "Invite",
    button: "Open",
    verb: "Open invite",
    filter: "other",
  },
  bug_solved: {
    icon: BadgeCheck,
    tone: "solved",
    chip: "Fixed",
    button: "Open",
    verb: "Open",
    filter: "other",
  },
  lead_assigned: {
    icon: UserRoundPlus,
    tone: "lead",
    chip: "Your lead",
    button: "Open",
    verb: "Open lead",
    filter: "leads",
  },
  lead_new: {
    icon: UserRoundPlus,
    tone: "lead",
    chip: "New lead",
    button: "Open",
    verb: "Open lead",
    filter: "leads",
  },
  updates: {
    icon: Sparkles,
    tone: "news",
    chip: "What's new",
    button: "See",
    verb: "What's new",
    filter: "other",
  },
};

type Filter = "all" | "leads" | "reports" | "other";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "leads", label: "Leads" },
  { key: "reports", label: "Reports" },
  { key: "other", label: "Other" },
];

const MINUTE = 60_000;

/** "Just now", "12 min ago", "3 h ago", "Yesterday", "12 Oct". */
export function ago(iso: string, now: number = Date.now()): string {
  const at = Date.parse(iso);
  const minutes = Math.floor((now - at) / MINUTE);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h ago`;
  const day = (time: number) => new Date(time).toDateString();
  if (day(at) === day(now - 24 * 60 * MINUTE)) return "Yesterday";
  return new Date(at).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
  });
}

/**
 * The time on a row: the clock for today and yesterday ("6:48 pm", under its
 * day's heading), the date before that ("12 Oct").
 */
export function stamp(iso: string, now: number = Date.now()): string {
  const at = new Date(iso);
  const day = (time: number) => new Date(time).toDateString();
  if (
    day(at.getTime()) === day(now) ||
    day(at.getTime()) === day(now - 24 * 60 * MINUTE)
  )
    return at
      .toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })
      .replace(/\s?(AM|PM)$/i, (match) => ` ${match.trim().toLowerCase()}`);
  return at.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

/** Today, Yesterday and Earlier, newest first; one card each. */
export function groupNotifications(
  list: readonly UpdateNotification[],
  now: number = Date.now(),
) {
  const newest = [...list].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  );
  const today = new Date(now).toDateString();
  const yesterday = new Date(now - 24 * 60 * MINUTE).toDateString();
  const dayOf = (entry: UpdateNotification) =>
    new Date(entry.created_at).toDateString();
  return [
    {
      key: "today",
      title: "Today",
      items: newest.filter((entry) => dayOf(entry) === today),
    },
    {
      key: "yesterday",
      title: "Yesterday",
      items: newest.filter((entry) => dayOf(entry) === yesterday),
    },
    {
      key: "earlier",
      title: "Earlier",
      items: newest.filter(
        (entry) => dayOf(entry) !== today && dayOf(entry) !== yesterday,
      ),
    },
  ].filter((group) => group.items.length);
}

const LEAD_KINDS: ReadonlySet<Kind> = new Set(["lead_assigned", "lead_new"]);

/** "Sameer Sheikh" -> "SS", "Asha" -> "A"; "" when there are no letters. */
export function initials(name: string): string {
  const words = name.split(/\s+/).filter((word) => /^\p{L}/u.test(word));
  const first = words[0]?.[0] ?? "";
  const last = words.length > 1 ? words[words.length - 1][0] : "";
  return `${first}${last}`.toUpperCase();
}

function Row({
  entry,
  disabled,
  openable,
  first,
  onOpen,
}: {
  entry: UpdateNotification;
  disabled: boolean;
  /** It has somewhere to go (an unsafe link never shows a button). */
  openable: boolean;
  /** The top-most row with something to do: its button is the solid one. */
  first: boolean;
  onOpen: () => void;
}) {
  const kind = KINDS[entry.kind];
  const Icon = kind.icon;
  const lead = LEAD_KINDS.has(entry.kind);
  // A lead says where it came from ("Meta Ads"); others their own words.
  const source = lead ? (leadSource(entry).split(":")[0] ?? "").trim() : "";
  const detail = source || entry.body || "";
  return (
    <li data-unread={!entry.read}>
      <button
        type="button"
        className={styles.row}
        data-tone={kind.tone}
        data-sx-feature={lead ? "notice_row_opened" : `notice_row_${kind.tone}`}
        disabled={disabled}
        onClick={onOpen}
      >
        <span className={styles.icon} aria-hidden="true">
          <Icon size={20} strokeWidth={1.8} />
        </span>
        <span className={styles.words}>
          <span className={styles.chip}>{kind.chip}</span>
          {/* A lead's chip says "New lead" or "Your lead"; the title is the
              lead's name, so it shows more of itself. */}
          <strong>
            {lead
              ? leadName(entry) || entry.title.replace(/\s+now$/, "")
              : entry.title}
          </strong>
          {detail ? <small>{detail}</small> : null}
          {!entry.read ? <span className={styles.hidden}>Unread</span> : null}
        </span>
        <span className={styles.side}>
          <time dateTime={entry.created_at} title={ago(entry.created_at)}>
            {stamp(entry.created_at)}
          </time>
          {!openable ? null : (
            <span className={styles.go} data-first={first || undefined}>
              <span aria-hidden="true">{kind.button}</span>
              <span className={styles.hidden}>{kind.verb}</span>
            </span>
          )}
        </span>
      </button>
    </li>
  );
}

export function UpdatesBell({
  notifications,
  unreadCount,
  status,
  openNews,
  openEvent,
  markRead,
}: {
  notifications: readonly UpdateNotification[];
  unreadCount: number;
  status: "loading" | "ready" | "error";
  openNews: (anchor: HTMLElement | null) => void;
  openEvent: (entry: UpdateNotification) => Promise<void>;
  /** Marks these read; with it the sheet offers Mark all read. */
  markRead?: (ids: string[]) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };
  const [filter, setFilter] = useState<Filter>("all");
  const unread = notifications.filter((entry) => !entry.read);
  // The switch shows only when the list holds more than one sort of thing.
  const sorts = new Set(notifications.map((entry) => KINDS[entry.kind].filter));
  const filters = FILTERS.filter(
    (item) => item.key === "all" || sorts.has(item.key),
  );
  const shown =
    filter === "all" || !sorts.has(filter)
      ? notifications
      : notifications.filter((entry) => KINDS[entry.kind].filter === filter);
  const groups = groupNotifications(shown);
  const openable = (entry: UpdateNotification) =>
    entry.kind === "updates" || isRelativeUpdateHref(entry.href);
  const blocked = (entry: UpdateNotification) =>
    pending !== null || !openable(entry);
  // Only the top-most row that can be opened gets the solid green button.
  const firstOpen =
    groups.flatMap((group) => group.items).find(openable)?.id ?? null;
  const openRow = (entry: UpdateNotification) => {
    if (entry.kind === "updates") {
      // The line tapped is read whether or not What's new lists all of it
      // (phone personas ph1-27/ph1-53, 1 Nov 2026).
      if (!entry.read) void markRead?.([entry.id]).catch(() => {});
      close();
      openNews(trigger.current);
      return;
    }
    if (!isRelativeUpdateHref(entry.href)) return;
    setPending(entry.id);
    setFailed(false);
    void openEvent(entry)
      .then(close)
      .catch(() => setFailed(true))
      .finally(() => setPending(null));
  };
  const readAll = () => {
    if (!markRead || !unread.length) return;
    setPending("all");
    setFailed(false);
    void markRead(unread.map((entry) => entry.id))
      .catch(() => setFailed(true))
      .finally(() => setPending(null));
  };
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={styles.trigger}
        aria-label="Notifications"
        title="Notifications"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
          setFailed(false);
        }}
      >
        <Bell size={20} strokeWidth={1.75} aria-hidden="true" />
        {unreadCount > 0 ? (
          <span className={styles.badge} aria-label={`${unreadCount} unread`}>
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        ) : null}
      </button>
      <Sheet open={open} onClose={close} title="Notifications">
        <div className={styles.body}>
          {filters.length > 2 || (markRead && unread.length) ? (
            <div className={styles.toolbar}>
              {filters.length > 2 ? (
                <div
                  className={styles.pills}
                  role="group"
                  aria-label="Show notifications"
                >
                  {filters.map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      className={styles.pill}
                      aria-pressed={
                        (sorts.has(filter) ? filter : "all") === item.key
                      }
                      onClick={() => setFilter(item.key)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              ) : (
                <span />
              )}
              {unread.length ? (
                <span
                  className={styles.hidden}
                >{`${unread.length} unread`}</span>
              ) : null}
              {markRead && unread.length ? (
                <button
                  type="button"
                  className={styles.readAll}
                  disabled={pending !== null}
                  onClick={readAll}
                >
                  <CheckCheck size={16} aria-hidden="true" />
                  Mark all read
                </button>
              ) : null}
            </div>
          ) : null}
          {failed ? (
            <p className={styles.failed} role="alert">
              That didn&apos;t go through. Try again.
            </p>
          ) : null}
          {status === "error" && !notifications.length ? (
            <p className={styles.quiet} role="status">
              Notifications could not load. Try again when you return.
            </p>
          ) : null}
          {status === "loading" && !notifications.length ? (
            <div className={styles.skeleton} role="status" aria-busy="true">
              <span className={styles.hidden}>Loading notifications…</span>
              {[0, 1, 2].map((index) => (
                <span key={index} className={styles.skeletonRow} />
              ))}
            </div>
          ) : null}
          {status === "ready" && !notifications.length ? (
            <div className={styles.empty}>
              <span className={styles.emptyIcon} aria-hidden="true">
                <BellRing size={28} />
              </span>
              <strong>You&apos;re up to date</strong>
              <span>
                Ready reports, invites and what&apos;s new in Sales X-Ray land
                here.
              </span>
            </div>
          ) : null}
          {groups.map((group) => (
            <section
              key={group.key}
              className={styles.group}
              aria-label={group.title}
            >
              <h3 data-group={group.key}>{group.title}</h3>
              <ul>
                {group.items.map((entry) => (
                  <Row
                    key={entry.id}
                    entry={entry}
                    disabled={blocked(entry)}
                    openable={openable(entry)}
                    first={entry.id === firstOpen}
                    onOpen={() => openRow(entry)}
                  />
                ))}
              </ul>
            </section>
          ))}
        </div>
      </Sheet>
    </>
  );
}
