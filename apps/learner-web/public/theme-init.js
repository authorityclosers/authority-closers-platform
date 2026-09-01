(() => {
  const storageKey = "ac-appearance-theme";
  let preference = "system";
  try {
    const stored = window.localStorage.getItem(storageKey);
    if (stored === "light" || stored === "dark" || stored === "system") {
      preference = stored;
    }
  } catch {
    // System preference remains the safe fallback when storage is blocked.
  }

  let systemPrefersDark = false;
  try {
    systemPrefersDark = window.matchMedia(
      "(prefers-color-scheme: dark)",
    ).matches;
  } catch {
    // Light is the deterministic fallback for an unavailable media query.
  }

  const effective =
    preference === "system"
      ? systemPrefersDark
        ? "dark"
        : "light"
      : preference;
  const root = document.documentElement;
  root.dataset.theme = effective;
  root.dataset.themePreference = preference;
  root.style.colorScheme = effective;
})();
