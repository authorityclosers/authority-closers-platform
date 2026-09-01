import { describe, expect, it, vi } from "vitest";

import { ApiError } from "./learner-api";
import {
  activityServerFingerprint,
  availableLocalStorage,
  clearActivityLocalDraft,
  clearAllLearnerLocalDrafts,
  clearOnboardingLocalDraft,
  LEARNER_LOCAL_DRAFT_RETENTION_MS,
  localDraftMatchesServer,
  mutationFailureKind,
  onboardingServerFingerprint,
  readActivityLocalDraft,
  readOnboardingLocalDraft,
  registerBeforeUnloadGuard,
  registerHistoryNavigationGuard,
  registerInternalNavigationGuard,
  writeActivityLocalDraft,
  writeOnboardingLocalDraft,
  type ActivityDraftScope,
  type OnboardingDraftScope,
} from "./local-drafts";

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => void values.delete(key),
    setItem: (key, value) => void values.set(key, value),
  };
}

const onboardingScope: OnboardingDraftScope = {
  kind: "onboarding",
  personId: "person-1",
};

const activityScope: ActivityDraftScope = {
  kind: "activity",
  tenantId: "tenant-1",
  personId: "person-1",
  enrollmentId: "enrollment-1",
  activityId: "activity-1",
};

const onboardingServerDraft = {
  experienceContext: "sales",
  learningGoal: "Server goal",
  practiceSituation: "Server situation",
  weeklyMinutes: "30",
};

