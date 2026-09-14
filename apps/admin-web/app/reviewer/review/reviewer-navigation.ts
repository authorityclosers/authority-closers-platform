export const REVIEWER_NAVIGATION_CONFIRMATION =
  "You have unsaved reviewer feedback. Leave this review and discard your draft?";

const EVENT = "ac:reviewer-navigation-request";
let activeCleanup: (() => void) | null = null;

export function requestReviewerNavigation(navigate: () => void): boolean {
  if (typeof window === "undefined") {
    navigate();
    return true;
  }
  const event = new CustomEvent(EVENT, { cancelable: true });
  if (!window.dispatchEvent(event)) return false;
  navigate();
  return true;
}

export function registerReviewerNavigationGuard(dirty: boolean): () => void {
  if (!dirty || typeof window === "undefined" || typeof document === "undefined") return () => undefined;
  activeCleanup?.();
  let accepted = false;
  let resetTimer: ReturnType<typeof setTimeout> | null = null;
  const confirmLeave = () => {
    if (accepted) return true;
    const result = window.confirm(REVIEWER_NAVIGATION_CONFIRMATION);
    if (result) {
      accepted = true;
      resetTimer = setTimeout(() => { accepted = false; resetTimer = null; }, 0);
    }
    return result;
  };
  const onClick = (event: MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const target = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!(target instanceof HTMLAnchorElement) || target.target === "_blank" || target.origin !== window.location.origin) return;
    if (target.href === window.location.href || confirmLeave()) return;
    event.preventDefault();
    event.stopPropagation();
  };
  const onPopState = () => {
    if (confirmLeave()) return;
    window.history.pushState(null, "", window.location.href);
  };
  const onBeforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
  const onImperative = (raw: Event) => {
    if (confirmLeave()) return;
    raw.preventDefault();
    raw.stopImmediatePropagation();
  };
  document.addEventListener("click", onClick, true);
  window.addEventListener("popstate", onPopState, true);
  window.addEventListener("beforeunload", onBeforeUnload);
  window.addEventListener(EVENT, onImperative, true);
  const cleanup = () => {
    document.removeEventListener("click", onClick, true);
    window.removeEventListener("popstate", onPopState, true);
    window.removeEventListener("beforeunload", onBeforeUnload);
    window.removeEventListener(EVENT, onImperative, true);
    if (resetTimer !== null) clearTimeout(resetTimer);
    if (activeCleanup === cleanup) activeCleanup = null;
  };
  activeCleanup = cleanup;
  return cleanup;
}
