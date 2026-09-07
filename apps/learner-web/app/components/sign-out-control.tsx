"use client";

import { LogOut } from "lucide-react";
import { useState, type AriaRole } from "react";

import {
  ApiError,
  createLearnerApi,
  type LearnerApi,
} from "../lib/learner-api";
import {
  getDefaultOfflineReadCache,
  type OfflineReadCache,
} from "../lib/offline-read-cache";
import {
  availableLocalStorage,
  clearAllLearnerLocalDraftsWithLock,
  type LocalDraftStorageResult,
  type OnboardingRecoveryLockManager,
} from "../lib/local-drafts";
import { ROUTES } from "../lib/routes";

const defaultApi = createLearnerApi();

export function signOutFailureMessage(error: unknown): string {
  return error instanceof TypeError
    ? "Sign-out could not reach the service. Check your connection and retry."
    : "Sign-out did not finish. Your session may still be active; retry before leaving this browser.";
}

export function SignOutFailure({
  message,
  retry,
  retryLabel = "Retry sign out",
}: {
  message: string;
  retry: () => void;
  retryLabel?: string;
}) {
  return (
    <div className="sign-out-failure" role="alert">
      <p>{message}</p>
      <button className="text-button" type="button" onClick={retry}>
        {retryLabel}
      </button>
    </div>
  );
}

export async function logoutAndClearLocalDrafts(
  api: Pick<LearnerApi, "logout">,
  storage: Storage | null,
  lockManager?: OnboardingRecoveryLockManager | null,
  offlineReadCache?: Pick<OfflineReadCache, "purge"> | null,
): Promise<{
  cleanup: LocalDraftStorageResult;
  serverRevocationConfirmed: boolean;
}> {
  let serverRevocationConfirmed = true;
  try {
    await api.logout();
  } catch (error) {
    if (
      !(error instanceof ApiError) ||
      error.code !== "logout_revocation_unavailable"
    ) {
      throw error;
    }
    serverRevocationConfirmed = false;
  }

  let localDraftCleanup: LocalDraftStorageResult;
  try {
    localDraftCleanup = storage
      ? await clearAllLearnerLocalDraftsWithLock(storage, lockManager)
      : { ok: false, reason: "unavailable" };
  } catch {
    localDraftCleanup = { ok: false, reason: "unavailable" };
  }

  let offlineReadCleanupOk = true;
  if (offlineReadCache) {
    try {
      offlineReadCleanupOk = (await offlineReadCache.purge()).ok;
    } catch {
      offlineReadCleanupOk = false;
    }
  }

  return {
    cleanup:
      localDraftCleanup.ok && offlineReadCleanupOk
        ? localDraftCleanup
        : { ok: false, reason: "unavailable" },
    serverRevocationConfirmed,
  };
}

export function SignOutControl({
  api = defaultApi,
  className = "button button--outline",
  offlineReadCache = getDefaultOfflineReadCache(),
  role,
  tabIndex,
}: {
  api?: Pick<LearnerApi, "logout">;
  className?: string;
  offlineReadCache?: Pick<OfflineReadCache, "purge"> | null;
  role?: AriaRole;
  tabIndex?: number;
}) {
  const [signingOut, setSigningOut] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [cleanupOnly, setCleanupOnly] = useState(false);
  const [locallySignedOut, setLocallySignedOut] = useState(false);
  const [serverRevocationUnconfirmed, setServerRevocationUnconfirmed] =
    useState(false);

  function finishRedirect() {
    window.location.assign(ROUTES.login);
  }

  async function retryCleanup() {
    setSigningOut(true);
    const storage = availableLocalStorage(window);
    const outcome = await logoutAndClearLocalDrafts(
      { logout: async () => undefined },
      storage,
      undefined,
      offlineReadCache,
    );
    const result = outcome.cleanup;
    if (result.ok) {
      if (serverRevocationUnconfirmed) {
        setLocallySignedOut(true);
        setFailure(
          "This browser is signed out and its learner recovery copies were removed. Server-side revocation could not be confirmed; contact support if this was a shared device.",
        );
        setSigningOut(false);
        return;
      }
      finishRedirect();
      return;
    }
    setFailure(
      "Your session is signed out, but this browser still could not remove its bounded learner recovery and offline copies. Clear this site's storage before another person uses the device.",
    );
    setSigningOut(false);
  }

  async function signOut() {
    if (signingOut || cleanupOnly || locallySignedOut) return;
    setSigningOut(true);
    setFailure(null);
    setCleanupOnly(false);
    setLocallySignedOut(false);
    setServerRevocationUnconfirmed(false);
    try {
      const outcome = await logoutAndClearLocalDrafts(
        api,
        availableLocalStorage(window),
        undefined,
        offlineReadCache,
      );
      if (!outcome.cleanup.ok) {
        setCleanupOnly(true);
        setServerRevocationUnconfirmed(!outcome.serverRevocationConfirmed);
        setFailure(
          outcome.serverRevocationConfirmed
            ? "Your session is signed out, but this browser could not remove its bounded learner recovery and offline copies. Retry local cleanup before leaving this device."
            : "This browser is signed out, but server revocation was not confirmed and local learner recovery and offline copies could not be removed. Retry local cleanup, then contact support if this was a shared device.",
        );
        setSigningOut(false);
        return;
      }
      if (!outcome.serverRevocationConfirmed) {
        setLocallySignedOut(true);
        setFailure(
          "This browser is signed out and its learner recovery copies were removed. Server-side revocation could not be confirmed; contact support if this was a shared device.",
        );
        setSigningOut(false);
        return;
      }
      finishRedirect();
    } catch (error) {
      setFailure(signOutFailureMessage(error));
      setSigningOut(false);
    }
  }

  return (
    <div className="sign-out-control">
      <button
        className={className}
        type="button"
        onClick={() => void signOut()}
        disabled={signingOut || cleanupOnly || locallySignedOut}
        role={role}
        tabIndex={tabIndex}
      >
        <LogOut size={16} aria-hidden="true" />
        {signingOut
          ? "Signing out…"
          : cleanupOnly || locallySignedOut
            ? "Signed out"
            : "Sign out"}
      </button>
      {failure ? (
        <SignOutFailure
          message={failure}
          retry={
            cleanupOnly
              ? () => void retryCleanup()
              : locallySignedOut
                ? finishRedirect
                : () => void signOut()
          }
          retryLabel={
            cleanupOnly
              ? "Retry local cleanup"
              : locallySignedOut
                ? "Continue to sign in"
                : "Retry sign out"
          }
        />
      ) : null}
    </div>
  );
}
