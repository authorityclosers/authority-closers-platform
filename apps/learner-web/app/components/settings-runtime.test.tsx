import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../lib/learner-api";
import type { OnboardingRecoveryLockManager } from "../lib/local-drafts";
import {
  SettingsView,
  clearUnavailableMembershipLearnerLocalDrafts,
  createSettingsDraftCleanupController,
  startSettingsResourceLoad,
  type SettingsResources,
} from "./settings-runtime";
import { ThemeControl } from "./theme-control";

const me = {
  person_id: "person-1",
  email: "alex@example.com",
  display_name: "Alex Morgan",
  email_verified_at: "2026-09-01T00:00:00Z",
  selected_tenant_id: "tenant-1",
  membership_role: "learner",
  permissions: [],
};

const onboarding = {
  person_id: "person-1",
  experience_context: "sales",
  learning_goal: "Close more confidently",
  practice_situation: null,
  weekly_minutes: 30,
  status: "completed" as const,
  current_step: 3,
  revision: 2,
  updated_at: "2026-09-01T00:00:00Z",
  next_action_href: "/home",
  next_action_reason: "learning_profile_complete",
};

const api = {
  me: vi.fn(async () => me),
  onboarding: vi.fn(async () => onboarding),
  logout: vi.fn(async () => undefined),
} as never;

const availableLockManager: OnboardingRecoveryLockManager = {
  async request<T>(
    _name: string,
    _options: { mode: "exclusive"; ifAvailable: true },
    callback: (lock: unknown | null) => Promise<unknown> | unknown,
  ): Promise<T> {
    return (await callback({})) as T;
  },
};

function readyResources(): SettingsResources {
  return {
    me: { status: "ready", data: me },
    onboarding: { status: "ready", data: onboarding },
  };
}

