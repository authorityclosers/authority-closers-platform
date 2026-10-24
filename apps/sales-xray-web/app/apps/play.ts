/**
 * Sales X-Ray on Google Play (24 Oct 2026). The download-link app and Play's
 * build are signed with different keys, so Android won't update one with the
 * other: a seller moves to Play by uninstalling the download-link app first.
 *
 * Until the listing is public, Play's testing opt-in serves only people on its
 * tester list (some on gmail), so the links and the download-link app's card
 * speak to testers and keep the app file for everyone else (orchestrator,
 * 24 Oct 2026). Set PLAY_STORE_URL once the store page is live: the links,
 * the card and their words move to it together.
 */

/** Play's testing opt-in: testers only. */
export const PLAY_OPT_IN_URL =
  "https://play.google.com/apps/internaltest/4701571889733710337";

/** Play's public store page: null until the listing is public. */
export const PLAY_STORE_URL: string | null = null;

export type PlayWords = Readonly<{
  /** Where every Play button goes. */
  url: string;
  /** Under "Android" on /apps and in the Get the app dialog. */
  where: string;
  /** The main action. */
  get: string;
  /** For someone moving from the download-link app. */
  switching: string;
  /** The app file's way in, under the main action. */
  file: string;
  /** The download-link app's card. */
  cardTitle: string;
  cardMessage: string;
}>;

export function playWords(storeUrl: string | null): PlayWords {
  // A recording the downloaded app hasn't sent yet goes with it when it is
  // uninstalled: check Calls first (orchestrator, 24 Oct 2026).
  const switching =
    "Switching from the downloaded app? Open Calls there and make sure every recording shows as sent, then uninstall it; your calls and leads stay in your account.";
  return storeUrl
    ? {
        url: storeUrl,
        where: "On Google Play",
        get: "Get it on Google Play",
        switching,
        file: "No Play Store on this phone? Download the app",
        cardTitle: "Sales X-Ray is now on Google Play",
        cardMessage:
          "Switch now. Before you uninstall, open Calls and make sure every recording shows as sent. Then uninstall this app and install it from Google Play; your calls and leads stay in your account.",
      }
    : {
        url: PLAY_OPT_IN_URL,
        where: "Google Play, or the app file",
        get: "Testers: install from Google Play",
        switching,
        file: "No Play invite? Download the app",
        cardTitle: "Sales X-Ray is moving to Google Play",
        cardMessage:
          "Got a Play testing invite? Switch now. Before you uninstall, open Calls and make sure every recording shows as sent. Then uninstall this app and install from Play; your calls and leads stay in your account. No invite yet? Keep using this app; we'll tell you when Play is open for everyone.",
      };
}

export const PLAY = playWords(PLAY_STORE_URL);

/**
 * Changes this phone holds that the server doesn't have yet, said before an
 * uninstall (which deletes them): orchestrator, 24 Oct 2026.
 */
export function unsentLine(count: number): string {
  return `${count === 1 ? "1 change" : `${count} changes`} not sent yet — open Sales X-Ray online first.`;
}
