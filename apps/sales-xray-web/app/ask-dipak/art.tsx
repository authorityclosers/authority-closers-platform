/**
 * Ask Dipak's drawings (graphics pass, 18 Nov 2026; option G-A "duotone spot
 * art", picked from three boards in /home/acdev/research/askdipak-full-20261118/
 * options/): each motif is soft tint shapes in its topic's colour under a crisp
 * line drawing in the same colour, with one small spark. One family for the
 * ten topic drawings, the three real situations and the seven lesson-part
 * marks, so Ask Dipak reads as one set, not clip-art. Colours come from
 * --ad-tone / --ad-tone-soft (by meaning) and --ad-spark, so light and dark
 * both follow the theme. No faces, no words, no numbers.
 */
import type { ReactNode } from "react";

import styles from "./ask-dipak.module.css";

type Motif = {
  /** Soft shapes, filled with the tone at low strength. */
  fill: ReactNode;
  /** The drawing, stroked in the tone. */
  line: ReactNode;
  /** Small solid parts in the tone. */
  solid?: ReactNode;
  /** One spark in the accent colour. */
  spark?: ReactNode;
};

/** Motifs by Dipak's category id (01-10), on a 96 x 64 grid. */
const MOTIFS: Readonly<Record<string, Motif>> = {
  // 01 Sales Mindset & Psychology: a compass with a steady centre.
  "01": {
    fill: <circle cx="48" cy="32" r="21" />,
    line: (
      <>
        <circle cx="48" cy="32" r="21" />
        <path d="M48 7v4M48 53v4M23 32h4M69 32h4" />
        <path d="m48 17 6.5 15L48 47l-6.5-15z" />
        <path d="M41.5 32h13" />
      </>
    ),
    solid: <path d="m48 17 6.5 15h-13z" />,
    spark: <circle cx="48" cy="32" r="2.6" />,
  },
  // 02 Rapport Building & Trust: two speech bubbles meeting, a heart in one.
  "02": {
    fill: (
      <>
        <path d="M18 12h30a7 7 0 0 1 7 7v12a7 7 0 0 1-7 7H31l-9 7v-7h-4a7 7 0 0 1-7-7V19a7 7 0 0 1 7-7z" />
        <path d="M50 26h24a7 7 0 0 1 7 7v10a7 7 0 0 1-7 7h-2v7l-8-7H50a7 7 0 0 1-7-7V33a7 7 0 0 1 7-7z" />
      </>
    ),
    line: (
      <>
        <path d="M18 12h30a7 7 0 0 1 7 7v12a7 7 0 0 1-7 7H31l-9 7v-7h-4a7 7 0 0 1-7-7V19a7 7 0 0 1 7-7z" />
        <path d="M57 26h17a7 7 0 0 1 7 7v10a7 7 0 0 1-7 7h-2v7l-8-7H50a7 7 0 0 1-7-7v-5" />
        <path d="M22 25h20" />
      </>
    ),
    solid: (
      <path d="M62 36.5c0-2 1.6-3.5 3.5-3.5 1.2 0 2 .6 2.5 1.4.5-.8 1.3-1.4 2.5-1.4 1.9 0 3.5 1.5 3.5 3.5 0 3.6-6 7-6 7s-6-3.4-6-7z" />
    ),
  },
  // 03 Communication & Listening: listening waves around a dialogue.
  "03": {
    fill: (
      <path d="M38 16h20a7 7 0 0 1 7 7v10a7 7 0 0 1-7 7H47l-8 7v-7h-1a7 7 0 0 1-7-7V23a7 7 0 0 1 7-7z" />
    ),
    line: (
      <>
        <path d="M38 16h20a7 7 0 0 1 7 7v10a7 7 0 0 1-7 7H47l-8 7v-7h-1a7 7 0 0 1-7-7V23a7 7 0 0 1 7-7z" />
        <path d="M23 21c-4 6-4 14 0 20M15 15c-8 10-8 22 0 32M73 21c4 6 4 14 0 20M81 15c8 10 8 22 0 32" />
        <path d="M40 25h16M40 31h10" />
      </>
    ),
    spark: <circle cx="55" cy="31" r="2.4" />,
  },
  // 04 Problem & Desire Discovery: a magnifier revealing a question.
  "04": {
    fill: <circle cx="42" cy="28" r="17" />,
    line: (
      <>
        <circle cx="42" cy="28" r="17" />
        <path d="m54.5 40.5 13 13" strokeWidth="5" />
        <path d="M36.5 23.5a5.5 5.5 0 1 1 7.5 5.1c-1.3.6-2 1.6-2 3" />
      </>
    ),
    spark: <circle cx="42" cy="36" r="2.2" />,
  },
  // 05 Value Creation & Quantification: stacked value blocks and a ruler.
  "05": {
    fill: (
      <>
        <rect x="18" y="40" width="26" height="13" rx="3.5" />
        <rect x="23" y="25" width="26" height="13" rx="3.5" />
        <rect x="28" y="10" width="26" height="13" rx="3.5" />
      </>
    ),
    line: (
      <>
        <rect x="18" y="40" width="26" height="13" rx="3.5" />
        <rect x="23" y="25" width="26" height="13" rx="3.5" />
        <rect x="28" y="10" width="26" height="13" rx="3.5" />
        <path d="M68 9v45M68 14h5M68 22h8M68 30h5M68 38h8M68 46h5" />
      </>
    ),
    spark: <circle cx="41" cy="16.5" r="2.4" />,
  },
  // 06 Qualification & Decision Process: a branching path, one end ticked.
  "06": {
    fill: (
      <>
        <circle cx="22" cy="32" r="8" />
        <circle cx="74" cy="17" r="8" />
        <circle cx="74" cy="47" r="8" />
      </>
    ),
    line: (
      <>
        <circle cx="22" cy="32" r="8" />
        <path d="M30 32h9c9 0 10-15 19-15h8M39 32c9 0 10 15 19 15h8" />
        <circle cx="74" cy="17" r="8" />
        <circle cx="74" cy="47" r="8" />
        <path d="m70.5 17 2.5 2.5 4.5-5" />
      </>
    ),
    spark: <circle cx="22" cy="32" r="2.6" />,
  },
  // 07 Solution Presentation & Influence: a frame with a focus beam.
  "07": {
    fill: (
      <>
        <path d="M60 22 80 12v40L60 42z" />
        <rect x="14" y="12" width="46" height="32" rx="6" />
      </>
    ),
    line: (
      <>
        <rect x="14" y="12" width="46" height="32" rx="6" />
        <path d="M37 44v8M28 53h18M60 22l20-10M60 42l20 10" />
        <path d="M23 36v-6M31 36v-11M39 36v-8M47 36V21" />
      </>
    ),
    spark: <circle cx="80" cy="32" r="2.4" />,
  },
  // 08 Objection Handling & Negotiation: a price tag and a speech bubble bridged.
  "08": {
    fill: (
      <>
        <path d="M12 22V11h19l18 18-13.5 13.5z" />
        <path d="M60 22h17a7 7 0 0 1 7 7v8a7 7 0 0 1-7 7h-5l-7 7v-7h-5a7 7 0 0 1-7-7v-8a7 7 0 0 1 7-7z" />
      </>
    ),
    line: (
      <>
        <path d="M12 22V11h19l18 18-13.5 13.5z" />
        <path d="M60 22h17a7 7 0 0 1 7 7v8a7 7 0 0 1-7 7h-5l-7 7v-7h-5a7 7 0 0 1-7-7v-8a7 7 0 0 1 7-7z" />
        <path d="M38 50c5 4 12 4 16-1" />
        <path d="M62 31.5h14M62 37h9" />
      </>
    ),
    spark: <circle cx="22" cy="20" r="2.8" />,
  },
  // 09 Closing & Follow-Up: stepping stones and a tick.
  "09": {
    fill: (
      <>
        <ellipse cx="18" cy="50" rx="9" ry="4.5" />
        <ellipse cx="37" cy="42" rx="9" ry="4.5" />
        <ellipse cx="56" cy="34" rx="9" ry="4.5" />
        <circle cx="76" cy="18" r="11" />
      </>
    ),
    line: (
      <>
        <ellipse cx="18" cy="50" rx="9" ry="4.5" />
        <ellipse cx="37" cy="42" rx="9" ry="4.5" />
        <ellipse cx="56" cy="34" rx="9" ry="4.5" />
        <circle cx="76" cy="18" r="11" />
        <path d="m71 18 3.5 3.5 7-7.5" />
      </>
    ),
  },
  // 10 Sales Growth & Performance: a plant beside an upward line.
  "10": {
    fill: (
      <>
        <path d="M28 38c-9 0-14-7-14-14 9 0 14 7 14 14zM28 31c0-8 6-14 14-14 0 8-6 14-14 14z" />
        <path d="M20 46h16l-2 9H22z" />
      </>
    ),
    line: (
      <>
        <path d="M28 46V27M28 38c-9 0-14-7-14-14 9 0 14 7 14 14zM28 31c0-8 6-14 14-14 0 8-6 14-14 14z" />
        <path d="M20 46h16l-2 9H22z" />
        <path d="m50 47 10-11 8 6 14-19M74 23h8v8" />
      </>
    ),
  },
};

