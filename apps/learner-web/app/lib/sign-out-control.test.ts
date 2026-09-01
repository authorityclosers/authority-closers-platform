import { describe, expect, it, vi } from "vitest";

import { logoutAndClearLocalDrafts } from "../components/sign-out-control";
import { ApiError } from "./learner-api";
import {
  onboardingServerFingerprint,
  readOnboardingLocalDraft,
  writeOnboardingLocalDraft,
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

const scope: OnboardingDraftScope = {
  kind: "onboarding",
  personId: "person-1",
};
const draft = {
  experienceContext: "sales",
  learningGoal: "Keep this only until sign-out",
  practiceSituation: "A test situation",
  weeklyMinutes: "30",
};

function seedDraft(storage: Storage) {
  writeOnboardingLocalDraft(storage, {
    scope,
    draft,
    baseRevision: 1,
    serverFingerprint: onboardingServerFingerprint(draft),
  });
}

describe("learner sign-out local recovery cleanup", () => {
  it("purges learner recovery copies only after server sign-out succeeds", async () => {
    const storage = memoryStorage();
    seedDraft(storage);
    const logout = vi.fn().mockResolvedValue(undefined);

    await expect(
      logoutAndClearLocalDrafts({ logout }, storage),
    ).resolves.toEqual({
      cleanup: { ok: true },
      serverRevocationConfirmed: true,
    });
    expect(logout).toHaveBeenCalledOnce();
    expect(readOnboardingLocalDraft(storage, scope).status).toBe("missing");
  });

  it("retains the recovery copy when server sign-out fails so retry remains possible", async () => {
    const storage = memoryStorage();
    seedDraft(storage);
    const logout = vi.fn().mockRejectedValue(new TypeError("offline"));

    await expect(
      logoutAndClearLocalDrafts({ logout }, storage),
    ).rejects.toThrow("offline");
    expect(readOnboardingLocalDraft(storage, scope).status).toBe("ready");
  });

  it("purges recovery copies when the server reports local-only sign-out", async () => {
    const storage = memoryStorage();
    seedDraft(storage);
    const logout = vi.fn().mockRejectedValue(
      new ApiError(503, "Server revocation unavailable", {
        code: "logout_revocation_unavailable",
      }),
    );

    await expect(
      logoutAndClearLocalDrafts({ logout }, storage),
    ).resolves.toEqual({
      cleanup: { ok: true },
      serverRevocationConfirmed: false,
    });
    expect(readOnboardingLocalDraft(storage, scope).status).toBe("missing");
  });

  it("reports local cleanup failure after a successful server sign-out", async () => {
    const storage = memoryStorage();
    seedDraft(storage);
    storage.removeItem = () => {
      throw new Error("blocked");
    };

    await expect(
      logoutAndClearLocalDrafts(
        { logout: vi.fn().mockResolvedValue(undefined) },
        storage,
      ),
    ).resolves.toEqual({
      cleanup: { ok: false, reason: "unavailable" },
      serverRevocationConfirmed: true,
    });
  });

  it("still revokes the server session when localStorage is unavailable", async () => {
    const logout = vi.fn().mockResolvedValue(undefined);

    await expect(logoutAndClearLocalDrafts({ logout }, null)).resolves.toEqual({
      cleanup: { ok: false, reason: "unavailable" },
      serverRevocationConfirmed: true,
    });
    expect(logout).toHaveBeenCalledOnce();
  });
});
