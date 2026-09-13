// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CallbackPage from "../auth/callback/page";
import ForgotPasswordPage from "../forgot-password/page";
import LoginPage from "../login/page";
import OnboardingPage from "../onboarding/page";
import RegisterPage from "../register/page";
import ResetPasswordPage from "../reset-password/page";
import SessionExpiredPage from "../session-expired/page";
import VerifyEmailPage from "../verify-email/page";
import * as apiModule from "../lib/learner-api";
import { createLearnerApi } from "../lib/learner-api";
import { SALES_XRAY_PATH } from "../lib/sales-auth-return";
import * as bridge from "../lib/dev-api-proxy";
import { FREE_COURSE_SLUG } from "../lib/course-intent";
import { OnboardingCompletionState } from "./onboarding-form";
import { routeAfterOnboarding } from "./login-form";
import { StagingAuthHandoff } from "./staging-auth-handoff";
import {
  PasswordResetForm,
  RecoveryRequestForm,
  RegistrationForm,
  VerifyEmailFlow,
} from "./password-auth-forms";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const salesQuery = `?next=${encodeURIComponent(SALES_XRAY_PATH)}`;
const activity = "86f7efee-f504-4d6f-b4bc-9b3cb84ba2be";
const token = "t".repeat(43);

describe("Sales authentication continuation", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.spyOn(bridge, "isStagingAuthenticatedBridge").mockReturnValue(false);
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    window.history.replaceState(null, "", "/");
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
  });

  async function mount(content: ReactNode | Promise<ReactNode>) {
    const resolved = await content;
    await act(async () => root.render(resolved));
  }

  it("keeps the strict Sales hint on every auth wrapper", async () => {
    const pages = [
      await LoginPage({
        searchParams: Promise.resolve({ next: SALES_XRAY_PATH }),
      }),
      await RegisterPage({
        searchParams: Promise.resolve({ next: SALES_XRAY_PATH }),
      }),
      await ForgotPasswordPage({
        searchParams: Promise.resolve({ next: SALES_XRAY_PATH }),
      }),
      await VerifyEmailPage({
        searchParams: Promise.resolve({ next: SALES_XRAY_PATH }),
      }),
      await ResetPasswordPage({
        searchParams: Promise.resolve({ next: SALES_XRAY_PATH }),
      }),
      await SessionExpiredPage({
        searchParams: Promise.resolve({ next: SALES_XRAY_PATH }),
      }),
      await OnboardingPage({
        searchParams: Promise.resolve({ next: SALES_XRAY_PATH }),
      }),
    ];
    const markup = pages.map((page) => renderToStaticMarkup(page)).join("\n");

    expect(markup).toContain("Sales Xray");
    expect(markup).toContain(salesQuery);
    expect(markup).not.toContain("course=");

    const verifyMarkup = renderToStaticMarkup(
      await VerifyEmailPage({
        searchParams: Promise.resolve({ next: SALES_XRAY_PATH }),
      }),
    );
    expect(verifyMarkup).toContain("Email verification.");
    expect(verifyMarkup).not.toContain("Check your inbox.");
  });

  it("preserves Sales through password registration and recovery requests", async () => {
    const registerPassword = vi.fn(async () => ({
      status: "verification_required" as const,
    }));
    const requestPasswordRecovery = vi.fn(async () => ({
      accepted: true as const,
    }));
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      registerPassword,
      requestPasswordRecovery,
    } as unknown as apiModule.LearnerApi);

    await mount(<RegistrationForm salesNext={SALES_XRAY_PATH} />);
    await act(async () =>
      container
        .querySelector<HTMLInputElement>('input[name="consent"]')!
        .click(),
    );
    const registerForm = container.querySelector<HTMLFormElement>("form")!;
    registerForm.querySelector<HTMLInputElement>('[name="firstName"]')!.value =
      "Learner";
    registerForm.querySelector<HTMLInputElement>('[name="email"]')!.value =
      "learner@example.com";
    registerForm.querySelector<HTMLInputElement>(
      '[name="whatsappNumber"]',
    )!.value = "+12025550123";
    registerForm.querySelector<HTMLInputElement>('[name="password"]')!.value =
      "twelve-characters-and-more";
    await act(async () =>
      registerForm.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      ),
    );

    expect(registerPassword).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ salesNext: SALES_XRAY_PATH }),
    );
    expect(
      container.querySelector('a[href^="/login"]')?.getAttribute("href"),
    ).toBe("/login?next=%2Fsales-xray");
    expect(
      [...container.querySelectorAll("a")]
        .find((link) => link.textContent?.includes("fresh verification"))
        ?.getAttribute("href"),
    ).toBe("/verify-email?next=%2Fsales-xray");

    await mount(<RecoveryRequestForm salesNext={SALES_XRAY_PATH} />);
    const recoveryForm = container.querySelector<HTMLFormElement>("form")!;
    recoveryForm.querySelector<HTMLInputElement>("[name=email]")!.value =
      "learner@example.com";
    await act(async () =>
      recoveryForm.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      ),
    );

    expect(requestPasswordRecovery).toHaveBeenCalledExactlyOnceWith(
      "learner@example.com",
      { courseIntent: null, activityIntent: null, salesNext: SALES_XRAY_PATH },
    );
    expect(
      container.querySelector('a[href^="/login"]')?.getAttribute("href"),
    ).toBe("/login?next=%2Fsales-xray");
  });

  it("keeps activity-only context ahead of a competing Sales hint", async () => {
    const bodies: unknown[] = [];
    const fetcher = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        bodies.push(JSON.parse(String(init?.body)));
        return new Response(JSON.stringify({ accepted: true }), {
          status: 200,
        });
      },
    );
    await createLearnerApi(fetcher).requestPasswordRecovery(
      "learner@example.com",
      {
        activityIntent: activity,
        salesNext: SALES_XRAY_PATH,
      },
    );
    expect(bodies).toEqual([{ email: "learner@example.com" }]);

    const registerPassword = vi.fn(async () => ({
      status: "verification_required" as const,
    }));
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      registerPassword,
    } as unknown as apiModule.LearnerApi);
    await mount(
      <RegistrationForm
        activityIntent={activity}
        salesNext={SALES_XRAY_PATH}
      />,
    );
    await act(async () =>
      container
        .querySelector<HTMLInputElement>('input[name="consent"]')!
        .click(),
    );
    const form = container.querySelector<HTMLFormElement>("form")!;
    form.querySelector<HTMLInputElement>('[name="firstName"]')!.value =
      "Learner";
    form.querySelector<HTMLInputElement>('[name="email"]')!.value =
      "learner@example.com";
    form.querySelector<HTMLInputElement>('[name="whatsappNumber"]')!.value =
      "+12025550123";
    form.querySelector<HTMLInputElement>('[name="password"]')!.value =
      "twelve-characters-and-more";
    await act(async () =>
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      ),
    );
    expect(registerPassword).toHaveBeenCalledExactlyOnceWith({
      firstName: "Learner",
      email: "learner@example.com",
      whatsappNumber: "+12025550123",
      password: "twelve-characters-and-more",
      consent: true,
      activityIntent: activity,
    });
  });

  it("carries Sales from fresh verification and reset links to their next action", async () => {
    const verifyPasswordEmail = vi.fn(async () => ({
      authenticated: true as const,
      person_id: "person-1",
      email: "learner@example.com",
      display_name: "Learner",
    }));
    const resetPassword = vi.fn(async () => ({ reset: true as const }));
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      verifyPasswordEmail,
      resetPassword,
    } as unknown as apiModule.LearnerApi);

    window.history.replaceState(
      null,
      "",
      `/verify-email${salesQuery}#token=${token}`,
    );
    await mount(<VerifyEmailFlow salesNext={SALES_XRAY_PATH} />);
    await act(async () => await Promise.resolve());
    expect(
      container.querySelector('a[href^="/onboarding"]')?.getAttribute("href"),
    ).toBe("/onboarding?next=%2Fsales-xray");
    expect(verifyPasswordEmail).toHaveBeenCalledExactlyOnceWith(token);

    window.history.replaceState(
      null,
      "",
      `/reset-password${salesQuery}#token=${token}`,
    );
    await mount(<PasswordResetForm salesNext={SALES_XRAY_PATH} />);
    await act(async () => await Promise.resolve());
    const resetForm = container.querySelector<HTMLFormElement>("form")!;
    resetForm.querySelector<HTMLInputElement>("[name=password]")!.value =
      "a sufficiently long password";
    resetForm.querySelector<HTMLInputElement>("[name=passwordConfirm]")!.value =
      "a sufficiently long password";
    await act(async () =>
      resetForm.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      ),
    );
    expect(resetPassword).toHaveBeenCalledExactlyOnceWith(
      token,
      "a sufficiently long password",
    );
    expect(
      container.querySelector('a[href^="/login"]')?.getAttribute("href"),
    ).toBe("/login?next=%2Fsales-xray");
  });

  it("keeps callback recovery and onboarding completion bounded to Sales", async () => {
    const callback = renderToStaticMarkup(
      await CallbackPage({
        searchParams: Promise.resolve({
          result: "registration_required",
          next: SALES_XRAY_PATH,
        }),
      }),
    );
    expect(callback).toContain('href="/register?next=%2Fsales-xray"');
    expect(callback).toContain('href="/login?next=%2Fsales-xray"');

    const completion = renderToStaticMarkup(
      <OnboardingCompletionState
        status="skipped"
        returnHref={SALES_XRAY_PATH}
        cleanupPending={false}
        cleanupAcknowledged={false}
        onRetryLocalCleanup={() => {}}
        onCopyRecovery={() => {}}
        onExportRecovery={() => {}}
        onAcknowledgeRemainingCopy={() => {}}
        onEdit={() => {}}
      />,
    );
    expect(completion).toContain("Open Sales Xray");
    expect(completion).not.toContain("Open learner home");
  });

  it("routes password login through canonical onboarding before Sales", () => {
    expect(routeAfterOnboarding("completed", null, null, SALES_XRAY_PATH)).toBe(
      SALES_XRAY_PATH,
    );
    expect(routeAfterOnboarding("skipped", null, null, SALES_XRAY_PATH)).toBe(
      SALES_XRAY_PATH,
    );
    expect(
      routeAfterOnboarding("in_progress", null, null, SALES_XRAY_PATH),
    ).toBe("/onboarding?next=%2Fsales-xray");
  });

  it("keeps staging on its fixed origin and suppresses Sales behind course context", () => {
    const salesOnly = renderToStaticMarkup(
      <StagingAuthHandoff
        path="/register"
        action="Account creation"
        salesNext={SALES_XRAY_PATH}
      />,
    );
    expect(salesOnly).toContain(
      'href="https://staging.authorityclosers.com/register?next=%2Fsales-xray"',
    );

    const courseAndActivity = renderToStaticMarkup(
      <StagingAuthHandoff
        path="/register"
        action="Account creation"
        courseIntent={FREE_COURSE_SLUG}
        activityIntent={activity}
        salesNext={SALES_XRAY_PATH}
      />,
    );
    expect(courseAndActivity).toContain(
      `href="https://staging.authorityclosers.com/register?course=${FREE_COURSE_SLUG}&amp;activity=${activity}"`,
    );
    expect(courseAndActivity).not.toContain("next=");
  });
});
