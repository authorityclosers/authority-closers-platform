"use client";

/**
 * Notifications (owner program, 25 Oct 2026, item 5: "ugly and stupid";
 * rebuild it with a strong core and some personality). A sheet from the bell:
 * what needs you first, then what is new, then what you have read; each line
 * in its kind's colour with its one action, unread lines marked, and Mark all
 * read. Nothing waiting: a calm line that says what lands here.
 */

import {
  Bell,
  BellRing,
  CheckCheck,
  FileCheck2,
  PauseCircle,
  Sparkles,
  UserPlus,
  type LucideIcon,
} from "lucide-react";
import { useRef, useState } from "react";

import { Sheet } from "../ui/sheet";
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

/** Needs you (urgent, unread), New (unread), Earlier (read): newest first. */
export function groupNotifications(list: readonly UpdateNotification[]) {
  const newest = [...list].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  );
  return [
    {
      key: "urgent",
      title: "Needs you",
      items: newest.filter((entry) => !entry.read && entry.urgent),
    },
    {
      key: "new",
      title: "New",
      items: newest.filter((entry) => !entry.read && !entry.urgent),
    },
    {
      key: "earlier",
      title: "Earlier",
      items: newest.filter((entry) => entry.read),
    },
  ].filter((group) => group.items.length);
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
  return (
    <li data-unread={!entry.read} data-urgent={entry.urgent || undefined}>
      <button
        type="button"
        className={styles.row}
        data-tone={kind.tone}
        disabled={disabled}
        onClick={onOpen}
      >
        <span className={styles.icon} aria-hidden="true">
          <Icon size={20} />
        </span>
        <span className={styles.words}>
          <strong>{entry.title}</strong>
          {entry.body ? <span>{entry.body}</span> : null}
          <small>
            <time dateTime={entry.created_at}>{ago(entry.created_at)}</time>
            {!entry.read ? <span className={styles.unread}>Unread</span> : null}
          </small>
        </span>
        <span className={styles.verb}>{kind.verb}</span>
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
              <h3 data-group={group.key}>
                {group.title}
                <span>{group.items.length}</span>
              </h3>
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
