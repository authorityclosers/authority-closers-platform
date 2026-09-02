import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { NotificationResource } from "../lib/notifications";
import { NotificationsRuntime } from "./notifications-runtime";

const items = [
  {
    id: "notification-1",
    title: "Your next practice is ready",
    message: "Continue from the saved learning checkpoint.",
    kind: "learning" as const,
    read: false,
    createdAt: "2026-09-02T10:30:00Z",
    targetHref: "/learning",
  },
  {
    id: "notification-2",
    title: "Profile updated",
    message: "Your account details are current.",
    kind: "account" as const,
    read: true,
    createdAt: null,
    targetHref: null,
  },
];

describe("NotificationsRuntime", () => {
  it("states the unconnected first-slice boundary without fabricating alerts", () => {
    const html = renderToStaticMarkup(createElement(NotificationsRuntime));

    expect(html).toContain("Notifications are not connected yet");
    expect(html).toContain("server-backed notification source");
    expect(html).not.toContain("Mark all read");
    expect(html).not.toContain("Welcome to Authority Closers");
  });

  it("renders read state, safe related links, and timestamps when data exists", () => {
    const resource: NotificationResource = {
      status: "ready",
      items,
      unreadCount: 1,
    };
    const html = renderToStaticMarkup(
      createElement(NotificationsRuntime, { resource }),
    );

    expect(html).toContain('aria-label="Notification history"');
    expect(html).toContain("Your next practice is ready");
    expect(html).toContain("Unread");
    expect(html).toContain("Read");
    expect(html).toContain('href="/learning"');
    expect(html).toContain("Open related screen");
  });

  it("does not turn an external notification target into a navigation link", () => {
    const resource: NotificationResource = {
      status: "ready",
      items: [{ ...items[0], targetHref: "https://example.com" }],
      unreadCount: 1,
    };
    const html = renderToStaticMarkup(
      createElement(NotificationsRuntime, { resource }),
    );

    expect(html).not.toContain("https://example.com");
    expect(html).not.toContain("Open related screen");
  });

  it("shows an honest empty state for a connected source with no rows", () => {
    const resource: NotificationResource = {
      status: "ready",
      items: [],
      unreadCount: 0,
    };
    const html = renderToStaticMarkup(
      createElement(NotificationsRuntime, { resource }),
    );

    expect(html).toContain("No notifications yet");
    expect(html).not.toContain("not connected yet");
  });

  it("keeps partial and offline data visible with an explicit status", () => {
    const resource: NotificationResource = {
      status: "offline_or_stale",
      items,
      unreadCount: null,
      message: "Showing the last known notification view from this device.",
    };
    const html = renderToStaticMarkup(
      createElement(NotificationsRuntime, { resource }),
    );

    expect(html).toContain("last known notification view");
    expect(html).toContain('role="status"');
    expect(html).toContain("Your next practice is ready");
  });

  it("offers retry only for a retryable notification failure", () => {
    const resource: NotificationResource = {
      status: "retryable_error",
      message: "The notification service could not be reached.",
    };
    const html = renderToStaticMarkup(
      createElement(NotificationsRuntime, {
        resource,
        onRetry: vi.fn(),
      }),
    );

    expect(html).toContain('role="alert"');
    expect(html).toContain("Notifications could not load");
    expect(html).toContain("> Retry</button>");
  });
});
