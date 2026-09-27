"use client";

import { useId, type ReactNode } from "react";
import styles from "./lens.module.css";

export const lensStates = [
  "ready",
  "listening",
  "understanding",
  "writing",
  "done",
  "paused",
] as const;
export type LensState = (typeof lensStates)[number];

// Film surfaces override --lx-lens-outline/--lx-lens-fill with the board colours.
const outline = "var(--lx-lens-outline, var(--lx-ink))";
const fill = "var(--lx-lens-fill, var(--lx-paper))";
const glow = "var(--lx-glow)";
const highlight = "var(--lx-film-text)";

function Aperture({ id }: { id: string }) {
  return (
    <radialGradient id={id} cx="50%" cy="42%" r="62%">
      <stop offset="0" stopColor="var(--lx-film-2)" />
      <stop offset="1" stopColor="var(--lx-film)" />
    </radialGradient>
  );
}

function Glow({
  id,
  y,
  height,
  blur,
}: {
  id: string;
  y: string;
  height: string;
  blur: string;
}) {
  return (
    <filter id={id} x="-50%" y={y} width="200%" height={height}>
      <feGaussianBlur stdDeviation={blur} result="b" />
      <feMerge>
        <feMergeNode in="b" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
  );
}

/** The ears, rim, aperture and glint shared by the 120-unit poses. */
function Body({
  aperture,
  earX = ["9", "102"],
  earY = "50",
  cy = "60",
  r = "44",
  pupil = "30",
  glint = "M42 47 A22 22 0 0 1 56 39",
}: {
  aperture: string;
  earX?: [string, string];
  earY?: string;
  cy?: string;
  r?: string;
  pupil?: string;
  glint?: string;
}) {
  return (
    <>
      <rect
        x={earX[0]}
        y={earY}
        width="9"
        height="20"
        rx="4.5"
        fill={outline}
      />
      <rect
        x={earX[1]}
        y={earY}
        width="9"
        height="20"
        rx="4.5"
        fill={outline}
      />
      <circle
        cx="60"
        cy={cy}
        r={r}
        fill={fill}
        stroke={outline}
        strokeWidth="5"
      />
      <circle cx="60" cy={cy} r={pupil} fill={`url(#${aperture})`} />
      <path
        d={glint}
        fill="none"
        stroke={highlight}
        strokeOpacity=".38"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </>
  );
}

