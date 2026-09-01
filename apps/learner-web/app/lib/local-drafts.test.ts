import { describe, expect, it, vi } from "vitest";

import { ApiError } from "./learner-api";
import {
  activityServerFingerprint,
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
});
