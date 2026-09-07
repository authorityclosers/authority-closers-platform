import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

import { describe, expect, it, vi } from "vitest";

import { NAMED_PRESETS } from "../components/theme-control";
import {
  normalizeAccentPreference,
  normalizeDensityPreference,
  normalizeMotionPreference,
  normalizeThemePreference,
  resolveMotionPreference,
  resolveThemePreference,
  subscribeToThemeChanges,
} from "./appearance-preferences";

describe("learner appearance preference", () => {
  function runPrepaint({
    stored,
    storedAccent = null,
    storedDensity = null,
    storedMotion = null,
    systemPrefersDark,
    systemPrefersReducedMotion = false,
    storageThrows = false,
    mediaThrows = false,
  }: {
    stored: unknown;
    storedAccent?: unknown;
    storedDensity?: unknown;
    storedMotion?: unknown;
    systemPrefersDark: boolean;
    systemPrefersReducedMotion?: boolean;
    storageThrows?: boolean;
    mediaThrows?: boolean;
  }) {
    const source = readFileSync(
      new URL("../../public/theme-init.js", import.meta.url),
      "utf8",
    );
    const root = { dataset: {} as Record<string, string>, style: {} };

    runInNewContext(source, {
      document: { documentElement: root },
      window: {
        localStorage: {
          getItem: (key: string) => {
            if (storageThrows) throw new Error("storage blocked");
            if (key === "ac-appearance-theme") return stored;
            if (key === "ac-appearance-accent") return storedAccent;
            if (key === "ac-appearance-density") return storedDensity;
            if (key === "ac-appearance-motion") return storedMotion;
            return null;
          },
        },
        matchMedia: (query: string) => {
          if (mediaThrows) throw new Error("media unavailable");
          if (query.includes("prefers-reduced-motion")) {
            return { matches: systemPrefersReducedMotion };
          }
          return { matches: systemPrefersDark };
        },
      },
    });

    return root;
  }

  it("accepts only supported persisted theme preferences", () => {
    expect(normalizeThemePreference("light")).toBe("light");
    expect(normalizeThemePreference("dark")).toBe("dark");
    expect(normalizeThemePreference("system")).toBe("system");
    expect(normalizeThemePreference("unexpected")).toBe("light");
    expect(normalizeThemePreference(null)).toBe("light");
  });

  it("accepts only supported persisted accent preferences", () => {
    expect(normalizeAccentPreference("cobalt")).toBe("cobalt");
    expect(normalizeAccentPreference("indigo")).toBe("indigo");
    expect(normalizeAccentPreference("emerald")).toBe("emerald");
    expect(normalizeAccentPreference("amber")).toBe("amber");
    expect(normalizeAccentPreference("slate")).toBe("slate");
    expect(normalizeAccentPreference("magenta")).toBe("cobalt");
    expect(normalizeAccentPreference(undefined)).toBe("cobalt");
  });

  it("accepts only supported persisted density preferences", () => {
    expect(normalizeDensityPreference("comfortable")).toBe("comfortable");
    expect(normalizeDensityPreference("compact")).toBe("compact");
    expect(normalizeDensityPreference("ultra")).toBe("comfortable");
    expect(normalizeDensityPreference(null)).toBe("comfortable");
  });

  it("accepts only supported persisted motion preferences", () => {
    expect(normalizeMotionPreference("system")).toBe("system");
    expect(normalizeMotionPreference("reduced")).toBe("reduced");
    expect(normalizeMotionPreference("full")).toBe("full");
    expect(normalizeMotionPreference("instant")).toBe("system");
    expect(normalizeMotionPreference(null)).toBe("system");
  });

  it("resolves system theme without changing explicit choices", () => {
    expect(resolveThemePreference("system", true)).toBe("dark");
    expect(resolveThemePreference("system", false)).toBe("light");
    expect(resolveThemePreference("light", true)).toBe("light");
    expect(resolveThemePreference("dark", false)).toBe("dark");
  });

  it("resolves motion preferences correctly", () => {
    expect(resolveMotionPreference("reduced", false)).toBe(true);
    expect(resolveMotionPreference("full", true)).toBe(false);
    expect(resolveMotionPreference("system", true)).toBe(true);
    expect(resolveMotionPreference("system", false)).toBe(false);
  });

  it("includes all bounded named presets", () => {
    expect(NAMED_PRESETS).toHaveLength(5);
    const ids = NAMED_PRESETS.map((p) => p.id);
    expect(ids).toContain("authority-cobalt");
    expect(ids).toContain("deep-focus");
    expect(ids).toContain("signal-emerald");
    expect(ids).toContain("executive-amber");
    expect(ids).toContain("precision-slate");
  });

  it("applies the persisted theme from an external pre-paint script", () => {
    const root = runPrepaint({ stored: "dark", systemPrefersDark: false });

    expect(root.dataset).toEqual({ theme: "dark", themePreference: "dark" });
    expect(root.style).toEqual({ colorScheme: "dark" });
  });

  it("resolves system before paint and never overrides explicit choices", () => {
    expect(
      runPrepaint({ stored: "system", systemPrefersDark: true }).dataset,
    ).toEqual({ theme: "dark", themePreference: "system" });
    expect(
      runPrepaint({ stored: "system", systemPrefersDark: false }).dataset,
    ).toEqual({ theme: "light", themePreference: "system" });
    expect(
      runPrepaint({ stored: "light", systemPrefersDark: true }).dataset,
    ).toEqual({ theme: "light", themePreference: "light" });
  });

  it("applies stored accent, density, and motion before paint", () => {
    const root = runPrepaint({
      stored: "dark",
      storedAccent: "emerald",
      storedDensity: "compact",
      storedMotion: "reduced",
      systemPrefersDark: false,
    });

    expect(root.dataset).toEqual({
      theme: "dark",
      themePreference: "dark",
      accent: "emerald",
      density: "compact",
      motion: "reduced",
      reducedMotion: "true",
    });
    expect(root.style).toEqual({ colorScheme: "dark" });
  });

  it("falls back deterministically when storage or media queries are blocked", () => {
    const root = runPrepaint({
      stored: "dark",
      storedAccent: "indigo",
      storedDensity: "compact",
      storedMotion: "reduced",
      systemPrefersDark: true,
      storageThrows: true,
      mediaThrows: true,
    });

    expect(root.dataset).toEqual({
      theme: "light",
      themePreference: "light",
    });
    expect(root.style).toEqual({ colorScheme: "light" });
  });

  it("preserves valid bootstrap appearance data when storage access throws", () => {
    const source = readFileSync(
      new URL("../../public/theme-init.js", import.meta.url),
      "utf8",
    );
    const root = {
      dataset: {
        theme: "dark",
        themePreference: "dark",
        accent: "amber",
        density: "compact",
        motion: "reduced",
        reducedMotion: "true",
      } as Record<string, string>,
      style: {},
    };

    runInNewContext(source, {
      document: { documentElement: root },
      window: {
        localStorage: {
          getItem: () => {
            throw new Error("storage blocked");
          },
        },
        matchMedia: (query: string) => ({
          matches: query.includes("prefers-color-scheme"),
        }),
      },
    });

    expect(root.dataset).toEqual({
      theme: "dark",
      themePreference: "dark",
      accent: "amber",
      density: "compact",
      motion: "reduced",
      reducedMotion: "true",
    });
    expect(root.style).toEqual({ colorScheme: "dark" });
  });

  it("loads the CSP-compatible theme initializer before interactive code", () => {
    const layout = readFileSync(
      new URL("../layout.tsx", import.meta.url),
      "utf8",
    );
    expect(layout).toContain('src="/theme-init.js"');
    expect(layout).toContain('strategy="beforeInteractive"');
    expect(layout).not.toContain("dangerouslySetInnerHTML");
    // The root must load the lightweight runtime, not the settings module.
    expect(layout).toContain('from "./components/theme-runtime"');
    expect(layout).not.toContain('from "./components/theme-control"');
  });

  it("removes every runtime theme listener during cleanup", () => {
    const media = {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as Pick<
      MediaQueryList,
      "addEventListener" | "removeEventListener"
    >;
    const target = {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as Pick<Window, "addEventListener" | "removeEventListener">;
    const refresh = vi.fn() as EventListener;

    const cleanup = subscribeToThemeChanges(media, target, refresh);
    cleanup();

    expect(media.addEventListener).toHaveBeenCalledWith("change", refresh);
    expect(media.removeEventListener).toHaveBeenCalledWith("change", refresh);
    expect(target.addEventListener).toHaveBeenCalledWith("storage", refresh);
    expect(target.addEventListener).toHaveBeenCalledWith(
      "ac-theme-change",
      refresh,
    );
    expect(target.addEventListener).toHaveBeenCalledWith(
      "ac-appearance-change",
      refresh,
    );
    expect(target.removeEventListener).toHaveBeenCalledWith("storage", refresh);
    expect(target.removeEventListener).toHaveBeenCalledWith(
      "ac-theme-change",
      refresh,
    );
    expect(target.removeEventListener).toHaveBeenCalledWith(
      "ac-appearance-change",
      refresh,
    );
  });
});
