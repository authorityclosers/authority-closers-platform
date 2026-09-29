"use client";

import { useShellProfile } from "./shell/profile-store";

export function firstNameOf(name: string | null | undefined): string | null {
  return name?.trim().split(/\s+/)[0] || null;
}

/**
 * The signed-in person's first name, from the shell's cached profile or a
 * profile read. It arrives after mount, so server and client render alike.
 */
export function useProfileFirstName(): string | null {
  const profile = useShellProfile(true, process.env.NODE_ENV !== "test");
  return firstNameOf(profile?.name);
}
