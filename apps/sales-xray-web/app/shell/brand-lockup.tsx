"use client";

import Link from "next/link";
import { useId, type CSSProperties } from "react";

import styles from "./brand-lockup.module.css";

// The Sales X-Ray mark (brand B "Insight", owner's pick, 23 Oct 2026): a call's waveform whose centre bar is a
// lowercase "i", the insight Sales X-Ray finds in every call. Mint bars and a white i on a lit deep-teal tile: the
// same art as the app icon. The brand colours are fixed artwork, the same in every theme, so they live in this SVG
// rather than in the theme tokens.
const BAR_WIDTH = 11;
const BARS = [
  { x: 11.5, y: 43, height: 24 },
  { x: 28, y: 33, height: 44 },
  { x: 61, y: 33, height: 44 },
  { x: 77.5, y: 43, height: 24 },
] as const;

// "Sales X-Ray" outlined from Hind Medium and Hind Bold, with the brand's capsule hyphen (100-unit type size).
const WORDMARK_VIEWBOX = "0 -70 498 92";
const WORDMARK =
  "M43.7 -64.7V-54.5Q37 -58.7 28.5 -58.7Q23 -58.7 19.85 -56.25Q16.7 -53.8 16.7 -49.8Q16.7 -45.8 19.8 -43.4Q22.9 -41 29.3 -38.2Q33.5 -36.4 35.85 -35.1Q38.2 -33.8 41.25 -31.45Q44.3 -29.1 45.75 -25.85Q47.2 -22.6 47.2 -18.4Q47.2 -9.5 40.9 -4.4Q34.6 0.7 24.6 0.7Q13.5 0.7 6.2 -3.6V-14.3Q14.1 -8.4 24.5 -8.4Q30 -8.4 33.2 -10.95Q36.4 -13.5 36.4 -18Q36.4 -20.7 34.5 -22.95Q32.6 -25.2 30.4 -26.35Q28.2 -27.5 23.8 -29.5Q21.2 -30.7 20.15 -31.2Q19.1 -31.7 16.7 -33Q14.3 -34.3 13.15 -35.2Q12 -36.1 10.3 -37.7Q8.6 -39.3 7.85 -40.9Q7.1 -42.5 6.45 -44.65Q5.8 -46.8 5.8 -49.3Q5.8 -57.9 12.05 -62.9Q18.3 -67.9 28.2 -67.9Q37.3 -67.9 43.7 -64.7ZM84.2 -22.6H76.6Q71 -22.6 68.15 -20.4Q65.3 -18.2 65.3 -14.8Q65.3 -11.3 67.5 -9.3Q69.7 -7.3 73.9 -7.3Q78.7 -7.3 81.45 -9.95Q84.2 -12.6 84.2 -16.9ZM58.7 -38.6V-48.1Q64.6 -51.5 74.3 -51.5Q94.2 -51.5 94.2 -32.2V0H84.5V-6Q80.6 0.4 70.8 0.4Q63.6 0.4 59.25 -3.75Q54.9 -7.9 54.9 -14.3Q54.9 -21.6 60.4 -25.65Q65.9 -29.7 75.8 -29.7H84.2V-32.6Q84.2 -37.8 81.7 -40.45Q79.2 -43.1 73.4 -43.1Q65.3 -43.1 58.7 -38.6ZM106.3 0V-70.7H116.2V0ZM160.4 -29V-30.8Q160.2 -36.5 157.3 -39.85Q154.4 -43.2 149 -43.2Q144 -43.2 140.4 -39.55Q136.8 -35.9 135.9 -29ZM166.7 -11.5V-2.7Q161.1 0.5 151.9 0.5Q140.1 0.5 133.1 -6.6Q126.1 -13.7 126.1 -25.2Q126.1 -37.4 132.5 -44.35Q138.9 -51.3 148.8 -51.3Q158.5 -51.3 164.2 -45.25Q169.9 -39.2 169.9 -27.8Q169.9 -24.7 169.3 -21.3H136Q137 -14.7 141.6 -11.2Q146.2 -7.7 153.2 -7.7Q161.3 -7.7 166.7 -11.5ZM208.8 -49V-40.1Q203.9 -43 196.2 -43Q192.7 -43 190.65 -41.4Q188.6 -39.8 188.6 -37.2Q188.6 -36.5 188.75 -35.85Q188.9 -35.2 189.3 -34.55Q189.7 -33.9 190.05 -33.45Q190.4 -33 191.2 -32.5Q192 -32 192.45 -31.65Q192.9 -31.3 193.95 -30.8Q195 -30.3 195.5 -30.05Q196 -29.8 197.25 -29.25Q198.5 -28.7 199 -28.5Q204.9 -25.9 208.25 -22.65Q211.6 -19.4 211.6 -14Q211.6 -7.2 206.8 -3.35Q202 0.5 193.8 0.5Q184.8 0.5 178.8 -2.5V-11.8Q185.8 -7.5 193.3 -7.5Q197.2 -7.5 199.35 -9.1Q201.5 -10.7 201.5 -13.3Q201.5 -15.5 199.8 -17.25Q198.1 -19 196.35 -19.85Q194.6 -20.7 190.4 -22.5Q178.5 -27.4 178.5 -36.9Q178.5 -43.6 183.5 -47.4Q188.5 -51.2 196 -51.2Q204.2 -51.2 208.8 -49ZM260.03 -34.2 239.73 -67.4H257.63L268.83 -47.7Q270.83 -51.4 274.53 -58.15Q278.23 -64.9 279.53 -67.4H298.33L277.93 -34.1L299.63 0H281.33L269.13 -21Q266.93 -16.9 262.73 -9.55Q258.53 -2.2 257.33 0H238.73ZM355.73 -54.9V-35.9H363.03Q373.03 -35.9 373.03 -45.7Q373.03 -50 370.43 -52.45Q367.83 -54.9 363.33 -54.9ZM375.03 0 360.43 -23.4H355.73V0H340.33V-67.4H363.63Q374.93 -67.4 381.78 -61.4Q388.63 -55.4 388.63 -45.8Q388.63 -31.4 376.33 -25.9L393.43 0ZM424.83 -20.8H420.13Q416.43 -20.8 414.43 -19.2Q412.43 -17.6 412.43 -15.1Q412.43 -10 418.33 -10Q421.43 -10 423.13 -11.9Q424.83 -13.8 424.83 -17.1ZM401.13 -35.1V-48.2Q407.13 -51.6 418.43 -51.6Q429.23 -51.6 434.53 -46.95Q439.83 -42.3 439.83 -32.5V0H425.53V-6.2Q422.33 0.3 412.93 0.3Q405.53 0.3 401.38 -3.9Q397.23 -8.1 397.23 -14.4Q397.23 -21.7 402.58 -25.75Q407.93 -29.8 418.43 -29.8H424.83V-33.3Q424.83 -39.7 416.33 -39.7Q408.13 -39.7 401.13 -35.1ZM463.93 -0.8 444.33 -50.7H460.23L465.73 -34.9Q467.83 -28.8 469.18 -24.4Q470.53 -20 470.83 -18.6L471.13 -17.2Q472.23 -21.2 476.53 -34.9L481.53 -50.7H496.53L478.23 -1.5Q470.33 19.8 454.13 19.8Q451.03 19.8 448.53 19.3V7.7Q450.13 8.1 451.93 8.1Q460.23 8.1 463.93 -0.8Z";
