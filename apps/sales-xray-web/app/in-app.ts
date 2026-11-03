/**
 * Inside the Sales Xray phone app the website's own chrome (policy links,
 * marketing, the Sign in tab) is noise: the app is the product. The app says
 * it is the app with a user-agent token, "SalesXrayApp/<version>", on every
 * request from the first page load (agreed with the Android shell, 17 Oct
 * 2026). Builds from before that token still carry the phone bridge object.
 */
export const IN_APP_ATTRIBUTE = "data-sx-app";
const APP_TOKEN = /\bSalesXrayApp\/\d/;

export function isAppUserAgent(userAgent: string | null | undefined): boolean {
  return APP_TOKEN.test(userAgent ?? "");
}

/**
 * The phone's font size, inside the app (native-feel spec, 3 Nov 2026). The
 * app pins the WebView's own text zoom at 100%, so the page applies Android's
 * font scale itself, as the root font size: every type token is in rem, so
 * text grows as sp does while the layout, in px, stays as dp does. The scale
 * is window.SXFontScale where a build passes it before the page, else the one
 * the app's status last reported (kept here, so the first paint is already at
 * size). Clamped to 1-2: Android goes to 200%, and below 1 text would drop
 * under Material's 11.
 */
export const FONT_SCALE_MIN = 1;
export const FONT_SCALE_MAX = 2;
export const FONT_SCALE_ATTRIBUTE = "data-sx-font-scale";
const FONT_SCALE_KEY = "sx.font-scale";

function fontScaleScript(): string {
  return `var s=window.SXFontScale;if(typeof s!=="number"){try{s=parseFloat(localStorage.getItem(${JSON.stringify(FONT_SCALE_KEY)})||"")}catch(e){}}if(typeof s==="number"&&isFinite(s)){var z=Math.round(Math.min(${FONT_SCALE_MAX},Math.max(${FONT_SCALE_MIN},s))*100)/100;document.documentElement.setAttribute(${JSON.stringify(FONT_SCALE_ATTRIBUTE)},String(z));document.documentElement.style.fontSize=z*100+"%"}`;
}

/** Follows the font scale the app's status reports, now and from the next start. */
export function followFontScale(scale: unknown): void {
  if (typeof scale !== "number" || !Number.isFinite(scale)) return;
  const z =
    Math.round(
      Math.min(FONT_SCALE_MAX, Math.max(FONT_SCALE_MIN, scale)) * 100,
    ) / 100;
  try {
    localStorage.setItem(FONT_SCALE_KEY, String(z));
  } catch {}
  const root = document.documentElement;
  root.setAttribute(FONT_SCALE_ATTRIBUTE, String(z));
  root.style.fontSize = `${z * 100}%`;
}

/** Runs before the first paint, so app-only layout never shifts in. */
export function inAppInitScript(): string {
  return `(function(){try{if(${APP_TOKEN.toString()}.test(navigator.userAgent)||typeof window.SXPhone!=="undefined")document.documentElement.setAttribute(${JSON.stringify(IN_APP_ATTRIBUTE)},"");${fontScaleScript()}}catch(e){}})();`;
}
