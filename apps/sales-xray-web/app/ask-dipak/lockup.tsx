/**
 * The Ask Dipak horizontal lockup (brand kit v0.2, logos/ask-dipak/, final; owner's brand order, 19 Nov 2026):
 * the Speech D mark with "Ask Dipak" and "by Sales X-Ray", placed as the kit's fixed artwork files, never
 * redrawn or retyped. The light file on the light theme, the dark file (flat mint mark) on dark. Each file
 * carries its own clear space, the diameter of the "?" dot; the symbol inside stays above the kit's 16 px
 * minimum at every height used here (24 px and up).
 */
import styles from "./lockup.module.css";

export const ASK_DIPAK_LOCKUP = {
  light: "/brand/ask-dipak/lockup-horizontal-light.svg",
  dark: "/brand/ask-dipak/lockup-horizontal-dark.svg",
  name: "Ask Dipak",
} as const;

export function AskDipakLockup({
  className,
  inBar = false,
}: {
  className?: string;
  /** The top bar's title on laptops: a little smaller, on the title's line. */
  inBar?: boolean;
}) {
  const classes = [styles.lockup, inBar ? styles.bar : "", className ?? ""];
  return (
    <span
      className={classes.filter(Boolean).join(" ")}
      role="img"
      aria-label={ASK_DIPAK_LOCKUP.name}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- fixed brand artwork, an SVG file as it is */}
      <img className={styles.light} src={ASK_DIPAK_LOCKUP.light} alt="" />
      {/* eslint-disable-next-line @next/next/no-img-element -- fixed brand artwork, an SVG file as it is */}
      <img className={styles.dark} src={ASK_DIPAK_LOCKUP.dark} alt="" />
    </span>
  );
}
