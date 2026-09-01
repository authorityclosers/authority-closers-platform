import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

import { describe, expect, it, vi } from "vitest";

import {
  normalizeThemePreference,
  resolveThemePreference,
  subscribeToThemeChanges,
} from "../components/theme-control";

describe("learner theme preference", () => {
  function runPrepaint({
    stored,
    systemPrefersDark,
    storageThrows = false,
    mediaThrows = false,
  }: {
    stored: unknown;
    systemPrefersDark: boolean;
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
          getItem: () => {
            if (storageThrows) throw new Error("storage blocked");
            return stored;
          },
        },
        matchMedia: () => {
          if (mediaThrows) throw new Error("media unavailable");
          return { matches: systemPrefersDark };
        },
      },
    });

    return root;
  }

  it("accepts only supported persisted preferences", () => {
    expect(normalizeThemePreference("light")).toBe("light");
    expect(normalizeThemePreference("dark")).toBe("dark");
    expect(normalizeThemePreference("system")).toBe("system");
    expect(normalizeThemePreference("unexpected")).toBe("system");
    expect(normalizeThemePreference(null)).toBe("system");
  });

  it("resolves system without changing explicit choices", () => {
    expect(resolveThemePreference("system", true)).toBe("dark");
    expect(resolveThemePreference("system", false)).toBe("light");
    expect(resolveThemePreference("light", true)).toBe("light");
    expect(resolveThemePreference("dark", false)).toBe("dark");
  });

  it("applies the persisted theme from an external pre-paint script", () => {
    const root = runPrepaint({ stored: "dark", systemPrefersDark: false });

    expect(root.dataset).toEqual({
      theme: "dark",
      themePreference: "dark",
    });
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

  it("falls back deterministically when storage or media queries are blocked", () => {
    const root = runPrepaint({
      stored: "dark",
      systemPrefersDark: true,
      storageThrows: true,
      mediaThrows: true,
    });

    expect(root.dataset).toEqual({
      theme: "light",
      themePreference: "system",
    });
    expect(root.style).toEqual({ colorScheme: "light" });
  });

  it("loads the CSP-compatible theme initializer before interactive code", () => {
    const layout = readFileSync(
      new URL("../layout.tsx", import.meta.url),
      "utf8",
    );
    expect(layout).toContain('src="/theme-init.js"');
    expect(layout).toContain('strategy="beforeInteractive"');
    expect(layout).not.toContain("dangerouslySetInnerHTML");
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
    expect(target.removeEventListener).toHaveBeenCalledWith("storage", refresh);
    expect(target.removeEventListener).toHaveBeenCalledWith(
      "ac-theme-change",
      refresh,
    );
  });
});
