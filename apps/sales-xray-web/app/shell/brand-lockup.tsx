"use client";

import Link from "next/link";
import { useId, type CSSProperties } from "react";

import { MARK_ART } from "../brand/brand-art";
import styles from "./brand-lockup.module.css";

// The Sales X-Ray mark, polished (brand kit v0.2, logos/sales-x-ray/, owner's order 19 Nov 2026): the live
// Insight tile, put on a 20-unit grid. A call's waveform whose centre bar is a lowercase "i", the insight Sales
// X-Ray finds in every call. Bars 2u wide with 1u gaps, side bars 4u and tall bars 8u, the i's stem 7u with its dot
// (2.5u) 1.25u above, corner 22.5%. Geometry is copied from sx-lockup-light.svg (100-unit tile), never redrawn.
// The brand colours are fixed artwork, the same in every theme, so they live in ../brand/brand-art.ts.
const BAR_WIDTH = 10;
const BARS = [
  { x: 15, y: 40.95, height: 20 },
  { x: 30, y: 30.95, height: 40 },
  { x: 60, y: 30.95, height: 40 },
  { x: 75, y: 40.95, height: 20 },
] as const;
const ART_TOP = 22.2;
const ART_BOTTOM = 75.95;

// "Sales X-Ray" outlined from Plus Jakarta Sans (Sales 500, X-Ray 800, kerned by hand), with the green capsule
// hyphen: sx-wordmark-light.svg from the kit. The name takes the theme's ink; the hyphen takes --xr-green-mark,
// the kit's own value for it in light and in dark.
const WORDMARK_VIEWBOX = "2.95 -78.5 549 99";
const WORDMARK =
  "M33.85 1.2Q26.78 1.2 20.89 -1.46Q15 -4.12 10.89 -8.71Q6.78 -13.3 4.95 -19.03L13.53 -22.48Q16.18 -15.25 21.54 -11.41Q26.9 -7.58 34.1 -7.58Q38.5 -7.58 41.81 -8.99Q45.12 -10.4 46.95 -12.94Q48.78 -15.48 48.78 -18.85Q48.78 -23.62 46.12 -26.34Q43.48 -29.05 38.43 -30.53L24.73 -34.73Q16.57 -37.18 12.26 -42.56Q7.95 -47.95 7.95 -55Q7.95 -61.08 10.94 -65.74Q13.93 -70.4 19.18 -73.05Q24.43 -75.7 31.12 -75.7Q37.83 -75.7 43.26 -73.29Q48.7 -70.88 52.51 -66.83Q56.33 -62.78 58.05 -57.62L49.65 -54.1Q47.33 -60.35 42.49 -63.64Q37.65 -66.92 31.2 -66.92Q27.2 -66.92 24.16 -65.55Q21.12 -64.17 19.45 -61.61Q17.78 -59.05 17.78 -55.6Q17.78 -51.5 20.38 -48.28Q22.98 -45.05 28.33 -43.43L40.75 -39.65Q49.6 -36.98 54.09 -32Q58.58 -27.03 58.58 -19.6Q58.58 -13.48 55.44 -8.8Q52.3 -4.12 46.73 -1.46Q41.15 1.2 33.85 1.2ZM86.4 1.2Q81.1 1.2 77.05 -0.75Q73 -2.7 70.7 -6.15Q68.4 -9.6 68.4 -14.1Q68.4 -18.4 70.25 -21.85Q72.1 -25.3 76.05 -27.7Q80 -30.1 86 -31.1L104.4 -34.2V-36.6Q104.4 -41 101.15 -43.75Q97.9 -46.5 92.6 -46.5Q88 -46.5 84.45 -44.15Q80.9 -41.8 79.2 -37.9L71.1 -42.1Q72.6 -45.8 75.9 -48.75Q79.2 -51.7 83.6 -53.4Q88 -55.1 92.8 -55.1Q99 -55.1 103.7 -52.75Q108.4 -50.4 111.05 -46.25Q113.7 -42.1 113.7 -36.6V0H104.6V-7Q103.3 -5.3 101.7 -4Q98.8 -1.6 94.9 -0.2Q91 1.2 86.4 1.2ZM104.4 -26.3 88.1 -23.6Q82.9 -22.7 80.55 -20.3Q78.2 -17.9 78.2 -14.4Q78.2 -11.1 80.85 -8.9Q83.5 -6.7 87.5 -6.7Q92.6 -6.7 96.35 -8.85Q100.1 -11 102.25 -14.7Q104.4 -18.4 104.4 -22.9ZM127.05 0V-75.7H136.43V0ZM174.8 1.2Q167 1.2 160.9 -2.5Q154.8 -6.2 151.3 -12.65Q147.8 -19.1 147.8 -27.1Q147.8 -35.2 151.25 -41.5Q154.7 -47.8 160.65 -51.45Q166.6 -55.1 174 -55.1Q180 -55.1 184.65 -52.95Q189.3 -50.8 192.55 -47.15Q195.8 -43.5 197.55 -38.85Q199.3 -34.2 199.3 -29.2Q199.3 -28.1 199.15 -26.75Q199 -25.4 198.8 -24.2H157.6Q157.7 -20 159.4 -16.6Q161.7 -12.2 165.85 -9.75Q170 -7.3 174.9 -7.3Q180.3 -7.3 184 -9.8Q187.7 -12.3 190 -16.2L197.8 -12.2Q196.2 -8.5 192.85 -5.45Q189.5 -2.4 184.95 -0.6Q180.4 1.2 174.8 1.2ZM157.7 -32.2H189.3Q189.2 -35.3 188 -37.9Q186.1 -42 182.4 -44.4Q178.7 -46.8 174 -46.8Q169.3 -46.8 165.4 -44.4Q161.5 -42 159.3 -37.5Q158.1 -35.1 157.7 -32.2ZM229.65 1.2Q221.63 1.2 215.61 -2.79Q209.6 -6.78 207.05 -13.6L214.53 -17.15Q216.78 -12.38 220.79 -9.57Q224.8 -6.78 229.65 -6.78Q234.05 -6.78 236.95 -8.86Q239.85 -10.95 239.85 -14.38Q239.85 -16.78 238.5 -18.23Q237.15 -19.68 235.28 -20.52Q233.4 -21.38 231.75 -21.8L223.65 -24.1Q216.43 -26.15 213.05 -30.06Q209.68 -33.98 209.68 -39.18Q209.68 -43.98 212.12 -47.55Q214.58 -51.12 218.83 -53.09Q223.08 -55.05 228.35 -55.05Q235.45 -55.05 241.12 -51.45Q246.8 -47.85 249.15 -41.43L241.58 -37.88Q239.78 -42.1 236.18 -44.53Q232.58 -46.95 228.13 -46.95Q224.03 -46.95 221.59 -44.93Q219.15 -42.9 219.15 -39.75Q219.15 -37.45 220.35 -36.03Q221.55 -34.6 223.28 -33.83Q225 -33.05 226.55 -32.6L235.4 -30Q241.98 -28.08 245.61 -24.06Q249.25 -20.05 249.25 -14.53Q249.25 -9.95 246.75 -6.38Q244.25 -2.8 239.85 -0.8Q235.45 1.2 229.65 1.2ZM272.25 0 296.65 -37.3 272.25 -74.5H290.05L305.25 -51.3L320.45 -74.5H338.25L313.95 -37.3L338.25 0H320.45L305.35 -23.2L290.05 0ZM377.25 0V-74.5H405.75Q413.45 -74.5 419.4 -71.8Q425.35 -69.1 428.75 -63.8Q432.15 -58.5 432.15 -50.7Q432.15 -43.1 428.65 -37.75Q425.15 -32.4 419.25 -29.7L436.25 0H418.85L403.75 -27H392.75V0ZM392.75 -40.5H405.85Q409.15 -40.5 411.55 -41.8Q413.95 -43.1 415.3 -45.4Q416.65 -47.7 416.65 -50.7Q416.65 -53.8 415.3 -56.1Q413.95 -58.4 411.55 -59.7Q409.15 -61 405.85 -61H392.75ZM457.75 1.2Q451.85 1.2 447.55 -0.7Q443.25 -2.6 440.95 -6.15Q438.65 -9.7 438.65 -14.6Q438.65 -19.2 440.75 -22.75Q442.85 -26.3 447.2 -28.7Q451.55 -31.1 458.05 -32.1L473.15 -34.5V-36Q473.15 -39.1 470.7 -41.2Q468.25 -43.3 464.05 -43.3Q460.05 -43.3 457 -41.1Q453.95 -38.9 452.55 -35.3L440.55 -41Q442.15 -45.6 445.65 -48.9Q449.15 -52.2 454.05 -54Q458.95 -55.8 464.75 -55.8Q471.65 -55.8 476.95 -53.3Q482.25 -50.8 485.2 -46.35Q488.15 -41.9 488.15 -36V0H474.15V-5.2Q473.25 -4.2 472.25 -3.5Q469.35 -1.1 465.75 0.05Q462.15 1.2 457.75 1.2ZM473.15 -23.5 460.75 -21.3Q457.55 -20.7 455.85 -19.25Q454.15 -17.8 454.15 -15.1Q454.15 -12.6 456.05 -11.2Q457.95 -9.8 460.75 -9.8Q464.45 -9.8 467.25 -11.4Q470.05 -13 471.6 -15.75Q473.15 -18.5 473.15 -21.8ZM504.85 22Q502.45 22 500.2 21.6Q497.95 21.2 496.25 20.3V8Q497.65 8.4 499.55 8.7Q501.45 9 503.05 9Q507.45 9 509.35 6.95Q511.25 4.9 512.45 2.3L513.45 0L491.95 -54.6H508.05L520.95 -19.5L533.85 -54.6H549.95L526.55 5.1Q524.35 10.7 521.15 14.5Q517.95 18.3 513.9 20.15Q509.85 22 504.85 22Z";
