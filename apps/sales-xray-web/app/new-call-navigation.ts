import {
  callIdFromPath,
  isAppHome,
  NEW_ANALYSIS_PATH,
} from "./analysis-routes";

/** Navigation intent only; never deletes or cancels the saved submission. */
export function newCallHref(homeHref = "/") {
  const url = new URL(homeHref, "https://sales-xray.invalid");
  url.searchParams.delete("call");
  url.searchParams.delete("new");
  if (isAppHome(url)) return NEW_ANALYSIS_PATH;
  url.searchParams.set("new", "1");
  return `${url.pathname}${url.search}${url.hash}`;
}

export function isNewCallRequested() {
  return (
    window.location.pathname === NEW_ANALYSIS_PATH ||
    new URLSearchParams(window.location.search).get("new") === "1"
  );
}

/**
 * True when a link to New analysis lands on the page already showing a call:
 * its own new-call address, or the address its call took (a new analysis
 * takes its call's address). The router does not remount that page, so it
 * must start the new call itself (3 Nov 2026 regression, U3). The phone app's
 * own web copy ends paths with "/".
 */
export function linksToThisNewCall(
  href: string,
  shownCallId: string | null = null,
) {
  const here = new URL(window.location.href);
  const to = new URL(href, here);
  const path = (url: URL) => url.pathname.replace(/\/+$/, "") || "/";
  if (to.origin !== here.origin) return false;
  if (path(to) !== NEW_ANALYSIS_PATH && to.searchParams.get("new") !== "1")
    return false;
  return (
    (path(to) === path(here) && to.search === here.search) ||
    (shownCallId !== null && callIdFromPath(here.pathname) === shownCallId)
  );
}

export function setNewCallRequested(requested: boolean) {
  const url = new URL(window.location.href);
  if (requested) {
    url.searchParams.delete("call");
    if (callIdFromPath(url.pathname) !== null) url.pathname = NEW_ANALYSIS_PATH;
    else if (url.pathname !== NEW_ANALYSIS_PATH)
      url.searchParams.set("new", "1");
  } else {
    url.searchParams.delete("new");
  }
  window.history.replaceState(window.history.state, "", url);
}
