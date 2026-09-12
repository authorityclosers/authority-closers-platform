"use client";

import {
  ArrowRight,
  Bell,
  Check,
  CheckCheck,
  LoaderCircle,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useState, useRef, useEffect } from "react";
import { formatNotificationTime } from "../lib/notifications";
import { ROUTES } from "../lib/routes";
import { useAppUpdates } from "./app-updates-provider";
import { ownedTargetHref } from "./notification-target";
import styles from "./notifications-runtime.module.css";

export function AppUpdatesInbox() {
  const updates = useAppUpdates();
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const unreadFilterRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (
      filter === "unread" &&
      updates?.state.status === "ready" &&
      updates.state.feed.unread_count === 0 &&
      document.activeElement === document.body
    )
      unreadFilterRef.current?.focus();
  }, [filter, updates?.state]);
  if (!updates) return null;
  const { state, pendingId, saveError, refresh, markRead } = updates;
  const feed = state.status === "ready" ? state.feed : null;
  const items =
    feed?.items.filter((item) => filter !== "unread" || !item.read) ?? [];
  return (
    <div className={styles.inbox}>
      <header className={styles.inboxHeader}>
        <span className={styles.inboxArt} aria-hidden="true">
          <Bell size={29} />
          <Sparkles size={18} />
        </span>
        <div>
          <p className={styles.eyebrow}>What’s new</p>
          <h1>Notifications</h1>
          <p>Small updates. A better place to learn.</p>
        </div>
      </header>
      <div className={styles.inboxTools}>
        <div
          className={styles.filters}
          role="group"
          aria-label="Filter notifications"
        >
          <button
            type="button"
            aria-pressed={filter === "all"}
            onClick={() => setFilter("all")}
          >
            App updates
          </button>
          <button
            type="button"
            ref={unreadFilterRef}
            aria-pressed={filter === "unread"}
            onClick={() => setFilter("unread")}
          >
            Unread{feed ? <span>{feed.unread_count}</span> : null}
          </button>
        </div>
        <button
          type="button"
          className={styles.refresh}
          onClick={refresh}
          disabled={state.status === "loading" || pendingId !== null}
          aria-label="Refresh notifications"
        >
          <RefreshCw size={17} aria-hidden="true" />
        </button>
      </div>
      {state.status === "loading" ? (
        <div className={styles.state} role="status">
          <LoaderCircle className="spin" size={22} aria-hidden="true" />
          Loading updates…
        </div>
      ) : null}
      {state.status === "error" ? (
        <div className={styles.state} role="alert">
          <h2>Updates couldn’t load</h2>
          <p>Check your connection and try again.</p>
          <button
            type="button"
            className="button button--outline"
            onClick={refresh}
          >
            Try again
          </button>
        </div>
      ) : null}
      {state.status === "signed_out" || state.status === "forbidden" ? (
        <div className={styles.state} role="alert">
          <h2>
            {state.status === "signed_out"
              ? "Sign in to see your updates"
              : "Open your learner account"}
          </h2>
          <p>App updates are available from your academy’s learner account.</p>
          <Link className="button button--outline" href={ROUTES.login}>
            Sign in
          </Link>
        </div>
      ) : null}
      {saveError ? (
        <p className={styles.statusBanner} role="alert">
          {saveError}
        </p>
      ) : null}
      {feed && items.length === 0 ? (
        <section className={styles.state}>
          <CheckCheck size={28} aria-hidden="true" />
          <h2>
            {filter === "unread" ? "You’re up to date" : "No app updates yet"}
          </h2>
          <p>
            {filter === "unread"
              ? "Your release notes are still in App updates."
              : "New release notes will appear here when they’re available."}
          </p>
        </section>
      ) : null}
      {items.length ? (
        <ul className={styles.releaseList} aria-label="App update history">
          {items.map((item) => {
            const target = ownedTargetHref(item.target_href);
            return (
              <li
                key={item.id}
                className={styles.releaseCard}
                data-read={item.read}
              >
                <div className={styles.releaseMeta}>
                  <span className={styles.version}>
                    <Sparkles size={14} aria-hidden="true" />
                    {item.version}
                  </span>
                  <span className={styles.readState}>
                    {item.read ? "Read" : "New"}
                  </span>
                </div>
                <h2>{item.title}</h2>
                <p>{item.message}</p>
                {item.highlights.length ? (
                  <ul className={styles.highlights}>
                    {item.highlights.map((highlight) => (
                      <li key={highlight}>
                        <Check size={16} aria-hidden="true" />
                        <span>{highlight}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                <div className={styles.releaseActions}>
                  {target && target !== ROUTES.notifications ? (
                    <Link className={styles.target} href={target}>
                      Explore update <ArrowRight size={15} aria-hidden="true" />
                    </Link>
                  ) : null}
                  <button
                    type="button"
                    className={item.read ? styles.readReceipt : styles.markRead}
                    aria-disabled={item.read || pendingId !== null}
                    aria-busy={pendingId === item.id}
                    onClick={() => void markRead(item.id)}
                  >
                    {pendingId === item.id ? (
                      <LoaderCircle
                        size={16}
                        className="spin"
                        aria-hidden="true"
                      />
                    ) : (
                      <CheckCheck size={16} aria-hidden="true" />
                    )}
                    <span aria-live="polite">
                      {pendingId === item.id
                        ? "Saving…"
                        : item.read
                          ? "Read"
                          : "Mark as read"}
                    </span>
                  </button>
                  <time dateTime={item.created_at}>
                    {formatNotificationTime(item.created_at)}
                  </time>
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
      <p className={styles.sourceNote}>
        App release notes. Learning and account alerts are not connected yet.
      </p>
    </div>
  );
}

export function AppUpdatePopoverContent() {
  const updates = useAppUpdates();
  if (!updates) return null;
  const { state } = updates;
  const newest = state.status === "ready" ? state.feed.items[0] : null;
  return (
    <div className={styles.popoverBody}>
      <div className={styles.popoverIcon} aria-hidden="true">
        <Sparkles size={20} />
      </div>
      <div>
        <p className={styles.popoverStateTitle}>
          {newest?.title ??
            (state.status === "loading"
              ? "Loading updates…"
              : state.status === "ready"
                ? "No app updates yet"
                : "Open notifications to reconnect")}
        </p>
        <p
          id="learner-notifications-popover-description"
          className={styles.popoverCopy}
        >
          {newest
            ? `${newest.version} · ${state.status === "ready" ? state.feed.unread_count : 0} unread`
            : "Release notes and what’s new in your app."}
        </p>
      </div>
    </div>
  );
}
