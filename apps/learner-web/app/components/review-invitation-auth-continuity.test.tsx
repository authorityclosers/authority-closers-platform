// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as apiModule from "../lib/learner-api";
import { LoginForm } from "./login-form";
import {
  PasswordResetForm,
  RecoveryRequestForm,
  RegistrationForm,
  VerifyEmailFlow,
} from "./password-auth-forms";

const token = "invitation-fixture-" + "k".repeat(48);
const fragment = `#review_invitation=${token}`;
let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  (
    globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
  window.history.replaceState(null, "", `/login${fragment}`);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

function expectNoReviewerEntry() {
  expect(container.textContent).not.toMatch(
    /review invitation|invited email|open review|continue to review|return to invitation/i,
  );
  expect(container.querySelector('a[href*="review"]')).toBeNull();
  expect(container.innerHTML).not.toContain(token);
}

describe("learner authentication excludes reviewer handoffs", () => {
  it("returns a password reset to learner sign-in and clears unrelated invitation material", async () => {
    const resetPassword = vi.fn(async () => ({ password_reset: true }));
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      resetPassword,
    } as unknown as apiModule.LearnerApi);
    const resetToken = "reset-fixture-" + "r".repeat(43);
    window.history.replaceState(
      { __NA: true },
      "",
      `/reset-password${fragment}&token=${resetToken}`,
    );
    await act(async () => root.render(<PasswordResetForm />));
    expect(window.location.hash).toBe("");
    expect(window.history.state).toEqual({ __NA: true });
    const form = container.querySelector("form")!;
    form.querySelector<HTMLInputElement>('[name="password"]')!.value =
      "synthetic-password-for-test";
    form.querySelector<HTMLInputElement>('[name="passwordConfirm"]')!.value =
      "synthetic-password-for-test";
    await act(async () => {
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });
    expect(resetPassword).toHaveBeenCalledExactlyOnceWith(
      resetToken,
      "synthetic-password-for-test",
    );
    expect(container.querySelector('a[href="/login"]')).not.toBeNull();
    expectNoReviewerEntry();
  });

  it("keeps successful learner verification pointed at onboarding", async () => {
    const verifyPasswordEmail = vi.fn(async () => ({ authenticated: true }));
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      verifyPasswordEmail,
    } as unknown as apiModule.LearnerApi);
    const verificationToken = "verify-fixture-" + "v".repeat(43);
    window.history.replaceState(
      null,
      "",
      `/verify-email${fragment}&token=${verificationToken}`,
    );
    await act(async () => root.render(<VerifyEmailFlow />));
    expect(verifyPasswordEmail).toHaveBeenCalledExactlyOnceWith(
      verificationToken,
    );
    expect(window.location.hash).toBe("");
    expect(
      container.querySelector('a[href="/onboarding"]')?.textContent,
    ).toContain("Continue to onboarding");
    expectNoReviewerEntry();
  });
  it("ignores invitation fragments during learner sign-in and completes normal onboarding routing", async () => {
    const loginPassword = vi.fn(async () => ({}));
    const onboarding = vi.fn(async () => ({ status: "completed" }));
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      loginPassword,
      onboarding,
    } as unknown as apiModule.LearnerApi);
    const navigate = vi
      .spyOn(window.location, "assign")
      .mockImplementation(() => {});
    await act(async () => root.render(<LoginForm />));
    expect(container.querySelector('a[href="/register"]')).not.toBeNull();
    expect(
      container.querySelector('a[href="/forgot-password"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('a[href*="/v1/auth/google"]'),
    ).not.toBeNull();
    const form = container.querySelector("form")!;
    form.querySelector<HTMLInputElement>('[name="email"]')!.value =
      "reviewer@example.test";
    form.querySelector<HTMLInputElement>('[name="password"]')!.value =
      "synthetic-password-for-test";
    await act(async () => {
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });
    expect(loginPassword).toHaveBeenCalledExactlyOnceWith(
      "reviewer@example.test",
      "synthetic-password-for-test",
    );
    expect(onboarding).toHaveBeenCalledOnce();
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/home");
    expectNoReviewerEntry();
  });

  it("keeps learner registration and verification help free of reviewer UI while retaining consent", async () => {
    const registerPassword = vi.fn(async () => ({
      status: "verification_required",
    }));
    const verifyPasswordEmail = vi.fn();
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      registerPassword,
      verifyPasswordEmail,
    } as unknown as apiModule.LearnerApi);
    await act(async () => root.render(<RegistrationForm />));
    const form = container.querySelector("form")!;
    await act(async () => {
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });
    expect(registerPassword).not.toHaveBeenCalled();
    await act(async () =>
      form.querySelector<HTMLInputElement>('[name="consent"]')!.click(),
    );
    form.querySelector<HTMLInputElement>('[name="firstName"]')!.value =
      "Reviewer";
    form.querySelector<HTMLInputElement>('[name="email"]')!.value =
      "reviewer@example.test";
    form.querySelector<HTMLInputElement>('[name="whatsappNumber"]')!.value =
      "+12025550123";
    form.querySelector<HTMLInputElement>('[name="password"]')!.value =
      "synthetic-password-for-test";
    await act(async () => {
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });
    expect(registerPassword).toHaveBeenCalledWith(
      expect.objectContaining({ consent: true }),
    );
    expect(JSON.stringify(registerPassword.mock.calls)).not.toContain(token);
    expect(container.querySelector('a[href="/login"]')).not.toBeNull();
    expect(container.querySelector('a[href="/verify-email"]')).not.toBeNull();
    window.history.replaceState({ __NA: true }, "", `/verify-email${fragment}`);
    await act(async () => root.render(<VerifyEmailFlow />));
    expect(verifyPasswordEmail).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("");
    expect(window.history.state).toEqual({ __NA: true });
    expect(container.querySelector('a[href="/login"]')).not.toBeNull();
    expectNoReviewerEntry();
  });

  it("keeps recovery requests and completion links in the learner flow", async () => {
    const requestPasswordRecovery = vi.fn(async () => ({ accepted: true }));
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      requestPasswordRecovery,
    } as unknown as apiModule.LearnerApi);
    await act(async () => root.render(<RecoveryRequestForm />));
    const form = container.querySelector("form")!;
    form.querySelector<HTMLInputElement>('[name="email"]')!.value =
      "reviewer@example.test";
    await act(async () => {
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });
    expect(JSON.stringify(requestPasswordRecovery.mock.calls)).not.toContain(
      token,
    );
    expect(container.querySelector('a[href="/login"]')).not.toBeNull();
    expect(container.querySelector('a[href="/verify-email"]')).not.toBeNull();
    expectNoReviewerEntry();
  });
});
