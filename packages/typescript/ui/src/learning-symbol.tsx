/// <reference path="./styles.d.ts" />
import type { CSSProperties } from "react";
import styles from "./learning-symbol.module.css";

export type LearningSymbolKind =
  | "watch"
  | "reflect"
  | "implement"
  | "review"
  | "improve"
  | "course"
  | "conversation"
  | "listen"
  | "credits"
  | "experience"
  | "rhythm";

/** Original AC illustrations. Decorative by default; never confer completion or access. */
export function LearningSymbol({
  kind,
  size = 64,
  muted = false,
  label,
}: {
  kind: LearningSymbolKind;
  size?: number;
  muted?: boolean;
  label?: string;
}) {
  return (
    <svg
      viewBox="0 0 80 80"
      width={size}
      height={size}
      className={styles.symbol}
      data-muted={muted || undefined}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
      data-learning-symbol={kind}
    >
      <ellipse cx="40" cy="70" rx="25" ry="4" className={styles.shadow} />
      {kind === "credits" ? (
        <g>
          <ellipse cx="47" cy="55" rx="22" ry="10" className={styles.depth} />
          <path d="M25 45v9c0 13 44 13 44 0v-9Z" className={styles.depth} />
          <ellipse cx="47" cy="45" rx="22" ry="10" className={styles.soft} />
          <circle cx="33" cy="33" r="24" className={styles.depth} />
          <circle cx="33" cy="29" r="24" className={styles.fill} />
          <circle cx="33" cy="29" r="17" className={styles.ring} />
          <path d="M39 21a10 10 0 1 0 0 16" className={styles.highlight} />
          <path d="M31 55v4m8-2v5m9-4v5m9-7v5" className={styles.highlight} />
        </g>
      ) : kind === "experience" ? (
        <g>
          <path d="m40 10 25 13v30L40 70 15 53V23Z" className={styles.depth} />
          <path d="m40 6 25 13v30L40 66 15 49V19Z" className={styles.fill} />
          <path d="m24 23 16-8 16 8" className={styles.highlight} />
          <path d="m42 23-14 17h10l-1 14 15-20H42Z" className={styles.paper} />
          <path d="m9 9 2 5 5 2-5 2-2 5-2-5-5-2 5-2Z" className={styles.soft} />
        </g>
      ) : kind === "rhythm" ? (
        <g>
          <rect
            x="12"
            y="17"
            width="56"
            height="48"
            rx="11"
            className={styles.depth}
          />
          <rect
            x="12"
            y="13"
            width="56"
            height="48"
            rx="11"
            className={styles.fill}
          />
          <path d="M14 28h52M27 8v12M53 8v12" className={styles.highlight} />
          <g className={styles.paper}>
            <circle cx="27" cy="39" r="3" />
            <circle cx="40" cy="39" r="3" />
            <circle cx="53" cy="39" r="3" />
            <circle cx="27" cy="51" r="3" />
            <circle cx="40" cy="51" r="3" />
          </g>
          <path d="m48 51 4 4 7-8" className={styles.highlight} />
        </g>
      ) : kind === "watch" ? (
        <g>
          <rect
            x="11"
            y="16"
            width="58"
            height="43"
            rx="12"
            className={styles.depth}
          />
          <rect
            x="11"
            y="12"
            width="58"
            height="43"
            rx="12"
            className={styles.fill}
          />
          <path d="M20 23h14" className={styles.highlight} />
          <path
            d="M34 27q0-3 3-1l13 8q3 2 0 4l-13 8q-3 2-3-1Z"
            className={styles.paper}
          />
          <path d="M25 65h30M40 59v6" className={styles.outline} />
        </g>
      ) : kind === "reflect" ? (
        <g transform="rotate(-7 40 40)">
          <rect
            x="18"
            y="12"
            width="43"
            height="55"
            rx="8"
            className={styles.depth}
          />
          <rect
            x="18"
            y="9"
            width="43"
            height="55"
            rx="8"
            className={styles.fill}
          />
          <path d="M28 23h21M28 33h14M28 43h9" className={styles.highlight} />
          <path
            d="m44 55 4-13 15-17q3-3 6 0l1 1q3 3 0 6L55 49Z"
            className={styles.paper}
          />
          <path d="m44 55 3-10 7 6Z" className={styles.depth} />
          <path d="m61 28 7 6" className={styles.outline} />
        </g>
      ) : kind === "implement" ? (
        <g>
          <rect
            x="13"
            y="34"
            width="20"
            height="31"
            rx="5"
            className={styles.soft}
          />
          <rect
            x="30"
            y="25"
            width="20"
            height="40"
            rx="5"
            className={styles.depth}
          />
          <rect
            x="47"
            y="14"
            width="20"
            height="51"
            rx="5"
            className={styles.fill}
          />
          <path
            d="m20 23 12-11 9 7 16-13m-9 0h9v9"
            className={styles.outline}
          />
          <path d="M54 26h6M54 33h6M54 40h6" className={styles.highlight} />
        </g>
      ) : kind === "review" || kind === "conversation" ? (
        <g>
          <path
            d="M29 30h33q8 0 8 8v14q0 8-8 8h-5l-8 8v-8H29q-8 0-8-8V38q0-8 8-8"
            className={styles.soft}
          />
          <path
            d="M16 12h34q9 0 9 9v18q0 9-9 9H30L18 59V48h-2q-9 0-9-9V21q0-9 9-9"
            className={styles.depth}
          />
          <path
            d="M16 9h34q9 0 9 9v18q0 9-9 9H30L18 56V45h-2q-9 0-9-9V18q0-9 9-9"
            className={styles.fill}
          />
          {kind === "review" ? (
            <path d="m23 27 7 7 13-14" className={styles.highlight} />
          ) : (
            <g className={styles.paper}>
              <circle cx="23" cy="27" r="3" />
              <circle cx="34" cy="27" r="3" />
              <circle cx="45" cy="27" r="3" />
            </g>
          )}
        </g>
      ) : kind === "improve" ? (
        <g>
          <circle cx="38" cy="41" r="25" className={styles.depth} />
          <circle cx="38" cy="37" r="25" className={styles.fill} />
          <circle cx="38" cy="37" r="16" className={styles.ring} />
          <circle cx="38" cy="37" r="6" className={styles.paper} />
          <path d="m39 36 24-24m-1 0v10h10" className={styles.outline} />
          <path d="m58 15 5-8 2 10 8 2-8 5" className={styles.soft} />
        </g>
      ) : kind === "listen" ? (
        <g>
          <path d="M15 42V32a25 25 0 0 1 50 0v10" className={styles.headband} />
          <rect
            x="9"
            y="34"
            width="17"
            height="29"
            rx="8"
            className={styles.depth}
          />
          <rect
            x="54"
            y="34"
            width="17"
            height="29"
            rx="8"
            className={styles.fill}
          />
          <path d="M32 36v13m8-20v26m8-19v13" className={styles.outline} />
        </g>
      ) : (
        <g>
          <path
            d="M8 18q17-5 32 5 15-10 32-5v43q-18-3-32 5-14-8-32-5Z"
            className={styles.depth}
          />
          <path
            d="M8 13q17-5 32 5 15-10 32-5v43q-18-3-32 5-14-8-32-5Z"
            className={styles.fill}
          />
          <path d="M40 18v43" className={styles.highlight} />
          <path
            d="m17 26 13 3m-13 9 13 3m20-12 13-3m-13 15 13-3"
            className={styles.highlight}
          />
          <path d="M59 11v18l5-4 5 2V12" className={styles.paper} />
        </g>
      )}
    </svg>
  );
}

/** Counts/percentage come from the caller's authoritative projection, not activity guesses. */
export function ProgressOrbit({
  value,
  label,
  size = 84,
}: {
  value: number;
  label: string;
  size?: number;
}) {
  const bounded = Number.isFinite(value)
    ? Math.min(100, Math.max(0, value))
    : null;
  return (
    <span
      className={styles.orbit}
      style={{ "--orbit-size": `${size}px` } as CSSProperties}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={bounded ?? undefined}
      aria-valuetext={
        bounded === null ? "Progress unavailable" : `${bounded}% complete`
      }
    >
      <svg viewBox="0 0 80 80" aria-hidden="true" focusable="false">
        <circle cx="40" cy="40" r="34" className={styles.track} />
        <circle
          cx="40"
          cy="40"
          r="34"
          pathLength="100"
          strokeDasharray={`${bounded ?? 0} 100`}
          className={styles.arc}
        />
      </svg>
      <strong aria-hidden="true">
        {bounded === null ? "—" : `${bounded}%`}
      </strong>
    </span>
  );
}
