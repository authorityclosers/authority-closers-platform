"use client";

import { Avatar } from "../ui/kit";
import { characterFor, useCharacters } from "./characters";

/**
 * A person's avatar: their photo, else their character (owner #32, 26 Oct
 * 2026), else their initials while the characters are read or before they
 * ship.
 */
export function PersonAvatar({
  personId,
  name,
  photoUrl = null,
  size = 24,
}: {
  personId: string | null;
  name: string;
  photoUrl?: string | null;
  size?: number;
}) {
  const characters = useCharacters(!photoUrl && personId !== null);
  const url =
    photoUrl ??
    (personId ? (characterFor(personId, characters)?.url ?? null) : null);
  // A new picture gets a new avatar, so one that failed doesn't hide the next.
  return <Avatar key={url ?? ""} name={name} photoUrl={url} size={size} />;
}
