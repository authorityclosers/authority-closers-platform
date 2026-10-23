/**
 * The Leads badge's one read (route splitting, 23 Oct 2026): its own module, so
 * the tab bar on every page doesn't load the whole Lead Desk client for it.
 */

export type Badge = { overdue: number; to_call: number };

export async function readBadge(signal?: AbortSignal): Promise<Badge | null> {
  try {
    const response = await fetch("/v1/lead-desk/badge", {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: { accept: "application/json" },
      signal,
    });
    if (!response.ok) return null;
    const badge = (await response.json()) as Partial<Badge>;
    return typeof badge.overdue === "number" &&
      typeof badge.to_call === "number"
      ? { overdue: badge.overdue, to_call: badge.to_call }
      : null;
  } catch {
    return null;
  }
}
