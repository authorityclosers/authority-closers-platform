import {
  registerHistoryNavigationGuard,
  registerInternalNavigationGuard,
} from "../../lib/local-drafts";

export const REVIEW_NAVIGATION_CONFIRMATION =
  "You have unsaved review feedback. Leave this review and discard your draft?";

const IMPERATIVE_NAVIGATION_EVENT = "ac:review-navigation-request";

let activeCleanup: (() => void) | null = null;

/**
 * Run an imperative navigation through the active review guard, if one is
 * mounted. Link clicks and browser history are guarded by the shared helpers;
 * this bridge covers router.push and other command-palette actions that do not
 * produce a click event.
 */
export function requestReviewNavigation(navigate: () => void): boolean {
  if (typeof window === "undefined") {
    navigate();
    return true;
  }

  const event = new CustomEvent(IMPERATIVE_NAVIGATION_EVENT, {
    cancelable: true,
  });
  if (!window.dispatchEvent(event)) return false;
  navigate();
  return true;
}

/**
 * Guard internal links, browser back/forward, and imperative learner-shell
 * navigation while the assigned-review form has unsaved work.
 *
 * Draft contents remain in the mounted form. Cancellation prevents the
 * navigation, and no private review data is copied to browser storage.
 */
export function registerReviewNavigationGuard(active: boolean): () => void {
  if (
    !active ||
    typeof window === "undefined" ||
    typeof document === "undefined"
  ) {
    return () => undefined;
  }

  // A route transition can briefly overlap unmounting the previous page. Keep
  // one document-level guard so overlapping sessions cannot show two dialogs.
  activeCleanup?.();

  let acceptedForTask = false;
  let resetTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  const confirmNavigation = (): boolean => {
    if (acceptedForTask) return true;
    const accepted = window.confirm(REVIEW_NAVIGATION_CONFIRMATION);
    if (!accepted) return false;

    // A single accepted click may produce both a Next link callback and a
    // history/navigation event. Suppress only those same-task duplicates.
    acceptedForTask = true;
    resetTimer = setTimeout(() => {
      acceptedForTask = false;
      resetTimer = null;
    }, 0);
    return true;
  };

  const internalCleanup = registerInternalNavigationGuard(
    document,
    true,
    confirmNavigation,
  );
  const historyCleanup = registerHistoryNavigationGuard(
    window as unknown as Parameters<typeof registerHistoryNavigationGuard>[0],
    true,
    confirmNavigation,
  );
  const imperativeListener: EventListener = (rawEvent) => {
    const event = rawEvent as CustomEvent;
    if (!event.cancelable || confirmNavigation()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  window.addEventListener(
    IMPERATIVE_NAVIGATION_EVENT,
    imperativeListener,
    true,
  );

  const cleanup = () => {
    if (disposed) return;
    disposed = true;
    internalCleanup();
    historyCleanup();
    window.removeEventListener(
      IMPERATIVE_NAVIGATION_EVENT,
      imperativeListener,
      true,
    );
    if (resetTimer !== null) clearTimeout(resetTimer);
    if (activeCleanup === cleanup) activeCleanup = null;
  };
  activeCleanup = cleanup;
  return cleanup;
}
