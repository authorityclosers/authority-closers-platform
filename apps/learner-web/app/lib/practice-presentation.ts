import { normalizePracticeCompanion, type PracticeCompanionKind } from "@ac/ui";

// Presentation only: this preference cannot change content, scoring or rewards.
// Studio may pass an academy default later; no tenant authoring capability is implied.
const KEY = "ac-practice-companion";
const EVENT = "ac-practice-companion-change";
let fallback: PracticeCompanionKind | undefined;
const MOTION_KEY = "ac-practice-companion-motion";
let motionFallback: boolean | undefined;
export function readPracticeCompanionMotion(): boolean {
  if (typeof window === "undefined") return true;
  if (motionFallback !== undefined) return motionFallback;
  try {
    return window.localStorage.getItem(MOTION_KEY) !== "off";
  } catch {
    return true;
  }
}
export function savePracticeCompanionMotion(enabled: boolean) {
  try {
    window.localStorage.setItem(MOTION_KEY, enabled ? "on" : "off");
    motionFallback = undefined;
  } catch {
    motionFallback = enabled;
  }
  window.dispatchEvent(new Event(EVENT));
}
export function readPracticeCompanion(): PracticeCompanionKind | null {
  if (typeof window === "undefined") return null;
  if (fallback) return fallback;
  try {
    const value = window.localStorage.getItem(KEY);
    return value === null ? null : normalizePracticeCompanion(value);
  } catch {
    return null;
  }
}
export function savePracticeCompanion(value: PracticeCompanionKind) {
  const safe = normalizePracticeCompanion(value);
  try {
    window.localStorage.setItem(KEY, safe);
    fallback = undefined;
  } catch {
    fallback = safe;
  }
  window.dispatchEvent(new Event(EVENT));
}
export function subscribePracticeCompanion(changed: () => void) {
  const storage = (event: StorageEvent) => {
    if (event.key === KEY || event.key === MOTION_KEY || event.key === null)
      changed();
  };
  window.addEventListener(EVENT, changed);
  window.addEventListener("storage", storage);
  return () => {
    window.removeEventListener(EVENT, changed);
    window.removeEventListener("storage", storage);
  };
}
