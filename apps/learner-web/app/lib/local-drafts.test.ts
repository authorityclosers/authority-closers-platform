import { describe, expect, it, vi } from "vitest";

import { ApiError } from "./learner-api";
import {
  activityServerFingerprint,
  availableLocalStorage,
  clearActivityLocalDraftIfMatchesWithLock,
  clearActivityLocalDraft,
  clearAllLearnerLocalDrafts,
  clearAllLearnerLocalDraftsWithLock,
  clearLearnerLocalDraftsForPerson,
  clearLearnerLocalDraftsForPersonWithLock,
  clearOnboardingLocalDraft,
  clearOnboardingLocalDraftIfMatches,
  clearOnboardingLocalDraftIfMatchesWithLock,
  LEARNER_LOCAL_DRAFT_RETENTION_MS,
  localDraftMatchesServer,
  mutationFailureKind,
  onboardingServerFingerprint,
  purgeActivityLocalDraftIfMatchesWithLock,
  purgeOnboardingLocalDraftIfMatchesWithLock,
  peekOnboardingLocalDraft,
  peekOnboardingLocalDraftForCleanup,
  readActivityLocalDraft,
  readActivityLocalDraftWithLock,
  readOnboardingLocalDraft,
  readOnboardingLocalDraftWithLock,
  registerBeforeUnloadGuard,
  registerHistoryNavigationGuard,
  registerInternalNavigationGuard,
  writeActivityLocalDraft,
  writeActivityLocalDraftWithLockAndEnvelope,
  writeActivityLocalDraftWithLease,
  writeActivityLocalDraftWithLock,
  writeOnboardingLocalDraft,
  writeOnboardingLocalDraftWithLockAndEnvelope,
  writeOnboardingLocalDraftWithLease,
  writeOnboardingLocalDraftWithLock,
  withOnboardingRecoveryLock,
  type ActivityDraftScope,
  type LocalDraftStorageResult,
  type OnboardingRecoveryLease,
  type OnboardingRecoveryLockManager,
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

function exclusiveLockManager(): OnboardingRecoveryLockManager {
  let held = false;
  return {
    request: async (_name, _options, callback) => {
      if (held) return callback(null);
      held = true;
      try {
        return await callback({});
      } finally {
        held = false;
      }
    },
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
  it("retains a newer onboarding recovery copy when an older save cleans up", async () => {
    const storage = memoryStorage();
    const lockManager = exclusiveLockManager();
    const now = Date.UTC(2026, 8, 2, 12);
    const oldWrite = await writeOnboardingLocalDraftWithLockAndEnvelope(
      storage,
      {
        scope: onboardingScope,
        draft: onboardingServerDraft,
        baseRevision: 1,
        serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
        localStep: 1,
        now,
      },
      lockManager,
    );
    const newerDraft = { ...onboardingServerDraft, learningGoal: "New tab" };
    const newerWrite = await writeOnboardingLocalDraftWithLockAndEnvelope(
      storage,
      {
        scope: onboardingScope,
        draft: newerDraft,
        baseRevision: 1,
        serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
        localStep: 2,
        now: now + 1,
      },
      lockManager,
    );

    expect(oldWrite.result).toEqual({ ok: true });
    expect(newerWrite.result).toEqual({ ok: true });
    expect(oldWrite.envelope).not.toEqual(newerWrite.envelope);
    expect(
      await clearOnboardingLocalDraftIfMatchesWithLock(
        storage,
        onboardingScope,
        oldWrite.envelope,
        now + 2,
        lockManager,
      ),
    ).toEqual({ ok: false, reason: "changed" });
    expect(
      readOnboardingLocalDraft(storage, onboardingScope, now + 2),
    ).toMatchObject({
      status: "ready",
      envelope: { draft: newerDraft, localStep: 2 },
    });
  });

  it("retains a newer activity recovery copy when an older submit cleans up", async () => {
    const storage = memoryStorage();
    const lockManager = exclusiveLockManager();
    const now = Date.UTC(2026, 8, 2, 12);
    const oldWrite = await writeActivityLocalDraftWithLockAndEnvelope(
      storage,
      {
        scope: activityScope,
        response: "Old operation",
        baseRevision: 1,
        serverFingerprint: activityServerFingerprint(""),
        now,
      },
      lockManager,
    );
    const newerWrite = await writeActivityLocalDraftWithLockAndEnvelope(
      storage,
      {
        scope: activityScope,
        response: "New tab response",
        baseRevision: 1,
        serverFingerprint: activityServerFingerprint(""),
        now: now + 1,
      },
      lockManager,
    );

    expect(oldWrite.result).toEqual({ ok: true });
    expect(newerWrite.result).toEqual({ ok: true });
    expect(
      await clearActivityLocalDraftIfMatchesWithLock(
        storage,
        activityScope,
        oldWrite.envelope,
        now + 2,
        lockManager,
      ),
    ).toEqual({ ok: false, reason: "changed" });
    expect(
      readActivityLocalDraft(storage, activityScope, now + 2),
    ).toMatchObject({
      status: "ready",
      envelope: { draft: { response: "New tab response" } },
    });
  });

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

  it("keeps onboarding read, write, and clear safe when storage is unavailable", () => {
    expect(readOnboardingLocalDraft(null, onboardingScope)).toEqual({
      status: "unavailable",
    });
    expect(
      writeOnboardingLocalDraft(null, {
        scope: onboardingScope,
        draft: onboardingServerDraft,
        baseRevision: 1,
        serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
        localStep: 2,
      }),
    ).toEqual({ ok: false, reason: "unavailable" });
    expect(clearOnboardingLocalDraft(null, onboardingScope)).toEqual({
      ok: false,
      reason: "unavailable",
    });
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
        localStep: 3,
        now,
      }),
    ).toEqual({ ok: true });

    const result = readOnboardingLocalDraft(storage, onboardingScope, now + 1);
    expect(result).toMatchObject({
      status: "ready",
      envelope: {
        version: 3,
        scope: onboardingScope,
        baseRevision: 4,
        serverFingerprint: fingerprint,
        draft: localDraft,
        localStep: 3,
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

  it("does not remove a newer onboarding recovery copy during conditional cleanup", () => {
    const storage = memoryStorage();
    const now = Date.UTC(2026, 8, 1, 12);
    const savedDraft = { ...onboardingServerDraft, learningGoal: "Saved goal" };
    const newerDraft = { ...savedDraft, learningGoal: "Newer unsaved goal" };

    writeOnboardingLocalDraft(storage, {
      scope: onboardingScope,
      draft: savedDraft,
      baseRevision: 4,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
      localStep: 2,
      now,
    });
    const saved = peekOnboardingLocalDraft(storage, onboardingScope, now + 1);
    expect(saved.status).toBe("ready");
    if (saved.status !== "ready") throw new Error("expected saved envelope");

    writeOnboardingLocalDraft(storage, {
      scope: onboardingScope,
      draft: newerDraft,
      baseRevision: 4,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
      localStep: 2,
      now: now + 1,
    });

    expect(
      clearOnboardingLocalDraftIfMatches(
        storage,
        onboardingScope,
        saved.envelope,
      ),
    ).toEqual({ ok: false, reason: "changed" });
    expect(
      readOnboardingLocalDraft(storage, onboardingScope, now + 2),
    ).toMatchObject({ status: "ready", envelope: { draft: newerDraft } });
  });

  it("migrates a valid legacy onboarding envelope and rejects an invalid local step", async () => {
    const storage = memoryStorage();
    const now = Date.UTC(2026, 8, 1, 12);
    const legacyEnvelope = {
      version: 2,
      scope: onboardingScope,
      baseRevision: 4,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
      createdAt: new Date(now).toISOString(),
      updatedAt: new Date(now).toISOString(),
      expiresAt: new Date(now + LEARNER_LOCAL_DRAFT_RETENTION_MS).toISOString(),
      draft: onboardingServerDraft,
    };
    storage.setItem(
      "ac-learner-local-draft:onboarding:person-1",
      JSON.stringify(legacyEnvelope),
    );

    expect(
      readOnboardingLocalDraft(storage, onboardingScope, now + 1, 3),
    ).toMatchObject({
      status: "ready",
      envelope: { version: 3, localStep: 3 },
    });
    await expect(
      readOnboardingLocalDraftWithLock(
        storage,
        onboardingScope,
        now + 1,
        3,
        exclusiveLockManager(),
      ),
    ).resolves.toMatchObject({
      status: "ready",
      envelope: { version: 3, localStep: 3 },
      cleanupTarget: { version: 2 },
    });

    storage.setItem(
      "ac-learner-local-draft:onboarding:person-1",
      JSON.stringify({ ...legacyEnvelope, version: 3, localStep: 4 }),
    );
    expect(readOnboardingLocalDraft(storage, onboardingScope, now + 1)).toEqual(
      { status: "invalid" },
    );
  });

  it("conditionally clears a valid legacy onboarding envelope by its raw snapshot", () => {
    const storage = memoryStorage();
    const now = Date.UTC(2026, 8, 1, 12);
    const legacyEnvelope = {
      version: 2,
      scope: onboardingScope,
      baseRevision: 4,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
      createdAt: new Date(now).toISOString(),
      updatedAt: new Date(now).toISOString(),
      expiresAt: new Date(now + LEARNER_LOCAL_DRAFT_RETENTION_MS).toISOString(),
      draft: onboardingServerDraft,
    };
    storage.setItem(
      "ac-learner-local-draft:onboarding:person-1",
      JSON.stringify(legacyEnvelope),
    );

    const cleanupTarget = peekOnboardingLocalDraftForCleanup(
      storage,
      onboardingScope,
      now + 1,
    );
    expect(cleanupTarget).toEqual({
      status: "ready",
      envelope: legacyEnvelope,
    });
    expect(
      clearOnboardingLocalDraftIfMatches(
        storage,
        onboardingScope,
        cleanupTarget.status === "ready" ? cleanupTarget.envelope : null,
        now + 1,
      ),
    ).toEqual({ ok: true });
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

  it("uses the shared lock for activity read, write, and conditional cleanup", async () => {
    const storage = memoryStorage();
    const now = Date.UTC(2026, 8, 1, 12);
    const lockManager = exclusiveLockManager();

    expect(
      await writeActivityLocalDraftWithLock(
        storage,
        {
          scope: activityScope,
          response: "Locked recovery response",
          baseRevision: 2,
          serverFingerprint: activityServerFingerprint("Server response"),
          now,
        },
        lockManager,
      ),
    ).toEqual({ ok: true });
    const read = await readActivityLocalDraftWithLock(
      storage,
      activityScope,
      now,
      lockManager,
    );
    expect(read).toMatchObject({ status: "ready" });
    if (read.status !== "ready") throw new Error("expected activity envelope");

    expect(
      await clearActivityLocalDraftIfMatchesWithLock(
        storage,
        activityScope,
        read.envelope,
        now,
        lockManager,
      ),
    ).toEqual({ ok: true });
    expect(readActivityLocalDraft(storage, activityScope).status).toBe(
      "missing",
    );
    expect(
      await readActivityLocalDraftWithLock(storage, activityScope, now, null),
    ).toEqual({ status: "unavailable" });
  });

  it("blocks activity writers and person cleanup while activity cleanup holds the lock", async () => {
    const storage = memoryStorage();
    const now = Date.UTC(2026, 8, 1, 12);
    writeActivityLocalDraft(storage, {
      scope: activityScope,
      response: "Original recovery response",
      baseRevision: 2,
      serverFingerprint: activityServerFingerprint("Server response"),
      now,
    });
    const expected = readActivityLocalDraft(storage, activityScope, now);
    if (expected.status !== "ready") throw new Error("expected envelope");

    const lockManager = exclusiveLockManager();
    let writerAttempt: Promise<LocalDraftStorageResult> | null = null;
    let personCleanupAttempt: Promise<LocalDraftStorageResult> | null = null;
    let signOutCleanupAttempt: Promise<LocalDraftStorageResult> | null = null;
    const originalGetItem = storage.getItem;
    storage.getItem = (key) => {
      if (
        !writerAttempt &&
        key ===
          "ac-learner-local-draft:activity:tenant-1:person-1:enrollment-1:activity-1"
      ) {
        writerAttempt = writeActivityLocalDraftWithLock(
          storage,
          {
            scope: activityScope,
            response: "Concurrent response",
            baseRevision: 2,
            serverFingerprint: activityServerFingerprint("Server response"),
            now: now + 1,
          },
          lockManager,
        );
        personCleanupAttempt = clearLearnerLocalDraftsForPersonWithLock(
          storage,
          activityScope.personId,
          lockManager,
        );
        signOutCleanupAttempt = clearAllLearnerLocalDraftsWithLock(
          storage,
          lockManager,
        );
      }
      return originalGetItem(key);
    };

    expect(
      await clearActivityLocalDraftIfMatchesWithLock(
        storage,
        activityScope,
        expected.envelope,
        now,
        lockManager,
      ),
    ).toEqual({ ok: true });
    expect(writerAttempt).not.toBeNull();
    expect(personCleanupAttempt).not.toBeNull();
    expect(signOutCleanupAttempt).not.toBeNull();
    await expect(writerAttempt).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
    await expect(personCleanupAttempt).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
    await expect(signOutCleanupAttempt).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
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

  it("reports expired recovery copies without deleting them outside a lock", () => {
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
    expect(
      readOnboardingLocalDraft(
        storage,
        onboardingScope,
        now + LEARNER_LOCAL_DRAFT_RETENTION_MS,
      ).status,
    ).toBe("expired");
    expect(
      storage.getItem("ac-learner-local-draft:onboarding:person-1"),
    ).not.toBeNull();
  });

  it("purges only an unchanged expired or invalid raw onboarding snapshot under lock", async () => {
    const now = Date.UTC(2026, 8, 8, 12);
    const expiredStorage = memoryStorage();
    const createdAt = now - LEARNER_LOCAL_DRAFT_RETENTION_MS;
    const expiredEnvelope = {
      version: 3,
      scope: onboardingScope,
      baseRevision: 1,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
      createdAt: new Date(createdAt).toISOString(),
      updatedAt: new Date(createdAt).toISOString(),
      expiresAt: new Date(now).toISOString(),
      localStep: 1,
      draft: onboardingServerDraft,
    };
    expiredStorage.setItem(
      "ac-learner-local-draft:onboarding:person-1",
      JSON.stringify(expiredEnvelope),
    );
    expect(
      await purgeOnboardingLocalDraftIfMatchesWithLock(
        expiredStorage,
        onboardingScope,
        { raw: JSON.stringify(expiredEnvelope) },
        now,
        exclusiveLockManager(),
      ),
    ).toEqual({ ok: true });
    expect(
      expiredStorage.getItem("ac-learner-local-draft:onboarding:person-1"),
    ).toBeNull();

    const invalidStorage = memoryStorage();
    const invalidRaw = "not-json";
    invalidStorage.setItem(
      "ac-learner-local-draft:onboarding:person-1",
      invalidRaw,
    );
    expect(
      await purgeOnboardingLocalDraftIfMatchesWithLock(
        invalidStorage,
        onboardingScope,
        { raw: invalidRaw },
        now,
        exclusiveLockManager(),
      ),
    ).toEqual({ ok: true });
    expect(
      invalidStorage.getItem("ac-learner-local-draft:onboarding:person-1"),
    ).toBeNull();

    const changedStorage = memoryStorage();
    const invalidEnvelope = { ...expiredEnvelope, expiresAt: "later" };
    changedStorage.setItem(
      "ac-learner-local-draft:onboarding:person-1",
      JSON.stringify(invalidEnvelope),
    );
    changedStorage.setItem(
      "ac-learner-local-draft:onboarding:person-1",
      JSON.stringify({ ...invalidEnvelope, localStep: 2 }),
    );
    expect(
      await purgeOnboardingLocalDraftIfMatchesWithLock(
        changedStorage,
        onboardingScope,
        { raw: JSON.stringify(invalidEnvelope) },
        now,
        exclusiveLockManager(),
      ),
    ).toEqual({ ok: false, reason: "changed" });
    expect(
      changedStorage.getItem("ac-learner-local-draft:onboarding:person-1"),
    ).not.toBeNull();
  });

  it("never purges a newer valid onboarding copy that replaces the raw snapshot", async () => {
    const base = Date.UTC(2026, 8, 1, 12);
    const expiredAt = base + LEARNER_LOCAL_DRAFT_RETENTION_MS;
    const storage = memoryStorage();
    writeOnboardingLocalDraft(storage, {
      scope: onboardingScope,
      draft: onboardingServerDraft,
      baseRevision: 1,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
      now: base,
    });
    const expectedRaw = {
      raw: storage.getItem("ac-learner-local-draft:onboarding:person-1")!,
    };
    const originalGetItem = storage.getItem;
    let reads = 0;
    storage.getItem = (key) => {
      reads += 1;
      if (reads === 2) {
        writeOnboardingLocalDraft(storage, {
          scope: onboardingScope,
          draft: { ...onboardingServerDraft, learningGoal: "New answer" },
          baseRevision: 1,
          serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
          now: expiredAt + 1,
        });
      }
      return originalGetItem(key);
    };

    expect(
      await purgeOnboardingLocalDraftIfMatchesWithLock(
        storage,
        onboardingScope,
        expectedRaw,
        expiredAt,
        exclusiveLockManager(),
      ),
    ).toEqual({ ok: false, reason: "changed" });
    expect(
      readOnboardingLocalDraft(storage, onboardingScope, expiredAt + 2),
    ).toMatchObject({
      status: "ready",
      envelope: { draft: { learningGoal: "New answer" } },
    });
  });

  it("never purges a newer valid activity copy that replaces an expired raw snapshot", async () => {
    const base = Date.UTC(2026, 8, 1, 12);
    const expiredAt = base + LEARNER_LOCAL_DRAFT_RETENTION_MS;
    const storage = memoryStorage();
    writeActivityLocalDraft(storage, {
      scope: activityScope,
      response: "Expired response",
      baseRevision: 1,
      serverFingerprint: activityServerFingerprint("Server response"),
      now: base,
    });
    const expectedRaw = {
      raw: storage.getItem(
        "ac-learner-local-draft:activity:tenant-1:person-1:enrollment-1:activity-1",
      )!,
    };
    const originalGetItem = storage.getItem;
    let reads = 0;
    storage.getItem = (key) => {
      reads += 1;
      if (reads === 2) {
        writeActivityLocalDraft(storage, {
          scope: activityScope,
          response: "New activity answer",
          baseRevision: 1,
          serverFingerprint: activityServerFingerprint("Server response"),
          now: expiredAt + 1,
        });
      }
      return originalGetItem(key);
    };

    expect(
      await purgeActivityLocalDraftIfMatchesWithLock(
        storage,
        activityScope,
        expectedRaw,
        expiredAt,
        exclusiveLockManager(),
      ),
    ).toEqual({ ok: false, reason: "changed" });
    expect(
      readActivityLocalDraft(storage, activityScope, expiredAt + 2),
    ).toMatchObject({
      status: "ready",
      envelope: { draft: { response: "New activity answer" } },
    });
  });

  it("wires expired and invalid cleanup into locked production reads", async () => {
    const base = Date.UTC(2026, 8, 1, 12);
    const expiredAt = base + LEARNER_LOCAL_DRAFT_RETENTION_MS;
    const onboardingStorage = memoryStorage();
    writeOnboardingLocalDraft(onboardingStorage, {
      scope: onboardingScope,
      draft: onboardingServerDraft,
      baseRevision: 1,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
      now: base,
    });
    await expect(
      readOnboardingLocalDraftWithLock(
        onboardingStorage,
        onboardingScope,
        expiredAt,
        1,
        exclusiveLockManager(),
      ),
    ).resolves.toEqual({ status: "missing" });
    expect(
      onboardingStorage.getItem("ac-learner-local-draft:onboarding:person-1"),
    ).toBeNull();

    const activityStorage = memoryStorage();
    activityStorage.setItem(
      "ac-learner-local-draft:activity:tenant-1:person-1:enrollment-1:activity-1",
      "malformed",
    );
    await expect(
      readActivityLocalDraftWithLock(
        activityStorage,
        activityScope,
        base,
        exclusiveLockManager(),
      ),
    ).resolves.toEqual({ status: "missing" });
    expect(
      activityStorage.getItem(
        "ac-learner-local-draft:activity:tenant-1:person-1:enrollment-1:activity-1",
      ),
    ).toBeNull();
  });

  it("revokes a captured recovery lease after the lock callback returns", async () => {
    const storage = memoryStorage();
    const now = Date.UTC(2026, 8, 1, 12);
    let capturedLease: OnboardingRecoveryLease | undefined;
    await expect(
      withOnboardingRecoveryLock(
        storage,
        onboardingScope,
        (lease) => {
          capturedLease = lease;
        },
        exclusiveLockManager(),
      ),
    ).resolves.toEqual({ ok: true, value: undefined });
    expect(capturedLease).toBeDefined();
    expect(
      writeOnboardingLocalDraftWithLease(
        storage,
        {
          scope: onboardingScope,
          draft: onboardingServerDraft,
          baseRevision: 1,
          serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
          now,
        },
        capturedLease as OnboardingRecoveryLease,
      ),
    ).toEqual({ ok: false, reason: "unavailable" });
    expect(
      writeActivityLocalDraftWithLease(
        storage,
        {
          scope: activityScope,
          response: "Should not be written",
          baseRevision: 1,
          serverFingerprint: activityServerFingerprint(""),
          now,
        },
        capturedLease as OnboardingRecoveryLease,
      ),
    ).toEqual({ ok: false, reason: "unavailable" });
  });

  it("fails closed when the Web Lock is unavailable or busy", async () => {
    const storage = memoryStorage();
    const now = Date.UTC(2026, 8, 1, 12);
    const draft = { ...onboardingServerDraft, learningGoal: "Keep locally" };
    writeOnboardingLocalDraft(storage, {
      scope: onboardingScope,
      draft,
      baseRevision: 4,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
      localStep: 2,
      now,
    });
    const expected = peekOnboardingLocalDraftForCleanup(
      storage,
      onboardingScope,
      now,
    );
    if (expected.status !== "ready") throw new Error("expected envelope");

    expect(
      await readOnboardingLocalDraftWithLock(
        storage,
        onboardingScope,
        now,
        2,
        null,
      ),
    ).toEqual({ status: "unavailable" });
    expect(
      await writeOnboardingLocalDraftWithLock(
        storage,
        {
          scope: onboardingScope,
          draft: { ...draft, learningGoal: "Should remain unchanged" },
          baseRevision: 4,
          serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
          localStep: 2,
          now: now + 1,
        },
        null,
      ),
    ).toEqual({ ok: false, reason: "unavailable" });
    expect(
      await clearOnboardingLocalDraftIfMatchesWithLock(
        storage,
        onboardingScope,
        expected.envelope,
        now,
        {
          request: async (_name, _options, callback) => callback(null),
        },
      ),
    ).toEqual({ ok: false, reason: "busy" });
    expect(readOnboardingLocalDraft(storage, onboardingScope)).toMatchObject({
      status: "ready",
      envelope: { draft },
    });
  });

  it("does not expose synchronous onboarding storage bypasses in a browser", () => {
    const storage = memoryStorage();
    vi.stubGlobal("window", {});
    try {
      expect(
        writeOnboardingLocalDraft(storage, {
          scope: onboardingScope,
          draft: onboardingServerDraft,
          baseRevision: 1,
          serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
        }),
      ).toEqual({ ok: false, reason: "unavailable" });
      expect(readOnboardingLocalDraft(storage, onboardingScope)).toEqual({
        status: "unavailable",
      });
      expect(clearOnboardingLocalDraft(storage, onboardingScope)).toEqual({
        ok: false,
        reason: "unavailable",
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("blocks a prechecked writer during conditional cleanup interleaving", async () => {
    const storage = memoryStorage();
    const now = Date.UTC(2026, 8, 1, 12);
    const draft = { ...onboardingServerDraft, learningGoal: "Saved goal" };
    const newerDraft = { ...draft, learningGoal: "Newer unsaved goal" };
    writeOnboardingLocalDraft(storage, {
      scope: onboardingScope,
      draft,
      baseRevision: 4,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
      localStep: 2,
      now,
    });
    const expected = peekOnboardingLocalDraftForCleanup(
      storage,
      onboardingScope,
      now,
    );
    if (expected.status !== "ready") throw new Error("expected envelope");

    let writerAttempt: Promise<LocalDraftStorageResult> | null = null;
    const lockManager = exclusiveLockManager();
    const originalGetItem = storage.getItem;
    storage.getItem = (key) => {
      if (
        !writerAttempt &&
        key === "ac-learner-local-draft:onboarding:person-1"
      ) {
        writerAttempt = writeOnboardingLocalDraftWithLock(
          storage,
          {
            scope: onboardingScope,
            draft: newerDraft,
            baseRevision: 4,
            serverFingerprint: onboardingServerFingerprint(
              onboardingServerDraft,
            ),
            localStep: 2,
            now: now + 1,
          },
          lockManager,
        );
      }
      return originalGetItem(key);
    };

    expect(
      await clearOnboardingLocalDraftIfMatchesWithLock(
        storage,
        onboardingScope,
        expected.envelope,
        now,
        lockManager,
      ),
    ).toEqual({ ok: true });
    expect(writerAttempt).not.toBeNull();
    await expect(writerAttempt).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
    expect(readOnboardingLocalDraft(storage, onboardingScope).status).toBe(
      "missing",
    );
  });

  it("accepts the exact seven-day timestamp boundary", () => {
    const storage = memoryStorage();
    const now = Date.UTC(2026, 8, 8, 12);
    const createdAt = new Date(
      now - LEARNER_LOCAL_DRAFT_RETENTION_MS,
    ).toISOString();
    const updatedAt = new Date(now).toISOString();
    storage.setItem(
      "ac-learner-local-draft:onboarding:person-1",
      JSON.stringify({
        version: 3,
        scope: onboardingScope,
        baseRevision: 1,
        serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
        createdAt,
        updatedAt,
        expiresAt: new Date(
          now + LEARNER_LOCAL_DRAFT_RETENTION_MS,
        ).toISOString(),
        localStep: 1,
        draft: onboardingServerDraft,
      }),
    );

    expect(
      readOnboardingLocalDraft(storage, onboardingScope, now),
    ).toMatchObject({ status: "ready" });
  });

  it("rejects future, reversed, and over-retained envelope timestamps", () => {
    const now = Date.UTC(2026, 8, 1, 12);
    const key = "ac-learner-local-draft:onboarding:person-1";
    const validEnvelope = {
      version: 3,
      scope: onboardingScope,
      baseRevision: 1,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
      createdAt: new Date(now).toISOString(),
      updatedAt: new Date(now).toISOString(),
      expiresAt: new Date(now + LEARNER_LOCAL_DRAFT_RETENTION_MS).toISOString(),
      localStep: 1,
      draft: onboardingServerDraft,
    };
    const invalidCases = [
      {
        label: "future createdAt",
        patch: {
          createdAt: new Date(now + 1).toISOString(),
          updatedAt: new Date(now + 1).toISOString(),
        },
      },
      {
        label: "future updatedAt",
        patch: { updatedAt: new Date(now + 1).toISOString() },
      },
      {
        label: "reversed timestamps",
        patch: {
          createdAt: new Date(now + 2).toISOString(),
          updatedAt: new Date(now).toISOString(),
        },
      },
      {
        label: "createdAt older than retention",
        patch: {
          createdAt: new Date(
            now - LEARNER_LOCAL_DRAFT_RETENTION_MS - 1,
          ).toISOString(),
        },
      },
      {
        label: "expiresAt beyond retention",
        patch: {
          expiresAt: new Date(
            now + LEARNER_LOCAL_DRAFT_RETENTION_MS + 1,
          ).toISOString(),
        },
      },
    ];

    for (const invalidCase of invalidCases) {
      const storage = memoryStorage();
      storage.setItem(
        key,
        JSON.stringify({ ...validEnvelope, ...invalidCase.patch }),
      );
      expect(
        readOnboardingLocalDraft(storage, onboardingScope, now),
        invalidCase.label,
      ).toEqual({ status: "invalid" });
      expect(storage.getItem(key), invalidCase.label).not.toBeNull();
    }
  });

  it("fails closed for a global purge without a lock and purges under an exclusive lock", async () => {
    const storage = memoryStorage();
    writeOnboardingLocalDraft(storage, {
      scope: onboardingScope,
      draft: onboardingServerDraft,
      baseRevision: 1,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
    });
    storage.setItem(
      "ac-learner-local-draft:activity:tenant-1:person-1",
      "activity",
    );

    expect(await clearAllLearnerLocalDraftsWithLock(storage, null)).toEqual({
      ok: false,
      reason: "unavailable",
    });
    expect(
      storage.getItem("ac-learner-local-draft:onboarding:person-1"),
    ).not.toBeNull();

    expect(
      await clearAllLearnerLocalDraftsWithLock(storage, exclusiveLockManager()),
    ).toEqual({ ok: true });
    expect(
      storage.getItem("ac-learner-local-draft:onboarding:person-1"),
    ).toBeNull();
  });

  it("reports quota and throwing storage instead of claiming recovery succeeded", () => {
    const quotaStorage = memoryStorage();
    quotaStorage.setItem = () => {
      throw Object.assign(new Error("full"), { name: "QuotaExceededError" });
    };
    expect(
      writeOnboardingLocalDraft(quotaStorage, {
        scope: onboardingScope,
        draft: onboardingServerDraft,
        baseRevision: 1,
        serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
        localStep: 1,
      }),
    ).toEqual({ ok: false, reason: "quota" });
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
    expect(
      writeOnboardingLocalDraft(blockedStorage, {
        scope: onboardingScope,
        draft: onboardingServerDraft,
        baseRevision: 1,
        serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
        localStep: 1,
      }),
    ).toEqual({ ok: false, reason: "unavailable" });

    const clearFailureStorage = memoryStorage();
    clearFailureStorage.removeItem = () => {
      throw Object.assign(new Error("blocked"), {
        name: "QuotaExceededError",
      });
    };
    expect(
      clearOnboardingLocalDraft(clearFailureStorage, onboardingScope),
    ).toEqual({ ok: false, reason: "quota" });
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

  it("purges membership-loss recovery only for the resolved person", () => {
    const storage = memoryStorage();
    const otherOnboardingScope = { ...onboardingScope, personId: "person-2" };
    const otherActivityScope = { ...activityScope, personId: "person-2" };

    writeOnboardingLocalDraft(storage, {
      scope: onboardingScope,
      draft: onboardingServerDraft,
      baseRevision: 1,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
    });
    writeOnboardingLocalDraft(storage, {
      scope: otherOnboardingScope,
      draft: onboardingServerDraft,
      baseRevision: 1,
      serverFingerprint: onboardingServerFingerprint(onboardingServerDraft),
    });
    writeActivityLocalDraft(storage, {
      scope: activityScope,
      response: "Person one response",
      baseRevision: 1,
      serverFingerprint: activityServerFingerprint("Person one response"),
    });
    writeActivityLocalDraft(storage, {
      scope: otherActivityScope,
      response: "Person two response",
      baseRevision: 1,
      serverFingerprint: activityServerFingerprint("Person two response"),
    });

    expect(clearLearnerLocalDraftsForPerson(storage, "person-1")).toEqual({
      ok: true,
    });
    expect(readOnboardingLocalDraft(storage, onboardingScope).status).toBe(
      "missing",
    );
    expect(readActivityLocalDraft(storage, activityScope).status).toBe(
      "missing",
    );
    expect(readOnboardingLocalDraft(storage, otherOnboardingScope).status).toBe(
      "ready",
    );
    expect(readActivityLocalDraft(storage, otherActivityScope).status).toBe(
      "ready",
    );
    expect(clearLearnerLocalDraftsForPerson(storage, null)).toEqual({
      ok: false,
      reason: "unavailable",
    });
    expect(readOnboardingLocalDraft(storage, otherOnboardingScope).status).toBe(
      "ready",
    );
  });

  it("keeps exact-person membership cleanup locked and honest when unavailable", async () => {
    const storage = memoryStorage();
    const otherScope = { ...activityScope, personId: "person-2" };
    writeActivityLocalDraft(storage, {
      scope: activityScope,
      response: "Person one response",
      baseRevision: 1,
      serverFingerprint: activityServerFingerprint("Person one response"),
    });
    writeActivityLocalDraft(storage, {
      scope: otherScope,
      response: "Person two response",
      baseRevision: 1,
      serverFingerprint: activityServerFingerprint("Person two response"),
    });

    expect(
      await clearLearnerLocalDraftsForPersonWithLock(
        storage,
        activityScope.personId,
        { request: async (_name, _options, callback) => callback(null) },
      ),
    ).toEqual({ ok: false, reason: "unavailable" });
    expect(readActivityLocalDraft(storage, activityScope).status).toBe("ready");
    expect(readActivityLocalDraft(storage, otherScope).status).toBe("ready");

    expect(
      await clearLearnerLocalDraftsForPersonWithLock(
        storage,
        activityScope.personId,
        exclusiveLockManager(),
      ),
    ).toEqual({ ok: true });
    expect(readActivityLocalDraft(storage, activityScope).status).toBe(
      "missing",
    );
    expect(readActivityLocalDraft(storage, otherScope).status).toBe("ready");
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
    const cleanAddEventListener = vi.fn();
    const cleanCleanup = registerInternalNavigationGuard(
      { addEventListener: cleanAddEventListener, removeEventListener: vi.fn() },
      false,
      () => false,
    );
    cleanCleanup();
    expect(cleanAddEventListener).not.toHaveBeenCalled();

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
    const cleanCleanup = registerHistoryNavigationGuard(
      target,
      false,
      confirmNavigation,
    );
    cleanCleanup();
    expect(target.addEventListener).not.toHaveBeenCalled();

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
