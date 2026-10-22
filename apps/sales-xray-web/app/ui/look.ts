/**
 * The design-direction preview switch (22 Oct 2026): the owner compares two
 * looks on dev before one becomes the app's (ui/sx-looks.css). `?look=glass`
 * or `?look=pro` on any dev address puts that look on <html> for the rest of
 * the tab's visit; `?look=off` takes it away. Only the dev server renders
 * this script, so builds that ship never change their look.
 *
 * `?theme=light|dark|system` sets the saved theme the same way, so a phone
 * can be shown both themes without changing its own settings (it runs
 * before the theme's own pre-paint script, which then reads it).
 *
 * It also marks low-memory phones `data-sx-glass="lite"`, where a large
 * blur under the bars drops frames while scrolling: their glass gets a
 * smaller blur and a thicker tint.
 */

import { THEME_STORAGE_KEY } from "../lightbox/theme";

export const LOOKS = ["glass", "pro"] as const;
export type Look = (typeof LOOKS)[number];
export const LOOK_STORAGE_KEY = "sx-look";

/** Runs before the first paint, from app/layout.tsx, on the dev server only. */
export function lookInitScript(): string {
  const looks = JSON.stringify(LOOKS);
  const key = JSON.stringify(LOOK_STORAGE_KEY);
  const theme = JSON.stringify(THEME_STORAGE_KEY);
  return `(function(){try{var a=new URLSearchParams(location.search),t=a.get("theme");if(t==="light"||t==="dark")localStorage.setItem(${theme},t);else if(t==="system")localStorage.removeItem(${theme})}catch(e){}try{var d=document.documentElement,s=window.sessionStorage,k=${key},q=new URLSearchParams(location.search).get("look");if(q==="off")s.removeItem(k);else if(q&&${looks}.indexOf(q)>=0)s.setItem(k,q);var v=s.getItem(k);if(v&&${looks}.indexOf(v)>=0)d.setAttribute("data-sx-look",v);else d.removeAttribute("data-sx-look");var n=navigator,m=n.deviceMemory,c=n.hardwareConcurrency;if((m&&m<=4)||(c&&c<=4))d.setAttribute("data-sx-glass","lite")}catch(e){}})();`;
}

/** Whether this server may offer the preview: `next dev` only. */
export function lookPreviewEnabled(env: { NODE_ENV?: string }): boolean {
  return env.NODE_ENV === "development";
}