/** The home's four featured topics, drawn with their main category's motif. */
const FEATURED_MOTIF: Readonly<Record<string, string>> = {
  talk: "02",
  discover: "04",
  price: "08",
  close: "09",
};

function Layers({ motif, line = 2.4 }: { motif: Motif; line?: number }) {
  return (
    <>
      <g className={styles.artFill}>{motif.fill}</g>
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth={line}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {motif.line}
      </g>
      {motif.solid ? <g fill="currentColor">{motif.solid}</g> : null}
      {motif.spark ? <g className={styles.artSpark}>{motif.spark}</g> : null}
    </>
  );
}

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
        x="2"
        y="2"
        width="92"
        height="60"
        rx="30"
      />
      <Layers motif={MOTIFS[id] ?? MOTIFS["01"]} />
    </svg>
  );
}

export const hasArt = (id: string): boolean =>
  Object.prototype.hasOwnProperty.call(MOTIFS, id);

/** The seven lesson parts' marks, in the same duotone family (24 grid). */
const PART_MARKS: Readonly<Record<string, Motif>> = {
  turn: {
    fill: (
      <path d="M5 4h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-7l-5 4v-4H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
    ),
    line: (
      <>
        <path d="M5 4h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-7l-5 4v-4H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
        <path d="M9.6 8.6a2.4 2.4 0 1 1 3.3 2.2c-.6.3-.9.7-.9 1.3M12 14.4v.1" />
      </>
    ),
  },
  shift: {
    fill: <circle cx="17" cy="17" r="5" />,
    line: (
      <>
        <circle cx="7" cy="7" r="4" strokeDasharray="2 2.4" />
        <circle cx="17" cy="17" r="5" />
        <path d="M9.5 10.5 13 14m0-4v4h-4" />
      </>
    ),
  },
  quick: {
    fill: <rect x="3" y="3" width="18" height="18" rx="5" />,
    line: (
      <>
        <circle cx="7.5" cy="7.5" r="1.6" />
        <circle cx="7.5" cy="16.5" r="1.6" />
        <path d="M7.5 9.1v5.8M11.5 7.5h7M11.5 16.5h5" />
      </>
    ),
  },
  deep: {
    fill: <path d="M3 5.5c3-1.5 6-1.5 9 1v14c-3-2.5-6-2.5-9-1z" />,
    line: (
      <path d="M3 5.5c3-1.5 6-1.5 9 1 3-2.5 6-2.5 9-1v14c-3-1.5-6-1.5-9 1-3-2.5-6-2.5-9-1zM12 6.5v14" />
    ),
  },
  cue: {
    fill: <path d="M6 3h12v18l-6-4.5L6 21z" />,
    line: <path d="M6 3h12v18l-6-4.5L6 21zM9.5 8h5" />,
  },
  mission: {
    fill: <path d="M5 4h12l-2.5 4.5L17 13H5z" />,
    line: <path d="M5 21V4h12l-2.5 4.5L17 13H5" />,
  },
  next: {
    fill: <circle cx="18" cy="12" r="4" />,
    line: (
      <>
        <path d="M3 12h9m-3-4 4 4-4 4" />
        <circle cx="18" cy="12" r="4" />
      </>
    ),
  },
};

export function PartMark({ part, size = 22 }: { part: string; size?: number }) {
  const motif = PART_MARKS[part];
  if (!motif) return null;
  return (
    <svg
      className={styles.partMark}
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      data-part-mark={part}
    >
      <Layers motif={motif} line={1.8} />
    </svg>
  );
}

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
