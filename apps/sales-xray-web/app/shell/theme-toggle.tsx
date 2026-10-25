"use client";

import { Moon, Sun } from "lucide-react";

import type { ThemePreference } from "../lightbox/theme";
import { useTheme } from "../lightbox/theme-provider";
import styles from "./theme-toggle.module.css";

// Light and Dark only (owner, 26 Oct 2026); an old System reads as Light.
const NEXT: Record<ThemePreference, ThemePreference> = {
  system: "dark",
  light: "dark",
  dark: "light",
};

const LABEL: Record<ThemePreference, string> = {
  system: "Light",
  light: "Light",
  dark: "Dark",
};

/**
 * Top-bar theme switch: Light and Dark. It renders only where the theme
 * control is enabled, so production stays light until the theme matrix passes.
 */
export function ThemeToggle() {
  const theme = useTheme();
  if (!theme) return null;
  const Icon = theme.preference === "dark" ? Moon : Sun;
  const next = NEXT[theme.preference];
  const label = `Theme: ${LABEL[theme.preference]}. Switch to ${LABEL[next]}.`;
  return (
    <button
      type="button"
      className={styles.toggle}
      onClick={() => theme.setPreference(next)}
      aria-label={label}
      title={label}
    >
      <Icon
        key={theme.preference}
        className={styles.icon}
        size={18}
        aria-hidden="true"
      />
    </button>
  );
}
