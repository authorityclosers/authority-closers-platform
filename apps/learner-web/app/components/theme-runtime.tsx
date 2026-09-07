"use client";

import { useEffect, useRef } from "react";

import {
  applyAppearancePreferences,
  readRuntimeAppearancePreferences,
  subscribeToThemeChanges,
  type AppearancePreferences,
} from "../lib/appearance-preferences";

export function ThemeRuntime() {
  const fallbackPreferencesRef = useRef<AppearancePreferences | null>(null);

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
      const preferences = readRuntimeAppearancePreferences(
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
