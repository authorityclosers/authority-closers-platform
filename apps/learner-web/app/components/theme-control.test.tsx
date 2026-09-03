import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ACCENT_STORAGE_KEY,
  AppearanceControl,
  DENSITY_STORAGE_KEY,
  MOTION_STORAGE_KEY,
  THEME_STORAGE_KEY,
  ThemeControl,
  applyAppearancePreferences,
  readAppearancePreferences,
  saveAppearancePreferences,
} from "./theme-control";

describe("ThemeControl Component and Appearance Runtime", () => {
  let storageState: Record<string, string> = {};

  beforeEach(() => {
    storageState = {};
    const mockStorage = {
      getItem: (key: string) => storageState[key] ?? null,
      setItem: (key: string, value: string) => {
        storageState[key] = value;
      },
      removeItem: (key: string) => {
        delete storageState[key];
      },
      clear: () => {
        storageState = {};
      },
      length: 0,
      key: () => null,
    };

    vi.stubGlobal("localStorage", mockStorage);
    if (typeof window !== "undefined") {
      Object.defineProperty(window, "localStorage", {
        value: mockStorage,
        configurable: true,
        writable: true,
      });
    }

    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders all appearance sections and options with accessible semantics", () => {
    const html = renderToStaticMarkup(createElement(AppearanceControl));

    // Named presets
    expect(html).toContain("Named presets");
    expect(html).toContain("Authority Cobalt");
    expect(html).toContain("Deep Focus");
    expect(html).toContain("Signal Emerald");
    expect(html).toContain("Executive Amber");
    expect(html).toContain("Precision Slate");

    // Theme mode
    expect(html).toContain("Theme mode");
    expect(html).toContain("Light");
    expect(html).toContain("Dark");
    expect(html).toContain("System");

    // Accent options
    expect(html).toContain("Accent color");
    expect(html).toContain("Cobalt");
    expect(html).toContain("Indigo");
    expect(html).toContain("Emerald");
    expect(html).toContain("Amber");
    expect(html).toContain("Slate");

    // Density
    expect(html).toContain("Display density");
    expect(html).toContain("Comfortable");
    expect(html).toContain("Compact");

    // Motion
    expect(html).toContain("Motion &amp; microinteractions");
    expect(html).toContain("Reduced motion");
    expect(html).toContain("Full motion");

    // Reset button
    expect(html).toContain("Reset to default appearance");

    // Accessibility attributes
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-live="polite"');
    expect(html).toContain('aria-pressed="true"');
  });

  it("renders the compact 3-button theme control when advanced is false", () => {
    const html = renderToStaticMarkup(createElement(ThemeControl));

    expect(html).toContain('aria-label="Appearance theme"');
    expect(html).toContain("Light");
    expect(html).toContain("Dark");
    expect(html).toContain("System");
    expect(html).not.toContain("Accent color");
    expect(html.match(/aria-pressed=/g)).toHaveLength(3);
  });

  it("reads and writes appearance preferences via saveAppearancePreferences", () => {
    const result = saveAppearancePreferences({
      theme: "dark",
      accent: "indigo",
      density: "compact",
      motion: "reduced",
    });

    expect(result.ok).toBe(true);
    expect(storageState[THEME_STORAGE_KEY]).toBe("dark");
    expect(storageState[ACCENT_STORAGE_KEY]).toBe("indigo");
    expect(storageState[DENSITY_STORAGE_KEY]).toBe("compact");
    expect(storageState[MOTION_STORAGE_KEY]).toBe("reduced");

    const read = readAppearancePreferences();
    expect(read).toEqual({
      theme: "dark",
      accent: "indigo",
      density: "compact",
      motion: "reduced",
    });
  });

  it("handles storage quota errors gracefully with fail-closed recovery", () => {
    const quotaMock = {
      getItem: () => null,
      setItem: () => {
        const error = new Error("QuotaExceededError");
        error.name = "QuotaExceededError";
        throw error;
      },
      removeItem: () => {},
      clear: () => {},
      length: 0,
      key: () => null,
    };

    vi.stubGlobal("localStorage", quotaMock);
    if (typeof window !== "undefined") {
      Object.defineProperty(window, "localStorage", {
        value: quotaMock,
        configurable: true,
        writable: true,
      });
    }

    const result = saveAppearancePreferences({
      theme: "dark",
      accent: "emerald",
      density: "compact",
      motion: "reduced",
    });

    // Does not throw an unhandled error; returns fail-closed result
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBe("quota_exceeded");
    }
  });

  it("handles storage blocked errors gracefully", () => {
    const blockedMock = {
      getItem: () => {
        throw new Error("SecurityError");
      },
      setItem: () => {
        throw new Error("SecurityError");
      },
      removeItem: () => {},
      clear: () => {},
      length: 0,
      key: () => null,
    };

    vi.stubGlobal("localStorage", blockedMock);
    if (typeof window !== "undefined") {
      Object.defineProperty(window, "localStorage", {
        value: blockedMock,
        configurable: true,
        writable: true,
      });
    }

    const result = saveAppearancePreferences({
      accent: "amber",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBe("storage_unavailable");
    }
  });

  it("applies preferences to the root documentElement", () => {
    const root = {
      dataset: {} as Record<string, string>,
      style: {} as Record<string, string>,
    };
    vi.stubGlobal("document", { documentElement: root });

    applyAppearancePreferences({
      theme: "dark",
      accent: "emerald",
      density: "compact",
      motion: "reduced",
    });

    expect(root.dataset.theme).toBe("dark");
    expect(root.dataset.themePreference).toBe("dark");
    expect(root.dataset.accent).toBe("emerald");
    expect(root.dataset.density).toBe("compact");
    expect(root.dataset.motion).toBe("reduced");
    expect(root.dataset.reducedMotion).toBe("true");
    expect(root.style.colorScheme).toBe("dark");
  });

  it("supports resetting to default appearance", () => {
    saveAppearancePreferences({
      theme: "dark",
      accent: "slate",
      density: "compact",
      motion: "reduced",
    });

    saveAppearancePreferences({
      theme: "light",
      accent: "cobalt",
      density: "comfortable",
      motion: "system",
    });

    const read = readAppearancePreferences();
    expect(read).toEqual({
      theme: "light",
      accent: "cobalt",
      density: "comfortable",
      motion: "system",
    });
  });
});
