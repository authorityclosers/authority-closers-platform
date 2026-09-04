"use client";

import {
  ArrowRight,
  Bell,
  CircleAlert,
  Info,
  LoaderCircle,
  RefreshCw,
  WifiOff,
  X,
} from "lucide-react";
import Link from "next/link";
import type { RefObject } from "react";

import {
  formatNotificationTime,
  NOTIFICATION_SOURCE_UNAVAILABLE_COPY,
  notificationKindLabel,
  type NotificationItem,
  type NotificationResource,
} from "../lib/notifications";
import { ROUTES } from "../lib/routes";
import styles from "./notifications-runtime.module.css";

type NotificationsRuntimeProps = {
  resource?: NotificationResource;
  onRetry?: () => void;
};

export type NotificationPopoverProps = {
  panelRef?: RefObject<HTMLDivElement | null>;
  onClose: () => void;
};

const defaultResource: NotificationResource = {
  status: "empty",
  reason: "source_not_connected",
  items: [],
};

/**
 * The compact bell surface mirrors the route's unavailable state until a
 * server-backed notification/read-state port is activated. It owns no unread
 * count and performs no read mutation.
 */
export function NotificationPopover({
  panelRef,
  onClose,
}: NotificationPopoverProps) {
  return (
    <div
      id="learner-notifications-popover"
      ref={panelRef}
      className="notification-popover"
      role="dialog"
      aria-modal="false"
      aria-labelledby="learner-notifications-popover-title"
      aria-describedby="learner-notifications-popover-description"
    >
      <div className="notification-popover__header">
        <div className="notification-popover__title-row">
          <div>
            <p className="notification-popover__eyebrow">Workspace updates</p>
            <h2
              id="learner-notifications-popover-title"
              className="notification-popover__title"
            >
              Notifications
            </h2>
          </div>
          <button
            type="button"
            className="notification-popover__close"
            onClick={onClose}
            aria-label="Close notifications"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <div className="notification-popover__status-row">
          <span className="notification-popover__status-badge" role="status">
            Unavailable
          </span>
          <p
            id="learner-notifications-popover-description"
            className="notification-popover__subhead"
          >
            Notification history is unavailable in this first-slice workspace.
          </p>
        </div>
      </div>

      <div className="notification-popover__body">
        <div className="notification-popover__empty-icon" aria-hidden="true">
          <Bell size={24} />
        </div>
        <p className="notification-popover__empty-title">
          {NOTIFICATION_SOURCE_UNAVAILABLE_COPY.heading}
        </p>
        <p className="notification-popover__empty-copy">
          {NOTIFICATION_SOURCE_UNAVAILABLE_COPY.message}
        </p>
      </div>

      <div className="notification-popover__footer">
        <Link
          href={ROUTES.notifications}
          className="notification-popover__action-link"
          onClick={onClose}
        >
          View full notifications page{" "}
          <ArrowRight size={14} aria-hidden="true" />
        </Link>
      </div>
    </div>
  );
}

function StateIcon({ tone = "info" }: { tone?: "info" | "warning" | "error" }) {
  const Icon =
    tone === "error" ? CircleAlert : tone === "warning" ? WifiOff : Bell;
  return (
    <span className={styles.stateIcon} data-tone={tone} aria-hidden="true">
      <Icon size={22} />
    </span>
  );
}

export function ownedTargetHref(href: string | null): string | null {
  if (!href || !href.startsWith("/") || href.startsWith("//")) return null;
  // Backslashes are treated as forward slashes by browser URL parsers. Reject
  // literal and encoded separators before resolving against an origin so a
  // value such as /\\evil.example cannot become an external navigation.
  if (/[\\\u0000-\u001f\u007f]/.test(href) || /%(?:2f|5c)/i.test(href)) {
    return null;
  }
  try {
    const parsed = new URL(href, "https://learner.invalid");
    if (parsed.origin !== "https://learner.invalid") return null;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return null;
  }
}

function NotificationRow({ item }: { item: NotificationItem }) {
  const targetHref = ownedTargetHref(item.targetHref);
  return (
    <li className={styles.row} data-read={item.read ? "true" : "false"}>
      <span className={styles.rowIcon} aria-hidden="true">
        {item.kind === "learning" ? <Info size={17} /> : <Bell size={17} />}
      </span>
      <div className={styles.rowCopy}>
        <div className={styles.rowHeading}>
          <h2>{item.title}</h2>
          <span className={styles.kind}>
            {notificationKindLabel(item.kind)}
          </span>
        </div>
        <p>{item.message}</p>
        {targetHref ? (
          <Link className={styles.target} href={targetHref}>
            Open related screen <ArrowRight size={14} aria-hidden="true" />
          </Link>
        ) : null}
      </div>
      <div className={styles.rowMeta}>
        <time dateTime={item.createdAt ?? undefined}>
          {formatNotificationTime(item.createdAt)}
        </time>
        <span className={styles.readState}>
          {item.read ? "Read" : "Unread"}
        </span>
      </div>
    </li>
  );
}

