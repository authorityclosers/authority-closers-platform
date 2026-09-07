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

import {
  readAppearancePreferences,
  saveAppearancePreferences,
  type AccentPreference,
  type AppearancePreferences,
  type DensityPreference,
  type MotionPreference,
  type ThemePreference,
} from "../lib/appearance-preferences";

// Keep existing consumers on the same shared preference store during extraction.
export {
  ACCENT_STORAGE_KEY,
  DENSITY_STORAGE_KEY,
  MOTION_STORAGE_KEY,
  THEME_STORAGE_KEY,
  applyAppearancePreferences,
  normalizeAccentPreference,
  normalizeDensityPreference,
  normalizeMotionPreference,
  normalizeThemePreference,
  readAppearancePreferences,
  readRuntimeAppearancePreferences,
  resolveMotionPreference,
  resolveThemePreference,
  saveAppearancePreferences,
  subscribeToThemeChanges,
  type AccentPreference,
  type AppearancePreferences,
  type DensityPreference,
  type EffectiveTheme,
  type MotionPreference,
  type SaveAppearanceResult,
  type ThemePreference,
} from "../lib/appearance-preferences";
export { ThemeRuntime } from "./theme-runtime";

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
    color: "#047857",
    description: "High signal",
  },
  {
    value: "amber" as const,
    label: "Amber",
    color: "#b45309",
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

function AppearanceChoice<T extends string>({
  label,
  detail,
  value,
  options,
  onChange,
}: {
  label: string;
  detail: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <label className={styles.preferenceRow}>
      <span>
        <strong>{label}</strong>
        <small>{detail}</small>
      </span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => {
          const option = options.find(
            (item) => item.value === event.target.value,
          );
          if (option) onChange(option.value);
        }}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function ThemeControl({
  advanced = false,
  compact = false,
}: {
  advanced?: boolean;
  compact?: boolean;
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

  if (compact) {
    const activePreset = NAMED_PRESETS.find(
      (preset) =>
        preset.theme === preferences.theme &&
        preset.accent === preferences.accent &&
        preset.density === preferences.density &&
        preset.motion === preferences.motion,
    );
    return (
      <div className={styles.compactAppearance}>
        {storageError ? (
          <div className={styles.compactStorageError} role="alert">
            <CircleAlert size={18} aria-hidden="true" />
            <p>
              {storageError === "quota_exceeded"
                ? "This browser’s storage is full."
                : "This browser isn’t allowing preferences to be saved."}{" "}
              Your choices apply for this session only.
            </p>
          </div>
        ) : null}
        <AppearanceChoice
          label="Theme"
          detail="Choose light, dark, or follow your device."
          value={preferences.theme}
          options={themeOptions}
          onChange={(theme) => handleUpdate({ theme }, `${theme} theme`)}
        />
        <AppearanceChoice
          label="Accent color"
          detail="A personal touch for links and controls."
          value={preferences.accent}
          options={accentOptions}
          onChange={(accent) => handleUpdate({ accent }, `${accent} accent`)}
        />
        <AppearanceChoice
          label="Display density"
          detail="Choose how much breathing room you prefer."
          value={preferences.density}
          options={densityOptions}
          onChange={(density) =>
            handleUpdate({ density }, `${density} density`)
          }
        />
        <AppearanceChoice
          label="Motion"
          detail="Follow your device or reduce animations."
          value={preferences.motion}
          options={motionOptions.map((option) => ({
            ...option,
            label:
              option.value === "reduced"
                ? "Reduced"
                : option.value === "full"
                  ? "Full"
                  : "System",
          }))}
          onChange={(motion) => handleUpdate({ motion }, `${motion} motion`)}
        />
        <details className={styles.presetDisclosure}>
          <summary>
            Coordinated looks <span>{activePreset?.name ?? "Custom"}</span>
          </summary>
          <AppearanceChoice
            label="Appearance preset"
            detail="Apply a matching theme, accent, spacing, and motion."
            value={activePreset?.id ?? "custom"}
            options={[
              ...(activePreset ? [] : [{ value: "custom", label: "Custom" }]),
              ...NAMED_PRESETS.map((preset) => ({
                value: preset.id,
                label: preset.name,
              })),
            ]}
            onChange={(id) => {
              const preset = NAMED_PRESETS.find((item) => item.id === id);
              if (preset) handleApplyPreset(preset);
            }}
          />
        </details>
        <div className={styles.compactAppearanceFooter}>
          <button
            className={styles.resetButton}
            type="button"
            onClick={handleReset}
          >
            <RotateCcw size={16} aria-hidden="true" /> Reset appearance
          </button>
          <p
            className={styles.savedFeedback}
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            {feedback ?? "Changes apply instantly."}
          </p>
        </div>
      </div>
    );
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
                                ? "#047857"
                                : preset.accent === "amber"
                                  ? "#b45309"
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

      <div className={styles.appearanceGrid}>
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
                    handleUpdate(
                      { theme: option.value },
                      `${option.label} theme`,
                    )
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
            Sets the primary brand highlight, button tint, link color, and
            player accent.
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
            Controls animations, player timelines, drawers, and transition
            speed.
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

export function AppearanceControl({
  compact = false,
}: { compact?: boolean } = {}) {
  return <ThemeControl advanced={true} compact={compact} />;
}
