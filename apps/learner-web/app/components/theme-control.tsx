"use client";

import {
  Check,
  CircleAlert,
  Eye,
  Maximize2,
  Minimize2,
  Monitor,
  Moon,
  Palette,
  RotateCcw,
  Sliders,
  Sparkles,
  Sun,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import styles from "./settings-clarity.module.css";

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

export interface AppearancePreferences {
  theme: ThemePreference;
  accent: AccentPreference;
  density: DensityPreference;
  motion: MotionPreference;
}

export interface NamedAppearancePreset {
  id: string;
  name: string;
  tagline: string;
  theme: ThemePreference;
  accent: AccentPreference;
  density: DensityPreference;
  motion: MotionPreference;
}

export const NAMED_PRESETS: NamedAppearancePreset[] = [
  {
    id: "authority-cobalt",
    name: "Authority Cobalt",
    tagline: "Classic Command Center balance",
    theme: "light",
    accent: "cobalt",
    density: "comfortable",
    motion: "system",
  },
  {
    id: "deep-focus",
    name: "Deep Focus",
    tagline: "High-contrast dark indigo and compact rhythm",
    theme: "dark",
    accent: "indigo",
    density: "compact",
    motion: "reduced",
  },
  {
    id: "signal-emerald",
    name: "Signal Emerald",
    tagline: "High-signal closer emerald with standard rhythm",
    theme: "light",
    accent: "emerald",
    density: "comfortable",
    motion: "system",
  },
  {
    id: "executive-amber",
    name: "Executive Amber",
    tagline: "Warm authority tones and relaxed reading space",
    theme: "light",
    accent: "amber",
    density: "comfortable",
    motion: "system",
  },
  {
    id: "precision-slate",
    name: "Precision Slate",
    tagline: "Dark monochrome slate with compact efficiency",
    theme: "dark",
    accent: "slate",
    density: "compact",
    motion: "system",
  },
];

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

export function readAppearancePreferences(
  fallback: Partial<AppearancePreferences> = {},
): AppearancePreferences {
  const defaults: AppearancePreferences = {
    theme: "light",
    accent: "cobalt",
    density: "comfortable",
    motion: "system",
    ...fallback,
  };

  const storage = getLocalStorage();

  let theme = defaults.theme;
  try {
    theme = normalizeThemePreference(storage?.getItem(THEME_STORAGE_KEY));
  } catch {
    const current =
      typeof document !== "undefined"
        ? document.documentElement.dataset.themePreference
        : undefined;
    theme = normalizeThemePreference(current ?? defaults.theme);
  }

  let accent = defaults.accent;
  try {
    accent = normalizeAccentPreference(storage?.getItem(ACCENT_STORAGE_KEY));
  } catch {
    const current =
      typeof document !== "undefined"
        ? document.documentElement.dataset.accent
        : undefined;
    accent = normalizeAccentPreference(current ?? defaults.accent);
  }

  let density = defaults.density;
  try {
    density = normalizeDensityPreference(storage?.getItem(DENSITY_STORAGE_KEY));
  } catch {
    const current =
      typeof document !== "undefined"
        ? document.documentElement.dataset.density
        : undefined;
    density = normalizeDensityPreference(current ?? defaults.density);
  }

  let motion = defaults.motion;
  try {
    motion = normalizeMotionPreference(storage?.getItem(MOTION_STORAGE_KEY));
  } catch {
    const current =
      typeof document !== "undefined"
        ? document.documentElement.dataset.motion
        : undefined;
    motion = normalizeMotionPreference(current ?? defaults.motion);
  }

  return { theme, accent, density, motion };
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

export function ThemeRuntime() {
  const fallbackPreferencesRef = useRef<AppearancePreferences>({
    theme: "light",
    accent: "cobalt",
    density: "comfortable",
    motion: "system",
  });

  useEffect(() => {
    let colorSchemeMedia: Pick<
      MediaQueryList,
      "addEventListener" | "removeEventListener"
    > = {
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    };
    let reducedMotionMedia: Pick<
      MediaQueryList,
      "addEventListener" | "removeEventListener"
    > = {
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    };

    try {
      colorSchemeMedia = window.matchMedia("(prefers-color-scheme: dark)");
    } catch {
      // Deterministic fallback.
    }

    try {
      reducedMotionMedia = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      );
    } catch {
      // Deterministic fallback.
    }

    const refresh = () => {
      const preferences = readAppearancePreferences(
        fallbackPreferencesRef.current,
      );
      fallbackPreferencesRef.current = preferences;
      applyAppearancePreferences(preferences);
    };

    refresh();
    const cleanupTheme = subscribeToThemeChanges(
      colorSchemeMedia,
      window,
      refresh,
    );
    reducedMotionMedia.addEventListener("change", refresh);

    return () => {
      cleanupTheme();
      reducedMotionMedia.removeEventListener("change", refresh);
    };
  }, []);

  return null;
}

const themeOptions = [
  { value: "light" as const, label: "Light", icon: Sun },
  { value: "dark" as const, label: "Dark", icon: Moon },
  { value: "system" as const, label: "System", icon: Monitor },
];

const accentOptions = [
  {
    value: "cobalt" as const,
    label: "Cobalt",
    color: "#3157d8",
    description: "Authority blue",
  },
  {
    value: "indigo" as const,
    label: "Indigo",
    color: "#4f46e5",
    description: "Deep focus",
  },
  {
    value: "emerald" as const,
    label: "Emerald",
    color: "#059669",
    description: "High signal",
  },
  {
    value: "amber" as const,
    label: "Amber",
    color: "#d97706",
    description: "Executive warmth",
  },
  {
    value: "slate" as const,
    label: "Slate",
    color: "#334155",
    description: "Monochrome precision",
  },
];

const densityOptions = [
  {
    value: "comfortable" as const,
    label: "Comfortable",
    icon: Maximize2,
    detail: "Standard spacing with relaxed reading rhythm",
  },
  {
    value: "compact" as const,
    label: "Compact",
    icon: Minimize2,
    detail: "Higher information density with 44px touch targets",
  },
];

const motionOptions = [
  {
    value: "system" as const,
    label: "System",
    icon: Monitor,
    detail: "Follow device settings",
  },
  {
    value: "reduced" as const,
    label: "Reduced motion",
    icon: Eye,
    detail: "Instant transitions without motion sickness",
  },
  {
    value: "full" as const,
    label: "Full motion",
    icon: Zap,
    detail: "Smooth microinteractions and transitions",
  },
];

export function ThemeControl({
  advanced = false,
}: {
  advanced?: boolean;
} = {}) {
  const [preferences, setPreferences] = useState<AppearancePreferences>({
    theme: "light",
    accent: "cobalt",
    density: "comfortable",
    motion: "system",
  });
  const [feedback, setFeedback] = useState<string | null>(null);
  const [storageError, setStorageError] = useState<
    "storage_unavailable" | "quota_exceeded" | null
  >(null);
  const feedbackTimerRef = useRef<number | undefined>(undefined);

  function announce(message: string): void {
    setFeedback(message);
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("ac-toast", { detail: message }));
    }
    if (feedbackTimerRef.current !== undefined) {
      window.clearTimeout(feedbackTimerRef.current);
    }
    feedbackTimerRef.current = window.setTimeout(() => {
      setFeedback(null);
      feedbackTimerRef.current = undefined;
    }, 3800);
  }

  useEffect(() => {
    return () => {
      if (feedbackTimerRef.current !== undefined) {
        window.clearTimeout(feedbackTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const refresh = () => {
      const next = readAppearancePreferences();
      setPreferences(next);
    };
    refresh();
    window.addEventListener("storage", refresh);
    window.addEventListener("ac-theme-change", refresh);
    window.addEventListener("ac-appearance-change", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("ac-theme-change", refresh);
      window.removeEventListener("ac-appearance-change", refresh);
    };
  }, []);

  function handleUpdate(
    partial: Partial<AppearancePreferences>,
    label: string,
  ) {
    const result = saveAppearancePreferences(partial);
    const updated = { ...preferences, ...partial };
    setPreferences(updated);

    if (result.ok) {
      setStorageError(null);
      announce(`Appearance updated: ${label} applied.`);
    } else {
      setStorageError(result.reason);
      announce(
        result.reason === "quota_exceeded"
          ? "Storage quota reached. Applied for this session only."
          : "Storage unavailable. Applied for this session only.",
      );
    }
  }

  function handleApplyPreset(preset: NamedAppearancePreset) {
    const result = saveAppearancePreferences({
      theme: preset.theme,
      accent: preset.accent,
      density: preset.density,
      motion: preset.motion,
    });
    setPreferences({
      theme: preset.theme,
      accent: preset.accent,
      density: preset.density,
      motion: preset.motion,
    });

    if (result.ok) {
      setStorageError(null);
      announce(`Preset applied: ${preset.name}.`);
    } else {
      setStorageError(result.reason);
      announce(
        "Preset applied for current session; device storage unavailable.",
      );
    }
  }

  function handleReset() {
    const defaults: AppearancePreferences = {
      theme: "light",
      accent: "cobalt",
      density: "comfortable",
      motion: "system",
    };
    const result = saveAppearancePreferences(defaults);
    setPreferences(defaults);

    if (result.ok) {
      setStorageError(null);
      announce("Appearance reset to Authority Closers defaults.");
    } else {
      setStorageError(result.reason);
      announce("Appearance reset for this session; storage unavailable.");
    }
  }

  if (!advanced) {
    return (
      <div className="theme-control-stack">
        <div
          className={`theme-control ${styles.themeControl}`}
          role="group"
          aria-label="Appearance theme"
        >
          {themeOptions.map((option) => {
            const Icon = option.icon;
            const isSelected = preferences.theme === option.value;
            return (
              <button
                className="theme-control__option"
                type="button"
                key={option.value}
                aria-pressed={isSelected}
                onClick={() =>
                  handleUpdate({ theme: option.value }, `${option.label} theme`)
                }
              >
                <Icon size={18} aria-hidden="true" />
                <span>{option.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.appearanceStack}>
      {/* Live Region for Screen Readers */}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className={styles.appearanceStatusAnnouncer}
      >
        {feedback}
      </div>

      {/* Fail-closed Storage Recovery Warning */}
      {storageError ? (
        <div
          className={styles.appearanceStorageRecovery}
          role="alert"
          aria-live="assertive"
        >
          <CircleAlert size={18} aria-hidden="true" />
          <div className={styles.appearanceStorageRecoveryCopy}>
            <strong>Storage recovery active</strong>
            <p>
              {storageError === "quota_exceeded"
                ? "Browser storage quota is full. Your appearance preferences are active in this tab, but cannot be saved permanently."
                : "Local storage is unavailable or blocked on this device. Your appearance choices are active in this tab, but cannot be saved permanently."}
            </p>
          </div>
        </div>
      ) : null}

      {/* 1. Quick Presets */}
      <div
        className={styles.appearanceGroup}
        role="group"
        aria-labelledby="appearance-presets-label"
      >
        <div className={styles.appearanceGroupHeader}>
          <Sparkles size={17} aria-hidden="true" />
          <h3
            id="appearance-presets-label"
            className={styles.appearanceGroupTitle}
          >
            Named presets
          </h3>
        </div>
        <p className={styles.appearanceGroupDetail}>
          Complete appearance combinations tuned for focus, contrast, and
          rhythm.
        </p>
        <div className={styles.presetCardsGrid}>
          {NAMED_PRESETS.map((preset) => {
            const isActive =
              preferences.theme === preset.theme &&
              preferences.accent === preset.accent &&
              preferences.density === preset.density &&
              preferences.motion === preset.motion;
            return (
              <button
                type="button"
                key={preset.id}
                className={`${styles.presetCard}${isActive ? ` ${styles.presetCardActive}` : ""}`}
                onClick={() => handleApplyPreset(preset)}
                aria-pressed={isActive}
              >
                <div className={styles.presetCardHeader}>
                  <div className={styles.presetCardTitleRow}>
                    <span
                      className={styles.presetAccentDot}
                      style={{
                        backgroundColor:
                          preset.accent === "cobalt"
                            ? "#3157d8"
                            : preset.accent === "indigo"
                              ? "#4f46e5"
                              : preset.accent === "emerald"
                                ? "#059669"
                                : preset.accent === "amber"
                                  ? "#d97706"
                                  : "#334155",
                      }}
                      aria-hidden="true"
                    />
                    <strong className={styles.presetName}>{preset.name}</strong>
                  </div>
                  {isActive ? (
                    <span
                      className={styles.presetActiveBadge}
                      aria-label="Active preset"
                    >
                      <Check size={14} aria-hidden="true" />
                    </span>
                  ) : null}
                </div>
                <span className={styles.presetTagline}>{preset.tagline}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* 2. Color Mode (Theme) */}
      <div
        className={styles.appearanceGroup}
        role="group"
        aria-labelledby="appearance-theme-label"
      >
        <div className={styles.appearanceGroupHeader}>
          <Sun size={17} aria-hidden="true" />
          <h3
            id="appearance-theme-label"
            className={styles.appearanceGroupTitle}
          >
            Theme mode
          </h3>
        </div>
        <div
          className={`theme-control ${styles.themeControl}`}
          role="group"
          aria-label="Appearance theme"
        >
          {themeOptions.map((option) => {
            const Icon = option.icon;
            const isSelected = preferences.theme === option.value;
            return (
              <button
                className="theme-control__option"
                type="button"
                key={option.value}
                aria-pressed={isSelected}
                onClick={() =>
                  handleUpdate({ theme: option.value }, `${option.label} theme`)
                }
              >
                <Icon size={18} aria-hidden="true" />
                <span>{option.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* 3. Named Accent Palette */}
      <div
        className={styles.appearanceGroup}
        role="group"
        aria-labelledby="appearance-accent-label"
      >
        <div className={styles.appearanceGroupHeader}>
          <Palette size={17} aria-hidden="true" />
          <h3
            id="appearance-accent-label"
            className={styles.appearanceGroupTitle}
          >
            Accent color
          </h3>
        </div>
        <p className={styles.appearanceGroupDetail}>
          Sets the primary brand highlight, button tint, link color, and player
          accent.
        </p>
        <div
          className={styles.accentGrid}
          role="group"
          aria-label="Accent palette"
        >
          {accentOptions.map((accent) => {
            const isSelected = preferences.accent === accent.value;
            return (
              <button
                type="button"
                key={accent.value}
                className={`${styles.accentButton}${isSelected ? ` ${styles.accentButtonActive}` : ""}`}
                aria-pressed={isSelected}
                onClick={() =>
                  handleUpdate(
                    { accent: accent.value },
                    `${accent.label} accent`,
                  )
                }
              >
                <span
                  className={styles.accentSwatchPreview}
                  style={{ backgroundColor: accent.color }}
                  aria-hidden="true"
                />
                <span className={styles.accentCopy}>
                  <strong>{accent.label}</strong>
                  <small>{accent.description}</small>
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* 4. Display Density */}
      <div
        className={styles.appearanceGroup}
        role="group"
        aria-labelledby="appearance-density-label"
      >
        <div className={styles.appearanceGroupHeader}>
          <Sliders size={17} aria-hidden="true" />
          <h3
            id="appearance-density-label"
            className={styles.appearanceGroupTitle}
          >
            Display density
          </h3>
        </div>
        <div
          className={styles.densityGrid}
          role="group"
          aria-label="Display density"
        >
          {densityOptions.map((density) => {
            const Icon = density.icon;
            const isSelected = preferences.density === density.value;
            return (
              <button
                type="button"
                key={density.value}
                className={`${styles.densityButton}${isSelected ? ` ${styles.densityButtonActive}` : ""}`}
                aria-pressed={isSelected}
                onClick={() =>
                  handleUpdate(
                    { density: density.value },
                    `${density.label} density`,
                  )
                }
              >
                <div className={styles.densityButtonHeader}>
                  <Icon size={18} aria-hidden="true" />
                  <strong>{density.label}</strong>
                </div>
                <span className={styles.densityDetail}>{density.detail}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* 5. Motion Preferences */}
      <div
        className={styles.appearanceGroup}
        role="group"
        aria-labelledby="appearance-motion-label"
      >
        <div className={styles.appearanceGroupHeader}>
          <Zap size={17} aria-hidden="true" />
          <h3
            id="appearance-motion-label"
            className={styles.appearanceGroupTitle}
          >
            Motion &amp; microinteractions
          </h3>
        </div>
        <p className={styles.appearanceGroupDetail}>
          Controls animations, player timelines, drawers, and transition speed.
        </p>
        <div
          className={styles.motionGrid}
          role="group"
          aria-label="Motion preference"
        >
          {motionOptions.map((motion) => {
            const Icon = motion.icon;
            const isSelected = preferences.motion === motion.value;
            return (
              <button
                type="button"
                key={motion.value}
                className={`${styles.motionButton}${isSelected ? ` ${styles.motionButtonActive}` : ""}`}
                aria-pressed={isSelected}
                onClick={() =>
                  handleUpdate(
                    { motion: motion.value },
                    `${motion.label} motion`,
                  )
                }
              >
                <div className={styles.motionButtonHeader}>
                  <Icon size={18} aria-hidden="true" />
                  <strong>{motion.label}</strong>
                </div>
                <span className={styles.motionDetail}>{motion.detail}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* 6. Reset to Defaults */}
      <div className={styles.appearanceFooter}>
        <button
          type="button"
          className={styles.resetButton}
          onClick={handleReset}
        >
          <RotateCcw size={16} aria-hidden="true" />
          <span>Reset to default appearance</span>
        </button>
      </div>
    </div>
  );
}

export function AppearanceControl() {
  return <ThemeControl advanced={true} />;
}
