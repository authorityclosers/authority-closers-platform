// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ForgotPasswordPage from "../forgot-password/page";
import ResetPasswordPage from "../reset-password/page";
import VerifyEmailPage from "../verify-email/page";
import {
  ApiError,
  createLearnerApi,
  type LearnerApi,
} from "../lib/learner-api";
import * as apiModule from "../lib/learner-api";
import { FREE_COURSE_SLUG } from "../lib/course-intent";
import * as bridge from "../lib/dev-api-proxy";
import { LoginForm } from "./login-form";
import {
  PasswordResetForm,
  RecoveryRequestForm,
  VerifyEmailFlow,
} from "./password-auth-forms";
import { StagingAuthHandoff } from "./staging-auth-handoff";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const activity = "86f7efee-f504-4d6f-b4bc-9b3cb84ba2be";
const course = FREE_COURSE_SLUG;
const query = `?course=${course}&activity=${activity}`;
const token = "t".repeat(43);

const pageContextCases = [
  {
    label: "course-only",
    searchParams: { course },
    query: `?course=${course}`,
  },
  {
    label: "course-and-activity",
    searchParams: { course, activity },
    query,
  },
] as const;

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("password email activity continuity", () => {
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

  it("sends only validated course and activity context with password email requests", async () => {
    const requests: Array<{ path: string; body: unknown }> = [];
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        requests.push({
          path: String(input),
          body: JSON.parse(String(init?.body)),
        });
        if (String(input).endsWith("/register")) {
          return response({ status: "verification_required" }, 202);
        }
        return response({ accepted: true });
      },
    );
    const api = createLearnerApi(fetcher);

    await api.registerPassword({
      firstName: "Learner",
      email: "learner@example.com",
      whatsappNumber: "+12025550123",
      password: "twelve-characters-and-more",
      consent: true,
      courseIntent: course,
      activityIntent: activity.toUpperCase(),
    });
    await api.registerPassword({
      firstName: "Course-only learner",
      email: "course-only@example.com",
      whatsappNumber: "+12025550124",
      password: "twelve-characters-and-more",
      consent: true,
      courseIntent: course,
    });
    await api.requestPasswordRecovery("learner@example.com", {
      courseIntent: course,
      activityIntent: activity,
    });
    await api.resendPasswordVerification("learner@example.com", {
      courseIntent: course,
      activityIntent: activity,
    });
    await api.requestPasswordRecovery("learner@example.com", {
      courseIntent: course,
    });

    expect(requests.map(({ body }) => body)).toEqual([
      {
        first_name: "Learner",
        email: "learner@example.com",
        whatsapp_number: "+12025550123",
        password: "twelve-characters-and-more",
        consent: true,
        consent_version: expect.any(String),
        course,
        activity,
      },
      {
        first_name: "Course-only learner",
        email: "course-only@example.com",
        whatsapp_number: "+12025550124",
        password: "twelve-characters-and-more",
        consent: true,
        consent_version: expect.any(String),
        course,
      },
      { email: "learner@example.com", course, activity },
      { email: "learner@example.com", course, activity },
      { email: "learner@example.com", course },
    ]);
  });

  it("preserves a course-only intent in auth recovery links", () => {
    const login = renderToStaticMarkup(<LoginForm courseIntent={course} />);
    expect(login).toContain(`href="/forgot-password?course=${course}"`);
    expect(login).not.toContain("activity=");
  });

  it("shows pending verification guidance when opened without a token", async () => {
    const resendPasswordVerification = vi.fn(async () => ({ accepted: true }));
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      resendPasswordVerification,
    } as unknown as LearnerApi);

    window.history.replaceState(null, "", "/verify-email");
    await mount(<VerifyEmailFlow />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.querySelector("h2")?.textContent).toBe(
      "Check your inbox.",
    );
    expect(container.textContent).toContain("request a fresh link below");
    expect(container.textContent).not.toContain("Link unavailable.");
    const form = container.querySelector<HTMLFormElement>("form")!;
    form.querySelector<HTMLInputElement>("[name=email]")!.value =
      "learner@example.com";
    await act(async () =>
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      ),
    );
    expect(resendPasswordVerification).toHaveBeenCalledExactlyOnceWith(
      "learner@example.com",
    );
    expect(container.textContent).toContain("pending verification");
  });

  it("keeps an invalid token in the unavailable-link state", async () => {
    const verifyPasswordEmail = vi.fn(async () => {
      throw new ApiError(400, "This verification link is invalid or expired.");
    });
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      verifyPasswordEmail,
    } as unknown as LearnerApi);

    window.history.replaceState(null, "", `/verify-email#token=${token}`);
    await mount(<VerifyEmailFlow />);
    await act(async () => await Promise.resolve());

    expect(container.querySelector("h2")?.textContent).toBe(
      "Link unavailable.",
    );
    expect(container.textContent).not.toContain("Check your inbox.");
    expect(container.textContent).toContain("invalid or expired");
  });

  it("uses neutral recovery confirmation and links pending verification to resend", async () => {
    const requestPasswordRecovery = vi.fn(async () => ({ accepted: true }));
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      requestPasswordRecovery,
    } as unknown as LearnerApi);

    await mount(
      <RecoveryRequestForm courseIntent={course} activityIntent={activity} />,
    );
    const form = container.querySelector<HTMLFormElement>("form")!;
    form.querySelector<HTMLInputElement>("[name=email]")!.value =
      "learner@example.com";
    await act(async () =>
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      ),
    );

    expect(requestPasswordRecovery).toHaveBeenCalledExactlyOnceWith(
      "learner@example.com",
      { courseIntent: course, activityIntent: activity, salesNext: null },
    );
    expect(container.textContent).toContain("account recovery email");
    expect(container.textContent).not.toContain("active account");
    expect(container.textContent).not.toContain("30-minute");
    expect(
      container
        .querySelector<HTMLAnchorElement>('a[href^="/verify-email"]')
        ?.getAttribute("href"),
    ).toBe(`/verify-email?course=${course}&activity=${activity}`);
  });

  it("keeps the validated context in login and staging auth links", () => {
    const login = renderToStaticMarkup(
      <LoginForm courseIntent={course} activityIntent={activity} />,
    );
    expect(login).toContain(
      `href="/forgot-password?course=${course}&amp;activity=${activity}"`,
    );

    for (const path of [
      "/forgot-password",
      "/verify-email",
      "/reset-password",
    ] as const) {
      const handoff = renderToStaticMarkup(
        <StagingAuthHandoff
          path={path}
          action="Auth"
          courseIntent={course}
          activityIntent={activity}
        />,
      );
      expect(handoff).toContain(
        `href="https://staging.authorityclosers.com${path}?course=${course}&amp;activity=${activity}"`,
      );
    }
  });

  it("preserves context when the verification link reaches its success action", async () => {
    window.history.replaceState(
      null,
      "",
      `/verify-email${query}#token=${token}`,
    );
    const verifyPasswordEmail = vi.fn(async () => ({
      authenticated: true,
      person_id: "person-1",
      email: "learner@example.com",
      display_name: "Learner",
    }));
    vi.spyOn(bridge, "isStagingAuthenticatedBridge").mockReturnValue(false);
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      verifyPasswordEmail,
    } as unknown as LearnerApi);

    await mount(
      <VerifyEmailFlow courseIntent={course} activityIntent={activity} />,
    );
    await act(async () => await Promise.resolve());

    expect(container.querySelector("a")?.getAttribute("href")).toBe(
      `/onboarding${query}`,
    );
    expect(verifyPasswordEmail).toHaveBeenCalledExactlyOnceWith(token);
  });

  it.each(pageContextCases)(
    "passes $label query context through the VerifyEmailPage wrapper",
    async ({ searchParams, query: expectedQuery }) => {
      window.history.replaceState(
        null,
        "",
        `/verify-email${expectedQuery}#token=${token}`,
      );
      const verifyPasswordEmail = vi.fn(async () => ({
        authenticated: true,
        person_id: "person-1",
        email: "learner@example.com",
        display_name: "Learner",
      }));
      vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
        verifyPasswordEmail,
      } as unknown as LearnerApi);

      await mount(
        VerifyEmailPage({ searchParams: Promise.resolve(searchParams) }),
      );
      await act(async () => await Promise.resolve());

      expect(container.querySelector("a.button")?.getAttribute("href")).toBe(
        `/onboarding${expectedQuery}`,
      );
      expect(verifyPasswordEmail).toHaveBeenCalledExactlyOnceWith(token);
    },
  );

  it("preserves context after an explicit password reset", async () => {
    window.history.replaceState(
      null,
      "",
      `/reset-password${query}#token=${token}`,
    );
    const resetPassword = vi.fn(async () => ({ reset: true }));
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      resetPassword,
    } as unknown as LearnerApi);

    await mount(
      <PasswordResetForm courseIntent={course} activityIntent={activity} />,
    );
    await act(async () => await Promise.resolve());
    const form = container.querySelector<HTMLFormElement>("form")!;
    form.querySelector<HTMLInputElement>("[name=password]")!.value =
      "a sufficiently long password";
    form.querySelector<HTMLInputElement>("[name=passwordConfirm]")!.value =
      "a sufficiently long password";
    await act(async () =>
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      ),
    );

    expect(resetPassword).toHaveBeenCalledExactlyOnceWith(
      token,
      "a sufficiently long password",
    );
    expect(container.querySelector("a")?.getAttribute("href")).toBe(
      `/login${query}`,
    );
  });

  it.each(pageContextCases)(
    "passes $label query context through the ResetPasswordPage wrapper",
    async ({ searchParams, query: expectedQuery }) => {
      window.history.replaceState(
        null,
        "",
        `/reset-password${expectedQuery}#token=${token}`,
      );
      const resetPassword = vi.fn(async () => ({ reset: true }));
      vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
        resetPassword,
      } as unknown as LearnerApi);

      await mount(
        ResetPasswordPage({ searchParams: Promise.resolve(searchParams) }),
      );
      await act(async () => await Promise.resolve());
      const form = container.querySelector<HTMLFormElement>("form")!;
      form.querySelector<HTMLInputElement>("[name=password]")!.value =
        "a sufficiently long password";
      form.querySelector<HTMLInputElement>("[name=passwordConfirm]")!.value =
        "a sufficiently long password";
      await act(async () =>
        form.dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        ),
      );

      expect(resetPassword).toHaveBeenCalledExactlyOnceWith(
        token,
        "a sufficiently long password",
      );
      expect(container.querySelector("a.button")?.getAttribute("href")).toBe(
        `/login${expectedQuery}`,
      );
    },
  );

  it("drops malformed and duplicate query arrays before both email flows", async () => {
    const searchParams = {
      course: [course, course],
      activity: ["not-a-uuid", "not-a-uuid"],
    };
    const verifyPasswordEmail = vi.fn(async () => ({
      authenticated: true,
      person_id: "person-1",
      email: "learner@example.com",
      display_name: "Learner",
    }));
    const resetPassword = vi.fn(async () => ({ reset: true }));
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      verifyPasswordEmail,
      resetPassword,
    } as unknown as LearnerApi);

    window.history.replaceState(null, "", `/verify-email#token=${token}`);
    await mount(
      VerifyEmailPage({ searchParams: Promise.resolve(searchParams) }),
    );
    await act(async () => await Promise.resolve());
    expect(container.querySelector("a.button")?.getAttribute("href")).toBe(
      "/onboarding",
    );
    expect(verifyPasswordEmail).toHaveBeenCalledExactlyOnceWith(token);

    window.history.replaceState(null, "", `/reset-password#token=${token}`);
    await mount(
      ResetPasswordPage({ searchParams: Promise.resolve(searchParams) }),
    );
    await act(async () => await Promise.resolve());
    const form = container.querySelector<HTMLFormElement>("form")!;
    form.querySelector<HTMLInputElement>("[name=password]")!.value =
      "a sufficiently long password";
    form.querySelector<HTMLInputElement>("[name=passwordConfirm]")!.value =
      "a sufficiently long password";
    await act(async () =>
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      ),
    );
    expect(resetPassword).toHaveBeenCalledExactlyOnceWith(
      token,
      "a sufficiently long password",
    );
    expect(container.querySelector("a.button")?.getAttribute("href")).toBe(
      "/login",
    );
  });

  it("passes page query context into the fixed staging recovery destination", async () => {
    vi.mocked(bridge.isStagingAuthenticatedBridge).mockReturnValue(true);
    const page = renderToStaticMarkup(
      await ForgotPasswordPage({
        searchParams: Promise.resolve({ course, activity }),
      }),
    );
    expect(page).toContain(
      `href="https://staging.authorityclosers.com/forgot-password?course=${course}&amp;activity=${activity}"`,
    );
  });
});
