import { useSyncExternalStore } from "react";

const noSubscription = () => () => {};

/** This page's origin in the browser; empty on the server, so both draw the same. */
export function useOrigin(): string {
  return useSyncExternalStore(
    noSubscription,
    () => window.location.origin,
    () => "",
  );
}
