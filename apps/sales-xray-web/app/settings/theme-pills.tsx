"use client";

import { Moon, Sun } from "lucide-react";

import { useTheme } from "../lightbox/theme-provider";
import styles from "./settings-hub.module.css";

/**
 * Light | Dark as v1.90 Home's pills, the picked one solid green; also the
 * Profile's Look row (sx-redesign, 21 Nov 2026: no dropdown). Null where the
 * theme control isn't released.
 */
export function ThemePills({ labelledBy }: { labelledBy?: string }) {
  const theme = useTheme();
  if (!theme) return null;
  const current = theme.preference === "dark" ? "dark" : "light";
  const options = [
    { id: "light", label: "Light", icon: Sun },
    { id: "dark", label: "Dark", icon: Moon },
  ] as const;
  return (
    <span
      className={styles.pills}
      role="radiogroup"
      aria-labelledby={labelledBy}
      aria-label={labelledBy ? undefined : "Look"}
    >
      {options.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          role="radio"
          aria-checked={current === id}
          className={styles.pill}
          onClick={() => theme.setPreference(id)}
        >
          <Icon size={15} aria-hidden="true" />
          {label}
        </button>
      ))}
    </span>
  );
}
