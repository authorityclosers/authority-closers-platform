"use client";

/**
 * What is due within the hour, as a red banner (owner, 25 Oct 2026, the client
 * demo, workflow 12: "a red top banner such as <lead> follow-up in 1 hour, with
 * a haptic"). The shell asks Sales Xray every minute, and when the app comes
 * back to the front, for the seller's soonest follow-up, task or meeting due
 * within the hour (GET /v1/lead-desk/soon, quiet outside work hours); the first
 * time it sees one, it raises the urgent banner, with the urgent haptic, naming
 * the lead and opening it. Once per follow-up: a refresh or another tab doesn't
 * raise it again. The lead's name is read on the seller's own session; a push
 * never carries it. It reads only while the shell says so (signed in, loaded,
 * not under test), and stops for a workspace without leads (Personal).
 */

import { useEffect } from "react";

import { raiseAlert } from "../ui/alerts";

export type SoonItem = {
  lead_id: string;
  lead_name: string;
  what: "follow_up" | "task" | "meeting";
  at: string;
  minutes: number;
  title: string | null;
  words: string;
};

const EVERY_MS = 60 * 1000;
const SEEN_KEY = "sx.due-soon.seen";
const KEEP = 50;

/** The soonest thing due within the hour; null for none; "off" where leads don't apply. */
export async function readSoon(
  signal?: AbortSignal,
): Promise<SoonItem | null | "off"> {
  try {
    const response = await fetch("/v1/lead-desk/soon", {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: { accept: "application/json" },
      signal,
    });
    if ([401, 403, 404].includes(response.status)) return "off";
    if (!response.ok) return null;
    const body = (await response.json()) as { item?: Partial<SoonItem> | null };
    const item = body.item;
    return item &&
      typeof item.lead_id === "string" &&
      typeof item.words === "string" &&
      typeof item.at === "string"
      ? (item as SoonItem)
      : null;
  } catch {
    return null;
  }
}

function seen(): string[] {
  try {
    const kept: unknown = JSON.parse(
      window.localStorage.getItem(SEEN_KEY) ?? "[]",
    );
    return Array.isArray(kept)
      ? kept.filter((key) => typeof key === "string")
      : [];
  } catch {
    return [];
  }
}

function remember(key: string) {
  try {
    window.localStorage.setItem(
      SEEN_KEY,
      JSON.stringify([...seen().filter((k) => k !== key), key].slice(-KEEP)),
    );
  } catch {
    // A private window keeps nothing: the banner may show again next visit.
  }
}

/** Raise the banner for this item, once per follow-up. True when raised. */
export function showSoon(item: SoonItem): boolean {
  const key = `${item.lead_id}:${item.what}:${item.at}`;
  if (seen().includes(key)) return false;
  remember(key);
  raiseAlert({
    id: `due-soon:${key}`,
    level: "normal",
    emphasis: "urgent",
    title: item.words,
    message: item.title ?? "Tap Open to see the lead.",
    action: {
      label: "Open",
      href: `/leads?lead=${encodeURIComponent(item.lead_id)}`,
    },
    timeout: 30_000,
  });
  return true;
}

/** Watches for work due within the hour while `live`; renders nothing. */
export function DueSoonWatch({ live }: { live: boolean }) {
  useEffect(() => {
    if (!live) return;
    const controller = new AbortController();
    let reading = false;
    // A workspace without leads (Personal) answers "off": no more reads.
    let off = false;
    const check = () => {
      if (off || reading || document.visibilityState !== "visible") return;
      reading = true;
      void readSoon(controller.signal)
        .then((found) => {
          if (controller.signal.aborted) return;
          if (found === "off") off = true;
          else if (found) showSoon(found);
        })
        .finally(() => {
          reading = false;
        });
    };
    check();
    const timer = window.setInterval(check, EVERY_MS);
    document.addEventListener("visibilitychange", check);
    window.addEventListener("focus", check);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("focus", check);
    };
  }, [live]);
  return null;
}
