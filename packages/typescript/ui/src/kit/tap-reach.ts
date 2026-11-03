/**
 * Touch screens: every control answers a 48 px tap (Android's touch target;
 * native-feel spec, 3 Nov 2026), whatever size it is drawn
 * (owner, 3 Nov 2026: fix it once in the kit, not screen by screen; the QA
 * robot's tap-target rows). A control drawn smaller gets data-reach, and
 * tokens/screen.css gives it an invisible layer out to 48 px, so nothing moves
 * or shows. Left as they are: links in running text, controls placed
 * absolutely, fixed or sticky, controls that draw their own ::after, and
 * controls with a ::before or parts placed against something outside them
 * (position: relative would move those).
 */

const CONTROLS =
  'a[href], button, [role="button"], [role="tab"], [role="radio"], [role="switch"], [role="checkbox"], [role="menuitem"]';
const TARGET = 48;

const drawn = (value: string) =>
  !!value && value !== "none" && value !== "normal";
const placed = (position: string) =>
  position === "absolute" || position === "fixed";

/** True when a control is drawn under 48 px and can take the reach with nothing moving. */
export function needsReach(control: Element): boolean {
  const box = control.getBoundingClientRect();
  if (box.width < 3 || box.height < 3) return false;
  if (box.width >= TARGET && box.height >= TARGET) return false;
  const style = getComputedStyle(control);
  // Unset values read "" in some engines (happy-dom): static and inline.
  const position = style.position || "static";
  if ((style.display || "inline") === "inline") return false;
  if (position !== "static" && position !== "relative") return false;
  if (drawn(getComputedStyle(control, "::after").content)) return false;
  if (position === "static") {
    const before = getComputedStyle(control, "::before");
    if (drawn(before.content) && placed(before.position)) return false;
    for (const part of control.querySelectorAll("*"))
      if (placed(getComputedStyle(part).position)) return false;
  }
  return true;
}

/**
 * Tags every control under `root` that needs the reach and returns how many.
 * A control is measured once, when it first shows; reads come before writes,
 * so the page lays out once.
 */
export function tagTapReach(
  root: ParentNode,
  seen: WeakSet<Element> = new WeakSet(),
): number {
  const tagged: Element[] = [];
  for (const control of root.querySelectorAll(CONTROLS)) {
    if (seen.has(control)) continue;
    const box = control.getBoundingClientRect();
    if (!box.width && !box.height) continue;
    seen.add(control);
    if (needsReach(control)) tagged.push(control);
  }
  for (const control of tagged) control.setAttribute("data-reach", "");
  return tagged.length;
}

/** Keeps tagging as screens and sheets open, at idle, on touch screens only. Returns the stop. */
export function watchTapReach(root: HTMLElement = document.body): () => void {
  if (
    typeof window === "undefined" ||
    !window.matchMedia?.("(pointer: coarse)").matches
  )
    return () => undefined;
  const seen = new WeakSet<Element>();
  let queued = false;
  const idle = (run: () => void) =>
    typeof window.requestIdleCallback === "function"
      ? window.requestIdleCallback(run, { timeout: 1500 })
      : window.setTimeout(run, 200);
  const schedule = () => {
    if (queued) return;
    queued = true;
    idle(() => {
      queued = false;
      tagTapReach(root, seen);
    });
  };
  const observer = new MutationObserver(schedule);
  observer.observe(root, { childList: true, subtree: true });
  schedule();
  return () => observer.disconnect();
}
