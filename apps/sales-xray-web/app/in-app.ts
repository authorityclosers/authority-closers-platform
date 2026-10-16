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

/** Runs before the first paint, so app-only layout never shifts in. */
export function inAppInitScript(): string {
  return `(function(){try{if(${APP_TOKEN.toString()}.test(navigator.userAgent)||typeof window.SXPhone!=="undefined")document.documentElement.setAttribute(${JSON.stringify(IN_APP_ATTRIBUTE)},"")}catch(e){}})();`;
}
