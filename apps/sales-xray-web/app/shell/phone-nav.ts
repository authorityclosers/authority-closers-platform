import { CALLS_PATH, NEW_ANALYSIS_PATH } from "../analysis-routes";

/**
 * The five phone tabs (Dipak's handoff, 31 Oct 2026): Home, Leads, Ask Dipak,
 * Reports and Growth; the + is in the top bar and your avatar opens You. A
 * page that is not a tab lights the place it belongs to: Chats and Prospects
 * under Leads, the calls and a call's report under Reports (it opens on All
 * Calls), Coaching under Growth, the organisation's pages under Home.
 * Settings lights none.
 */
export type PhoneTab = "dashboard" | "leads" | "reports" | "growth" | "new";

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
  chats: "leads",
  analyse: "new",
  calls: "reports",
  prospects: "leads",
  coaching: "growth",
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
    if (under(pathname, "/chats")) return "leads";
    if (under(pathname, CALLS_PATH) || under(pathname, "/calls"))
      return "reports";
    if (under(pathname, "/reports")) return "reports";
    if (under(pathname, "/growth")) return "growth";
    if (under(pathname, "/prospects")) return "leads";
    if (under(pathname, "/coaching")) return "growth";
    if (under(pathname, "/organisation")) return "dashboard";
    if (
      ["/account", "/settings", "/plans"].some((root) => under(pathname, root))
    )
      return null;
    // A call analysed here keeps /analysis/new in the router while the
    // address bar already shows the call: once the page says it is that
    // call's report, it is under Calls (owner, 19 Oct).
    if (under(pathname, NEW_ANALYSIS_PATH))
      return active === "calls" ? "reports" : "new";
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
    if (under(pathname, "/reports")) return "dashboard";
    if (under(pathname, "/account")) return "account";
    // Settings and its sections light the account entry, loading or not.
    if (under(pathname, "/settings")) return "account";
  }
  return active;
}
