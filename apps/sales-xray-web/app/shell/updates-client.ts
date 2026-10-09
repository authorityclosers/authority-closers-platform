export type UpdateNote = Readonly<{
  key: string;
  version: number;
  release_id: string;
  date: string;
  title: string;
  items: string[];
  major: boolean;
  draft: boolean;
  seen: boolean;
  published_at: string | null;
}>;
export type UpdateNotification = Readonly<{
  id: string;
  kind: "updates" | "report_ready" | "analysis_paused" | "invite_received";
  title: string;
  href: string | null;
  urgent: boolean;
  created_at: string;
  read: boolean;
  count?: number;
  body?: string;
}>;

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new Error("invalid_updates_response");
  return value as Record<string, unknown>;
}
function text(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}
function count(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}
function timestamp(value: unknown): value is string {
  return (
    text(value) &&
    /^\d{4}-\d{2}-\d{2}T/.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}
export function isRelativeUpdateHref(value: unknown): value is string {
  return (
    text(value) &&
    value.startsWith("/") &&
    !value.startsWith("//") &&
    !/[\\\u0000-\u001f\u007f]/.test(value)
  );
}
function note(value: unknown): UpdateNote {
  const v = record(value);
  if (
    !text(v.key) ||
    !count(v.version) ||
    v.version < 1 ||
    !text(v.release_id) ||
    !text(v.date) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(v.date) ||
    !Number.isFinite(Date.parse(v.date)) ||
    !text(v.title) ||
    !Array.isArray(v.items) ||
    !v.items.length ||
    !v.items.every(text) ||
    typeof v.major !== "boolean" ||
    typeof v.draft !== "boolean" ||
    typeof v.seen !== "boolean" ||
    !(v.published_at === null || timestamp(v.published_at))
  )
    throw new Error("invalid_updates_response");
  return v as UpdateNote;
}
function notification(value: unknown): UpdateNotification {
  const v = record(value);
  const release = v.kind === "updates";
  if (
    !text(v.id) ||
    !text(v.title) ||
    !timestamp(v.created_at) ||
    typeof v.read !== "boolean" ||
    typeof v.urgent !== "boolean" ||
    (release
      ? !count(v.count) || v.count < 1 || v.href !== null || v.urgent !== false
      : !["report_ready", "analysis_paused", "invite_received"].includes(
          String(v.kind),
        ) ||
        typeof v.body !== "string" ||
        typeof v.href !== "string")
  )
    throw new Error("invalid_notifications_response");
  // A bad destination must not hide an otherwise valid notification.
  return {
    ...v,
    href: isRelativeUpdateHref(v.href) ? v.href : null,
  } as UpdateNotification;
}
export function parseUpdates(value: unknown) {
  const v = record(value);
  if (!Array.isArray(v.updates) || !count(v.unseen_count))
    throw new Error("invalid_updates_response");
  return { notes: v.updates.map(note), unseen_count: v.unseen_count };
}
export function parseNotifications(value: unknown) {
  const v = record(value);
  if (!Array.isArray(v.notifications) || !count(v.unread_count))
    throw new Error("invalid_notifications_response");
  return {
    notifications: v.notifications.map(notification),
    unread_count: v.unread_count,
  };
}
export function parseSeen(value: unknown) {
  const v = record(value);
  if (!count(v.unseen_count)) throw new Error("invalid_seen_response");
  return { unseen_count: v.unseen_count };
}
export function parseRead(value: unknown) {
  const v = record(value);
  if (!count(v.unread_count)) throw new Error("invalid_read_response");
  return { unread_count: v.unread_count };
}
async function request(path: string, body?: object): Promise<unknown> {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: {
      accept: "application/json",
      ...(body ? { "content-type": "application/json" } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok)
    throw new Error(`updates_request_failed:${response.status}`);
  return response.json();
}
export const readUpdates = async () =>
  parseUpdates(await request("/v1/updates"));
export const readNotifications = async () =>
  parseNotifications(await request("/v1/notifications"));
export const markUpdatesSeen = async (keys: string[]) =>
  parseSeen(await request("/v1/updates/seen", { keys }));
export const markNotificationsRead = async (ids: string[]) =>
  parseRead(await request("/v1/notifications/read", { ids }));
