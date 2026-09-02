(() => {
  const storageKey = "ac-appearance-theme";
  const paletteStorageKey = "ac-appearance-palette";
  let preference = "light";
  let palette = "cobalt";
  try {
    const stored = window.localStorage.getItem(storageKey);
    if (stored === "light" || stored === "dark" || stored === "system") {
      preference = stored;
    }
    const storedPalette = window.localStorage.getItem(paletteStorageKey);
    if (
      storedPalette === "cobalt" ||
      storedPalette === "meadow" ||
      storedPalette === "ember"
    ) {
      palette = storedPalette;
    }
  } catch {
    // Light remains the deterministic product default when storage is blocked.
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
  root.dataset.palette = palette;
  root.style.colorScheme = effective;
})();