describe("Settings Direction B runtime", () => {
  it("renders the ready ledger with only current Settings capabilities", () => {
    const html = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: readyResources(),
        api,
        onRetry: vi.fn(),
      }),
    );

    expect(html.match(/<h1(?:\s|>)/g)).toHaveLength(1);
    expect(html).toContain("Settings");
    expect(html).toContain('id="settings-title"');
    expect(html).toContain('tabindex="-1"');
    expect(html).toContain("Alex Morgan");
    expect(html).toContain("alex@example.com");
    expect(html).toContain("Verified");
    expect(html).toContain("Close more confidently");
    expect(html).toContain("Edit learning setup");
    expect(html).toContain('href="/onboarding?return=settings"');
    expect(html).toContain('href="/forgot-password"');
    expect(html).toContain('href="/terms"');
    expect(html).toContain('href="/privacy"');
    expect(html).toContain('aria-pressed="true"');
    expect(html).not.toContain("indexLinkCurrent");
    expect(html).not.toContain('aria-current="page"');
    expect(html).not.toMatch(
      /avatar|notification|marketing|payment|delete account/i,
    );
  });

  it("keeps identity and appearance usable when learning setup fails", () => {
    const html = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: {
          me: { status: "ready", data: me },
          onboarding: { status: "error", error: new TypeError("offline") },
        },
        api,
        onRetry: vi.fn(),
      }),
    );

    expect(html).toContain("Alex Morgan");
    expect(html).toContain("Learning setup unavailable");
    expect(html).toContain("Retry learning setup");
    expect(html).toContain("Appearance");
    expect(html).toContain("Security &amp; privacy");
    expect(html).not.toContain("Settings could not open");
  });

  it("does not render learning data when identity fails before authorization", () => {
    const html = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: {
          me: { status: "error", error: new TypeError("offline") },
          onboarding: { status: "ready", data: onboarding },
        },
        api,
        onRetry: vi.fn(),
      }),
    );

    expect(html).toContain("Verified account unavailable");
    expect(html).toContain(
      "Learning setup will appear after learner access is confirmed.",
    );
    expect(html).not.toContain("Sales");
    expect(html).not.toContain("Close more confidently");
  });

  it("renders only the reauthentication boundary for an expired identity", () => {
    const html = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: {
          me: { status: "error", error: new ApiError(401, "expired") },
          onboarding: { status: "ready", data: onboarding },
        },
        api,
        onRetry: vi.fn(),
      }),
    );

    expect(html).toContain("Sign in to continue.");
    expect(html).toContain('href="/session-expired"');
    expect(html).not.toContain("Alex Morgan");
    expect(html).not.toContain("Close more confidently");
    expect(html).not.toContain("Appearance");
    expect(html).not.toContain("Sign out");
  });

  it("loads onboarding only after exact learner identity authorization", async () => {
    let resolveMe!: (value: typeof me) => void;
    let rejectOnboarding!: (error: unknown) => void;
    const updates: string[] = [];
    const onboardingRequest = vi.fn(
      () =>
        new Promise<typeof onboarding>((_, reject) => {
          rejectOnboarding = reject;
        }),
    );
    const clean = startSettingsResourceLoad(
      {
        me: () => new Promise((resolve) => (resolveMe = resolve)),
        onboarding: onboardingRequest,
      },
      (resource, result) => updates.push(`${resource}:${result.status}`),
    );

    expect(updates).toEqual([]);
    expect(onboardingRequest).not.toHaveBeenCalled();
    resolveMe(me);
    await Promise.resolve();
    expect(updates).toEqual(["me:ready"]);
    expect(onboardingRequest).toHaveBeenCalledTimes(1);
    clean();
    rejectOnboarding(new TypeError("offline"));
    await Promise.resolve();
    expect(updates).toEqual(["me:ready"]);
  });

  it("suppresses onboarding when identity resolves without learner membership", async () => {
    const nonLearner = { ...me, membership_role: "admin" };
    const onboardingRequest = vi.fn(async () => onboarding);
    const updates: string[] = [];

    startSettingsResourceLoad(
      {
        me: async () => nonLearner,
        onboarding: onboardingRequest,
      },
      (resource, result) => updates.push(resource + ":" + result.status),
    );
    await Promise.resolve();

    expect(updates).toEqual(["me:ready"]);
    expect(onboardingRequest).not.toHaveBeenCalled();
  });

  it("clears bounded learner drafts for unavailable membership and reports cleanup failure", async () => {
    const values = new Map([
      ["ac-learner-local-draft:onboarding:person-1", "draft"],
      ["unrelated-key", "keep"],
    ]);
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => void values.set(key, value),
      removeItem: (key: string) => void values.delete(key),
      key: (index: number) => Array.from(values.keys())[index] ?? null,
      get length() {
        return values.size;
      },
    } as Storage;

    expect(
      await clearUnavailableMembershipLearnerLocalDrafts(
        { localStorage: storage },
        "person-1",
        availableLockManager,
      ),
    ).toEqual({ ok: true });
    expect(values.has("ac-learner-local-draft:onboarding:person-1")).toBe(
      false,
    );
    expect(values.has("unrelated-key")).toBe(true);

    const failingStorage = {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
      key: () => {
        throw new Error("storage unavailable");
      },
      length: 1,
    } as unknown as Storage;
    const cleanup = await clearUnavailableMembershipLearnerLocalDrafts(
      { localStorage: failingStorage },
      "person-1",
      availableLockManager,
    );
    const cleanupReason = cleanup.ok ? "unavailable" : cleanup.reason;
    const html = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: {
          me: {
            status: "ready",
            data: { ...me, membership_role: "admin" },
          },
          onboarding: { status: "loading" },
        },
        draftCleanup: { status: "failure", reason: cleanupReason },
        api,
        onRetry: vi.fn(),
      }),
    );

    expect(cleanup).toEqual({ ok: false, reason: "unavailable" });
    expect(html).toContain("could not remove");
    expect(html).toContain("Retry cleanup");
  });

  it("does not purge drafts when membership cleanup has no resolved person", async () => {
    const values = new Map([
      ["ac-learner-local-draft:onboarding:person-1", "person one"],
      ["ac-learner-local-draft:onboarding:person-2", "person two"],
    ]);
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => void values.set(key, value),
      removeItem: (key: string) => void values.delete(key),
      key: (index: number) => Array.from(values.keys())[index] ?? null,
      get length() {
        return values.size;
      },
    } as Storage;

    expect(
      await clearUnavailableMembershipLearnerLocalDrafts(
        { localStorage: storage },
        null,
      ),
    ).toEqual({ ok: false, reason: "unavailable" });
    expect(values.size).toBe(2);
  });

  it("does not let stale or unmounted cleanup results overwrite current state", async () => {
    const requests: Array<{
      personId: string;
      resolve: (
        value: { ok: true } | { ok: false; reason: "unavailable" },
      ) => void;
    }> = [];
    const cleanup = vi.fn(
      (personId: string) =>
        new Promise<{ ok: true } | { ok: false; reason: "unavailable" }>(
          (resolve) => requests.push({ personId, resolve }),
        ),
    );
    const states: string[] = [];
    const controller = createSettingsDraftCleanupController(cleanup, (state) =>
      states.push(state.status),
    );

    controller.start("person-1");
    controller.retry("person-1");
    expect(cleanup).toHaveBeenCalledTimes(1);
    expect(states).toEqual(["pending"]);

    controller.invalidate();
    controller.start("person-2");
    expect(cleanup).toHaveBeenCalledWith("person-2");
    requests[0]?.resolve({ ok: true });
    await Promise.resolve();
    expect(states).toEqual(["pending", "pending"]);

    requests[1]?.resolve({ ok: true });
    await Promise.resolve();
    expect(states).toEqual(["pending", "pending", "success"]);

    controller.start("person-3");
    expect(cleanup).toHaveBeenCalledWith("person-3");
    controller.dispose();
    requests[2]?.resolve({ ok: true });
    await Promise.resolve();
    expect(states).toEqual(["pending", "pending", "success", "pending"]);
  });

  it("renders Light as the first-load theme while keeping all explicit choices", () => {
    const html = renderToStaticMarkup(createElement(ThemeControl));

    expect(html).toContain('aria-label="Appearance theme"');
    expect(html).toContain('aria-pressed="true"');
    expect(html).toMatch(/aria-pressed="true"[^>]*>[\s\S]*Light/);
    expect(html).toContain("Dark");
    expect(html).toContain("System");
  });
});
