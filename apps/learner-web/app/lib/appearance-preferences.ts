/** Shared device-local appearance state; deliberately has no UI dependencies. */
export const THEME_STORAGE_KEY = "ac-appearance-theme";
export const ACCENT_STORAGE_KEY = "ac-appearance-accent";
export const DENSITY_STORAGE_KEY = "ac-appearance-density";
export const MOTION_STORAGE_KEY = "ac-appearance-motion";

export type ThemePreference = "light" | "dark" | "system";
export type AccentPreference =
  | "cobalt"
  | "indigo"
  | "emerald"
  | "amber"
  | "slate";
export type DensityPreference = "comfortable" | "compact";
export type MotionPreference = "system" | "reduced" | "full";

export type EffectiveTheme = Exclude<ThemePreference, "system">;

type AppearancePreferenceKey = keyof AppearancePreferences;

const sessionAppearanceOverrides: Partial<AppearancePreferences> = {};

export interface AppearancePreferences {
  theme: ThemePreference;
  accent: AccentPreference;
  density: DensityPreference;
  motion: MotionPreference;
}

export function normalizeThemePreference(value: unknown): ThemePreference {
  return value === "light" || value === "dark" || value === "system"
    ? value
    : "light";
}

export function normalizeAccentPreference(value: unknown): AccentPreference {
  return value === "cobalt" ||
    value === "indigo" ||
    value === "emerald" ||
    value === "amber" ||
    value === "slate"
    ? value
    : "cobalt";
}

export function normalizeDensityPreference(value: unknown): DensityPreference {
  return value === "comfortable" || value === "compact" ? value : "comfortable";
}

export function normalizeMotionPreference(value: unknown): MotionPreference {
  return value === "system" || value === "reduced" || value === "full"
    ? value
    : "system";
}

export function resolveThemePreference(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): EffectiveTheme {
  return preference === "system"
    ? systemPrefersDark
      ? "dark"
      : "light"
    : preference;
}

export function resolveMotionPreference(
  preference: MotionPreference,
  systemPrefersReducedMotion: boolean,
): boolean {
  return preference === "reduced"
    ? true
    : preference === "full"
      ? false
      : systemPrefersReducedMotion;
}

function getLocalStorage(): Storage | null {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      return window.localStorage;
    }
  } catch {}
  try {
    if (typeof localStorage !== "undefined") {
      return localStorage;
    }
  } catch {}
  return null;
}

function readBootstrapAppearancePreferences(): Partial<AppearancePreferences> {
  if (typeof document === "undefined") {
    return {};
  }

  const dataset = document.documentElement.dataset;
  const bootstrap: Partial<AppearancePreferences> = {};

  if (
    dataset.themePreference === "light" ||
    dataset.themePreference === "dark" ||
    dataset.themePreference === "system"
  ) {
    bootstrap.theme = dataset.themePreference;
  } else if (dataset.theme === "light" || dataset.theme === "dark") {
    bootstrap.theme = dataset.theme;
  }

  if (
    dataset.accent === "cobalt" ||
    dataset.accent === "indigo" ||
    dataset.accent === "emerald" ||
    dataset.accent === "amber" ||
    dataset.accent === "slate"
  ) {
    bootstrap.accent = dataset.accent;
  }

  if (dataset.density === "comfortable" || dataset.density === "compact") {
    bootstrap.density = dataset.density;
  }

  if (
    dataset.motion === "system" ||
    dataset.motion === "reduced" ||
    dataset.motion === "full"
  ) {
    bootstrap.motion = dataset.motion;
  }

  return bootstrap;
}

export function readAppearancePreferences(
  fallback: Partial<AppearancePreferences> = {},
): AppearancePreferences {
  const defaults: AppearancePreferences = {
    theme: "light",
    accent: "cobalt",
    density: "comfortable",
    motion: "system",
    ...readBootstrapAppearancePreferences(),
    ...fallback,
  };

  const storage = getLocalStorage();

  const readStored = <T>(
    key: string,
    fallbackValue: T,
    normalize: (value: unknown) => T,
  ): T => {
    if (!storage) {
      return fallbackValue;
    }
    try {
      const stored = storage.getItem(key);
      return stored == null ? fallbackValue : normalize(stored);
    } catch {
      return fallbackValue;
    }
  };

  const read = {
    theme: readStored(
      THEME_STORAGE_KEY,
      defaults.theme,
      normalizeThemePreference,
    ),
    accent: readStored(
      ACCENT_STORAGE_KEY,
      defaults.accent,
      normalizeAccentPreference,
    ),
    density: readStored(
      DENSITY_STORAGE_KEY,
      defaults.density,
      normalizeDensityPreference,
    ),
    motion: readStored(
      MOTION_STORAGE_KEY,
      defaults.motion,
      normalizeMotionPreference,
    ),
  } satisfies AppearancePreferences;

  return {
    ...read,
    ...sessionAppearanceOverrides,
  };
}

