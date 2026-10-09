"use client";

import { Bell } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  isRelativeUpdateHref,
  type UpdateNotification,
} from "./updates-client";
import styles from "./updates-bell.module.css";

export function UpdatesBell({
  notifications,
  unreadCount,
  status,
  openNews,
  openEvent,
}: {
  notifications: readonly UpdateNotification[];
  unreadCount: number;
  status: "loading" | "ready" | "error";
  openNews: (anchor: HTMLElement | null) => void;
  openEvent: (entry: UpdateNotification) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [place, setPlace] = useState({ left: 8, top: 8 });
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();
  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };
  useLayoutEffect(() => {
    if (!open) return;
    const measure = () => {
      const rect = trigger.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(340, window.innerWidth - 16);
      const height = Math.min(420, window.innerHeight - 16);
      setPlace({
        left: Math.max(
          8,
          Math.min(rect.right - width, window.innerWidth - width - 8),
        ),
        top: Math.max(
          8,
          Math.min(rect.bottom + 8, window.innerHeight - height - 8),
        ),
      });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [open]);
  useEffect(() => {
    if (!open) return;
    panel.current?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        trigger.current?.focus();
      }
    };
    const outside = (event: PointerEvent) => {
      if (
        !panel.current?.contains(event.target as Node) &&
        !trigger.current?.contains(event.target as Node)
      )
        setOpen(false);
    };
    document.addEventListener("keydown", keydown);
    document.addEventListener("pointerdown", outside);
    return () => {
      document.removeEventListener("keydown", keydown);
      document.removeEventListener("pointerdown", outside);
    };
  }, [open]);
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
        aria-controls={open ? id : undefined}
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
      {open
        ? createPortal(
            <div
              ref={panel}
              id={id}
              className={styles.panel}
              style={place}
              role="dialog"
              aria-label="Notifications"
              tabIndex={-1}
            >
              <h2>Notifications</h2>
              {status === "error" ? (
                <p role="status">
                  Notifications could not load. Try again when you return.
                </p>
              ) : null}
              {status === "loading" && !notifications.length ? (
                <p role="status">Loading notifications…</p>
              ) : null}
              {status === "ready" && !notifications.length ? (
                <p>You&apos;re up to date.</p>
              ) : null}
              {failed ? (
                <p role="alert">Could not open this notification. Try again.</p>
              ) : null}
              <ul>
                {notifications.map((entry) => (
                  <li key={entry.id} data-unread={!entry.read}>
                    <button
                      type="button"
                      disabled={
                        pending !== null ||
                        (entry.kind !== "updates" &&
                          !isRelativeUpdateHref(entry.href))
                      }
                      onClick={() => {
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
                      }}
                    >
                      <strong>{entry.title}</strong>
                      {entry.body ? <span>{entry.body}</span> : null}
                      {!entry.read ? <small>Unread</small> : null}
                    </button>
                  </li>
                ))}
              </ul>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
