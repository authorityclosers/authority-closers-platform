import { CALLS_PATH, NEW_ANALYSIS_PATH } from "../analysis-routes";

export type PhoneTab =
  | "dashboard"
  | "calls"
  | "new"
  | "prospects"
  | "coaching"
  | "more";

type ShellActive =
  | "dashboard"
  | "analyse"
  | "calls"
  | "account"
  | "organisation"
  | "prospects"
  | "coaching";

const FROM_ACTIVE: Record<ShellActive, PhoneTab> = {
  dashboard: "dashboard",
  analyse: "new",
  calls: "calls",
  prospects: "prospects",
  coaching: "coaching",
  account: "more",
  organisation: "more",
};

const under = (pathname: string, root: string) =>
  pathname === root || pathname.startsWith(`${root}/`);

/**
 * The lit phone tab follows the address, so it never flips while a page or
 * its loading screen settles. Addresses that can mean several things (the
 * app home, preview hosts) fall back to what the page says it is.
 */
export function phoneTabFor(
  pathname: string | null,
  active: ShellActive | undefined,
): PhoneTab | null {
  if (pathname) {
    if (under(pathname, "/dashboard")) return "dashboard";
    if (under(pathname, CALLS_PATH) || under(pathname, "/calls"))
      return "calls";
    if (under(pathname, NEW_ANALYSIS_PATH)) return "new";
    if (under(pathname, "/prospects")) return "prospects";
    if (under(pathname, "/coaching")) return "coaching";
    if (
      ["/organisation", "/account", "/plans"].some((root) =>
        under(pathname, root),
      )
    )
      return "more";
  }
  return active ? FROM_ACTIVE[active] : null;
}
