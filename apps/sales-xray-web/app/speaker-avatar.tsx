"use client";

import { useState, type CSSProperties, type ReactNode } from "react";

import { ACCOUNT_PROFILE_PHOTO_PATH } from "./account-profile-client";
import { useShellProfile } from "./shell/profile-store";
import { speakerIcon } from "./speaker-icons";
import { initials, voiceStyle, type SpeakerProfile } from "./speaker-profiles";
import { useWorkspaceAccess } from "./workspace-access";
import styles from "./speaker.module.css";

/** Uses the private first-party photo, keeping each avatar's existing fallback. */
export function AccountAvatarImage({
  photoUrl,
  children,
}: {
  photoUrl: string | null | undefined;
  children: ReactNode;
}) {
  const [failed, setFailed] = useState(false);
  if (photoUrl !== ACCOUNT_PROFILE_PHOTO_PATH || failed) return children;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- The private photo must use the signed-in browser session directly.
    <img
      className="account-avatar-image"
      src={photoUrl}
      alt=""
      referrerPolicy="no-referrer"
      decoding="async"
      onError={() => setFailed(true)}
    />
  );
}

/**
 * A speaker's face in the report: your photo or initials on the brand gradient,
 * a chosen icon in the voice's colour, or simply the speaker's number.
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
  const access = useWorkspaceAccess();
  const account = useShellProfile(
    access?.authenticated === true,
    profile?.role === "you",
  );
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
        <AccountAvatarImage key={account?.email} photoUrl={account?.photo_url}>
          {initials(profile.name || youName)}
        </AccountAvatarImage>
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