const HYPHEN = { x: 343.75, y: -32.85, width: 27, height: 13.5 } as const;

export function BrandLockup({
  href,
  markOnly = false,
  prefetch,
}: {
  href: string;
  markOnly?: boolean;
  /** Off where the mark is always on screen (the sidebar's ribbon). */
  prefetch?: false;
}) {
  return (
    <Link
      className={`${styles.brand}${markOnly ? ` ${styles.markOnly}` : ""}`}
      href={href}
      prefetch={prefetch}
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
              <stop offset="0" stopColor={MARK_ART.ground[0]} />
              <stop offset="0.55" stopColor={MARK_ART.ground[1]} />
              <stop offset="1" stopColor={MARK_ART.ground[2]} />
            </linearGradient>
            <radialGradient id={`${id}-light`} cx="50%" cy="0%" r="75%">
              <stop offset="0" stopColor={MARK_ART.light} stopOpacity="0.16" />
              <stop offset="1" stopColor={MARK_ART.light} stopOpacity="0" />
            </radialGradient>
            <linearGradient
              id={`${id}-bars`}
              gradientUnits="userSpaceOnUse"
              x1="0"
              y1={ART_TOP}
              x2="0"
              y2={ART_BOTTOM}
            >
              <stop offset="0" stopColor={MARK_ART.bars[0]} />
              <stop offset="1" stopColor={MARK_ART.bars[1]} />
            </linearGradient>
            <linearGradient
              id={`${id}-i`}
              gradientUnits="userSpaceOnUse"
              x1="0"
              y1={ART_TOP}
              x2="0"
              y2={ART_BOTTOM}
            >
              <stop offset="0" stopColor={MARK_ART.i[0]} />
              <stop offset="1" stopColor={MARK_ART.i[1]} />
            </linearGradient>
            <radialGradient
              id={`${id}-halo`}
              gradientUnits="userSpaceOnUse"
              cx="50"
              cy="28.45"
              r="20"
            >
              <stop offset="0" stopColor={MARK_ART.halo} stopOpacity="0.5" />
              <stop offset="1" stopColor={MARK_ART.halo} stopOpacity="0" />
            </radialGradient>
          </defs>
          <rect
            width="100"
            height="100"
            rx="22.5"
            fill={`url(#${id}-ground)`}
          />
          <rect width="100" height="100" rx="22.5" fill={`url(#${id}-light)`} />
          <circle
            className={styles.halo}
            cx="50"
            cy="28.45"
            r="20"
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
              x="45"
              y="40.95"
              width={BAR_WIDTH}
              height="35"
              rx={BAR_WIDTH / 2}
            />
            <circle className={styles.dot} cx="50" cy="28.45" r="6.25" />
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
            <rect
              className={styles.hyphen}
              {...HYPHEN}
              rx={HYPHEN.height / 2}
            />
          </svg>
          <span className={styles.by}>by Authority Closers</span>
        </span>
      )}
    </>
  );
}
