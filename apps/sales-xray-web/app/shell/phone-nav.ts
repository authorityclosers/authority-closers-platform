import { CALLS_PATH, NEW_ANALYSIS_PATH } from "../analysis-routes";

/**
 * The five phone tabs of the new map (owner, 22 Oct 2026: "Approved: the new
 * map"): Home, Leads, + (Add), Chats and Calls. More is gone: your avatar
 * opens You, with your settings and the organisation's. A page that is not a
 * tab lights the place it belongs to (Prospects under Leads, Coaching under
 * Calls, the organisation's pages under Home); Settings lights none.
 */
export type PhoneTab = "dashboard" | "leads" | "chats" | "calls" | "new";

export type ShellActive =
  | "dashboard"
  | "leads"
  | "chats"
  | "analyse"
  | "calls"
  | "account"
  | "organisation"
  | "prospects"
  | "coaching"
  | "insights"
  | "review";

const FROM_ACTIVE: Record<ShellActive, PhoneTab | null> = {
  dashboard: "dashboard",
  leads: "leads",
  chats: "chats",
  analyse: "new",
  calls: "calls",
  prospects: "leads",
  coaching: "calls",
  account: null,
  organisation: "dashboard",
  insights: "dashboard",
  review: null,
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
    if (under(pathname, "/leads")) return "leads";
    if (under(pathname, "/chats")) return "chats";
    if (under(pathname, CALLS_PATH) || under(pathname, "/calls"))
      return "calls";
    if (under(pathname, "/prospects")) return "leads";
    if (under(pathname, "/coaching")) return "calls";
    if (under(pathname, "/organisation")) return "dashboard";
    if (
      ["/account", "/settings", "/plans"].some((root) => under(pathname, root))
    )
      return null;
    // A call analysed here keeps /analysis/new in the router while the
    // address bar already shows the call: once the page says it is that
    // call's report, it is under Calls (owner, 19 Oct).
    if (under(pathname, NEW_ANALYSIS_PATH))
      return active === "calls" ? "calls" : "new";
  }
  return active ? FROM_ACTIVE[active] : null;
}

/**
 * The lit rail icon follows the address too, so a page that forgets to say
 * where it is (it defaults to New analysis) still lights its own icon.
 */
export function shellActiveFor(
  pathname: string | null,
  active: ShellActive,
): ShellActive {
  if (pathname) {
    if (under(pathname, "/dashboard")) return "dashboard";
    if (under(pathname, "/leads")) return "leads";
    if (under(pathname, "/chats")) return "chats";
    if (under(pathname, CALLS_PATH) || under(pathname, "/calls"))
      return "calls";
    if (under(pathname, NEW_ANALYSIS_PATH))
      return active === "calls" ? "calls" : "analyse";
    if (under(pathname, "/prospects")) return "prospects";
    if (under(pathname, "/coaching")) return "coaching";
    if (under(pathname, "/organisation/insights")) return "insights";
    if (under(pathname, "/organisation")) return "organisation";
    if (under(pathname, "/account")) return "account";
    // Settings and its sections light the account entry, loading or not.
    if (under(pathname, "/settings")) return "account";
  }
  return active;
}
