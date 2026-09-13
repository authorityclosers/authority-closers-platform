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

const meOne: MeResponse = {
  person_id: "settings-google-one",
  display_name: "First learner",
  email: "one@example.invalid",
  email_verified_at: "2026-09-07T00:00:00Z",
  selected_tenant_id: "settings-tenant",
  membership_role: "learner",
  permissions: [],
};
const meTwo: MeResponse = {
  ...meOne,
  person_id: "settings-google-two",
  display_name: "Second learner",
  email: "two@example.invalid",
};
const onboarding: OnboardingResponse = {
  person_id: meOne.person_id,
  experience_context: "sales",
  learning_goal: "Thoughtful conversations",
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

beforeEach(() => {
  window.history.replaceState(null, "", "/settings");
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

function makeApi(
  identity: MeResponse,
  googleLinkStatus: LearnerApi["googleLinkStatus"],
): LearnerApi {
  return {
    me: vi.fn(async () => identity),
    onboarding: vi.fn(async () => onboarding),
    googleLinkStatus,
    logout: vi.fn(async () => undefined),
  } as unknown as LearnerApi;
}

async function render(api: LearnerApi) {
  await act(async () => root.render(<SettingsRuntime api={api} />));
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function openCategory(id: string) {
  const link = container.querySelector<HTMLAnchorElement>(`a[href="#${id}"]`);
  expect(link).not.toBeNull();
  await act(async () => link!.click());
}

describe("mounted Google-link settings behavior", () => {
  it("refreshes Google status when onboarding retry cancels the shared load", async () => {
    let rejectOnboardingOne!: (error: unknown) => void;
    let rejectOnboardingTwo!: (error: unknown) => void;
    let resolveGoogleOne!: (value: { linked: boolean }) => void;
    let resolveGoogleTwo!: (value: { linked: boolean }) => void;
    let onboardingCalls = 0;
    let googleCalls = 0;
    const api = {
      me: vi.fn(async () => meOne),
      onboarding: vi.fn(
        () =>
          new Promise<OnboardingResponse>((resolve, reject) => {
            onboardingCalls += 1;
            if (onboardingCalls === 1) rejectOnboardingOne = reject;
            else rejectOnboardingTwo = reject;
            void resolve;
          }),
      ),
      googleLinkStatus: vi.fn(
        () =>
          new Promise<{ linked: boolean }>((resolve) => {
            googleCalls += 1;
            if (googleCalls === 1) resolveGoogleOne = resolve;
            else resolveGoogleTwo = resolve;
          }),
      ),
      logout: vi.fn(async () => undefined),
    } as unknown as LearnerApi;

    await render(api);
    await flush();
    expect(api.googleLinkStatus).toHaveBeenCalledTimes(1);

    await openCategory("learning-setup");
    await act(async () => rejectOnboardingOne(new Error("temporary")));
    await flush();
    const retry = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Retry learning setup"),
    );
    expect(retry).not.toBeUndefined();
    await act(async () => retry!.click());
    await flush();
    expect(api.googleLinkStatus).toHaveBeenCalledTimes(2);

    await act(async () => resolveGoogleOne({ linked: true }));
    await flush();
    await openCategory("security-privacy");
    expect(container.querySelector('[aria-label="Google linked"]')).toBeNull();

    await act(async () => resolveGoogleTwo({ linked: false }));
    await flush();
    expect(
      container.querySelector('[aria-label="Google not linked"]'),
    ).not.toBeNull();
    await act(async () => rejectOnboardingTwo(new Error("cleanup")));
  });

  it("drops a late status from the previous identity generation", async () => {
    let resolveGoogleOne!: (value: { linked: boolean }) => void;
    let resolveGoogleTwo!: (value: { linked: boolean }) => void;
    const apiOne = makeApi(
      meOne,
      vi.fn(
        () =>
          new Promise<{ linked: boolean }>((resolve) => {
            resolveGoogleOne = resolve;
          }),
      ),
    );
    const apiTwo = makeApi(
      meTwo,
      vi.fn(
        () =>
          new Promise<{ linked: boolean }>((resolve) => {
            resolveGoogleTwo = resolve;
          }),
      ),
    );

    await render(apiOne);
    await flush();
    await render(apiTwo);
    await flush();
    await act(async () => resolveGoogleOne({ linked: true }));
    await flush();
    expect(container.textContent).toContain("Second learner");
    expect(container.querySelector('[aria-label="Google linked"]')).toBeNull();

    await act(async () => resolveGoogleTwo({ linked: false }));
    await flush();
    expect(
      container.querySelector('[aria-label="Google not linked"]'),
    ).not.toBeNull();
  });
});
