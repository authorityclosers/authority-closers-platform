"use client";

import { Monitor, Moon, Sun } from "lucide-react";

import type { ThemePreference } from "../lightbox/theme";
import { useTheme } from "../lightbox/theme-provider";
import styles from "./theme-toggle.module.css";

const NEXT: Record<ThemePreference, ThemePreference> = {
  system: "light",
  light: "dark",
  dark: "system",
};

const LABEL: Record<ThemePreference, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

/**
 * Top-bar theme switch: System, Light, Dark. It renders only where the theme
 * control is enabled, so production stays light until the theme matrix passes.
 */
export function ThemeToggle() {
  const theme = useTheme();
  if (!theme) return null;
  const Icon =
    theme.preference === "dark"
      ? Moon
      : theme.preference === "light"
        ? Sun
        : Monitor;
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
