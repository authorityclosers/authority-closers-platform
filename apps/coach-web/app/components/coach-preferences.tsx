"use client";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

type Theme = "light" | "dark" | "system";
type Preferences = { theme: Theme; reduceMotion: boolean };
const defaults: Preferences = { theme: "system", reduceMotion: false };
const key = "cohorva.coach.appearance.v1";
const Context = createContext<
  (Preferences & { save: (next: Preferences) => void; message: string }) | null
>(null);
const subscribeHydration = () => () => {};
const clientSnapshot = () => true;
const serverSnapshot = () => false;

export function CoachPreferencesProvider({
  children,
}: {
  children: ReactNode;
}) {
  const hydrated = useSyncExternalStore(
    subscribeHydration,
    clientSnapshot,
    serverSnapshot,
  );
  const [chosen, setPreferences] = useState<Preferences | null>(null);
  const preferences = useMemo(
    () => chosen ?? (hydrated ? readPreferences() : defaults),
    [chosen, hydrated],
  );
  const [message, setMessage] = useState("");
  useEffect(() => {
    apply(preferences);
  }, [preferences]);
  function save(next: Preferences) {
    setPreferences(next);
    apply(next);
    try {
      localStorage.setItem(key, JSON.stringify(next));
      setMessage("Saved for this browser.");
    } catch {
      setMessage(
        "Applied for now. This browser couldn’t save your preference.",
      );
    }
  }
  return (
    <Context.Provider value={{ ...preferences, save, message }}>
      {children}
    </Context.Provider>
  );
}
function readPreferences(): Preferences {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
    if (
      saved &&
      typeof saved === "object" &&
      "theme" in saved &&
      ["light", "dark", "system"].includes(String(saved.theme)) &&
      "reduceMotion" in saved &&
      typeof saved.reduceMotion === "boolean"
    ) {
      const value = {
        theme: saved.theme as Theme,
        reduceMotion: saved.reduceMotion,
      };
      return value;
    }
  } catch {
    /* Browser storage is optional, not a sign-in prerequisite. */
  }
  return defaults;
}
function apply(value: Preferences) {
  document.documentElement.dataset.theme = value.theme;
  document.documentElement.dataset.reduceMotion = value.reduceMotion
    ? "true"
    : "false";
}
export function useCoachPreferences() {
  const value = useContext(Context);
  if (!value) throw new Error("Coach preferences require their provider");
  return value;
}
