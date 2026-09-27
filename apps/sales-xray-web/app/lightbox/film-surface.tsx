import { createElement, type HTMLAttributes, type ReactNode } from "react";
import styles from "./film-surface.module.css";

export type FilmVariant = "drop" | "panel" | "player" | "focus";

/**
 * The dark call-bound surface: drop zone, analysing panel, player and focus card.
 * It stays dark in both themes. The scanline is ambient activity for drop and
 * panel only; it never represents progress.
 */
export function FilmSurface({
  as = "div",
  variant,
  corners = variant === "drop",
  scanline = false,
  htmlFor,
  className = "",
  children,
  ...rest
}: HTMLAttributes<HTMLElement> & {
  as?: "div" | "section" | "label" | "aside" | "article";
  variant: FilmVariant;
  corners?: boolean;
  scanline?: boolean;
  /** Only for `as="label"`. */
  htmlFor?: string;
  children?: ReactNode;
}) {
  const ambient = scanline && (variant === "drop" || variant === "panel");
  return createElement(
    as,
    {
      ...rest,
      ...(as === "label" && htmlFor ? { htmlFor } : {}),
      className: `${styles.film} ${className}`,
      "data-film-variant": variant,
    },
    ambient ? (
      <span className={styles.scanline} aria-hidden="true" data-film-scanline />
    ) : null,
    corners ? (
      <span className={styles.corners} aria-hidden="true" data-film-corners>
        <span />
        <span />
        <span />
        <span />
      </span>
    ) : null,
    children,
  );
}
