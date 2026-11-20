"use client";

/**
 * Notifications (owner program, 25 Oct 2026, item 5: "ugly and stupid";
 * rebuild it with a strong core and some personality). A sheet from the bell:
 * what needs you first, then what is new, then what you have read; each line
 * in its kind's colour with its one action, unread lines marked, and Mark all
 * read. Nothing waiting: a calm line that says what lands here.
 *
 * UI loop item 7 (owner's pick, 20 Nov 2026, option B: "The Notifications list
 * shouts"): Today and Earlier, newest first; a lead's initials with a small
 * unread dot instead of red rails and a red "Needs you"; one-line title and
 * one-line detail; the whole row opens it, with a chevron.
 */

import {
  BadgeCheck,
  Bell,
  BellRing,
  CheckCheck,
  ChevronRight,
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

const KINDS: Record<Kind, { icon: LucideIcon; tone: string; verb: string }> = {
  report_ready: { icon: FileCheck2, tone: "report", verb: "Open report" },
  analysis_paused: { icon: PauseCircle, tone: "paused", verb: "See why" },
  invite_received: { icon: UserPlus, tone: "invite", verb: "Open invite" },
  bug_solved: { icon: BadgeCheck, tone: "solved", verb: "Open" },
  lead_assigned: { icon: UserRoundPlus, tone: "lead", verb: "Open lead" },
  lead_new: { icon: UserRoundPlus, tone: "lead", verb: "Open lead" },
  updates: { icon: Sparkles, tone: "news", verb: "What's new" },
};

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

/** Today and Earlier, newest first; unread lines carry a dot, not a group. */
export function groupNotifications(
  list: readonly UpdateNotification[],
  now: number = Date.now(),
) {
  const newest = [...list].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  );
  const today = new Date(now).toDateString();
  const isToday = (entry: UpdateNotification) =>
    new Date(entry.created_at).toDateString() === today;
  return [
    { key: "today", title: "Today", items: newest.filter(isToday) },
    {
      key: "earlier",
      title: "Earlier",
      items: newest.filter((entry) => !isToday(entry)),
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
  onOpen,
}: {
  entry: UpdateNotification;
  disabled: boolean;
  onOpen: () => void;
}) {
  const kind = KINDS[entry.kind];
  const Icon = kind.icon;
  const lead = LEAD_KINDS.has(entry.kind);
  const letters = lead ? initials(leadName(entry)) : "";
  // A lead says where it came from ("Meta Ads · 11 h ago"); others their words.
  const source = lead ? (leadSource(entry).split(":")[0] ?? "").trim() : "";
  const when = <time dateTime={entry.created_at}>{ago(entry.created_at)}</time>;
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
          {letters ? (
            <span className={styles.initials}>{letters}</span>
          ) : (
            <Icon size={20} />
          )}
        </span>
        <span className={styles.words}>
          {/* As the picked design words it: the name shows more of itself. */}
          <strong>
            {lead ? entry.title.replace(/\s+now$/, "") : entry.title}
          </strong>
          <small>
            {source ? (
              <>
                {source} · {when}
              </>
            ) : entry.body ? (
              <>
                {when} · {entry.body}
              </>
            ) : (
              when
            )}
          </small>
          {!entry.read ? <span className={styles.hidden}>Unread</span> : null}
        </span>
        <span className={styles.hidden}>{kind.verb}</span>
        <ChevronRight className={styles.chevron} size={20} aria-hidden="true" />
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
  const unread = notifications.filter((entry) => !entry.read);
  const groups = groupNotifications(notifications);
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
          {markRead && unread.length ? (
            <div className={styles.toolbar}>
              <span>{`${unread.length} unread`}</span>
              <button
                type="button"
                className={styles.readAll}
                disabled={pending !== null}
                onClick={readAll}
              >
                <CheckCheck size={16} aria-hidden="true" />
                Mark all read
              </button>
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
                    disabled={
                      pending !== null ||
                      (entry.kind !== "updates" &&
                        !isRelativeUpdateHref(entry.href))
                    }
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
