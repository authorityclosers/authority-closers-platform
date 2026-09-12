// @vitest-environment happy-dom
import { act } from "react";
import { hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FREE_COURSE_SLUG } from "../lib/course-intent";
import * as apiModule from "../lib/learner-api";
import { LEARNER_POLICY_VERSION } from "../lib/learner-policy";
import { RegistrationForm } from "./password-auth-forms";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root | undefined;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
});
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  root = undefined;
  container.remove();
  vi.restoreAllMocks();
});

function forms() {
  const all = container.querySelectorAll("form");
  expect(all).toHaveLength(2);
  return { password: all[0]!, google: all[1]! };
}

it.each([null, FREE_COURSE_SLUG] as const)(
  "keeps server-rendered registration inert and credentials out of GET for course %s",
  (courseIntent) => {
    const createApi = vi.spyOn(apiModule, "createLearnerApi");
    container.innerHTML = renderToString(
      <RegistrationForm courseIntent={courseIntent} />,
    );
    const { password, google } = forms();
    expect(password.method).toBe("post");
    const controls = password.querySelectorAll<
      HTMLInputElement | HTMLButtonElement
    >("input, button");
    expect(controls).toHaveLength(7);
    for (const control of controls) expect(control.disabled).toBe(true);
    expect(
      google.querySelector<HTMLInputElement>('input[name="consent"]')!.disabled,
    ).toBe(true);
    expect(google.querySelector("button")!.disabled).toBe(true);
    expect(new FormData(google).has("consent_version")).toBe(false);

    // Even values restored by the browser remain unsuccessful disabled controls.
    password.querySelector<HTMLInputElement>('[name="email"]')!.value =
      "learner@example.test";
    password.querySelector<HTMLInputElement>('[name="password"]')!.value =
      "synthetic-test-password";
    expect([...new FormData(password).entries()]).toEqual([]);
    password
      .querySelector<HTMLButtonElement>('button:not([type="button"])')!
      .click();
    password.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    expect(createApi).not.toHaveBeenCalled();
  },
);

it.each([null, FREE_COURSE_SLUG] as const)(
  "hydrates registration without granting Google consent for course %s",
  async (courseIntent) => {
    container.innerHTML = renderToString(
      <RegistrationForm courseIntent={courseIntent} />,
    );
    await act(async () => {
      root = hydrateRoot(
        container,
        <RegistrationForm courseIntent={courseIntent} />,
      );
    });
    const { password, google } = forms();
    expect(password.method).toBe("post");
    for (const control of password.querySelectorAll<
      HTMLInputElement | HTMLButtonElement
    >("input, button")) {
      expect(control.disabled).toBe(false);
    }
    const consent = password.querySelector<HTMLInputElement>(
      'input[name="consent"]',
    )!;
    const googleButton = google.querySelector("button")!;
    expect(consent.checked).toBe(false);
    expect(googleButton.disabled).toBe(true);
    expect(new FormData(google).has("consent")).toBe(false);
    expect(new FormData(google).has("consent_version")).toBe(false);

    await act(async () => consent.click());
    expect(consent.checked).toBe(true);
    expect(googleButton.disabled).toBe(false);
    expect(google.method).toBe("get");
    const returnPath = courseIntent
      ? `/onboarding?course=${courseIntent}`
      : "/onboarding";
    expect(new FormData(google).getAll("return_path")).toEqual([returnPath]);
    expect([...new FormData(google).entries()]).toEqual([
      ["action", "register"],
      ["surface", "learner"],
      ["return_path", returnPath],
      ["consent", "true"],
      ["consent_version", LEARNER_POLICY_VERSION],
    ]);
    const toggle = password.querySelector<HTMLButtonElement>(
      'button[type="button"]',
    )!;
    await act(async () => toggle.click());
    expect(
      password.querySelector<HTMLInputElement>('[name="password"]')!.type,
    ).toBe("text");
    expect(toggle.getAttribute("aria-pressed")).toBe("true");

    await act(async () => consent.click());
    expect(consent.checked).toBe(false);
    expect(googleButton.disabled).toBe(true);
    expect(new FormData(google).has("consent")).toBe(false);
    expect(new FormData(google).has("consent_version")).toBe(false);
  },
);

it("requires explicit consent before the hydrated password submit calls the API", async () => {
  const registerPassword = vi.fn(async () => ({
    status: "verification_required",
  }));
  vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
    registerPassword,
  } as unknown as apiModule.LearnerApi);
  container.innerHTML = renderToString(<RegistrationForm />);
  await act(async () => {
    root = hydrateRoot(container, <RegistrationForm />);
  });
  const { password } = forms();
  for (const [name, value] of Object.entries({
    firstName: "Learner",
    email: "learner@example.test",
    whatsappNumber: "+12025550123",
    password: "synthetic-test-password",
  })) {
    password.querySelector<HTMLInputElement>(`[name="${name}"]`)!.value = value;
  }
  const submit = () =>
    password.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  await act(async () => {
    expect(submit()).toBe(false);
  });
  expect(registerPassword).not.toHaveBeenCalled();
  await act(async () =>
    password.querySelector<HTMLInputElement>('[name="consent"]')!.click(),
  );
  await act(async () => {
    expect(submit()).toBe(false);
  });
  expect(registerPassword).toHaveBeenCalledExactlyOnceWith({
    firstName: "Learner",
    email: "learner@example.test",
    whatsappNumber: "+12025550123",
    password: "synthetic-test-password",
    consent: true,
  });
  expect(container.textContent).toContain("Check your inbox.");
});
