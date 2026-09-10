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
import { useAppUpdates } from "./app-updates-provider";
import { AppUpdatesInbox, AppUpdatePopoverContent } from "./app-updates-inbox";
import { ownedTargetHref } from "./notification-target";
export { ownedTargetHref } from "./notification-target";

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
 * The compact bell shares the mounted app-update provider with the inbox.
 * Opening it never marks a release read. Isolated legacy notification previews
 * retain their explicit unavailable state when no provider is installed.
 */
export function NotificationPopover({
  panelRef,
  onClose,
}: NotificationPopoverProps) {
  const updates = useAppUpdates();
  return (
    <div
      id="learner-notifications-popover"
      ref={panelRef}
      className={styles.popover}
      role="dialog"
      aria-modal="false"
      aria-labelledby="learner-notifications-popover-title"
      aria-describedby="learner-notifications-popover-description"
    >
      <div className={styles.popoverHeader}>
        <h2 id="learner-notifications-popover-title">Notifications</h2>
        <button
          type="button"
          className={styles.popoverClose}
          onClick={onClose}
          aria-label="Close notifications"
        >
          <X size={16} aria-hidden="true" />
        </button>
      </div>

      {updates ? (
        <AppUpdatePopoverContent />
      ) : (
        <div className={styles.popoverBody}>
          <div className={styles.popoverIcon} aria-hidden="true">
            <Bell size={20} />
          </div>
          <div>
            <p className={styles.popoverStateTitle}>
              {NOTIFICATION_SOURCE_UNAVAILABLE_COPY.heading}
            </p>
            <p
              id="learner-notifications-popover-description"
              className={styles.popoverCopy}
            >
              {NOTIFICATION_SOURCE_UNAVAILABLE_COPY.message}
            </p>
          </div>
        </div>
      )}

      <div className={styles.popoverFooter}>
        <Link
          href={updates ? ROUTES.notifications : ROUTES.learning}
          className={styles.popoverAction}
          onClick={onClose}
        >
          {updates ? "View all updates" : "Go to My Learning"}{" "}
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
          <Link className="button button--cobalt" href={ROUTES.learning}>
            Go to My Learning <ArrowRight size={15} aria-hidden="true" />
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
  resource: providedResource,
  onRetry,
}: NotificationsRuntimeProps) {
  const updates = useAppUpdates();
  if (updates && providedResource === undefined) return <AppUpdatesInbox />;
  const resource = providedResource ?? defaultResource;
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
