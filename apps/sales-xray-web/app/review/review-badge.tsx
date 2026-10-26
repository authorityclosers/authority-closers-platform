"use client";

/**
 * Review's place in the shell (owner, 19 Oct): only gold reviewers (and the
 * owner, for the figures) see it. One shared reader, like the Leads badge:
 * on open, when the app comes back to the front and every two minutes. A new
 * Report waiting for review raises a corner card with a Review button; the
 * last count is remembered so a returning reviewer's chip draws on first paint.
 */

import { ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore, type CSSProperties } from "react";

import { notify } from "../notice-center";
import { readBadge, type Badge } from "./review-client";
import styles from "./review.module.css";

const EVERY_MS = 2 * 60 * 1000;
const AGAIN_MS = 20 * 1000;
const STORE = "sx-review-badge";
/** Review's own pages: /review and below, not every path that starts so. */
const onReview = (path: string | null | undefined) =>
  path != null && /^\/review(\/|$)/.test(path);
const SEEN = "sx-review-seen";

let current: Badge | null = remembered();
let readAt = 0;
let timer: number | null = null;
let reading = false;
const listeners = new Set<() => void>();

function remembered(): Badge | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORE);
    const value = raw ? (JSON.parse(raw) as Badge) : null;
    return value && typeof value.reviewer === "boolean" ? value : null;
  } catch {
    return null;
  }
}

function keep(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private mode: the chip just draws after the first read */
  }
}

function seenAt(): string | null {
  try {
    return window.localStorage.getItem(SEEN);
  } catch {
    return null;
  }
}

/** The reviewer opened Review: nothing waiting is "new" any more. */
export function markReviewSeen(newestAt: string | null) {
  if (newestAt) keep(SEEN, newestAt);
}

function announce(next: Badge) {
  if (!next.reviewer || !next.waiting || !next.newest_at) return;
  const seen = seenAt();
  if (seen === null) {
    // First visit on this device: remember, don't alarm.
    keep(SEEN, next.newest_at);
    return;
  }
  if (next.newest_at <= seen) return;
  if (onReview(window.location.pathname)) return;
  keep(SEEN, next.newest_at);
  notify({
    id: "review-new-report",
    tone: "info",
    title: "New Report to review",
    message:
      next.waiting === 1
        ? "One call is waiting for your review."
        : `${next.waiting} calls are waiting for your review.`,
    action: {
      label: "Review",
      run: () => {
        window.location.href = new URL("/review", window.location.origin).href;
      },
    },
    timeout: 20_000,
  });
}

function emit(next: Badge | null) {
  if (next) {
    keep(STORE, JSON.stringify(next));
    announce(next);
  }
  if (
    next?.reviewer === current?.reviewer &&
    next?.metrics === current?.metrics &&
    next?.waiting === current?.waiting
  )
    return;
  current = next;
  listeners.forEach((listener) => listener());
}

/** Review's own fresh count, straight after its queue loads. */
export function publishReviewBadge(next: Badge) {
  readAt = Date.now();
  emit(next);
}

function read(force = false) {
  if (reading || document.visibilityState !== "visible") return;
  if (!force && Date.now() - readAt < AGAIN_MS) return;
  reading = true;
  readAt = Date.now();
  void readBadge()
    .then((badge) => {
      if (badge) emit(badge);
    })
    .finally(() => {
      reading = false;
    });
}

const onVisible = () => read();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) {
    read(true);
    timer = window.setInterval(() => read(true), EVERY_MS);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size) return;
    if (timer !== null) window.clearInterval(timer);
    timer = null;
    document.removeEventListener("visibilitychange", onVisible);
    window.removeEventListener("focus", onVisible);
  };
}

const snapshot = () => current;
const serverSnapshot = () => null;
const idle = () => () => undefined;

export function useReviewBadge(live: boolean): Badge | null {
  return useSyncExternalStore(
    live ? subscribe : idle,
    live ? snapshot : serverSnapshot,
    serverSnapshot,
  );
}

function Count({ waiting }: { waiting: number }) {
  return waiting > 0 ? (
    <span className={styles.badgeCount} aria-hidden="true">
      {waiting > 99 ? "99+" : waiting}
    </span>
  ) : null;
}

/** The rail entry; nothing at all for people who don't review. */
export function ReviewRailLink({
  live,
  className,
  activeClassName,
  nameStyle,
}: {
  live: boolean;
  className: string;
  activeClassName: string;
  nameStyle: CSSProperties;
}) {
  const badge = useReviewBadge(live);
  const active = onReview(usePathname());
  if (!badge || (!badge.reviewer && !badge.metrics)) return null;
  const label = badge.waiting ? `Review, ${badge.waiting} waiting` : "Review";
  return (
    <Link
      className={`${className}${active ? ` ${activeClassName}` : ""}`}
      href={badge.reviewer ? "/review" : "/review/figures"}
      prefetch={false}
      aria-label={label}
      data-rail-tip={label}
      aria-current={active ? "page" : undefined}
    >
      <span className={styles.badgeIcon}>
        <ClipboardCheck size={20} strokeWidth={1.75} aria-hidden="true" />
        <Count waiting={badge.waiting} />
      </span>
      <span style={nameStyle}>Review</span>
    </Link>
  );
}

/** Phones keep five tabs (owner, 17 Oct); a reviewer gets a chip in the top bar. */
export function ReviewBarChip({ live }: { live: boolean }) {
  const badge = useReviewBadge(live);
  const active = onReview(usePathname());
  if (!badge?.reviewer || active) return null;
  return (
    <Link
      className={styles.barChip}
      href="/review"
      prefetch={false}
      data-waiting={badge.waiting > 0 ? "" : undefined}
      aria-label={badge.waiting ? `Review, ${badge.waiting} waiting` : "Review"}
    >
      <ClipboardCheck size={16} strokeWidth={2} aria-hidden="true" />
      {badge.waiting > 0 ? (
        <span className={styles.barChipCount}>{badge.waiting}</span>
      ) : (
        <span className={styles.barChipText}>Review</span>
      )}
    </Link>
  );
}
