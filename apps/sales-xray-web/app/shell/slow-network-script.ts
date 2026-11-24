/**
 * The page's own part of "Slow network. Still loading…" (slow-network.tsx),
 * kept out of the client component so the root layout, on the server, can
 * put it in the page as a script that runs before the app arrives.
 */
export const SLOW_AFTER_MS = 5_000;
export const SLOW_ATTRIBUTE = "data-sx-slow";
/** Set once the app runs: from then on the component decides, not the page's script. */
export const LIVE_ATTRIBUTE = "data-sx-live";

/** Runs before the first paint: still no app after 5 s shows the pill. */
export function slowNetworkScript(): string {
  return `(function(){var d=document.documentElement;setTimeout(function(){try{if(!d.hasAttribute(${JSON.stringify(LIVE_ATTRIBUTE)})&&navigator.onLine!==false)d.setAttribute(${JSON.stringify(SLOW_ATTRIBUTE)},"")}catch(e){}},${SLOW_AFTER_MS})})();`;
}