function NotificationsState({
  resource,
  onRetry,
}: {
  resource: NotificationResource;
  onRetry?: () => void;
}) {
  if (resource.status === "loading") {
    return (
      <div
        className={styles.skeleton}
        role="status"
        aria-label="Loading notifications"
      >
        <LoaderCircle className="spin" size={20} aria-hidden="true" />
        <span className={styles.skeletonLine} aria-hidden="true" />
        <span className={styles.skeletonLine} aria-hidden="true" />
      </div>
    );
  }

  if (
    resource.status === "empty" ||
    (resource.status === "ready" && resource.items.length === 0)
  ) {
    const sourceNotConnected =
      resource.status === "empty" && resource.reason === "source_not_connected";
    return (
      <section
        className={styles.state}
        aria-labelledby="notifications-state-title"
      >
        <StateIcon />
        <h2 id="notifications-state-title">
          {sourceNotConnected
            ? NOTIFICATION_SOURCE_UNAVAILABLE_COPY.heading
            : "No notifications yet"}
        </h2>
        <p>
          {sourceNotConnected
            ? NOTIFICATION_SOURCE_UNAVAILABLE_COPY.message
            : "There are no updates to show right now."}
        </p>
        <div className={styles.stateActions}>
          <Link className="button button--cobalt" href={ROUTES.dashboard}>
            Back to Dashboard
          </Link>
        </div>
      </section>
    );
  }

  if (
    resource.status === "retryable_error" ||
    resource.status === "terminal_error"
  ) {
    return (
      <section
        className={styles.state}
        role="alert"
        aria-labelledby="notifications-state-title"
      >
        <StateIcon tone="error" />
        <h2 id="notifications-state-title">
          {resource.status === "retryable_error"
            ? "Notifications could not load"
            : "Notifications are unavailable"}
        </h2>
        <p>{resource.message}</p>
        <div className={styles.stateActions}>
          {resource.status === "retryable_error" && onRetry ? (
            <button
              className="button button--cobalt"
              type="button"
              onClick={onRetry}
            >
              <RefreshCw size={15} aria-hidden="true" /> Retry
            </button>
          ) : null}
          <Link className="button button--outline" href={ROUTES.dashboard}>
            Back to Dashboard
          </Link>
        </div>
      </section>
    );
  }

  if (resource.status === "unauthorized_or_expired") {
    return (
      <section
        className={styles.state}
        role="alert"
        aria-labelledby="notifications-state-title"
      >
        <StateIcon tone="error" />
        <h2 id="notifications-state-title">Sign in to view notifications</h2>
        <p>{resource.message}</p>
        <div className={styles.stateActions}>
          <Link className="button button--cobalt" href={ROUTES.sessionExpired}>
            Sign in again
          </Link>
        </div>
      </section>
    );
  }

  return null;
}

function StatusBanner({ resource }: { resource: NotificationResource }) {
  if (resource.status !== "partial" && resource.status !== "offline_or_stale") {
    return null;
  }
  const offline = resource.status === "offline_or_stale";
  return (
    <div
      className={styles.statusBanner}
      data-tone={offline ? "warning" : "info"}
      role="status"
    >
      {offline ? (
        <WifiOff size={18} aria-hidden="true" />
      ) : (
        <CircleAlert size={18} aria-hidden="true" />
      )}
      <p>{resource.message}</p>
    </div>
  );
}

export function NotificationsRuntime({
  resource = defaultResource,
  onRetry,
}: NotificationsRuntimeProps) {
  const items =
    resource.status === "ready" ||
    resource.status === "partial" ||
    resource.status === "offline_or_stale"
      ? resource.items
      : resource.status === "retryable_error"
        ? (resource.items ?? [])
        : [];
  const showList = items.length > 0;

  return (
    <div className="notifications-view">
      <header
        className="notifications-header"
        aria-labelledby="notifications-heading"
      >
        <div className="learning-breadcrumbs" aria-label="Breadcrumb">
          <Link href={ROUTES.dashboard}>Dashboard</Link>
          <span aria-hidden="true">/</span>
          <span>Notifications</span>
        </div>
        <div className="notifications-header__row">
          <div>
            <h1 id="notifications-heading" className="notifications-title">
              Notifications
            </h1>
            <p className="notifications-subhead">
              Updates about your learning and account, when available.
            </p>
          </div>
        </div>
      </header>

      <NotificationsState resource={resource} onRetry={onRetry} />
      <StatusBanner resource={resource} />
      {showList ? (
        <ul className={styles.list} aria-label="Notification history">
          {items.map((item) => (
            <NotificationRow item={item} key={item.id} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}
