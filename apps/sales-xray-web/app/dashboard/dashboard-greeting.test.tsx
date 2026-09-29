// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { updateShellState } from "../shell/shell-store";
import { firstNameOf } from "../profile-first-name";
import { DashboardGreeting, greetingLines } from "./dashboard-greeting";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

describe("greeting lines", () => {
  it.each([
    [6, "Good morning"],
    [13, "Good afternoon"],
    [19, "Good evening"],
    [23, "Working late"],
    [3, "Working late"],
  ])("opens with the time of day at %i:00", (hour, lead) => {
    expect(greetingLines(hour)[0].lead).toBe(lead);
  });

  it("uses only the first name", () => {
    expect(firstNameOf("  Suyash Rahegaonkar ")).toBe("Suyash");
    expect(firstNameOf("   ")).toBeNull();
    expect(firstNameOf(null)).toBeNull();
  });
});

describe("dashboard greeting", () => {
  let root: Root | undefined;
  let host: HTMLDivElement;
  const title = () => host.querySelector("h2")?.textContent;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 8, 29, 9, 0));
    host = document.createElement("div");
    document.body.append(host);
  });

  afterEach(async () => {
    if (root) await act(async () => root?.unmount());
    host.remove();
    vi.useRealTimers();
    updateShellState({ profileName: null });
  });

  it("greets the signed-in person by first name and rotates", async () => {
    updateShellState({ profileName: "Suyash Rahegaonkar" });
    const mountedRoot = createRoot(host);
    root = mountedRoot;
    await act(async () => mountedRoot.render(<DashboardGreeting />));
    expect(title()).toBe("Good morning, Suyash👋");
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(title()).toBe("Welcome back, Suyash👋");
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(title()).toBe("Ready for your next call, Suyash?👋");
  });

  it("leaves the name out when the profile has none", async () => {
    const mountedRoot = createRoot(host);
    root = mountedRoot;
    await act(async () => mountedRoot.render(<DashboardGreeting />));
    expect(title()).toBe("Good morning👋");
  });

  it("keeps the fallback greeting through hydration, then uses local time", async () => {
    host.innerHTML = renderToString(<DashboardGreeting />);
    expect(title()).toBe("Welcome back👋");

    await act(async () => {
      const hydratedRoot = hydrateRoot(host, <DashboardGreeting />);
      root = hydratedRoot;
    });

    expect(title()).toBe("Good morning👋");
  });
});
