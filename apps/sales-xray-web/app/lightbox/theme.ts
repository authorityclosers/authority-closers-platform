export const THEME_STORAGE_KEY = "sales-xray:theme";
export const THEME_CHANGE_EVENT = "sales-xray:theme-change";
export const DARK_SCHEME_QUERY = "(prefers-color-scheme: dark)";

export const themePreferences = ["system", "light", "dark"] as const;
export type ThemePreference = (typeof themePreferences)[number];
export type ResolvedTheme = "light" | "dark";

/**
 * Light and Dark only, Light by default (owner, 26 Oct 2026): a missing,
 * unknown or unreadable value, or an old stored "system", means Light.
 */
export function parseThemePreference(value: unknown): ThemePreference {
  return value === "dark" ? "dark" : "light";
}

/** The device's setting no longer decides: only Dark is dark. */
export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  void systemPrefersDark;
  return preference === "dark" ? "dark" : "light";
}

/**
 * The control and pre-paint script ship everywhere (owner, 24 Oct 2026: "dark
 * and light mode toggle is not visible, and the app does not follow the theme
 * of the mobile"): System by default, following the phone live. Setting
 * AC_SALES_XRAY_THEME_PREVIEW=0 holds a deployment light, as production was
 * until then (INTEGRATION_DECISIONS.md decision 12).
 */
export function themeControlEnabled(
  env: Readonly<{
    NODE_ENV?: string;
    AC_SALES_XRAY_THEME_PREVIEW?: string;
  }>,
): boolean {
  return env.AC_SALES_XRAY_THEME_PREVIEW !== "0";
}

// A write that storage refuses still applies for this document.
let unsavedPreference: ThemePreference | null = null;

export function readThemePreference(): ThemePreference {
  if (unsavedPreference) return unsavedPreference;
  try {
    return parseThemePreference(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "light";
  }
}

export function writeThemePreference(preference: ThemePreference) {
  try {
    if (preference !== "dark")
      window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, preference);
    unsavedPreference = null;
  } catch {
    unsavedPreference = preference;
  }
  window.dispatchEvent(new Event(THEME_CHANGE_EVENT));
}

export function systemPrefersDark(): boolean {
  try {
    return typeof window.matchMedia === "function"
      ? window.matchMedia(DARK_SCHEME_QUERY).matches
      : false;
  } catch {
    return false;
  }
}

export function applyTheme(
  root: HTMLElement,
  preference: ThemePreference,
  resolved: ResolvedTheme,
) {
  root.setAttribute("data-theme", resolved);
  root.setAttribute("data-theme-preference", preference);
  root.style.colorScheme = resolved;
}

/**
 * Runs before the first paint, from the top of <body>. It repeats the logic
 * above without imports and tolerates blocked storage and a missing matchMedia.
 */
export function themeInitScript(): string {
  const key = JSON.stringify(THEME_STORAGE_KEY);
  return `(function(){var d=document.documentElement,t="light";try{if(window.localStorage.getItem(${key})==="dark")t="dark"}catch(e){}d.setAttribute("data-theme",t);d.setAttribute("data-theme-preference",t);d.style.colorScheme=t})();`;
}
