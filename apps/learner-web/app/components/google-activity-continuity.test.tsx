// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CallbackPage from "../auth/callback/page";
import RegisterPage from "../register/page";
import { googleAuthStartUrl } from "../lib/auth-links";
import { FREE_COURSE_SLUG } from "../lib/course-intent";
import * as bridge from "../lib/dev-api-proxy";
import { LoginForm } from "./login-form";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const activity = "86f7efee-f504-4d6f-b4bc-9b3cb84ba2be";
const course = FREE_COURSE_SLUG;
const query = `?course=${course}&activity=${activity}`;

describe("Google activity continuation through actual auth surfaces", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.spyOn(bridge, "isStagingAuthenticatedBridge").mockReturnValue(false);
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  async function mount(content: ReactNode | Promise<ReactNode>) {
    const resolved = await content;
    await act(async () => root.render(resolved));
  }

  it.each([false, true])(
    "keeps activity in Google login and registration links (staging=%s)",
    async (stagingBridge) => {
      await mount(
        <LoginForm
          activityIntent={activity}
          courseIntent={course}
          stagingBridge={stagingBridge}
        />,
      );
      const google = container.querySelector<HTMLAnchorElement>(
        'a[href*="/v1/auth/google/start"]',
      )!;
      const url = new URL(google.href);
      expect(url.searchParams.get("return_path")).toBe("/onboarding" + query);
      expect(url.searchParams.get("action")).toBe("authenticate");
      const register = container.querySelector<HTMLAnchorElement>(
        'a[href*="/register"]',
      )!;
      expect(
        new URL(register.href).pathname + new URL(register.href).search,
      ).toBe("/register" + query);
      if (stagingBridge)
        expect(url.origin).toBe("https://staging.authorityclosers.com");
    },
  );

  it("preserves registration intent in the actual GET form while consent stays required", async () => {
    await mount(
      RegisterPage({
        searchParams: Promise.resolve({
          activity: activity.toUpperCase(),
          course,
        }),
      }),
    );
    const form =
      container.querySelector<HTMLFormElement>('form[method="get"]')!;
    expect(
      form.querySelector<HTMLInputElement>('[name="return_path"]')!.value,
    ).toBe("/onboarding" + query);
    expect(form.querySelector<HTMLButtonElement>("button")!.disabled).toBe(
      true,
    );
    expect(
      form.querySelector<HTMLInputElement>('[name="consent"]')!.disabled,
    ).toBe(true);
    await act(async () =>
      container
        .querySelector<HTMLInputElement>('[name="consent"][type="checkbox"]')!
        .click(),
    );
    expect(form.querySelector<HTMLButtonElement>("button")!.disabled).toBe(
      false,
    );
    expect(
      form.querySelector<HTMLInputElement>('[name="consent"]')!.disabled,
    ).toBe(false);
    expect(
      container.querySelector('a[href^="/login"]')!.getAttribute("href"),
    ).toBe("/login" + query);
  });

  it("carries registration context to the fixed staging origin", async () => {
    vi.mocked(bridge.isStagingAuthenticatedBridge).mockReturnValue(true);
    await mount(
      RegisterPage({ searchParams: Promise.resolve({ activity, course }) }),
    );
    expect(
      container
        .querySelector('a[href^="https://staging."]')!
        .getAttribute("href"),
    ).toBe("https://staging.authorityclosers.com/register" + query);
  });

  it.each([
    ["provider_rejected", "/login"],
    ["provider_unavailable", "/login"],
    ["registration_required", "/register"],
    ["consent_required", "/register"],
  ])("preserves activity after server result %s", async (result, route) => {
    await mount(
      CallbackPage({
        searchParams: Promise.resolve({
          result,
          activity: activity.toUpperCase(),
          course,
        }),
      }),
    );
    expect(
      container.querySelector(".callback-card a.button")!.getAttribute("href"),
    ).toBe(route + query);
    expect(
      container.querySelector('a[href^="/login"]')!.getAttribute("href"),
    ).toBe("/login" + query);
  });

  it("offers existing password users a context-preserving recovery path", async () => {
    await mount(
      CallbackPage({
        searchParams: Promise.resolve({
          result: "registration_required",
          activity,
          course,
        }),
      }),
    );

    const passwordLink = [...container.querySelectorAll("a")].find(
      (link) => link.textContent?.trim() === "Sign in with password",
    );
    expect(passwordLink?.getAttribute("href")).toBe("/login" + query);
    expect(container.textContent).toContain(
      "connect Google later from account settings",
    );
  });

  it("preserves only validated context in callback view retry", async () => {
    await mount(
      CallbackPage({
        searchParams: Promise.resolve({
          result: "provider_rejected",
          state: "error-retryable",
          activity,
          course,
        }),
      }),
    );
    const retry = [...container.querySelectorAll("a")].find(
      (link) => link.textContent?.trim() === "Retry this view",
    )!;
    expect(retry.getAttribute("href")).toBe(
      `/auth/callback?result=provider_rejected&course=${course}&activity=${activity}&state=default`,
    );
  });

  it.each([
    [activity, activity],
    "https://outside.example/path",
    " " + activity,
  ])("drops malformed or ambiguous callback activity %j", async (candidate) => {
    await mount(
      CallbackPage({
        searchParams: Promise.resolve({
          result: "provider_rejected",
          activity: candidate,
          course,
        }),
      }),
    );
    expect(
      container.querySelector(".callback-card a.button")!.getAttribute("href"),
    ).toBe("/login?course=" + course);
    expect(container.querySelector('a[href*="activity="]')).toBeNull();
  });

  it.each(["authenticate", "register"] as const)(
    "validates Google %s navigation without adding authority parameters",
    (action) => {
      const url = new URL(
        googleAuthStartUrl(action, course, activity.toUpperCase()),
        "https://app.example.test",
      );
      expect(Object.fromEntries(url.searchParams)).toEqual({
        action,
        surface: "learner",
        return_path: "/onboarding" + query,
      });
      const rejected = new URL(
        googleAuthStartUrl(action, course, "https://outside.example/steal"),
        "https://app.example.test",
      );
      expect(rejected.searchParams.get("return_path")).toBe(
        (action === "register" ? "/onboarding" : "/home") + "?course=" + course,
      );
    },
  );
});
