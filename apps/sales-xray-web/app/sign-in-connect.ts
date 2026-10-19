/**
 * The full-page trip to Google, Apple or Facebook when connecting one in
 * Settings (never a pop-up). Its own module so tests can stand in for it.
 */
export function goToProvider(url: string): void {
  window.location.assign(new URL(url, window.location.origin).href);
}