const HYPHEN =
  "M310.83 -36.5H323.83A6.5 6.5 0 0 1 330.33 -30V-30A6.5 6.5 0 0 1 323.83 -23.5H310.83A6.5 6.5 0 0 1 304.33 -30V-30A6.5 6.5 0 0 1 310.83 -36.5Z";

export function BrandLockup({
  href,
  markOnly = false,
}: {
  href: string;
  markOnly?: boolean;
}) {
  return (
    <Link
      className={`${styles.brand}${markOnly ? ` ${styles.markOnly}` : ""}`}
      href={href}
      aria-label="Sales X-Ray home"
    >
      <BrandMark markOnly={markOnly} />
    </Link>
  );
}

/** The living Sales X-Ray mark and wordmark, for callers that own the wrapper. */
export function BrandMark({ markOnly = false }: { markOnly?: boolean }) {
  const id = `sx-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  return (
    <>
      <span className={styles.symbol} aria-hidden="true">
        <svg viewBox="0 0 100 100" focusable="false">
          <defs>
            <linearGradient id={`${id}-ground`} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#0F6157" />
              <stop offset="0.55" stopColor="#0B4A44" />
              <stop offset="1" stopColor="#073B36" />
            </linearGradient>
            <radialGradient id={`${id}-light`} cx="50%" cy="0%" r="75%">
              <stop offset="0" stopColor="#FFFFFF" stopOpacity="0.16" />
              <stop offset="1" stopColor="#FFFFFF" stopOpacity="0" />
            </radialGradient>
            <linearGradient
              id={`${id}-bars`}
              gradientUnits="userSpaceOnUse"
              x1="0"
              y1="22.66"
              x2="0"
              y2="82"
            >
              <stop offset="0" stopColor="#7CF7CF" />
              <stop offset="1" stopColor="#18C08C" />
            </linearGradient>
            <linearGradient
              id={`${id}-i`}
              gradientUnits="userSpaceOnUse"
              x1="0"
              y1="22.66"
              x2="0"
              y2="82"
            >
              <stop offset="0" stopColor="#FFFFFF" />
              <stop offset="1" stopColor="#D3F7EA" />
            </linearGradient>
            <radialGradient
              id={`${id}-halo`}
              gradientUnits="userSpaceOnUse"
              cx="50"
              cy="29.7"
              r="22.5"
            >
              <stop offset="0" stopColor="#3DEBB0" stopOpacity="0.55" />
              <stop offset="1" stopColor="#3DEBB0" stopOpacity="0" />
            </radialGradient>
          </defs>
          <rect width="100" height="100" fill={`url(#${id}-ground)`} />
          <rect width="100" height="100" fill={`url(#${id}-light)`} />
          <g transform="translate(13 11.28) scale(0.74)">
            <circle
              className={styles.halo}
              cx="50"
              cy="29.7"
              r="22.5"
              fill={`url(#${id}-halo)`}
            />
            {BARS.map((bar, index) => (
              <rect
                key={bar.x}
                className={styles.bar}
                style={{ "--i": index } as CSSProperties}
                x={bar.x}
                y={bar.y}
                width={BAR_WIDTH}
                height={bar.height}
                rx={BAR_WIDTH / 2}
                fill={`url(#${id}-bars)`}
              />
            ))}
            <g fill={`url(#${id}-i)`}>
              <rect
                className={styles.stem}
                x="44.5"
                y="44"
                width={BAR_WIDTH}
                height="38"
                rx={BAR_WIDTH / 2}
              />
              <circle className={styles.dot} cx="50" cy="29.7" r="7.04" />
            </g>
          </g>
        </svg>
      </span>
      {!markOnly && (
        <span className={styles.wordmark} aria-hidden="true">
          <svg
            className={styles.name}
            viewBox={WORDMARK_VIEWBOX}
            focusable="false"
          >
            <path d={WORDMARK} fill="currentColor" />
            <path className={styles.hyphen} d={HYPHEN} />
          </svg>
          <span className={styles.by}>by Authority Closers</span>
        </span>
      )}
    </>
  );
}
