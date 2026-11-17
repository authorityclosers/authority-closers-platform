/**
 * Ask Dipak's topic illustrations (redesign study 16 Nov 2026, §4; owner's
 * pick 17 Nov 2026): one small drawing per category, 2 px rounded strokes in
 * the topic's colour (--ad-tone) on its soft fill (--ad-tone-soft), so they
 * follow light and dark. Each is two or three shapes, legible at 40 px and
 * expressive at 72-96 px. No faces, no words, no numbers.
 */
import type { ReactNode } from "react";

import styles from "./ask-dipak.module.css";

/** Motifs by Dipak's category id (01-10). */
const MOTIFS: Readonly<Record<string, ReactNode>> = {
  // 01 Sales Mindset & Psychology: a compass with a steady centre.
  "01": (
    <>
      <circle cx="48" cy="32" r="19" />
      <path d="m48 18 5 14-5 14-5-14z" />
      <circle cx="48" cy="32" r="2.5" />
    </>
  ),
  // 02 Rapport Building & Trust: two speech bubbles meeting.
  "02": (
    <>
      <path d="M22 16h28a6 6 0 0 1 6 6v12a6 6 0 0 1-6 6H32l-8 6v-6h-2a6 6 0 0 1-6-6V22a6 6 0 0 1 6-6z" />
      <path d="M62 26h12a6 6 0 0 1 6 6v10a6 6 0 0 1-6 6h-1v6l-7-6h-4a6 6 0 0 1-6-6v-4" />
      <path d="M27 28h18" />
    </>
  ),
  // 03 Communication & Listening: listening waves around a dialogue.
  "03": (
    <>
      <path d="M38 20h20a6 6 0 0 1 6 6v8a6 6 0 0 1-6 6H46l-7 6v-6h-1a6 6 0 0 1-6-6v-8a6 6 0 0 1 6-6z" />
      <path d="M24 22c-4 6-4 14 0 20M16 17c-7 9-7 21 0 30" />
      <path d="M72 22c4 6 4 14 0 20M80 17c7 9 7 21 0 30" />
    </>
  ),
  // 04 Problem & Desire Discovery: a magnifier revealing a question.
  "04": (
    <>
      <circle cx="42" cy="28" r="15" />
      <path d="m53 39 13 13" />
      <path d="M37 24a5 5 0 1 1 7 5c-1.5.8-2 1.8-2 3M42 36.5v.5" />
    </>
  ),
  // 05 Value Creation & Quantification: stacked value blocks and a ruler.
  "05": (
    <>
      <rect x="22" y="38" width="22" height="12" rx="3" />
      <rect x="26" y="24" width="22" height="12" rx="3" />
      <rect x="30" y="10" width="22" height="12" rx="3" />
      <path d="M62 10v40M62 14h5M62 22h8M62 30h5M62 38h8M62 46h5" />
    </>
  ),
  // 06 Qualification & Decision Process: a branching decision path.
  "06": (
    <>
      <circle cx="24" cy="32" r="5" />
      <path d="M29 32h12c8 0 10-14 18-14h8M41 32c8 0 10 14 18 14h8" />
      <circle cx="72" cy="18" r="4" />
      <circle cx="72" cy="46" r="4" />
    </>
  ),
  // 07 Solution Presentation & Influence: a frame with a focus beam.
  "07": (
    <>
      <rect x="18" y="14" width="44" height="32" rx="5" />
      <path d="M40 46v8M30 54h20" />
      <path d="m62 24 16-8M62 36l16 8M78 16v28" />
    </>
  ),
  // 08 Objection Handling & Negotiation: a price tag and a speech bubble bridged.
  "08": (
    <>
      <path d="M16 22v-8h18l16 16-12 12-16-16z" />
      <circle cx="25" cy="21" r="2.5" />
      <path d="M58 22h16a6 6 0 0 1 6 6v8a6 6 0 0 1-6 6h-6l-6 6v-6h-4a6 6 0 0 1-6-6" />
      <path d="M44 44c4 4 10 4 14 0" />
    </>
  ),
  // 09 Closing & Follow-Up: stepping stones and a tick.
  "09": (
    <>
      <ellipse cx="22" cy="48" rx="8" ry="4" />
      <ellipse cx="40" cy="40" rx="8" ry="4" />
      <ellipse cx="58" cy="32" rx="8" ry="4" />
      <path d="m66 18 6 6 12-14" />
    </>
  ),
  // 10 Sales Growth & Performance: a plant beside an upward line.
  "10": (
    <>
      <path d="M28 52V30M28 38c-8 0-12-6-12-12 8 0 12 6 12 12zM28 32c0-7 5-12 12-12 0 7-5 12-12 12z" />
      <path d="M20 52h16" />
      <path d="m48 46 10-10 7 6 15-18M72 24h8v8" />
    </>
  ),
};

/** The home's four featured topics, drawn with their main category's motif. */
const FEATURED_MOTIF: Readonly<Record<string, string>> = {
  talk: "02",
  discover: "04",
  price: "08",
  close: "09",
};

export function TopicArt({
  category,
  featured,
  size = 72,
}: {
  category?: string;
  featured?: string;
  size?: number;
}) {
  const id = featured ? (FEATURED_MOTIF[featured] ?? "01") : (category ?? "01");
  return (
    <svg
      className={styles.art}
      viewBox="0 0 96 64"
      width={size * 1.5}
      height={size}
      aria-hidden="true"
      focusable="false"
      data-art={id}
    >
      <rect
        className={styles.artBack}
        x="4"
        y="4"
        width="88"
        height="56"
        rx="28"
      />
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {MOTIFS[id] ?? MOTIFS["01"]}
      </g>
    </svg>
  );
}

export const hasArt = (id: string): boolean =>
  Object.prototype.hasOwnProperty.call(MOTIFS, id);

/** Dipak's monogram until an approved photo exists (study §6: never generate his face). */
export function CoachMark({ size = "lg" }: { size?: "lg" | "sm" }) {
  return (
    <span
      className={`${styles.coachMark} ${size === "sm" ? styles.coachMarkSm : ""}`}
      role="img"
      aria-label="Dipak Vishwakarma"
    >
      DV
    </span>
  );
}
