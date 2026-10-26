import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  THEME_STORAGE_KEY,
  parseThemePreference,
  resolveTheme,
  themeControlEnabled,
  themeInitScript,
  writeThemePreference,
} from "./theme";
import { ThemeControl, ThemeProvider } from "./theme-provider";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const html = document.documentElement;
let root: Root;
let host: HTMLDivElement;

function mediaQuery(initial: boolean) {
  const listeners = new Set<() => void>();
  const query = {
    matches: initial,
    media: "(prefers-color-scheme: dark)",
    addEventListener: (_type: string, listener: () => void) =>
      listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) =>
      listeners.delete(listener),
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => query),
  );
  return {
    change(matches: boolean) {
      query.matches = matches;
      listeners.forEach((listener) => listener());
    },
  };
}

function radio(value: string) {
  return host.querySelector<HTMLInputElement>(
    `input[type="radio"][value="${value}"]`,
  )!;
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.clear();
  html.setAttribute("data-theme", "light");
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  localStorage.clear();
  html.removeAttribute("data-theme");
  html.removeAttribute("data-theme-preference");
  html.style.colorScheme = "";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("theme preference", () => {
  it("treats missing, unknown or old System values as Light, whatever the device", () => {
    expect(parseThemePreference(null)).toBe("light");
    expect(parseThemePreference("sepia")).toBe("light");
    expect(parseThemePreference("system")).toBe("light");
    expect(parseThemePreference("dark")).toBe("dark");
    expect(resolveTheme("system", true)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("releases the control in development and explicit previews, not production", () => {
    expect(themeControlEnabled({ NODE_ENV: "development" })).toBe(true);
    expect(themeControlEnabled({ NODE_ENV: "test" })).toBe(true);
    // Released everywhere (owner, 24 Oct 2026); "0" holds a deployment light.
    expect(themeControlEnabled({ NODE_ENV: "production" })).toBe(true);
    expect(
      themeControlEnabled({
        NODE_ENV: "production",
        AC_SALES_XRAY_THEME_PREVIEW: "0",
      }),
    ).toBe(false);
    expect(
      themeControlEnabled({
        NODE_ENV: "production",
        AC_SALES_XRAY_THEME_PREVIEW: "1",
      }),
    ).toBe(true);
  });
});

describe("pre-paint theme script", () => {
  const run = () => new Function(themeInitScript())();

  it("applies a stored preference before React loads", () => {
    mediaQuery(false);
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    run();
    expect(html.getAttribute("data-theme")).toBe("dark");
    expect(html.getAttribute("data-theme-preference")).toBe("dark");
    expect(html.style.colorScheme).toBe("dark");
  });

  it("is light for an unknown or old System value, even on a dark device", () => {
    mediaQuery(true);
    localStorage.setItem(THEME_STORAGE_KEY, "system");
    run();
    expect(html.getAttribute("data-theme")).toBe("light");
    expect(html.getAttribute("data-theme-preference")).toBe("light");
  });

  it("falls back to light when storage is blocked and matchMedia is missing", () => {
    vi.stubGlobal("matchMedia", undefined);
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    const storage = vi
      .spyOn(window, "localStorage", "get")
      .mockImplementation(() => {
        throw new DOMException("blocked", "SecurityError");
      });
    expect(run).not.toThrow();
    expect(storage).toHaveBeenCalled();
    storage.mockRestore();
    expect(html.getAttribute("data-theme")).toBe("light");
    expect(html.getAttribute("data-theme-preference")).toBe("light");
  });
});

describe("ThemeProvider and ThemeControl", () => {
  async function mount(controlEnabled = true) {
    await act(async () =>
      root.render(
        <ThemeProvider controlEnabled={controlEnabled}>
          <ThemeControl />
        </ThemeProvider>,
      ),
    );
  }

  it("persists an explicit choice and applies it to the document", async () => {
    mediaQuery(false);
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    await mount();
    expect(host.querySelector("legend")?.textContent).toBe("Theme");
    expect(radio("light").checked).toBe(true);
    expect(html.getAttribute("data-theme")).toBe("light");

    await act(async () => radio("dark").click());
    expect(radio("dark").checked).toBe(true);
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(html.getAttribute("data-theme")).toBe("dark");
    expect(html.getAttribute("data-theme-preference")).toBe("dark");
  });

  it("offers Light and Dark only, and stays light when the device turns dark", async () => {
    const device = mediaQuery(false);
    await mount();
    expect(host.querySelector('input[value="system"]')).toBeNull();
    expect(radio("light").checked).toBe(true);
    expect(html.getAttribute("data-theme")).toBe("light");

    await act(async () => device.change(true));
    expect(html.getAttribute("data-theme")).toBe("light");

    await act(async () => radio("dark").click());
    await act(async () => radio("light").click());
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
    expect(html.getAttribute("data-theme")).toBe("light");
  });

  it("picks up a choice made in another tab", async () => {
    mediaQuery(false);
    await mount();
    expect(radio("light").checked).toBe(true);
    await act(async () => {
      localStorage.setItem(THEME_STORAGE_KEY, "dark");
      window.dispatchEvent(
        new StorageEvent("storage", { key: THEME_STORAGE_KEY }),
      );
    });
    expect(radio("dark").checked).toBe(true);
    expect(html.getAttribute("data-theme")).toBe("dark");
  });

  it("still applies a choice for this page when storage refuses the write", async () => {
    mediaQuery(false);
    await mount();
    const originalStorage = window.localStorage;
    const write = vi
      .spyOn(window, "localStorage", "get")
      .mockImplementation(() => {
        throw new DOMException("quota", "QuotaExceededError");
      });
    await act(async () => radio("dark").click());
    expect(radio("dark").checked).toBe(true);
    expect(html.getAttribute("data-theme")).toBe("dark");
    expect(write).toHaveBeenCalled();
    write.mockRestore();
    expect(originalStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
    // A successful write clears the page-only fallback for later tests.
    await act(async () => writeThemePreference("light"));
    expect(radio("light").checked).toBe(true);
  });

  it("renders no control and leaves the document light when the control is not released", async () => {
    const device = mediaQuery(true);
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    await mount(false);
    await act(async () => device.change(true));
    expect(host.querySelector("fieldset")).toBeNull();
    expect(html.getAttribute("data-theme")).toBe("light");
    expect(html.hasAttribute("data-theme-preference")).toBe(false);
  });

  it("renders nothing outside a provider, as in the learner-web embed", async () => {
    await act(async () => root.render(<ThemeControl />));
    expect(host.innerHTML).toBe("");
  });
});
