export const THEME_STORAGE_KEY = "sales-xray:theme";
export const THEME_CHANGE_EVENT = "sales-xray:theme-change";
export const DARK_SCHEME_QUERY = "(prefers-color-scheme: dark)";

export const themePreferences = ["system", "light", "dark"] as const;
export type ThemePreference = (typeof themePreferences)[number];
export type ResolvedTheme = "light" | "dark";

/** A missing, unknown or unreadable value always means System. */
export function parseThemePreference(value: unknown): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}

export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference === "system") return systemPrefersDark ? "dark" : "light";
  return preference;
}

/**
 * The control and pre-paint script ship in development builds and in an explicit
 * theme preview. Production stays light until the P6 theme matrix passes
 * (INTEGRATION_DECISIONS.md decision 12).
 */
export function themeControlEnabled(
  env: Readonly<{
    NODE_ENV?: string;
    AC_SALES_XRAY_THEME_PREVIEW?: string;
  }>,
): boolean {
  return (
    env.NODE_ENV !== "production" || env.AC_SALES_XRAY_THEME_PREVIEW === "1"
  );
}

// A write that storage refuses still applies for this document.
let unsavedPreference: ThemePreference | null = null;

export function readThemePreference(): ThemePreference {
  if (unsavedPreference) return unsavedPreference;
  try {
    return parseThemePreference(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "system";
  }
}

export function writeThemePreference(preference: ThemePreference) {
  try {
    if (preference === "system")
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
  const query = JSON.stringify(DARK_SCHEME_QUERY);
  return `(function(){var d=document.documentElement,p="system",t="light";try{var s=window.localStorage.getItem(${key});if(s==="light"||s==="dark")p=s}catch(e){}if(p==="system"){try{if(typeof window.matchMedia==="function"&&window.matchMedia(${query}).matches)t="dark"}catch(e){}}else{t=p}d.setAttribute("data-theme",t);d.setAttribute("data-theme-preference",p);d.style.colorScheme=t})();`;
}
