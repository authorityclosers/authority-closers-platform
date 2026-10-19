"use client";

/*
 * What a signed-out person sees in place of a page (owner, 19 Oct: "the
 * signed-out screen is ugly"): one calm welcome that fits the phone, with a
 * living wave, three things Sales Xray does, and one clear way in. Sign in
 * comes back to the page the person was on. Motion is decoration only and
 * stops for reduced motion. No prices.
 */
import { ArrowRight, AudioLines, ListChecks, Sparkles } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { CSSProperties } from "react";

import { useWorkspaceAccess } from "../workspace-access";
import styles from "./signed-out-welcome.module.css";

const BARS = 28;
// A fixed shape (the same on server and client), so nothing changes on load.
const LEVELS = Array.from({ length: BARS }, (_, index) => {
  const wave = Math.abs(Math.sin(index * 0.42) * Math.cos(index * 0.11));
  return Math.round(22 + 70 * wave);
});

const POINTS = [
  { Icon: AudioLines, text: "Every sales call becomes a clear report" },
  { Icon: ListChecks, text: "Leads, follow-ups and calls in one place" },
  { Icon: Sparkles, text: "Coaching from your own conversations" },
] as const;

/** The sign-in address that brings the person back to ``path``. */
export function signInHref(path: string | null): string {
  const next =
    path && path.startsWith("/") && !path.startsWith("/login") ? path : null;
  return next ? `/login?next=${encodeURIComponent(next)}` : "/login";
}

export function SignedOutWelcome({
  title,
  text,
  guestHref,
}: {
  title: string;
  text: string;
  /** Where to try Sales Xray without an account, when the page allows it. */
  guestHref?: string;
}) {
  const access = useWorkspaceAccess();
  const pathname = usePathname();
  return (
    <section className={styles.welcome} aria-labelledby="signed-out-title">
      <div className={styles.hero}>
        <div className={styles.wave} aria-hidden="true">
          {LEVELS.map((level, index) => (
            <i
              key={index}
              style={{ "--h": `${level}%`, "--i": index } as CSSProperties}
            />
          ))}
        </div>
        <p className={styles.kicker}>Sales Xray</p>
        <h2 id="signed-out-title" className={styles.title}>
          {title}
        </h2>
        <p className={styles.text}>{text}</p>
      </div>
      <ul className={styles.points}>
        {POINTS.map(({ Icon, text: point }, index) => (
          <li key={point} style={{ "--i": index } as CSSProperties}>
            <span className={styles.pointIcon} aria-hidden="true">
              <Icon size={16} />
            </span>
            {point}
          </li>
        ))}
      </ul>
      <div className={styles.actions}>
        <Link
          className={styles.signIn}
          href={signInHref(pathname)}
          onClick={(event) => {
            if (access?.requestAccountSignIn) {
              event.preventDefault();
              access.requestAccountSignIn();
            }
          }}
        >
          Sign in
          <ArrowRight size={18} aria-hidden="true" />
        </Link>
        {guestHref ? (
          <Link className={styles.guest} href={guestHref}>
            Or analyse a call without an account
          </Link>
        ) : null}
        <p className={styles.oneAccount}>
          One account for every Authority Closers app
        </p>
      </div>
    </section>
  );
}
