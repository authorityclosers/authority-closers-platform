"use client";

import { useEffect, useState } from "react";

import { readAccountProfile } from "./account-profile-client";
import { getShellState } from "./shell/shell-store";

export function firstNameOf(name: string | null | undefined): string | null {
  return name?.trim().split(/\s+/)[0] || null;
}

/**
 * The signed-in person's first name, from the shell's cached profile or a
 * profile read. It arrives after mount, so server and client render alike.
 */
export function useProfileFirstName(): string | null {
  const [name, setName] = useState<string | null>(null);
  useEffect(() => {
    const cached = firstNameOf(getShellState().profileName);
    const controller = new AbortController();
    if (cached !== null) {
      queueMicrotask(() => {
        if (!controller.signal.aborted) setName(cached);
      });
    } else if (process.env.NODE_ENV !== "test") {
      readAccountProfile(controller.signal)
        .then((profile) => {
          if (!controller.signal.aborted) setName(firstNameOf(profile.name));
        })
        .catch(() => {
          // Without a profile the greeting simply has no name.
        });
    }
    return () => controller.abort();
  }, []);
  return name;
}
