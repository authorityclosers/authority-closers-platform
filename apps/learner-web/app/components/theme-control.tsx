"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import styles from "./settings-clarity.module.css";

export const THEME_STORAGE_KEY = "ac-appearance-theme";
export const THEME_PALETTE_STORAGE_KEY = "ac-appearance-palette";

export type ThemePreference = "light" | "dark" | "system";
export type ThemePalette = "cobalt" | "meadow" | "ember";
type EffectiveTheme = Exclude<ThemePreference, "system">;

export const DEFAULT_THEME_PALETTE: ThemePalette = "cobalt";

export function normalizeThemePreference(value: unknown): ThemePreference {
  return value === "light" || value === "dark" || value === "system"
    ? value
    : "light";
}

export function normalizeThemePalette(value: unknown): ThemePalette {
  return value === "cobalt" || value === "meadow" || value === "ember"
    ? value
    : DEFAULT_THEME_PALETTE;
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

function readPreference(): ThemePreference {
  try {
    return normalizeThemePreference(
      window.localStorage.getItem(THEME_STORAGE_KEY),
    );
  } catch {
    return "light";
  }
}

function readPalette(): ThemePalette {
  try {
    return normalizeThemePalette(
      window.localStorage.getItem(THEME_PALETTE_STORAGE_KEY),
    );
  } catch {
    return DEFAULT_THEME_PALETTE;
  }
}

function applyPreference(
  preference: ThemePreference,
  palette: ThemePalette = readPalette(),
) {
  let systemPrefersDark = false;
  try {
    systemPrefersDark = window.matchMedia(
      "(prefers-color-scheme: dark)",
    ).matches;
  } catch {
    // Light remains the deterministic fallback when media queries are blocked.
  }
  const effective = resolveThemePreference(preference, systemPrefersDark);
  document.documentElement.dataset.theme = effective;
  document.documentElement.dataset.themePreference = preference;
  document.documentElement.dataset.palette = palette;
  document.documentElement.style.colorScheme = effective;
}

export function subscribeToThemeChanges(
  media: Pick<MediaQueryList, "addEventListener" | "removeEventListener">,
  target: Pick<Window, "addEventListener" | "removeEventListener">,
  refresh: EventListener,
): () => void {
  media.addEventListener("change", refresh);
  target.addEventListener("storage", refresh);
  target.addEventListener("ac-theme-change", refresh);
  return () => {
    media.removeEventListener("change", refresh);
    target.removeEventListener("storage", refresh);
    target.removeEventListener("ac-theme-change", refresh);
  };
}

export function ThemeRuntime() {
  useEffect(() => {
    let media: Pick<
      MediaQueryList,
      "addEventListener" | "removeEventListener"
    > = {
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    };
    try {
      media = window.matchMedia("(prefers-color-scheme: dark)");
    } catch {
      // The light preference remains usable when media queries are blocked.
    }
    const refresh = () => applyPreference(readPreference(), readPalette());
    refresh();
    return subscribeToThemeChanges(media, window, refresh);
  }, []);
  return null;
}

const options = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
] as const;

export function ThemeControl() {
  const [preference, setPreference] = useState<ThemePreference>("light");
  const [palette, setPalette] = useState<ThemePalette>(DEFAULT_THEME_PALETTE);

  useEffect(() => {
    const refresh = () => {
      setPreference(readPreference());
      setPalette(readPalette());
    };
    refresh();
    window.addEventListener("storage", refresh);
    window.addEventListener("ac-theme-change", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("ac-theme-change", refresh);
    };
  }, []);

  function choose(nextPreference: ThemePreference) {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, nextPreference);
    } catch {
      // Appearance remains usable for the current page when storage is blocked.
    }
    setPreference(nextPreference);
    applyPreference(nextPreference, palette);
    window.dispatchEvent(new Event("ac-theme-change"));
  }

  function choosePalette(nextPalette: ThemePalette) {
    try {
      window.localStorage.setItem(THEME_PALETTE_STORAGE_KEY, nextPalette);
    } catch {
      // Palette remains usable for the current page when storage is blocked.
    }
    setPalette(nextPalette);
    applyPreference(preference, nextPalette);
    window.dispatchEvent(new Event("ac-theme-change"));
  }

  return (
    <div className="theme-control-stack">
      <div
        className={`theme-control ${styles.themeControl}`}
        role="group"
        aria-label="Appearance theme"
      >
        {options.map((option) => {
          const Icon = option.icon;
          return (
            <button
              className="theme-control__option"
              type="button"
              key={option.value}
              aria-pressed={preference === option.value}
              onClick={() => choose(option.value)}
            >
              <Icon size={18} aria-hidden="true" />
              <span>{option.label}</span>
            </button>
          );
        })}
      </div>
      <div
        className="theme-palette-control"
        role="group"
        aria-label="Accent palette"
      >
        <div className="theme-palette-control__heading">
          <span>Accent palette</span>
          <small>Stays on this device</small>
        </div>
        <div className="theme-palette-control__options">
          {(
            [
              ["cobalt", "Cobalt", "Blue clarity"],
              ["meadow", "Meadow", "Calm green"],
              ["ember", "Ember", "Warm focus"],
            ] as const
          ).map(([value, label, description]) => (
            <button
              className="theme-palette-control__option"
              type="button"
              key={value}
              aria-pressed={palette === value}
              onClick={() => choosePalette(value)}
            >
              <span
                className={`theme-palette-swatch theme-palette-swatch--${value}`}
                aria-hidden="true"
              />
              <span>
                <strong>{label}</strong>
                <small>{description}</small>
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
