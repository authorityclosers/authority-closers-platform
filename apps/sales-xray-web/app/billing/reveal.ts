/** Room left between what is revealed and the tab bar. */
const GAP_PX = 12;

/**
 * The top of whatever is pinned over the bottom of the screen (the phone tab
 * bar), or the screen's bottom when nothing is. Full-screen layers (a glass
 * backdrop, a scrim) are not bars and are skipped.
 */
function bottomBarTop(): number {
  const height = window.innerHeight;
  let top = height;
  const pinned = document.elementsFromPoint?.(
    window.innerWidth / 2,
    height - 40,
  );
  for (const element of pinned ?? []) {
    if (getComputedStyle(element).position !== "fixed") continue;
    const rect = element.getBoundingClientRect();
    if (rect.height < height / 2) top = Math.min(top, rect.top);
  }
  return top;
}

/**
 * Scrolls the page just enough that `element` sits above the phone tab bar.
 * scrollIntoView with a scroll margin left the Cancel renewal confirm under
 * the bar on Android Chrome (QA, 23 Oct 2026), so this measures the bar.
 */
export function revealAboveTabBar(element: Element | null): void {
  if (!element) return;
  const over =
    element.getBoundingClientRect().bottom - (bottomBarTop() - GAP_PX);
  if (over > 0) window.scrollBy({ top: over, behavior: "smooth" });
}
