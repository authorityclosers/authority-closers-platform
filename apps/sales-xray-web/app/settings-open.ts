/**
 * Settings float over the current screen. The URL hash (#settings or
 * #settings/<section>) says the dialog is open, so Back closes it and a copied
 * link reopens it.
 */
export const SETTINGS_HASH_PREFIX = "settings/";
export const SETTINGS_CHANGE_EVENT = "sales-xray:settings-change";

// True while the open dialog owns the newest history entry.
let pushedEntry = false;

export function settingsHashOpen(hash: string): boolean {
  return hash === "#settings" || hash.startsWith(`#${SETTINGS_HASH_PREFIX}`);
}

/** A plain primary click opens settings in place; modified clicks navigate. */
export function opensInPlace(event: {
  defaultPrevented: boolean;
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}): boolean {
  return !(
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  );
}

function withoutHash() {
  return `${window.location.pathname}${window.location.search}`;
}

export function openSettings(section?: string) {
  const hash = section ? `#${SETTINGS_HASH_PREFIX}${section}` : "#settings";
  if (settingsHashOpen(window.location.hash)) {
    window.history.replaceState(window.history.state, "", withoutHash() + hash);
  } else {
    window.history.pushState(window.history.state, "", withoutHash() + hash);
    pushedEntry = true;
  }
  window.dispatchEvent(new Event(SETTINGS_CHANGE_EVENT));
}

/**
 * "back" pops the entry the dialog pushed; "replace" is for a link inside the
 * dialog, which pushes its own route right after.
 */
export function closeSettings(mode: "back" | "replace" = "back") {
  if (!settingsHashOpen(window.location.hash)) return;
  if (mode === "back" && pushedEntry) {
    pushedEntry = false;
    window.history.back();
    return;
  }
  pushedEntry = false;
  window.history.replaceState(window.history.state, "", withoutHash());
  window.dispatchEvent(new Event(SETTINGS_CHANGE_EVENT));
}

/** Browser Back already left the dialog's entry. */
export function forgetSettingsEntry() {
  if (!settingsHashOpen(window.location.hash)) pushedEntry = false;
}
