"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

export const THEME_STORAGE_KEY = "ac-appearance-theme";

export type ThemePreference = "light" | "dark" | "system";
type EffectiveTheme = Exclude<ThemePreference, "system">;

export function normalizeThemePreference(value: unknown): ThemePreference {
  return value === "light" || value === "dark" || value === "system"
    ? value
    : "light";
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

function applyPreference(preference: ThemePreference) {
  const effective = resolveThemePreference(
    preference,
    window.matchMedia("(prefers-color-scheme: dark)").matches,
  );
  document.documentElement.dataset.theme = effective;
  document.documentElement.dataset.themePreference = preference;
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
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const refresh = () => applyPreference(readPreference());
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

  useEffect(() => {
    const refresh = () => setPreference(readPreference());
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
    applyPreference(nextPreference);
    window.dispatchEvent(new Event("ac-theme-change"));
  }

  return (
    <div className="theme-control" role="group" aria-label="Appearance theme">
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
  );
}
