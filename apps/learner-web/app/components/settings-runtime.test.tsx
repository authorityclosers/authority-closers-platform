import { createElement } from "react";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../lib/learner-api";
import type { OnboardingRecoveryLockManager } from "../lib/local-drafts";
import { markOfflineRead } from "../lib/offline-read-cache";
import { SETTINGS_SECTIONS } from "../lib/settings-registry";
import {
  SettingsView,
  clearUnavailableMembershipLearnerLocalDrafts,
  createSettingsDraftCleanupController,
  startSettingsResourceLoad,
  searchSettingsSections,
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

function readyResources(
  googleLink?: SettingsResources["googleLink"],
): SettingsResources {
  return {
    me: { status: "ready", data: me },
    onboarding: { status: "ready", data: onboarding },
    ...(googleLink ? { googleLink } : {}),
  };
}

describe("Focused Settings runtime", () => {
  it("renders one focused category with only current Settings capabilities", () => {
    const html = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: readyResources(),
        api,
        onRetry: vi.fn(),
      }),
    );

    expect(html.match(/<h1(?:\s|>)/g)).toHaveLength(1);
    expect(html).toContain("Settings");
    expect(html).toContain('aria-label="Search settings"');
    expect(html).not.toContain("Account control surface");
    expect(html).not.toContain("first-slice");
    expect(html).toContain("Setup &amp; preferences");
    expect(html).toContain("Security &amp; access");
    expect(html.match(/<h2 id="settings-group-/g)).toHaveLength(3);
    expect(
      html.match(/<section[^>]*aria-labelledby="settings-group-/g),
    ).toHaveLength(3);
    expect(html).toContain('id="settings-title"');
    expect(html).toContain('tabindex="-1"');
    expect(html).toContain("Alex Morgan");
    expect(html).toContain("alex@example.com");
    expect(html).toContain("Verified");
    expect(html).toContain("Close more confidently");
    expect(html).toContain("Edit learning setup");
    expect(html).toContain('aria-current="location"');
    expect(html).not.toContain('aria-current="page"');
    expect(html).toMatch(/<nav[^>]*aria-label="Settings sections"/);
    expect(html).not.toMatch(
      /avatar|notification|marketing|payment|delete account|mfa|sso|\bai\b|playback|tenant.?branding/i,
    );
  });

  it("keeps ordered operation owners mounted and hides every inactive category", () => {
    const html = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: readyResources(),
        api,
        onRetry: vi.fn(),
      }),
    );
    const expectedAnchors = SETTINGS_SECTIONS.map((section) => section.anchor);
    const indexAnchors = Array.from(html.matchAll(/href="#([^\"]+)"/g)).map(
      (match) => match[1],
    );
    const cardAnchors = Array.from(
      html.matchAll(/<section[^>]*\sid="([^\"]+)"/g),
    ).map((match) => match[1]);

    expect(indexAnchors).toEqual(expectedAnchors);
    expect(cardAnchors).toEqual(expectedAnchors);
    expect(
      html.match(/<div hidden="" data-settings-category="true">/g),
    ).toHaveLength(4);
    for (const section of SETTINGS_SECTIONS) {
      const selected = renderToStaticMarkup(
        createElement(SettingsView, {
          resources: readyResources(),
          api,
          onRetry: vi.fn(),
          initialSection: section.id,
        }),
      );
      expect(selected).toContain(`id="${section.headingId}"`);
      expect(selected).toContain(`aria-labelledby="${section.headingId}"`);
      expect(
        Array.from(selected.matchAll(/<section[^>]*\sid="([^\"]+)"/g)).map(
          (match) => match[1],
        ),
      ).toEqual(expectedAnchors);
      expect(
        selected.match(/<div hidden="" data-settings-category="true">/g),
      ).toHaveLength(4);
      expect(selected).toMatch(
        new RegExp(
          `<div data-settings-category="true"><section[^>]*id="${section.id}"`,
        ),
      );
    }
  });

  it("searches category and control keywords without creating new capabilities", () => {
    expect(searchSettingsSections("  ")).toEqual(SETTINGS_SECTIONS);
    expect(
      searchSettingsSections("dark motion").map((section) => section.id),
    ).toEqual(["appearance"]);
    expect(
      searchSettingsSections("PASSWORD").map((section) => section.id),
    ).toEqual(["security-privacy"]);
    expect(
      searchSettingsSections("weekly").map((section) => section.id),
    ).toEqual(["learning-setup"]);
    expect(searchSettingsSections("billing")).toEqual([]);
  });

  it("offers an exact authenticated Google-link action without claiming provider state", () => {
    const html = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: readyResources(),
        api,
        onRetry: vi.fn(),
        initialSection: "security-privacy",
      }),
    );
    const link = html.match(
      /<a href="([^\"]*auth\/google\/start[^\"]*)">\s*<span>Link Google account/s,
    )?.[1];
    expect(link).toBeDefined();
    const url = new URL(
      link!.replaceAll("&amp;", "&"),
      "https://app.authorityclosers.com",
    );
    expect(Object.fromEntries(url.searchParams)).toEqual({
      action: "link",
      surface: "learner",
      return_path: "/settings",
    });
    expect(html).toContain("Google confirmation returns you here");
    expect(html).toContain("this account remains unchanged");
    expect(html).not.toMatch(/Google (?:account )?is linked|linked Google/i);
  });

  it.each([
    { linked: true, label: "Google linked", copy: "Google is linked" },
    { linked: false, label: "Google not linked", copy: "Google is not linked" },
  ])(
    "exposes only the canonical Google-link state: $label",
    ({ linked, label, copy }) => {
      const html = renderToStaticMarkup(
        createElement(SettingsView, {
          resources: readyResources({ status: "ready", data: { linked } }),
          api,
          onRetry: vi.fn(),
          initialSection: "security-privacy",
        }),
      );

      expect(html).toContain(`aria-label="${label}"`);
      expect(html).toContain(copy);
      expect(html).toContain("Link Google account");
    },
  );

  it("keeps the Google action and status fail-closed until live identity is ready", () => {
    const loading = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: {
          me: { status: "loading" },
          onboarding: { status: "loading" },
          googleLink: { status: "ready", data: { linked: true } },
        },
        api,
        onRetry: vi.fn(),
        initialSection: "security-privacy",
      }),
    );
    expect(loading).not.toContain("auth/google/start");
    expect(loading).not.toContain("Google linked");

    const cachedMe = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: {
          me: { status: "ready", data: markOfflineRead({ ...me }, 7_000) },
          onboarding: { status: "ready", data: onboarding },
          googleLink: { status: "ready", data: { linked: true } },
        },
        api,
        onRetry: vi.fn(),
        initialSection: "security-privacy",
      }),
    );
    expect(cachedMe).not.toContain("auth/google/start");
    expect(cachedMe).not.toContain('aria-label="Google linked"');
  });

  it("offers retry for an unavailable status and sign-in recovery for a 401", () => {
    const retry = vi.fn();
    const unavailable = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: readyResources({
          status: "error",
          error: new ApiError(503, "unavailable"),
        }),
        api,
        onRetry: retry,
        initialSection: "security-privacy",
      }),
    );
    expect(unavailable).toContain('aria-label="Retry Google status"');
    expect(unavailable).toContain("Google link status is unavailable");
    expect(unavailable).toContain("Link Google account");

    const expired = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: readyResources({
          status: "error",
          error: new ApiError(401, "expired"),
        }),
        api,
        onRetry: retry,
        initialSection: "security-privacy",
      }),
    );
    expect(expired).toContain(
      "Sign in again to check or link a Google account",
    );
    expect(expired).toContain('href="/session-expired"');
    expect(expired).not.toContain("auth/google/start");
    expect(expired).not.toContain('aria-label="Retry Google status"');
  });

  it("uses compact labeled appearance controls with immediate local-save semantics", () => {
    const html = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: readyResources(),
        api,
        onRetry: vi.fn(),
        initialSection: "appearance",
      }),
    );
    expect(html).toContain("Preferences apply to this browser");
    expect(html).not.toContain("Saved on this browser");
    expect(html.match(/<select /g)).toHaveLength(5);
    for (const label of [
      "Theme",
      "Accent color",
      "Display density",
      "Motion",
      "Appearance preset",
    ])
      expect(html).toContain(`aria-label="${label}"`);
    expect(html).toContain("Changes apply instantly.");
    expect(html).not.toContain("Named presets");
    expect(html).not.toContain("first-slice");
  });

  it("places an offline read notice across the full settings ledger", () => {
    const offlineMe = markOfflineRead({ ...me }, 7_000);
    const html = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: {
          me: { status: "ready", data: offlineMe },
          onboarding: { status: "ready", data: onboarding },
        },
        api,
        onRetry: vi.fn(),
      }),
    );
    const ledgerStart = html.indexOf("settingsLedger");
    const noticeStart = html.indexOf('id="settings-offline-read"');
    const indexStart = html.indexOf("<aside", ledgerStart);
    const settingsStyles = readFileSync(
      new URL("./settings-clarity.module.css", import.meta.url),
      "utf8",
    );

    expect(ledgerStart).toBeGreaterThanOrEqual(0);
    expect(noticeStart).toBeGreaterThan(ledgerStart);
    expect(noticeStart).toBeLessThan(indexStart);
    expect(html).toContain("offline-read-notice");
    expect(html).toMatch(/class="[^"]*settingsOfflineNotice/);
    expect(settingsStyles).toMatch(
      /\.settingsOfflineNotice\s*\{\s*grid-column:\s*1\s*\/\s*-1;/s,
    );
  });

  it("collapses medium appearance groups before the two-column rail gets narrow", () => {
    const settingsStyles = readFileSync(
      new URL("./settings-clarity.module.css", import.meta.url),
      "utf8",
    );

    expect(settingsStyles).toMatch(
      /@media \(max-width: 950px\) and \(min-width: 761px\)[\s\S]*?\.appearanceGrid\s*\{\s*grid-template-columns:\s*1fr;[\s\S]*?\.motionGrid\s*\{\s*grid-template-columns:\s*1fr;/,
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
        initialSection: "learning-setup",
      }),
    );

    expect(html).toContain('href="#verified-account"');
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
    expect(html).not.toContain("Sales");
    expect(html).not.toContain("Close more confidently");
    const gated = renderToStaticMarkup(
      createElement(SettingsView, {
        resources: {
          me: { status: "error", error: new TypeError("offline") },
          onboarding: { status: "ready", data: onboarding },
        },
        api,
        onRetry: vi.fn(),
        initialSection: "learning-setup",
      }),
    );
    expect(gated).toContain(
      "Learning setup will appear after learner access is confirmed.",
    );
    expect(gated).not.toContain("Close more confidently");
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
      (resource, result) =>
        updates.push(`${resource}:${result?.status ?? "missing"}`),
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

  it("loads canonical Google-link status only after a fresh identity", async () => {
    let resolveMe!: (value: typeof me) => void;
    let resolveGoogle!: (value: { linked: boolean }) => void;
    const googleLinkStatus = vi.fn(
      () =>
        new Promise<{ linked: boolean }>((resolve) => {
          resolveGoogle = resolve;
        }),
    );
    const updates: string[] = [];
    const clean = startSettingsResourceLoad(
      {
        me: () => new Promise((resolve) => (resolveMe = resolve)),
        onboarding: vi.fn(async () => onboarding),
        googleLinkStatus,
      },
      (resource, result) =>
        updates.push(`${resource}:${result?.status ?? "missing"}`),
    );

    expect(googleLinkStatus).not.toHaveBeenCalled();
    resolveMe(me);
    await Promise.resolve();
    expect(googleLinkStatus).toHaveBeenCalledTimes(1);
    expect(updates).toEqual(["me:ready", "googleLink:loading"]);
    resolveGoogle({ linked: false });
    await Promise.resolve();
    expect(updates).toEqual([
      "me:ready",
      "googleLink:loading",
      "onboarding:ready",
      "googleLink:ready",
    ]);
    clean();
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
      (resource, result) =>
        updates.push(resource + ":" + (result?.status ?? "missing")),
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
