import { useSyncExternalStore } from "react";

/** Whether a media query matches now, following it as the window changes. */
export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (change) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", change);
      return () => list.removeEventListener("change", change);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

const PANEL_KEY = "sx.chats.lead-panel";

/** The lead beside the chat: open or closed, as this person last left it. */
export function readPanelChoice(): boolean | null {
  try {
    const value = localStorage.getItem(PANEL_KEY);
    return value === "open" ? true : value === "closed" ? false : null;
  } catch {
    return null;
  }
}

export function savePanelChoice(open: boolean): void {
  try {
    localStorage.setItem(PANEL_KEY, open ? "open" : "closed");
  } catch {
    /* storage off: it simply opens the default way next time */
  }
}
