/// <reference path="./styles.d.ts" />
"use client";
import { useEffect, useRef } from "react";
import styles from "./practice-companion.module.css";

/** Shared presentation presets, not tenant identity or game-rule authority. */
export const PRACTICE_COMPANIONS = [
  { id: "echo", name: "Echo", description: "A curious conversation companion" },
  {
    id: "scout",
    name: "Scout",
    description: "A steady guide for your next move",
  },
  { id: "page", name: "Page", description: "A thoughtful learning companion" },
] as const;
export type PracticeCompanionKind = (typeof PRACTICE_COMPANIONS)[number]["id"];
export type PracticeCompanionMood =
  | "ready"
  | "encourage"
  | "celebrate"
  | "pause";
export function normalizePracticeCompanion(
  value: unknown,
): PracticeCompanionKind {
  return value === "scout" || value === "page" ? value : "echo";
}

/** Original vector characters with finite gestures or explicitly enabled idle motion. */
export function PracticeCompanion({
  variant = "echo",
  mood = "ready",
  size = 160,
  label,
  motion = "once",
  active = true,
}: {
  variant?: PracticeCompanionKind;
  mood?: PracticeCompanionMood;
  size?: number;
  label?: string;
  motion?: "once" | "alive" | "off";
  active?: boolean;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const media =
      typeof matchMedia === "function"
        ? matchMedia("(prefers-reduced-motion: reduce)")
        : null;
    let inView = typeof IntersectionObserver === "undefined";
    let playing = false;
    let frame = 0;
    let pointer: { x: number; y: number } | null = null;
    const resetGaze = () => {
      cancelAnimationFrame(frame);
      frame = 0;
      pointer = null;
      svg.style.setProperty("--gaze-x", "0px");
      svg.style.setProperty("--gaze-y", "0px");
    };
    const update = () => {
      const reduced =
        media?.matches ||
        document.documentElement.dataset.reducedMotion === "true" ||
        document.documentElement.dataset.motion === "reduced";
      playing =
        active &&
        motion !== "off" &&
        inView &&
        document.visibilityState === "visible" &&
        !reduced;
      svg.dataset.play = playing ? "running" : "paused";
      if (!playing) {
        cancelAnimationFrame(frame);
        frame = 0;
        resetGaze();
      }
    };
    const observer =
      typeof IntersectionObserver === "undefined"
        ? null
        : new IntersectionObserver(
            (entries) => {
              inView = entries.some((entry) => entry.isIntersecting);
              update();
            },
            { threshold: 0 },
          );
    observer?.observe(svg);
    const preferences = new MutationObserver(update);
    preferences.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-reduced-motion", "data-motion"],
    });
    const look = (event: PointerEvent) => {
      if (!playing || motion !== "alive" || event.pointerType === "touch")
        return;
      pointer = { x: event.clientX, y: event.clientY };
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (!playing || !pointer) return;
        const rect = svg.getBoundingClientRect();
        const x = Math.max(
          -2.8,
          Math.min(2.8, (pointer.x - rect.x - rect.width / 2) / 80),
        );
        const y = Math.max(
          -1.8,
          Math.min(1.8, (pointer.y - rect.y - rect.height / 2) / 100),
        );
        svg.style.setProperty("--gaze-x", `${x}px`);
        svg.style.setProperty("--gaze-y", `${y}px`);
      });
    };
    document.addEventListener("pointermove", look, { passive: true });
    document.addEventListener("pointerleave", resetGaze);
    document.addEventListener("visibilitychange", update);
    media?.addEventListener("change", update);
    update();
    return () => {
      observer?.disconnect();
      preferences.disconnect();
      cancelAnimationFrame(frame);
      document.removeEventListener("pointermove", look);
      document.removeEventListener("pointerleave", resetGaze);
      document.removeEventListener("visibilitychange", update);
      media?.removeEventListener("change", update);
      svg.dataset.play = "paused";
      resetGaze();
    };
  }, [motion, active, mood]);
  return (
    <svg
      ref={svgRef}
      viewBox="0 0 180 160"
      width={size}
      height={(size * 160) / 180}
      className={styles.companion}
      data-mood={mood}
      data-companion={variant}
      data-motion={motion}
      data-play="paused"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      <ellipse cx="90" cy="148" rx="45" ry="6" className={styles.shadow} />
      <g className={styles.idle}>
        <g className={styles.character}>
          <path
            d="M65 120v17q0 7-13 7M115 120v17q0 7 13 7"
            className={styles.limbs}
          />
          <g className={styles.leftArm}>
            <path
              d={
                mood === "celebrate" ? "M48 83 27 57l-6-9" : "M48 88 26 96l-6-6"
              }
              className={styles.limbs}
            />
            <circle
              cx={mood === "celebrate" ? 21 : 20}
              cy={mood === "celebrate" ? 47 : 89}
              r="7"
              className={styles.hand}
            />
          </g>
          <g className={styles.rightArm}>
            <path
              d={
                mood === "celebrate"
                  ? "m132 83 19-25 6-10"
                  : "m132 86 20-8 4-15"
              }
              className={styles.limbs}
            />
            <circle
              cx="157"
              cy={mood === "celebrate" ? 47 : 61}
              r="7"
              className={styles.hand}
            />
          </g>
          {variant === "scout" ? (
            <>
              <rect
                x="44"
                y="25"
                width="92"
                height="104"
                rx="35"
                className={styles.depth}
              />
              <rect
                x="44"
                y="20"
                width="92"
                height="104"
                rx="35"
                className={styles.body}
              />
              <path d="m91 6 14 17-14-4-14 4Z" className={styles.soft} />
              <path d="m91 98 8 10-8-3-8 3Z" className={styles.inlay} />
            </>
          ) : variant === "page" ? (
            <>
              <rect
                x="44"
                y="23"
                width="91"
                height="106"
                rx="18"
                transform="rotate(-4 90 76)"
                className={styles.depth}
              />
              <rect
                x="40"
                y="17"
                width="91"
                height="106"
                rx="18"
                transform="rotate(-4 90 76)"
                className={styles.body}
              />
              <path d="M58 24v91" className={styles.seam} />
              <path d="m106 15 11-1v27l-6-5-5 6Z" className={styles.soft} />
            </>
          ) : (
            <>
              <path
                d="M66 24h48q28 0 28 28v45q0 25-25 25H82l-25 15 2-18q-23-7-23-28V54q0-30 30-30"
                className={styles.depth}
              />
              <path
                d="M66 18h48q28 0 28 28v45q0 25-25 25H82l-25 15 2-18q-23-7-23-28V48q0-30 30-30"
                className={styles.body}
              />
              <path d="M52 37q6-7 17-7" className={styles.glint} />
            </>
          )}
          <rect
            x="55"
            y="47"
            width="73"
            height="51"
            rx="23"
            className={styles.face}
          />
          {mood === "celebrate" ? (
            <g className={styles.expression}>
              <path d="m69 68 5-5 5 5m23 0 5-5 5 5" />
              <path d="M81 78q10 15 21 0" />
            </g>
          ) : (
            <>
              <g className={styles.gaze}>
                <g className={styles.eyes}>
                  <ellipse cx="75" cy="68" rx="3.7" ry="5.8" />
                  <ellipse cx="108" cy="68" rx="3.7" ry="5.8" />
                </g>
              </g>
              <g className={styles.expression}>
                <path
                  d={mood === "pause" ? "M83 83q8-5 16 0" : "M83 79q8 8 16 0"}
                />
                {mood === "pause" ? <path d="m69 55 11-3m23 0 11 3" /> : null}
              </g>
            </>
          )}
          <g className={styles.blush}>
            <ellipse cx="64" cy="79" rx="5" ry="3" />
            <ellipse cx="119" cy="79" rx="5" ry="3" />
          </g>
          {mood === "celebrate" ? (
            <g className={styles.sparks}>
              <path d="m29 24 3 7 8 3-8 3-3 8-3-8-8-3 8-3ZM145 14l3 7 8 3-8 3-3 8-3-8-8-3 8-3Z" />
              <circle cx="156" cy="113" r="3" />
              <circle cx="23" cy="119" r="3" />
            </g>
          ) : null}
        </g>
      </g>
    </svg>
  );
}
