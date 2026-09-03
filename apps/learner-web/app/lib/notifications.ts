export type NotificationKind = "learning" | "account" | "system";

export type NotificationItem = {
  id: string;
  title: string;
  message: string;
  kind: NotificationKind;
  read: boolean;
  createdAt: string | null;
  targetHref: string | null;
};

export type NotificationResource =
  | { status: "loading"; items?: NotificationItem[] }
  | { status: "ready"; items: NotificationItem[]; unreadCount: number }
  | {
      status: "empty";
      reason: "source_not_connected" | "no_notifications";
      items: [];
    }
  | {
      status: "partial";
      items: NotificationItem[];
      unreadCount: number | null;
      message: string;
    }
  | {
      status: "retryable_error";
      items?: NotificationItem[];
      message: string;
    }
  | { status: "terminal_error"; message: string }
  | {
      status: "offline_or_stale";
      items: NotificationItem[];
      unreadCount: number | null;
      message: string;
    }
  | { status: "unauthorized_or_expired"; message: string };

export interface NotificationReadPort {
  list(signal?: AbortSignal): Promise<NotificationResource>;
}

/**
 * The first slice has no notification service contract. This adapter makes
 * that boundary explicit without inventing a client-side source of truth.
 */
export const unavailableNotificationReadPort: NotificationReadPort = {
  async list(): Promise<NotificationResource> {
    return {
      status: "empty",
      reason: "source_not_connected",
      items: [],
    };
  },
};

export function formatNotificationTime(createdAt: string | null): string {
  if (!createdAt) return "Time unavailable";
  const parsed = new Date(createdAt);
  if (Number.isNaN(parsed.getTime())) return "Time unavailable";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

export function notificationKindLabel(kind: NotificationKind): string {
  if (kind === "learning") return "Learning";
  if (kind === "account") return "Account";
  return "System";
}
