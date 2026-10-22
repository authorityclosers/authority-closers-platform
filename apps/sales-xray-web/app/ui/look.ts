/**
 * The look's pre-paint helpers (Liquid Glass, owner's pick, 22 Oct 2026).
 *
 * Every build: low-memory phones are marked `data-sx-glass="lite"` before
 * the first paint. A large blur under the floating bars drops frames while
 * scrolling there, so their glass gets a light blur and a thicker tint
 * (ui/sx-tokens.css). On a Redmi Note 8 Pro (6 GB) the full glass scrolled
 * as smoothly as the old solid bars.
 *
 * Dev server only: `?theme=light|dark|system` sets the saved theme, so a
 * test phone can show both themes without changing its own settings. It runs
 * before the theme's own pre-paint script, which then reads it.
 */

import { THEME_STORAGE_KEY } from "../lightbox/theme";

/** Runs before the first paint, from app/layout.tsx, in every build. */
export function glassInitScript(): string {
  return `(function(){try{var n=navigator,m=n.deviceMemory,c=n.hardwareConcurrency;if((m&&m<=4)||(c&&c<=4))document.documentElement.setAttribute("data-sx-glass","lite")}catch(e){}})();`;
}

/** Runs before the theme script, from app/layout.tsx, on the dev server only. */
export function themePreviewScript(): string {
  const theme = JSON.stringify(THEME_STORAGE_KEY);
  return `(function(){try{var t=new URLSearchParams(location.search).get("theme");if(t==="light"||t==="dark")localStorage.setItem(${theme},t);else if(t==="system")localStorage.removeItem(${theme})}catch(e){}})();`;
}

/** Whether this server may take `?theme=`: `next dev` only. */
export function themePreviewEnabled(env: { NODE_ENV?: string }): boolean {
  return env.NODE_ENV === "development";
}
