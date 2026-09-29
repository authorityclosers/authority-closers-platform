"use client";

import type { CSSProperties } from "react";

import { speakerIcon } from "./speaker-icons";
import { initials, voiceStyle, type SpeakerProfile } from "./speaker-profiles";
import styles from "./speaker.module.css";

/**
 * A speaker's face in the report: your initials on the brand gradient (your
 * profile photo once the account stores it), a chosen icon in the voice's
 * colour, or simply the speaker's number.
 */
export function SpeakerAvatar({
  voice,
  profile,
  youName,
  size = 20,
}: {
  voice: number;
  profile: SpeakerProfile | null | undefined;
  /** The account holder's name, for "you" without a typed name. */
  youName?: string | null;
  size?: number;
}) {
  const icon = speakerIcon(profile?.icon);
  const style = {
    ...voiceStyle(voice),
    "--size": `${size}px`,
  } as CSSProperties;
  if (profile?.role === "you")
    return (
      <span
        className={styles.avatar}
        data-you="true"
        style={style}
        aria-hidden="true"
      >
        {initials(profile.name || youName)}
      </span>
    );
  if (icon)
    return (
      <span className={styles.avatar} style={style} aria-hidden="true">
        <icon.Icon size={Math.round(size * 0.58)} strokeWidth={2.1} />
      </span>
    );
  return (
    <span
      className={styles.avatar}
      data-plain="true"
      style={style}
      aria-hidden="true"
    >
      {voice + 1}
    </span>
  );
}
