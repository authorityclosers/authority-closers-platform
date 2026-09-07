// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  LearnerApi,
  MeResponse,
  OnboardingResponse,
} from "../lib/learner-api";
import { SettingsRuntime } from "./settings-runtime";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const me: MeResponse = {
  person_id: "settings-fixture",
  display_name: "Settings learner",
  email: "settings@example.invalid",
  email_verified_at: "2026-09-07T00:00:00Z",
  selected_tenant_id: "settings-tenant",
  membership_role: "learner",
  permissions: [],
};
const onboarding: OnboardingResponse = {
  person_id: me.person_id,
  experience_context: "sales",
  learning_goal: "More thoughtful conversations",
  practice_situation: null,
  weekly_minutes: 30,
  status: "completed",
  current_step: 4,
  revision: 1,
  updated_at: "2026-09-07T00:00:00Z",
  next_action_href: "/home",
  next_action_reason: "complete",
};

let root: Root;
let container: HTMLDivElement;
let api: LearnerApi;

beforeEach(() => {
  window.history.replaceState(null, "", "/settings");
  window.localStorage.clear();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  api = {
    me: vi.fn(async () => me),
    onboarding: vi.fn(async () => onboarding),
    logout: vi.fn(async () => undefined),
  } as unknown as LearnerApi;
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function mount() {
  await act(async () => {
    root.render(<SettingsRuntime api={api} />);
  });
}

async function category(id: string) {
  const link = container.querySelector<HTMLAnchorElement>(`a[href="#${id}"]`);
  expect(link).not.toBeNull();
  await act(async () => {
    link!.dispatchEvent(
      new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }),
    );
  });
}

describe("mounted settings category behavior", () => {
  it("preserves a pending sign-out operation when navigating away and back", async () => {
    let rejectLogout!: (error: unknown) => void;
    api.logout = vi.fn(
      () =>
        new Promise<void>((_resolve, reject) => {
          rejectLogout = reject;
        }),
    );
    await mount();
    await category("session");
    const control = container.querySelector<HTMLButtonElement>(
      "#session .sign-out-control > button",
    )!;
    await act(async () => {
      control.click();
    });
    expect(control.disabled).toBe(true);
    expect(control.textContent).toContain("Signing out");
    await category("appearance");
    expect(container.querySelector("#session")?.parentElement?.hidden).toBe(
      true,
    );
    await category("session");
    expect(container.querySelector("#session .sign-out-control > button")).toBe(
      control,
    );
    expect(control.disabled).toBe(true);
    expect(api.logout).toHaveBeenCalledTimes(1);
    await act(async () => {
      rejectLogout(new TypeError("Synthetic offline"));
    });
    expect(
      container.querySelector("#session [role=alert]")?.textContent,
    ).toContain("Sign-out could not reach the service");
  });

  it("retains cleanup-only recovery after category navigation and never repeats logout", async () => {
    await mount();
    await category("session");
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const control = container.querySelector<HTMLButtonElement>(
      "#session .sign-out-control > button",
    )!;
    await act(async () => {
      control.click();
    });
    expect(api.logout).toHaveBeenCalledTimes(1);
    expect(control.disabled).toBe(true);
    expect(control.textContent).toContain("Signed out");
    expect(
      container.querySelector("#session [role=alert]")?.textContent,
    ).toContain("Retry local cleanup");
    await category("appearance");
    await category("session");
    expect(container.querySelector("#session .sign-out-control > button")).toBe(
      control,
    );
    expect(
      container.querySelector("#session [role=alert]")?.textContent,
    ).toContain("Retry local cleanup");
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>("#session [role=alert] button")!
        .click();
    });
    expect(api.logout).toHaveBeenCalledTimes(1);
    expect(
      container.querySelector("#session [role=alert]")?.textContent,
    ).toContain("Clear this site's storage");
    await act(async () => {
      control.click();
    });
    expect(api.logout).toHaveBeenCalledTimes(1);
  });

  it("navigates one active panel, updates the existing hash, and moves focus", async () => {
    await mount();
    expect(container.textContent).toContain("Settings learner");
    await category("appearance");
    expect(window.location.hash).toBe("#appearance");
    expect(
      container.querySelectorAll(
        "[data-settings-panel] > :not([hidden]) > section",
      ),
    ).toHaveLength(1);
    expect(document.activeElement?.id).toBe("appearance-title");
    expect(
      container.querySelector("#verified-account")?.parentElement?.hidden,
    ).toBe(true);
    expect(
      container
        .querySelector('[aria-current="location"]')
        ?.getAttribute("href"),
    ).toBe("#appearance");
  });

  it("restores category detail from deep links and browser history", async () => {
    window.history.replaceState(null, "", "/settings#learning-setup");
    await mount();
    expect(container.textContent).toContain(onboarding.learning_goal);
    await act(async () => {
      window.history.replaceState(null, "", "/settings#security-privacy");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(container.querySelector("#security-privacy")).not.toBeNull();
    expect(
      container.querySelector("#learning-setup")?.parentElement?.hidden,
    ).toBe(true);
    expect(document.activeElement?.id).toBe("security-privacy-title");
  });

  it("keeps appearance changes immediate and reports blocked storage truthfully", async () => {
    await mount();
    await category("appearance");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const theme = container.querySelector<HTMLSelectElement>(
      'select[aria-label="Theme"]',
    )!;
    await act(async () => {
      theme.value = "dark";
      theme.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(theme.value).toBe("dark");
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "session only",
    );
    expect(window.localStorage.getItem("ac-appearance-theme")).toBeNull();
    expect(api.me).toHaveBeenCalledTimes(1);
    await category("security-privacy");
    expect(container.querySelector("#appearance")?.parentElement?.hidden).toBe(
      true,
    );
    await category("appearance");
    expect(container.querySelector('select[aria-label="Theme"]')).toBe(theme);
    expect(theme.value).toBe("dark");
    expect(
      container.querySelector('#appearance [role="alert"]')?.textContent,
    ).toContain("session only");
    expect(container.querySelector("#appearance")?.textContent).not.toContain(
      "Saved on this browser",
    );
    expect(window.localStorage.getItem("ac-appearance-theme")).toBeNull();
  });

  it("does not reveal learning setup for an identity lacking learner membership", async () => {
    api.me = vi.fn(async () => ({ ...me, membership_role: "admin" }));
    window.history.replaceState(null, "", "/settings#learning-setup");
    await mount();
    expect(api.onboarding).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain(onboarding.learning_goal);
    expect(container.textContent).toContain(
      "Learner membership is unavailable",
    );
  });
});
