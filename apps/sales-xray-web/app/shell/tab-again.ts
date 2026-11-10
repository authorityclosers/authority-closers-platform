import { useEffect, useRef } from "react";

/**
 * A tab tapped while its place is already on screen: the place's page hears
 * it and goes back to its start, as the Leads tab on a lead's page goes back
 * to the list (Redmi QA N1, 10 Nov 2026: the tab took ?lead= off the address
 * and the lead stayed open over the list).
 */
export const TAB_AGAIN_EVENT = "sx:tab-again";

export function tabAgain(tab: string) {
  window.dispatchEvent(
    new CustomEvent<string>(TAB_AGAIN_EVENT, { detail: tab }),
  );
}

/** Calls `onAgain` when `tab` is tapped again. */
export function useTabAgain(tab: string, onAgain: () => void) {
  const latest = useRef(onAgain);
  useEffect(() => {
    latest.current = onAgain;
  });
  useEffect(() => {
    const heard = (event: Event) => {
      if ((event as CustomEvent<string>).detail === tab) latest.current();
    };
    window.addEventListener(TAB_AGAIN_EVENT, heard);
    return () => window.removeEventListener(TAB_AGAIN_EVENT, heard);
  }, [tab]);
}
