"use client";

/**
 * Aman and Rohit in Ask Dipak (character kit v2, final: the owner loves it, 19 Nov 2026; brand order the same
 * night). Rules from the kit's 12-characters.md: Aman the salesperson wears green, Rohit the buyer orange; they
 * appear only in a situation's hook and its payoff, never in the teaching middle; they are fictional, and the
 * kit is extended, never redrawn.
 *
 * Every picture here was rendered from the kit's own rig (pb03-formats/src/characters, unchanged): the stills
 * are its busts at rest (idle motion off, as on the model sheet) inside each character's kit backdrop circle;
 * the loops are its frames (breathing, blinks, the nod) played forward then back so they have no seam, 240 px,
 * no sound, about 20 KB each. With reduced motion, or until a loop is near the screen, the still shows.
 */
import { useEffect, useRef, useState, type RefObject } from "react";

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

/** The two loops: the hook (Rohit, sceptical) and the payoff (Aman, confident, nodding). */
export const CHARACTER_LOOP = {
  hook: { still: "rohit-sceptical", name: "rohit-sceptical-loop" },
  payoff: { still: "aman-confident", name: "aman-confident-loop" },
} as const satisfies Record<
  string,
  { still: CharacterStillName; name: string }
>;

export const stillSrc = (name: CharacterStillName) => `${BASE}/${name}.svg`;
const loopSrc = (name: string, type: "webm" | "mp4") =>
  `${BASE}/${name}.${type}`;

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

function useReducedMotion() {
  const [reduced, setReduced] = useState(true);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

/** Near the screen yet? Loops load only then (and never without IntersectionObserver). */
function useNear(ref: RefObject<HTMLElement | null>) {
  const [near, setNear] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const watch = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true);
          watch.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    watch.observe(node);
    return () => watch.disconnect();
  }, [ref]);
  return near;
}

/** The hook's or the payoff's short loop: muted, looping, inline; the still first and with reduced motion. */
export function CharacterLoop({
  loop,
  size = 64,
  className,
}: {
  loop: keyof typeof CHARACTER_LOOP;
  size?: number;
  className?: string;
}) {
  const { still, name } = CHARACTER_LOOP[loop];
  const frame = useRef<HTMLSpanElement | null>(null);
  const reduced = useReducedMotion();
  const near = useNear(frame);
  return (
    <span
      ref={frame}
      className={className ? `${styles.loop} ${className}` : styles.loop}
      style={{ width: size, height: size }}
      role="img"
      aria-label={whoOf(still)}
      data-character-loop={loop}
    >
      {near && !reduced ? (
        <video
          className={styles.media}
          width={size}
          height={size}
          poster={stillSrc(still)}
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
          disablePictureInPicture
          aria-hidden="true"
        >
          <source src={loopSrc(name, "webm")} type="video/webm" />
          <source src={loopSrc(name, "mp4")} type="video/mp4" />
        </video>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- the kit's rendered character, an SVG file as it is
        <img
          className={styles.media}
          src={stillSrc(still)}
          width={size}
          height={size}
          alt=""
          aria-hidden="true"
          decoding="async"
        />
      )}
    </span>
  );
}
