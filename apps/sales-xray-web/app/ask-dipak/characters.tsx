"use client";

/**
 * Aman and Rohit in Ask Dipak (character kit v2, final: the owner loves it, 19 Nov 2026; brand order the same
 * night). Rules from the kit's 12-characters.md: Aman the salesperson wears green, Rohit the buyer orange; they
 * appear only in a situation's hook and its payoff, never in the teaching middle; they are fictional, and the
 * kit is extended, never redrawn.
 *
 * Every picture here was rendered from the kit's own rig (pb03-formats/src/characters, unchanged): the stills
 * are its busts at rest (idle motion off, as on the model sheet) inside each character's kit backdrop circle.
 *
 * No idle loops ship (owner, 19 Nov 2026 23:36 IST: "the videos are not approved for Ask Dipak, so make sure they
 * won't go live on the app in the next update"). The hook and the payoff show their still pose, the same picture
 * reduced motion showed. A loop may come back only through the server's Ask Dipak video switch
 * (GET /v1/sales-xray/ask-dipak/videos, OFF by default), never as a file in public/.
 */

import styles from "./characters.module.css";

const BASE = "/media/ask-dipak/characters";

export type CharacterStillName =
  | "aman-neutral"
  | "aman-worried"
  | "aman-confident"
  | "aman-aha"
  | "aman-relieved"
  | "rohit-neutral"
  | "rohit-sceptical"
  | "rohit-thinking"
  | "rohit-worried"
  | "rohit-annoyed"
  | "rohit-grateful";

export const CHARACTER_NAME = {
  aman: "Aman, the salesperson",
  rohit: "Rohit, the customer",
} as const;

/** The hook's pose (Rohit, sceptical) and the payoff's (Aman, confident). Stills only: no loop is approved. */
export const CHARACTER_LOOP = {
  hook: { still: "rohit-sceptical" },
  payoff: { still: "aman-confident" },
} as const satisfies Record<string, { still: CharacterStillName }>;

export const stillSrc = (name: CharacterStillName) => `${BASE}/${name}.svg`;

const whoOf = (name: CharacterStillName) =>
  name.startsWith("aman") ? CHARACTER_NAME.aman : CHARACTER_NAME.rohit;

/** A character still, a round bust. Decorative unless it carries a name. */
export function CharacterStill({
  name,
  size = 44,
  labelled = false,
  className,
}: {
  name: CharacterStillName;
  size?: number;
  labelled?: boolean;
  className?: string;
}) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- the kit's rendered character, an SVG file as it is
    <img
      className={className ? `${styles.still} ${className}` : styles.still}
      src={stillSrc(name)}
      width={size}
      height={size}
      alt={labelled ? whoOf(name) : ""}
      aria-hidden={labelled ? undefined : true}
      loading="lazy"
      decoding="async"
    />
  );
}

/** The hook's or the payoff's character: its still pose (no video, no loop request). */
export function CharacterLoop({
  loop,
  size = 64,
  className,
}: {
  loop: keyof typeof CHARACTER_LOOP;
  size?: number;
  className?: string;
}) {
  const { still } = CHARACTER_LOOP[loop];
  return (
    <span
      className={className ? `${styles.loop} ${className}` : styles.loop}
      style={{ width: size, height: size }}
      role="img"
      aria-label={whoOf(still)}
      data-character-loop={loop}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- the kit's rendered character, an SVG file as it is */}
      <img
        className={styles.media}
        src={stillSrc(still)}
        width={size}
        height={size}
        alt=""
        aria-hidden="true"
        decoding="async"
      />
    </span>
  );
}
