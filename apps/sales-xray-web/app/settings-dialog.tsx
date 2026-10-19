"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import {
  SETTINGS_CHANGE_EVENT,
  SETTINGS_HASH_PREFIX,
  forgetSettingsEntry,
  settingsHashOpen,
} from "./settings-open";
import { settingsPath } from "./settings/settings-sections";
import { useWorkspaceAccess } from "./workspace-access";

/**
 * Settings have their own pages (owner, 20 Oct: "revamp the settings"). Every
 * "open settings" control, and an old #settings or #settings/<section> link,
 * now goes to the matching section under /settings, in place of the entry
 * that opened it, so Back returns to the page you were on. Mounted once by the
 * app frame; signed-out visitors are never sent there.
 */
/** The app router, or null where a page is drawn without one (tests, previews). */
function useOptionalRouter() {
  try {
    return useRouter();
  } catch {
    return null;
  }
}

export function SettingsDialogHost() {
  const access = useWorkspaceAccess();
  const router = useOptionalRouter();
  const signedIn = access?.authenticated === true;

  useEffect(() => {
    if (!signedIn) return;
    const sync = () => {
      forgetSettingsEntry();
      const hash = window.location.hash;
      if (!settingsHashOpen(hash)) return;
      const section = hash.startsWith(`#${SETTINGS_HASH_PREFIX}`)
        ? hash.slice(SETTINGS_HASH_PREFIX.length + 1)
        : "";
      // A provider's way back (?connected= or ?connect_error=) comes along,
      // so the section can say how it went.
      const back = new URLSearchParams();
      const current = new URLSearchParams(window.location.search);
      for (const key of ["connected", "connect_error"]) {
        const value = current.get(key);
        if (value) back.set(key, value);
      }
      const path = settingsPath(section) + (back.size ? `?${back}` : "");
      if (router) router.replace(path);
      else window.location.replace(path);
    };
    sync();
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    window.addEventListener(SETTINGS_CHANGE_EVENT, sync);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
      window.removeEventListener(SETTINGS_CHANGE_EVENT, sync);
    };
  }, [signedIn, router]);

  return null;
}
