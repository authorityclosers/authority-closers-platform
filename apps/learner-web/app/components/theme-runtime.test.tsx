// @vitest-environment happy-dom

import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ACCENT_STORAGE_KEY,
  DENSITY_STORAGE_KEY,
  MOTION_STORAGE_KEY,
  THEME_STORAGE_KEY,
  saveAppearancePreferences,
} from "../lib/appearance-preferences";
import { ThemeRuntime } from "./theme-runtime";

// Importing the root runtime must never evaluate the settings presentation graph.
vi.mock("lucide-react", () => {
  throw new Error("The root theme runtime must not load settings icons.");
});
vi.mock("./settings-clarity.module.css", () => {
  throw new Error("The root theme runtime must not load settings CSS.");
});

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const appearanceAttributes = [
  "data-theme",
  "data-theme-preference",
  "data-accent",
  "data-density",
  "data-motion",
  "data-reduced-motion",
];

function createMediaQuery() {
  const listeners = new Set<EventListenerOrEventListenerObject>();
  return {
    matches: false,
    addEventListener: vi.fn(
      (_event: string, listener: EventListenerOrEventListenerObject) => {
        listeners.add(listener);
      },
    ),
    removeEventListener: vi.fn(
      (_event: string, listener: EventListenerOrEventListenerObject) => {
        listeners.delete(listener);
      },
    ),
    change(matches: boolean) {
      this.matches = matches;
      for (const listener of listeners) {
        const event = new Event("change");
        if (typeof listener === "function") listener(event);
        else listener.handleEvent(event);
      }
    },
    get listenerCount() {
      return listeners.size;
    },
  };
}

describe("mounted root appearance runtime", () => {
  let root: Root;
  let container: HTMLDivElement;
  let colorScheme: ReturnType<typeof createMediaQuery>;
  let reducedMotion: ReturnType<typeof createMediaQuery>;

  beforeEach(() => {
    const values = new Map<string, string>();
    const storage: Storage = {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => {
        values.set(key, value);
      },
      removeItem: (key) => {
        values.delete(key);
      },
      clear: () => values.clear(),
      key: (index) => [...values.keys()][index] ?? null,
      get length() {
        return values.size;
      },
    };
    vi.spyOn(window, "localStorage", "get").mockReturnValue(storage);
    colorScheme = createMediaQuery();
    reducedMotion = createMediaQuery();
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query) =>
        (query.includes("prefers-color-scheme")
          ? colorScheme
          : reducedMotion) as unknown as MediaQueryList,
    );
    // A successful write clears session-only overrides from earlier tests.
    saveAppearancePreferences({
      theme: "light",
      accent: "cobalt",
      density: "comfortable",
      motion: "system",
    });
    window.localStorage.clear();
    for (const name of appearanceAttributes) {
      document.documentElement.removeAttribute(name);
    }
    document.documentElement.style.removeProperty("color-scheme");
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  async function mount() {
    await act(async () => root.render(<ThemeRuntime />));
  }

  it("applies persisted appearance and updates system theme and motion", async () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "system");
    window.localStorage.setItem(ACCENT_STORAGE_KEY, "emerald");
    window.localStorage.setItem(DENSITY_STORAGE_KEY, "compact");
    window.localStorage.setItem(MOTION_STORAGE_KEY, "system");
    colorScheme.matches = true;
    reducedMotion.matches = true;

    await mount();

    const html = document.documentElement;
    expect(container.childElementCount).toBe(0);
    expect({ ...html.dataset }).toMatchObject({
      theme: "dark",
      themePreference: "system",
      accent: "emerald",
      density: "compact",
      motion: "system",
      reducedMotion: "true",
    });
    expect(html.style.colorScheme).toBe("dark");

    await act(async () => {
      colorScheme.change(false);
      reducedMotion.change(false);
    });

    expect(html.dataset.theme).toBe("light");
    expect(html.dataset.reducedMotion).toBe("false");
    expect(html.style.colorScheme).toBe("light");
  });

  it("shares local settings writes and observes cross-tab storage updates", async () => {
    await mount();
    await act(async () => {
      saveAppearancePreferences({
        theme: "dark",
        accent: "indigo",
        motion: "full",
      });
    });

    const html = document.documentElement;
    expect(html.dataset.theme).toBe("dark");
    expect(html.dataset.accent).toBe("indigo");
    await act(async () => reducedMotion.change(true));
    expect(html.dataset.reducedMotion).toBe("false");

    await act(async () => {
      window.localStorage.setItem(THEME_STORAGE_KEY, "light");
      window.localStorage.setItem(ACCENT_STORAGE_KEY, "amber");
      window.localStorage.setItem(MOTION_STORAGE_KEY, "reduced");
      window.dispatchEvent(new StorageEvent("storage"));
    });

    expect(html.dataset.theme).toBe("light");
    expect(html.dataset.accent).toBe("amber");
    expect(html.dataset.reducedMotion).toBe("true");
  });

  it("retains bootstrap and session-only choices when storage is blocked", async () => {
    Object.assign(document.documentElement.dataset, {
      theme: "dark",
      themePreference: "dark",
      accent: "amber",
      density: "compact",
      motion: "reduced",
      reducedMotion: "true",
    });
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("Storage unavailable");
    });
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("Storage unavailable");
    });

    await mount();
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.accent).toBe("amber");

    await act(async () => {
      expect(saveAppearancePreferences({ accent: "emerald" })).toEqual({
        ok: false,
        reason: "storage_unavailable",
      });
      window.dispatchEvent(new Event("ac-appearance-change"));
      colorScheme.change(false);
    });

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.accent).toBe("emerald");
    expect(document.documentElement.dataset.density).toBe("compact");
    expect(document.documentElement.dataset.reducedMotion).toBe("true");
  });

  it("cleans up media and window listeners across Strict Mode and unmount", async () => {
    const removeListener = vi.spyOn(window, "removeEventListener");
    await act(async () =>
      root.render(
        <StrictMode>
          <ThemeRuntime />
        </StrictMode>,
      ),
    );
    expect(colorScheme.listenerCount).toBe(1);
    expect(reducedMotion.listenerCount).toBe(1);

    await act(async () => root.render(null));
    expect(colorScheme.listenerCount).toBe(0);
    expect(reducedMotion.listenerCount).toBe(0);
    for (const event of [
      "storage",
      "ac-theme-change",
      "ac-appearance-change",
    ]) {
      expect(removeListener).toHaveBeenCalledWith(event, expect.any(Function));
    }

    const previousTheme = document.documentElement.dataset.theme;
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    window.dispatchEvent(new StorageEvent("storage"));
    colorScheme.change(true);
    expect(document.documentElement.dataset.theme).toBe(previousTheme);
  });
});
