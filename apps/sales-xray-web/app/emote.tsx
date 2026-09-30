"use client";

import { useEffect, useSyncExternalStore, type CSSProperties } from "react";

import styles from "./emote.module.css";

// Our curated emote set: Microsoft Fluent Emoji (flat, MIT), copied into
// public/emotes/emotes.json by app/brands/generate-logos-emotes.mjs. Use an
// emote only for something measured or written in the report (an outcome, a
// finding type, a measured change), never to claim how someone felt.

export type EmoteName =
  | "handshake"
  | "spiral-calendar"
  | "tear-off-calendar"
  | "cross-mark"
  | "no-entry"
  | "thinking-face"
  | "zipper-mouth-face"
  | "neutral-face"
  | "slightly-smiling-face"
  | "grinning-face-with-smiling-eyes"
  | "star-struck"
  | "worried-face"
  | "confused-face"
  | "face-with-raised-eyebrow"
  | "partying-face"
  | "fire"
  | "sparkles"
  | "light-bulb"
  | "trophy"
  | "warning"
  | "check-mark-button"
  | "stopwatch"
  | "hourglass-not-done"
  | "speaking-head"
  | "speech-balloon"
  | "raised-hand"
  | "ear"
  | "headphone"
  | "money-bag"
  | "chart-increasing"
  | "chart-decreasing"
  | "memo"
  | "telephone-receiver"
  | "alarm-clock"
  | "busts-in-silhouette"
  | "magnifying-glass-tilted-left"
  | "rocket"
  | "seedling"
  | "clapping-hands"
  | "flexed-biceps"
  | "bell"
  | "pushpin"
  | "hundred-points"
  | "red-question-mark"
  | "eyes"
  | "brain"
  | "gem-stone"
  | "chequered-flag"
  | "shushing-face"
  | "hugging-face"
  | "face-with-open-mouth"
  | "relieved-face"
  | "sleeping-face"
  | "yawning-face"
  | "person-raising-hand"
  | "bullseye";

type Shape = Readonly<{ w: number; h: number; body: string }>;

let shapes: Record<string, Shape> | null = null;
let loading: Promise<void> | null = null;
const listeners = new Set<() => void>();

function load() {
  loading ??= fetch("/emotes/emotes.json")
    .then((response) => (response.ok ? response.json() : {}))
    .catch(() => ({}))
    .then((found: { icons?: Record<string, Shape> }) => {
      shapes = found.icons ?? {};
      listeners.forEach((listener) => listener());
    });
  return loading;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * One emote at a fixed size. The space is held while it loads, so nothing
 * shifts; `label` makes it readable to screen readers, otherwise it is
 * decorative.
 */
export function Emote({
  name,
  size = 20,
  label,
  className,
}: {
  name: EmoteName;
  size?: number;
  label?: string;
  className?: string;
}) {
  const shape = useSyncExternalStore(
    subscribe,
    () => (shapes ? (shapes[name] ?? null) : undefined),
    () => undefined,
  );
  useEffect(() => {
    if (!shapes) void load();
  }, []);
  const style = { "--size": `${size}px` } as CSSProperties;
  const a11y = label
    ? { role: "img" as const, "aria-label": label }
    : { "aria-hidden": true as const };
  return shape ? (
    <svg
      className={`${styles.emote} ${className ?? ""}`}
      width={size}
      height={size}
      viewBox={`0 0 ${shape.w} ${shape.h}`}
      style={style}
      {...a11y}
      // Static MIT artwork from our own public/emotes/emotes.json.
      dangerouslySetInnerHTML={{ __html: shape.body }}
    />
  ) : (
    <span
      className={`${styles.placeholder} ${className ?? ""}`}
      style={style}
      {...a11y}
    />
  );
}