export function readRuntimeAppearancePreferences(
  previousPreferences: AppearancePreferences | null,
): AppearancePreferences {
  return previousPreferences === null
    ? readAppearancePreferences()
    : readAppearancePreferences(previousPreferences);
}

export function applyAppearancePreferences(
  preferences: AppearancePreferences,
): void {
  let systemPrefersDark = false;
  try {
    systemPrefersDark = window.matchMedia(
      "(prefers-color-scheme: dark)",
    ).matches;
  } catch {
    // Deterministic fallback.
  }

  let systemPrefersReducedMotion = false;
  try {
    systemPrefersReducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
  } catch {
    // Deterministic fallback.
  }

  const effectiveTheme = resolveThemePreference(
    preferences.theme,
    systemPrefersDark,
  );
  const effectiveReducedMotion = resolveMotionPreference(
    preferences.motion,
    systemPrefersReducedMotion,
  );

  if (typeof document !== "undefined") {
    const root = document.documentElement;
    root.dataset.theme = effectiveTheme;
    root.dataset.themePreference = preferences.theme;
    root.dataset.accent = preferences.accent;
    root.dataset.density = preferences.density;
    root.dataset.motion = preferences.motion;
    root.dataset.reducedMotion = effectiveReducedMotion ? "true" : "false";
    root.style.colorScheme = effectiveTheme;
  }
}

export type SaveAppearanceResult =
  | { ok: true }
  | { ok: false; reason: "storage_unavailable" | "quota_exceeded" };

export function saveAppearancePreferences(
  preferences: Partial<AppearancePreferences>,
): SaveAppearanceResult {
  const current = readAppearancePreferences();
  const next: AppearancePreferences = {
    theme:
      preferences.theme !== undefined
        ? normalizeThemePreference(preferences.theme)
        : current.theme,
    accent:
      preferences.accent !== undefined
        ? normalizeAccentPreference(preferences.accent)
        : current.accent,
    density:
      preferences.density !== undefined
        ? normalizeDensityPreference(preferences.density)
        : current.density,
    motion:
      preferences.motion !== undefined
        ? normalizeMotionPreference(preferences.motion)
        : current.motion,
  };

  const changedKeys = (
    Object.keys(preferences) as AppearancePreferenceKey[]
  ).filter((key) => preferences[key] !== undefined);
  let storageOk = true;
  let reason: "storage_unavailable" | "quota_exceeded" = "storage_unavailable";

  const storage = getLocalStorage();
  if (!storage) {
    storageOk = false;
    reason = "storage_unavailable";
  } else {
    try {
      if (preferences.theme !== undefined) {
        storage.setItem(THEME_STORAGE_KEY, next.theme);
      }
      if (preferences.accent !== undefined) {
        storage.setItem(ACCENT_STORAGE_KEY, next.accent);
      }
      if (preferences.density !== undefined) {
        storage.setItem(DENSITY_STORAGE_KEY, next.density);
      }
      if (preferences.motion !== undefined) {
        storage.setItem(MOTION_STORAGE_KEY, next.motion);
      }
    } catch (err) {
      storageOk = false;
      const errorName =
        typeof err === "object" && err !== null && "name" in err
          ? String((err as { name: unknown }).name)
          : "";
      const errorCode =
        typeof err === "object" && err !== null && "code" in err
          ? Number((err as { code: unknown }).code)
          : 0;

      if (errorName === "QuotaExceededError" || errorCode === 22) {
        reason = "quota_exceeded";
      } else {
        reason = "storage_unavailable";
      }
    }
  }

  if (storageOk) {
    for (const key of changedKeys) {
      delete sessionAppearanceOverrides[key];
    }
  } else {
    Object.assign(sessionAppearanceOverrides, {
      ...(preferences.theme !== undefined ? { theme: next.theme } : {}),
      ...(preferences.accent !== undefined ? { accent: next.accent } : {}),
      ...(preferences.density !== undefined ? { density: next.density } : {}),
      ...(preferences.motion !== undefined ? { motion: next.motion } : {}),
    });
  }

  applyAppearancePreferences(next);

  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("ac-theme-change"));
    window.dispatchEvent(new Event("ac-appearance-change"));
  }

  return storageOk ? { ok: true } : { ok: false, reason };
}

export function subscribeToThemeChanges(
  media: Pick<MediaQueryList, "addEventListener" | "removeEventListener">,
  target: Pick<Window, "addEventListener" | "removeEventListener">,
  refresh: EventListener,
): () => void {
  media.addEventListener("change", refresh);
  target.addEventListener("storage", refresh);
  target.addEventListener("ac-theme-change", refresh);
  target.addEventListener("ac-appearance-change", refresh);
  return () => {
    media.removeEventListener("change", refresh);
    target.removeEventListener("storage", refresh);
    target.removeEventListener("ac-theme-change", refresh);
    target.removeEventListener("ac-appearance-change", refresh);
  };
}
