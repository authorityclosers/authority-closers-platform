"use client";

import {
  createContext,
  useContext,
  useEffect,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { Moon, Sun } from "lucide-react";

import { setPhoneTheme } from "../leads/native-phone";
import { Segmented } from "./segmented";
import {
  DARK_SCHEME_QUERY,
  THEME_CHANGE_EVENT,
  THEME_STORAGE_KEY,
  applyTheme,
  readThemePreference,
  resolveTheme,
  systemPrefersDark,
  writeThemePreference,
  type ResolvedTheme,
  type ThemePreference,
} from "./theme";

type ThemeValue = Readonly<{
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
}>;

const ThemeContext = createContext<ThemeValue | null>(null);

function subscribePreference(notify: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === THEME_STORAGE_KEY) notify();
  };
  window.addEventListener(THEME_CHANGE_EVENT, notify);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(THEME_CHANGE_EVENT, notify);
    window.removeEventListener("storage", onStorage);
  };
}

function subscribeSystem(notify: () => void) {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(DARK_SCHEME_QUERY);
  query.addEventListener?.("change", notify);
  return () => query.removeEventListener?.("change", notify);
}

function EnabledThemeProvider({ children }: { children: ReactNode }) {
  const preference = useSyncExternalStore(
    subscribePreference,
    readThemePreference,
    () => "light" as const,
  );
  const prefersDark = useSyncExternalStore(
    subscribeSystem,
    systemPrefersDark,
    () => false,
  );
  const resolved = resolveTheme(preference, prefersDark);
  useEffect(() => {
    applyTheme(document.documentElement, preference, resolved);
  }, [preference, resolved]);
  // The phone app keeps the same pick for Android (once on load, then on change).
  useEffect(() => {
    void setPhoneTheme(preference);
  }, [preference]);
  return (
    <ThemeContext.Provider
      value={{ preference, resolved, setPreference: writeThemePreference }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

/**
 * Owns the standalone document theme. When the control is not released, it adds
 * no context and never touches the document, so everything stays light. The
 * learner-web embed never mounts it.
 */
export function ThemeProvider({
  controlEnabled,
  children,
}: {
  controlEnabled: boolean;
  children: ReactNode;
}) {
  return controlEnabled ? (
    <EnabledThemeProvider>{children}</EnabledThemeProvider>
  ) : (
    children
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}

// Sun and moon as the top bar's theme toggle draws them (shell/theme-toggle.tsx).
const themeOptions = [
  {
    value: "light",
    label: (
      <>
        <Sun aria-hidden="true" strokeWidth={1.8} />
        Light
      </>
    ),
    feature: "theme_light",
  },
  {
    value: "dark",
    label: (
      <>
        <Moon aria-hidden="true" strokeWidth={1.8} />
        Dark
      </>
    ),
    feature: "theme_dark",
  },
] as const;

export function ThemeControl({ className }: { className?: string }) {
  const theme = useTheme();
  if (!theme) return null;
  return (
    <Segmented
      className={className}
      legend="Theme"
      value={theme.preference}
      options={themeOptions}
      onChange={theme.setPreference}
      hint="Light is the default."
    />
  );
}
