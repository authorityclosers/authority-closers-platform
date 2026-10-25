/**
 * Focus rings for keyboards only (owner, 25 Oct 2026: "on each click there is
 * a border issue which is persistent, it looks ugly, like a glowing green
 * border around all buttons"). Browsers keep a ring after a click whenever
 * focus moves by script (a sheet closing hands focus back to the button that
 * opened it), so the page says how it was last used: a tap or click sets
 * data-sx-input="pointer" and the rings fade (styles.css); a key such as Tab
 * sets "keyboard" and every ring shows again.
 */

const ATTRIBUTE = "data-sx-input";
const QUIET_KEYS = new Set(["Shift", "Control", "Alt", "Meta", "CapsLock"]);

export function installFocusMode(doc: Document = document): () => void {
  const root = doc.documentElement;
  const pointer = () => root.setAttribute(ATTRIBUTE, "pointer");
  const keyboard = (event: KeyboardEvent) => {
    if (QUIET_KEYS.has(event.key) || event.metaKey || event.ctrlKey) return;
    root.setAttribute(ATTRIBUTE, "keyboard");
  };
  if (!root.hasAttribute(ATTRIBUTE)) pointer();
  doc.addEventListener("pointerdown", pointer, true);
  doc.addEventListener("keydown", keyboard, true);
  return () => {
    doc.removeEventListener("pointerdown", pointer, true);
    doc.removeEventListener("keydown", keyboard, true);
  };
}
