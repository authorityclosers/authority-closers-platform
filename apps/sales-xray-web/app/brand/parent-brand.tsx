/**
 * The parent brand under Sales X-Ray: "by Authority Closers" (owner's brand order, 19 Nov 2026).
 *
 * PARENT_MARK picks how it shows, in one place, so it is one line to swap back:
 * - "point": the Authority Closers "Point" logo, the kit's endorsement art (brand kit v0.2,
 *   logos/authority-closers/endorse-sales-x-ray-*.svg). The kit marks Point as a CANDIDATE (the owner likes
 *   it, awaiting formal sign-off); the owner asked for it in the app tonight, so it ships behind this switch.
 *   The file is placed as it is, never redrawn: the view shows only its "by + A + Authority Closers." part.
 * - "text": the words "by Authority Closers", as before 19 Nov 2026.
 */
import styles from "./parent-brand.module.css";

export type ParentMark = "point" | "text";
export const PARENT_MARK: ParentMark = "point";

export const PARENT_NAME = "by Authority Closers";
// The endorsement's own part of the kit file (outer user units of its 460 x 57.02 view): "by", the symbol and
// the name with its full stop. The product lockup before it is left out of the view, not out of the file.
const PART = "#svgView(viewBox(258,10,202,38))";
export const PARENT_ART = {
  light: `/brand/authority-closers/endorse-sales-x-ray-light.svg${PART}`,
  dark: `/brand/authority-closers/endorse-sales-x-ray-dark.svg${PART}`,
} as const;
// The horizontal lockup, for a footer: the kit's file with its own clear space (one dot on every side).
export const PARENT_LOGO = {
  light: "/brand/authority-closers/ac-horizontal-light.svg",
  dark: "/brand/authority-closers/ac-horizontal-dark.svg",
  name: "Authority Closers",
} as const;

export function ParentEndorsement({
  className,
  onDark = false,
  mark = PARENT_MARK,
}: {
  className?: string;
  /** On a surface that is dark in both themes (the sign-in film): the dark art always. */
  onDark?: boolean;
  mark?: ParentMark;
}) {
  if (mark === "text") return <span className={className}>{PARENT_NAME}</span>;
  const classes = [
    styles.endorse,
    onDark ? styles.onDark : "",
    className ?? "",
  ];
  return (
    <span
      className={classes.filter(Boolean).join(" ")}
      role="img"
      aria-label={PARENT_NAME}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- fixed brand artwork, an SVG file as it is */}
      <img className={styles.light} src={PARENT_ART.light} alt="" />
      {/* eslint-disable-next-line @next/next/no-img-element -- fixed brand artwork, an SVG file as it is */}
      <img className={styles.dark} src={PARENT_ART.dark} alt="" />
    </span>
  );
}

/** Authority Closers on its own (a footer): the Point horizontal lockup, or the name as words. */
export function ParentLogo({
  className,
  mark = PARENT_MARK,
}: {
  className?: string;
  mark?: ParentMark;
}) {
  if (mark === "text")
    return <span className={className}>{PARENT_LOGO.name}</span>;
  const classes = [styles.logo, className ?? ""];
  return (
    <span
      className={classes.filter(Boolean).join(" ")}
      role="img"
      aria-label={PARENT_LOGO.name}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- fixed brand artwork, an SVG file as it is */}
      <img className={styles.light} src={PARENT_LOGO.light} alt="" />
      {/* eslint-disable-next-line @next/next/no-img-element -- fixed brand artwork, an SVG file as it is */}
      <img className={styles.dark} src={PARENT_LOGO.dark} alt="" />
    </span>
  );
}
