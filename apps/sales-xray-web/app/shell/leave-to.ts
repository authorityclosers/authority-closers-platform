import { leavingOverlay } from "../ui/back-close";

/**
 * Goes to another page from inside an overlay, as the command bar's results do:
 * the overlay closing must not pop the history entry the new page is about to
 * cover (simulation lab, 3 Nov 2026: a lead found in the search from Home closed
 * the search and stayed on Home).
 */
export function leaveTo(
  href: string,
  router: { push: (href: string) => void } | null | undefined,
) {
  leavingOverlay();
  if (router) router.push(href);
  else window.location.assign(href);
}