describe("scoped recoverable local learner drafts", () => {
  it("treats a blocked localStorage getter as unavailable", () => {
    const owner = Object.defineProperty({}, "localStorage", {
      get() {
        throw new DOMException("blocked", "SecurityError");
      },
    }) as { readonly localStorage: Storage };

    expect(availableLocalStorage(owner)).toBeNull();
    expect(
      availableLocalStorage({ localStorage: memoryStorage() }),
    ).not.toBeNull();
  });

  it("stores onboarding recovery with its person, server base, fingerprint, and bounded timestamps", () => {
    const storage = memoryStorage();
    const now = Date.UTC(2026, 8, 1, 12);
    const localDraft = { ...onboardingServerDraft, learningGoal: "Local goal" };
    const fingerprint = onboardingServerFingerprint(onboardingServerDraft);

    expect(
      writeOnboardingLocalDraft(storage, {
        scope: onboardingScope,
        draft: localDraft,
        baseRevision: 4,
        serverFingerprint: fingerprint,
        now,
      }),
    ).toEqual({ ok: true });

    const result = readOnboardingLocalDraft(storage, onboardingScope, now + 1);
    expect(result).toMatchObject({
      status: "ready",
      envelope: {
        scope: onboardingScope,
        baseRevision: 4,
        serverFingerprint: fingerprint,
        draft: localDraft,
        createdAt: new Date(now).toISOString(),
        updatedAt: new Date(now).toISOString(),
        expiresAt: new Date(
          now + LEARNER_LOCAL_DRAFT_RETENTION_MS,
        ).toISOString(),
      },
    });

    clearOnboardingLocalDraft(storage, onboardingScope);
    expect(readOnboardingLocalDraft(storage, onboardingScope).status).toBe(
      "missing",
    );
  });

  it("isolates activity recovery by tenant, person, enrollment, and activity", () => {
    const storage = memoryStorage();
    const fingerprint = activityServerFingerprint("Server response");

    writeActivityLocalDraft(storage, {
      scope: activityScope,
      response: "Unsaved local evidence",
      baseRevision: 3,
      serverFingerprint: fingerprint,
    });

    expect(readActivityLocalDraft(storage, activityScope)).toMatchObject({
      status: "ready",
      envelope: {
        scope: activityScope,
        baseRevision: 3,
        serverFingerprint: fingerprint,
        draft: { response: "Unsaved local evidence" },
      },
    });
    expect(
      readActivityLocalDraft(storage, {
        ...activityScope,
        personId: "person-2",
      }).status,
    ).toBe("missing");
    expect(
      readActivityLocalDraft(storage, {
        ...activityScope,
        tenantId: "tenant-2",
      }).status,
    ).toBe("missing");

    clearActivityLocalDraft(storage, activityScope);
    expect(readActivityLocalDraft(storage, activityScope).status).toBe(
      "missing",
    );
  });

  it("detects a cross-device stale revision instead of treating it as restorable", () => {
    const storage = memoryStorage();
    writeActivityLocalDraft(storage, {
      scope: activityScope,
      response: "Device A local response",
      baseRevision: 2,
      serverFingerprint: activityServerFingerprint("Server revision 2"),
    });
    const result = readActivityLocalDraft(storage, activityScope);
    expect(result.status).toBe("ready");
    if (result.status !== "ready")
      throw new Error("expected recovery envelope");

    expect(
      localDraftMatchesServer(
        result.envelope,
        3,
        activityServerFingerprint("Device B server revision 3"),
      ),
    ).toBe(false);
  });

  it("detects changed server content even if a faulty source repeats the revision", () => {
    const storage = memoryStorage();
    writeOnboardingLocalDraft(storage, {
      scope: onboardingScope,
      draft: { ...onboardingServerDraft, learningGoal: "Device A goal" },
      baseRevision: 7,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
    });
    const result = readOnboardingLocalDraft(storage, onboardingScope);
    expect(result.status).toBe("ready");
    if (result.status !== "ready")
      throw new Error("expected recovery envelope");

    expect(
      localDraftMatchesServer(
        result.envelope,
        7,
        onboardingServerFingerprint({
          ...onboardingServerDraft,
          learningGoal: "New canonical goal",
        }),
      ),
    ).toBe(false);
  });

  it("expires and removes recovery copies after the approved seven-day window", () => {
    const storage = memoryStorage();
    const now = Date.UTC(2026, 8, 1, 12);
    writeOnboardingLocalDraft(storage, {
      scope: onboardingScope,
      draft: onboardingServerDraft,
      baseRevision: 1,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
      now,
    });

    expect(
      readOnboardingLocalDraft(
        storage,
        onboardingScope,
        now + LEARNER_LOCAL_DRAFT_RETENTION_MS,
      ).status,
    ).toBe("expired");
    expect(readOnboardingLocalDraft(storage, onboardingScope).status).toBe(
      "missing",
    );
  });

  it("reports quota and throwing storage instead of claiming recovery succeeded", () => {
    const quotaStorage = memoryStorage();
    quotaStorage.setItem = () => {
      throw Object.assign(new Error("full"), { name: "QuotaExceededError" });
    };
    expect(
      writeActivityLocalDraft(quotaStorage, {
        scope: activityScope,
        response: "Not persisted",
        baseRevision: 1,
        serverFingerprint: activityServerFingerprint(""),
      }),
    ).toEqual({ ok: false, reason: "quota" });

    const blockedStorage = memoryStorage();
    blockedStorage.getItem = () => {
      throw new Error("blocked");
    };
    expect(readActivityLocalDraft(blockedStorage, activityScope)).toEqual({
      status: "unavailable",
    });
  });

  it("purges only learner draft keys for sign-out or membership invalidation", () => {
    const storage = memoryStorage();
    writeOnboardingLocalDraft(storage, {
      scope: onboardingScope,
      draft: onboardingServerDraft,
      baseRevision: 1,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
    });
    writeActivityLocalDraft(storage, {
      scope: activityScope,
      response: "Local response",
      baseRevision: 1,
      serverFingerprint: activityServerFingerprint(""),
    });
    storage.setItem("ac-theme-preference", "dark");

    expect(clearAllLearnerLocalDrafts(storage)).toEqual({ ok: true });
    expect(readOnboardingLocalDraft(storage, onboardingScope).status).toBe(
      "missing",
    );
    expect(readActivityLocalDraft(storage, activityScope).status).toBe(
      "missing",
    );
    expect(storage.getItem("ac-theme-preference")).toBe("dark");
  });

  it("distinguishes conflict, offline, session, and retry failures", () => {
    expect(mutationFailureKind(new ApiError(409, "conflict"), true)).toBe(
      "conflict",
    );
    expect(mutationFailureKind(new TypeError("offline"), true)).toBe("offline");
    expect(mutationFailureKind(new Error("offline"), false)).toBe("offline");
    expect(mutationFailureKind(new ApiError(401, "expired"), true)).toBe(
      "session",
    );
    expect(mutationFailureKind(new ApiError(500, "failed"), true)).toBe(
      "retry",
    );
  });

  it("installs beforeunload only while dirty and removes the exact listener", () => {
    const addEventListener = vi.fn();
    const removeEventListener = vi.fn();
    const target = { addEventListener, removeEventListener };

    const cleanCleanup = registerBeforeUnloadGuard(target, false);
    cleanCleanup();
    expect(addEventListener).not.toHaveBeenCalled();

    const cleanup = registerBeforeUnloadGuard(target, true);
    expect(addEventListener).toHaveBeenCalledOnce();
    expect(addEventListener).toHaveBeenCalledWith(
      "beforeunload",
      expect.any(Function),
    );

    const listener = addEventListener.mock.calls[0]?.[1] as EventListener;
    const event = { preventDefault: vi.fn(), returnValue: undefined };
    listener(event as unknown as Event);
    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(event.returnValue).toBe("");

    cleanup();
    expect(removeEventListener).toHaveBeenCalledWith("beforeunload", listener);
  });

  it("guards internal soft navigation when no recovery copy exists", () => {
    class FakeAnchor {
      href = "https://staging.authorityclosers.com/home";
      target = "";
    }
    class FakeElement {
      constructor(private readonly anchor: FakeAnchor) {}
      closest() {
        return this.anchor;
      }
    }
    vi.stubGlobal("Element", FakeElement);
    vi.stubGlobal("HTMLAnchorElement", FakeAnchor);
    vi.stubGlobal("window", {
      location: {
        href: "https://staging.authorityclosers.com/activity/activity-1",
        origin: "https://staging.authorityclosers.com",
      },
    });
    const addEventListener = vi.fn();
    const removeEventListener = vi.fn();
    const confirmNavigation = vi.fn(() => false);
    const cleanup = registerInternalNavigationGuard(
      { addEventListener, removeEventListener },
      true,
      confirmNavigation,
    );
    const listener = addEventListener.mock.calls[0]?.[1] as EventListener;
    const event = {
      target: new FakeElement(new FakeAnchor()),
      button: 0,
      defaultPrevented: false,
      metaKey: false,
      ctrlKey: false,
      shiftKey: false,
      altKey: false,
      preventDefault: vi.fn(),
      stopImmediatePropagation: vi.fn(),
    };

    listener(event as unknown as Event);
    expect(confirmNavigation).toHaveBeenCalledOnce();
    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(event.stopImmediatePropagation).toHaveBeenCalledOnce();
    cleanup();
    expect(removeEventListener).toHaveBeenCalledWith("click", listener, true);
    vi.unstubAllGlobals();
  });

  it("guards browser history and imperative navigation without a recovery copy", () => {
    const listeners = new Map<string, EventListener>();
    const navigationListeners = new Map<string, EventListener>();
    const pushState = vi.fn();
    const target = {
      location: {
        href: "https://staging.authorityclosers.com/activity/activity-1",
      },
      history: { state: { route: "activity-1" }, pushState },
      addEventListener: vi.fn(
        (type: string, listener: EventListenerOrEventListenerObject) => {
          listeners.set(
            type,
            typeof listener === "function"
              ? listener
              : (event) => listener.handleEvent(event),
          );
        },
      ),
      removeEventListener: vi.fn(),
      navigation: {
        addEventListener: vi.fn(
          (type: string, listener: EventListenerOrEventListenerObject) => {
            navigationListeners.set(
              type,
              typeof listener === "function"
                ? listener
                : (event) => listener.handleEvent(event),
            );
          },
        ),
        removeEventListener: vi.fn(),
      },
    };
    const confirmNavigation = vi.fn(() => false);
    const cleanup = registerHistoryNavigationGuard(
      target,
      true,
      confirmNavigation,
    );

    const popstate = {
      stopImmediatePropagation: vi.fn(),
    } as unknown as Event;
    listeners.get("popstate")?.(popstate);
    expect(popstate.stopImmediatePropagation).toHaveBeenCalledOnce();
    expect(pushState).toHaveBeenCalledWith(
      { route: "activity-1" },
      "",
      "https://staging.authorityclosers.com/activity/activity-1",
    );

    const navigate = {
      cancelable: true,
      preventDefault: vi.fn(),
      stopImmediatePropagation: vi.fn(),
    } as unknown as Event;
    navigationListeners.get("navigate")?.(navigate);
    expect(navigate.preventDefault).toHaveBeenCalledOnce();
    expect(navigate.stopImmediatePropagation).toHaveBeenCalledOnce();

    cleanup();
    expect(target.removeEventListener).toHaveBeenCalledWith(
      "popstate",
      listeners.get("popstate"),
      true,
    );
    expect(target.navigation.removeEventListener).toHaveBeenCalledWith(
      "navigate",
      navigationListeners.get("navigate"),
    );
  });
});
