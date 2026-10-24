/**
 * Sales X-Ray on Google Play (24 Oct 2026). The download-link app and Play's
 * build are signed with different keys, so Android won't update one with the
 * other: a seller moves to Play by uninstalling the download-link app first.
 *
 * Until the public store page is live, Play's testing opt-in works only for
 * accounts on its tester list (anyone else sees "not available"), so the Play
 * link is offered to those accounts only: one constant to widen, or to swap
 * for the store page.
 */
import { useShellProfile } from "../shell/profile-store";

/** Play's testing opt-in (the AC team list); the store page replaces it once public. */
export const PLAY_OPT_IN_URL =
  "https://play.google.com/apps/internaltest/4701571889733710337";

/** Accounts on Play's tester list, by email domain. */
export const PLAY_TESTER_DOMAINS: readonly string[] = ["authorityclosers.com"];

export function onPlayTesterList(email: string | null | undefined): boolean {
  const domain = email?.split("@")[1]?.trim().toLowerCase();
  return Boolean(domain && PLAY_TESTER_DOMAINS.includes(domain));
}

/** The Play link for the signed-in account, or null where Play can't serve it yet. */
export function usePlayLink(): string | null {
  const profile = useShellProfile(true, process.env.NODE_ENV !== "test");
  return onPlayTesterList(profile?.email) ? PLAY_OPT_IN_URL : null;
}
