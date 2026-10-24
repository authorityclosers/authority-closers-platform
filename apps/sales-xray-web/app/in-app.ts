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
 * The phone's font size, inside the app (owner's OnePlus, 24 Oct 2026: text
 * grew without the icons at the default size, icons looked wrong at small).
 * The app pins the WebView's own text zoom at 100% and, from the build that
 * turns it on, passes Android's font scale as window.SXFontScale before any
 * page script. This page then draws everything (text, icons, spacing) at that
 * scale through the viewport: the page lays out on a narrower screen and is
 * drawn larger, so viewport units, fixed bars and positions stay consistent.
 * Clamped to 1.0-1.2: the WebView ignores a scale below 1 (tested on the Note
 * 8 Pro), and above 1.2 too little fits. Nothing else reads the scale.
 */
export const FONT_SCALE_MIN = 1;
export const FONT_SCALE_MAX = 1.2;
export const FONT_SCALE_ATTRIBUTE = "data-sx-font-scale";

function fontScaleScript(): string {
  return `var s=window.SXFontScale;if(typeof s==="number"&&isFinite(s)){var z=Math.round(Math.min(${FONT_SCALE_MAX},Math.max(${FONT_SCALE_MIN},s))*100)/100;document.documentElement.setAttribute(${JSON.stringify(FONT_SCALE_ATTRIBUTE)},String(z));if(z>1){var want="initial-scale="+z+", minimum-scale="+z+", maximum-scale="+z;var apply=function(){var m=document.querySelector('meta[name="viewport"]');if(!m)return false;var c=m.getAttribute("content")||"";if(c.indexOf(want)!==-1)return true;var keep=c.split(",").map(function(p){return p.trim()}).filter(function(p){return p&&!/^(width|initial-scale|minimum-scale|maximum-scale)=/.test(p)});keep.push(want);m.setAttribute("content",keep.join(", "));return true};if(!apply())document.addEventListener("DOMContentLoaded",apply,{once:true});new MutationObserver(function(){apply()}).observe(document.head||document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:["content"]})}}`;
}

/** Runs before the first paint, so app-only layout never shifts in. */
export function inAppInitScript(): string {
  return `(function(){try{if(${APP_TOKEN.toString()}.test(navigator.userAgent)||typeof window.SXPhone!=="undefined")document.documentElement.setAttribute(${JSON.stringify(IN_APP_ATTRIBUTE)},"");${fontScaleScript()}}catch(e){}})();`;
}
