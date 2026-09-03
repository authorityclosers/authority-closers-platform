(() => {
  const themeStorageKey = "ac-appearance-theme";
  const accentStorageKey = "ac-appearance-accent";
  const densityStorageKey = "ac-appearance-density";
  const motionStorageKey = "ac-appearance-motion";
  const root = document.documentElement;

  const isTheme = (value) =>
    value === "light" || value === "dark" || value === "system";
  const isEffectiveTheme = (value) => value === "light" || value === "dark";
  const isAccent = (value) =>
    value === "cobalt" ||
    value === "indigo" ||
    value === "emerald" ||
    value === "amber" ||
    value === "slate";
  const isDensity = (value) => value === "comfortable" || value === "compact";
  const isMotion = (value) =>
    value === "system" || value === "reduced" || value === "full";
  const bootstrapThemePreference = isTheme(root.dataset.themePreference)
    ? root.dataset.themePreference
    : isEffectiveTheme(root.dataset.theme)
      ? root.dataset.theme
      : null;
  const bootstrapEffectiveTheme = isEffectiveTheme(root.dataset.theme)
    ? root.dataset.theme
    : null;
  const bootstrapAccent = isAccent(root.dataset.accent)
    ? root.dataset.accent
    : null;
  const bootstrapDensity = isDensity(root.dataset.density)
    ? root.dataset.density
    : null;
  const bootstrapMotion = isMotion(root.dataset.motion)
    ? root.dataset.motion
    : null;
  const bootstrapReducedMotion =
    root.dataset.reducedMotion === "true"
      ? true
      : root.dataset.reducedMotion === "false"
        ? false
        : null;

  let preference = bootstrapThemePreference ?? "light";
  let storedAccent = bootstrapAccent;
  let storedDensity = bootstrapDensity;
  let storedMotion = bootstrapMotion;
  let themeStorageReadFailed = false;
  let motionStorageReadFailed = false;

  try {
    const stored = window.localStorage.getItem(themeStorageKey);
    if (isTheme(stored)) {
      preference = stored;
    }
  } catch {
    // Keep the server/bootstrap value when storage is blocked.
    themeStorageReadFailed = true;
  }

  try {
    const a = window.localStorage.getItem(accentStorageKey);
    if (isAccent(a)) {
      storedAccent = a;
    }
  } catch {
    // Keep the server/bootstrap value when storage is blocked.
  }

  try {
    const d = window.localStorage.getItem(densityStorageKey);
    if (isDensity(d)) {
      storedDensity = d;
    }
  } catch {
    // Keep the server/bootstrap value when storage is blocked.
  }

  try {
    const m = window.localStorage.getItem(motionStorageKey);
    if (isMotion(m)) {
      storedMotion = m;
    }
  } catch {
    // Keep the server/bootstrap value when storage is blocked.
    motionStorageReadFailed = true;
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
    themeStorageReadFailed && bootstrapEffectiveTheme
      ? bootstrapEffectiveTheme
      : preference === "system"
        ? systemPrefersDark
          ? "dark"
          : "light"
        : preference;

  const effectiveReducedMotion =
    motionStorageReadFailed && bootstrapReducedMotion !== null
      ? bootstrapReducedMotion
      : storedMotion === "reduced"
        ? true
        : storedMotion === "full"
          ? false
          : systemPrefersReducedMotion;

  root.dataset.theme = effective;
  root.dataset.themePreference =
    themeStorageReadFailed && bootstrapThemePreference
      ? bootstrapThemePreference
      : preference;
  if (storedAccent) {
    root.dataset.accent = storedAccent;
  }
  if (storedDensity) {
    root.dataset.density = storedDensity;
  }
  if (storedMotion) {
    root.dataset.motion = storedMotion;
  }
  if (effectiveReducedMotion || bootstrapReducedMotion !== null) {
    root.dataset.reducedMotion = effectiveReducedMotion ? "true" : "false";
  }
  root.style.colorScheme = effective;
})();
