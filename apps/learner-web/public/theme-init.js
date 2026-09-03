(() => {
  const themeStorageKey = "ac-appearance-theme";
  const accentStorageKey = "ac-appearance-accent";
  const densityStorageKey = "ac-appearance-density";
  const motionStorageKey = "ac-appearance-motion";

  let preference = "light";
  let storedAccent = null;
  let storedDensity = null;
  let storedMotion = null;

  try {
    const stored = window.localStorage.getItem(themeStorageKey);
    if (stored === "light" || stored === "dark" || stored === "system") {
      preference = stored;
    }
  } catch {
    // Light remains the deterministic product default when storage is blocked.
  }

  try {
    const a = window.localStorage.getItem(accentStorageKey);
    if (
      a === "cobalt" ||
      a === "indigo" ||
      a === "emerald" ||
      a === "amber" ||
      a === "slate"
    ) {
      storedAccent = a;
    }
  } catch {
    // Deterministic fallback when storage is blocked.
  }

  try {
    const d = window.localStorage.getItem(densityStorageKey);
    if (d === "comfortable" || d === "compact") {
      storedDensity = d;
    }
  } catch {
    // Deterministic fallback when storage is blocked.
  }

  try {
    const m = window.localStorage.getItem(motionStorageKey);
    if (m === "system" || m === "reduced" || m === "full") {
      storedMotion = m;
    }
  } catch {
    // Deterministic fallback when storage is blocked.
  }

  let systemPrefersDark = false;
  try {
    systemPrefersDark = window.matchMedia(
      "(prefers-color-scheme: dark)",
    ).matches;
  } catch {
    // Light is the deterministic fallback for an unavailable media query.
  }

  let systemPrefersReducedMotion = false;
  try {
    systemPrefersReducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
  } catch {
    // Deterministic fallback for an unavailable media query.
  }

  const effective =
    preference === "system"
      ? systemPrefersDark
        ? "dark"
        : "light"
      : preference;

  const effectiveReducedMotion =
    storedMotion === "reduced"
      ? true
      : storedMotion === "full"
        ? false
        : systemPrefersReducedMotion;

  const root = document.documentElement;
  root.dataset.theme = effective;
  root.dataset.themePreference = preference;
  if (storedAccent) {
    root.dataset.accent = storedAccent;
  }
  if (storedDensity) {
    root.dataset.density = storedDensity;
  }
  if (storedMotion) {
    root.dataset.motion = storedMotion;
    if (effectiveReducedMotion) {
      root.dataset.reducedMotion = "true";
    }
  }
  root.style.colorScheme = effective;
})();
