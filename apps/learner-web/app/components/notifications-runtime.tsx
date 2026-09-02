"use client";

import { Bell } from "lucide-react";
import Link from "next/link";

import { ROUTES } from "../lib/routes";

export function NotificationsRuntime() {
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
              Notification history is not available in this first-slice
              workspace.
            </p>
          </div>
        </div>
      </header>

      <section
        className="card empty-notifications-card"
        aria-labelledby="empty-notif-title"
      >
        <div className="empty-icon-circle" aria-hidden="true">
          <Bell size={28} />
        </div>
        <h2 id="empty-notif-title" className="empty-title">
          No notifications to show
        </h2>
        <p className="empty-description">
          This surface does not yet have a server-backed notification source, so
          no alerts or read-state changes are being presented here.
        </p>
        <div className="empty-actions">
          <Link className="button button--cobalt" href={ROUTES.dashboard}>
            Back to Dashboard
          </Link>
        </div>
      </section>
    </div>
  );
}