function pose(state: LensState, id: (name: string) => string): ReactNode {
  const aperture = id("aperture");
  if (state === "listening") {
    const wave = (side: "l" | "r", delay: string) => (
      <path
        className={`${styles.wave} ${side === "l" ? styles.waveLeft : styles.waveRight} ${delay}`}
        d={
          side === "l"
            ? "M7 46 A16 16 0 0 0 7 74"
            : "M113 46 A16 16 0 0 1 113 74"
        }
        fill="none"
        stroke="var(--lx-glow-ink)"
        strokeWidth="3"
        strokeLinecap="round"
      />
    );
    return (
      <>
        <defs>
          <Glow id={id("glow")} y="-50%" height="200%" blur="2" />
          <Aperture id={aperture} />
        </defs>
        {wave("l", "")}
        {wave("l", styles.delay2)}
        {wave("l", styles.delay3)}
        {wave("r", "")}
        {wave("r", styles.delay2)}
        {wave("r", styles.delay3)}
        <Body
          aperture={aperture}
          earX={["13", "98"]}
          r="40"
          pupil="27"
          glint="M43 48 A20 20 0 0 1 56 41"
        />
        <g fill={glow} filter={`url(#${id("glow")})`}>
          <rect
            className={styles.bar}
            x="46"
            y="50"
            width="4"
            height="20"
            rx="2"
          />
          <rect
            className={styles.bar}
            x="52.5"
            y="46"
            width="4"
            height="28"
            rx="2"
          />
          <rect
            className={styles.bar}
            x="59"
            y="43"
            width="4"
            height="34"
            rx="2"
          />
          <rect
            className={styles.bar}
            x="65.5"
            y="46"
            width="4"
            height="28"
            rx="2"
          />
          <rect
            className={styles.bar}
            x="72"
            y="50"
            width="4"
            height="20"
            rx="2"
          />
        </g>
      </>
    );
  }
  if (state === "understanding") {
    return (
      <>
        <defs>
          <Glow id={id("glow")} y="-300%" height="700%" blur="2.2" />
          <Aperture id={aperture} />
          <linearGradient id={id("trail")} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={glow} stopOpacity="0" />
            <stop offset="1" stopColor={glow} stopOpacity=".35" />
          </linearGradient>
          <clipPath id={id("clip")}>
            <circle cx="60" cy="60" r="30" />
          </clipPath>
        </defs>
        <g className={styles.orbit}>
          <circle
            className={styles.tag}
            cx="60"
            cy="6"
            r="4.5"
            fill="var(--lx-strength)"
          />
          <circle
            className={`${styles.tag} ${styles.tag2}`}
            cx="106"
            cy="84"
            r="4.5"
            fill="var(--lx-focus)"
          />
          <circle
            className={`${styles.tag} ${styles.tag3}`}
            cx="14"
            cy="84"
            r="4.5"
            fill="var(--lx-missed)"
          />
        </g>
        <rect x="9" y="50" width="9" height="20" rx="4.5" fill={outline} />
        <rect x="102" y="50" width="9" height="20" rx="4.5" fill={outline} />
        <circle
          cx="60"
          cy="60"
          r="44"
          fill={fill}
          stroke={outline}
          strokeWidth="5"
        />
        <circle cx="60" cy="60" r="30" fill={`url(#${aperture})`} />
        <g clipPath={`url(#${id("clip")})`}>
          <g opacity=".5" stroke={glow} strokeWidth="2" strokeLinecap="round">
            <path d="M36 60 h4 M43 55 v10 M48 50 v20 M53 56 v8 M58 47 v26 M63 53 v14 M68 49 v22 M73 56 v8 M78 58 v4" />
          </g>
          <g className={styles.scan}>
            <rect
              x="28"
              y="44"
              width="64"
              height="16"
              fill={`url(#${id("trail")})`}
            />
            <rect
              x="30"
              y="58.5"
              width="60"
              height="3"
              rx="1.5"
              fill={glow}
              filter={`url(#${id("glow")})`}
            />
          </g>
        </g>
        <path
          d="M42 47 A22 22 0 0 1 56 39"
          fill="none"
          stroke={highlight}
          strokeOpacity=".38"
          strokeWidth="3"
          strokeLinecap="round"
        />
      </>
    );
  }
  if (state === "writing") {
    return (
      <>
        <defs>
          <Glow id={id("glow")} y="-300%" height="700%" blur="2" />
          <Aperture id={aperture} />
        </defs>
        <g className={styles.bob}>
          <Body
            aperture={aperture}
            earX={["13", "98"]}
            earY="42"
            cy="52"
            r="40"
            pupil="27"
            glint="M43 40 A20 20 0 0 1 56 33"
          />
          <path
            className={styles.pen}
            d="M43 55 q5 -8 9 0 t9 0 t9 0 t6 -2"
            fill="none"
            stroke={glow}
            strokeWidth="3.5"
            strokeLinecap="round"
            filter={`url(#${id("glow")})`}
          />
        </g>
        <rect
          x="22"
          y="100"
          width="76"
          height="34"
          rx="7"
          fill={fill}
          stroke="var(--lx-line)"
          strokeWidth="2"
        />
        <path
          className={styles.inkLine}
          d="M32 110 h56"
          stroke="var(--lx-lens-note-ink, var(--lx-ink))"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <path
          className={`${styles.inkLine} ${styles.line2}`}
          d="M32 118 h44"
          stroke="var(--lx-muted)"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <path
          className={`${styles.inkLine} ${styles.line3}`}
          d="M32 126 h50"
          stroke="var(--lx-muted)"
          strokeWidth="3"
          strokeLinecap="round"
        />
      </>
    );
  }
  if (state === "done") {
    const spark = (className: string, d: string, color: string) => (
      <g fill={color}>
        <path className={`${styles.spark} ${className}`} d={d} />
      </g>
    );
    return (
      <>
        <defs>
          <Glow id={id("glow")} y="-100%" height="300%" blur="2" />
          <Aperture id={aperture} />
        </defs>
        <g className={styles.pop}>
          <Body aperture={aperture} />
          <path
            className={styles.smile}
            d="M46 57 Q60 71 74 57"
            fill="none"
            stroke={glow}
            strokeWidth="5"
            strokeLinecap="round"
            filter={`url(#${id("glow")})`}
          />
        </g>
        {spark(
          "",
          "M100 14 l2.4 6.6 6.6 2.4 -6.6 2.4 -2.4 6.6 -2.4 -6.6 -6.6 -2.4 6.6 -2.4z",
          "var(--lx-focus)",
        )}
        {spark(
          styles.spark2,
          "M16 18 l1.8 4.9 4.9 1.8 -4.9 1.8 -1.8 4.9 -1.8 -4.9 -4.9 -1.8 4.9 -1.8z",
          "var(--lx-strength)",
        )}
        {spark(
          styles.spark3,
          "M108 96 l1.6 4.4 4.4 1.6 -4.4 1.6 -1.6 4.4 -1.6 -4.4 -4.4 -1.6 4.4 -1.6z",
          "var(--lx-missed)",
        )}
        {spark(
          styles.spark4,
          "M12 98 l1.3 3.5 3.5 1.3 -3.5 1.3 -1.3 3.5 -1.3 -3.5 -3.5 -1.3 3.5 -1.3z",
          "var(--lx-glow-ink)",
        )}
      </>
    );
  }
  if (state === "paused") {
    return (
      <>
        <defs>
          <Aperture id={aperture} />
        </defs>
        <g transform="rotate(-7 60 60)">
          <Body aperture={aperture} />
          <rect
            className={styles.breathe}
            x="49"
            y="58"
            width="22"
            height="5"
            rx="2.5"
            fill="var(--lx-focus)"
          />
        </g>
        <circle
          cx="96"
          cy="22"
          r="14"
          fill="var(--lx-focus-soft)"
          stroke="var(--lx-focus)"
          strokeWidth="3"
        />
        <rect
          x="90.5"
          y="16"
          width="4"
          height="12"
          rx="1.5"
          fill="var(--lx-focus-ink)"
        />
        <rect
          x="97.5"
          y="16"
          width="4"
          height="12"
          rx="1.5"
          fill="var(--lx-focus-ink)"
        />
      </>
    );
  }
  return (
    <>
      <defs>
        <Glow id={id("glow")} y="-200%" height="500%" blur="2.4" />
        <Aperture id={aperture} />
      </defs>
      <g className={styles.float}>
        <Body aperture={aperture} />
        <circle
          cx="60"
          cy="60"
          r="29"
          fill="none"
          stroke={glow}
          strokeOpacity=".22"
          strokeWidth="1.5"
        />
        <rect
          className={styles.pupil}
          x="44"
          y="57"
          width="32"
          height="6"
          rx="3"
          fill={glow}
          filter={`url(#${id("glow")})`}
        />
      </g>
    </>
  );
}

/**
 * The Lens shows real system state only. It is decorative (aria-hidden): the
 * adjacent text carries the meaning, and callers derive `state` from confirmed
 * server facts, never from a timer.
 */
export function Lens({
  state,
  size = 112,
  className = "",
}: {
  state: LensState;
  size?: number;
  className?: string;
}) {
  const prefix = `lx-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const id = (name: string) => `${prefix}-${name}`;
  const tall = state === "writing";
  return (
    <svg
      className={`${styles.lens} ${className}`}
      viewBox={tall ? "0 0 120 140" : "0 0 120 120"}
      width={size}
      height={tall ? Math.round((size * 140) / 120) : size}
      aria-hidden="true"
      focusable="false"
      data-lens-state={state}
    >
      {pose(state, id)}
    </svg>
  );
}
