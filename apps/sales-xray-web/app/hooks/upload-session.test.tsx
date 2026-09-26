import { describe, expect, it, vi } from "vitest";

import {
  UploadCancelledError,
  UploadInProgressError,
  UploadReconciliationRequiredError,
  UploadSessionStore,
  type AnalysisStartSettled,
  type UploadMeta,
} from "./upload-session";

const firstMeta: UploadMeta = {
  intentId: "11111111-1111-4111-8111-111111111111",
  fileName: "call.wav",
  totalBytes: 12,
  reportLanguage: "en",
  homeHref: "/?new=1",
  sourceSha256: null,
};
const secondMeta: UploadMeta = {
  ...firstMeta,
  intentId: "22222222-2222-4222-8222-222222222222",
  fileName: "another-call.wav",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

describe("root upload session", () => {
  it("keeps the selected File while the live promise is adopted across views", async () => {
    const store = new UploadSessionStore();
    const file = new File(["audio"], "call.wav", { type: "audio/wav" });
    const pending = deferred<{ submissionId: string }>();
    const running = store.run(firstMeta, file, () => pending.promise);

    expect(store.getSnapshot()).toMatchObject({
      phase: "preparing",
      intentId: firstMeta.intentId,
    });
    expect(store.fileFor(firstMeta.intentId)).toBe(file);
    expect(store.adopt(firstMeta.intentId)).toBeDefined();
    expect(store.adopt(secondMeta.intentId)).toBeNull();
    await expect(
      store.run(secondMeta, new File(["other"], "other.wav"), async () => ({
        submissionId: secondMeta.intentId,
      })),
    ).rejects.toBeInstanceOf(UploadInProgressError);

    pending.resolve({ submissionId: firstMeta.intentId });
    await expect(running).resolves.toEqual({
      submissionId: firstMeta.intentId,
    });
    expect(store.getSnapshot()).toMatchObject({
      phase: "saved",
      submissionId: firstMeta.intentId,
    });
    expect(store.fileFor(firstMeta.intentId)).toBeNull();
  });

  it("owns the authorized analysis start after save and keeps it until it settles", async () => {
    const store = new UploadSessionStore();
    const add = vi.spyOn(window, "addEventListener");
    const started = deferred<AnalysisStartSettled>();
    const start = vi.fn(
      (
        _saved: { submissionId: string },
        _signal: AbortSignal,
        onPhase: (phase: "checking" | "starting") => void,
      ) => {
        onPhase("starting");
        return started.promise;
      },
    );
    await store.run(
      firstMeta,
      new File(["audio"], "call.wav"),
      async () => ({ submissionId: firstMeta.intentId }),
      start,
    );
    await vi.waitFor(() =>
      expect(store.getSnapshot()).toMatchObject({
        phase: "saved",
        analysis: { state: "starting" },
      }),
    );
    expect(start).toHaveBeenCalledTimes(1);
    expect(store.startingSubmissionId()).toBe(firstMeta.intentId);
    expect(add).toHaveBeenCalledWith("beforeunload", expect.any(Function));

    // Open call, dismiss or a remount cannot drop the pending start.
    store.settle(firstMeta.intentId);
    expect(store.getSnapshot()).toMatchObject({ phase: "saved" });
    await expect(
      store.run(secondMeta, new File(["other"], "other.wav"), async () => ({
        submissionId: secondMeta.intentId,
      })),
    ).rejects.toBeInstanceOf(UploadInProgressError);

    started.resolve({ state: "accepted" });
    await vi.waitFor(() =>
      expect(store.getSnapshot()).toMatchObject({
        phase: "saved",
        submissionId: firstMeta.intentId,
        analysis: { state: "accepted" },
      }),
    );
    expect(store.startingSubmissionId()).toBeNull();
    expect(start).toHaveBeenCalledTimes(1);
    store.settle(firstMeta.intentId);
    expect(store.getSnapshot()).toEqual({ phase: "idle" });
    add.mockRestore();
  });

  it("keeps the saved call and shows an action when the start fails", async () => {
    const store = new UploadSessionStore();
    await store.run(
      firstMeta,
      new File(["audio"], "call.wav"),
      async () => ({ submissionId: firstMeta.intentId }),
      async () => {
        throw new TypeError("start interrupted");
      },
    );
    await vi.waitFor(() =>
      expect(store.getSnapshot()).toMatchObject({
        phase: "saved",
        submissionId: firstMeta.intentId,
        analysis: { state: "needs_action" },
      }),
    );
    expect(store.startingSubmissionId()).toBeNull();
  });

  it("aborts a pending start on account change or sign-out without late publication", async () => {
    for (const change of ["account", "signout"] as const) {
      const store = new UploadSessionStore();
      store.observeAccount({
        status: "authenticated",
        authenticated: true,
        context: { personId: "p1", sessionId: "s1", tenantId: "t1" },
      });
      const seen: { signal: AbortSignal | null } = { signal: null };
      const started = deferred<AnalysisStartSettled>();
      await store.run(
        firstMeta,
        new File(["audio"], "call.wav"),
        async () => ({ submissionId: firstMeta.intentId }),
        (_saved, signal) => {
          seen.signal = signal;
          return started.promise;
        },
      );
      await vi.waitFor(() => expect(seen.signal).not.toBeNull());

      if (change === "account")
        store.observeAccount({
          status: "authenticated",
          authenticated: true,
          context: { personId: "p2", sessionId: "s2", tenantId: "t1" },
        });
      else {
        expect(store.beginSignOut()).toBe(true);
        store.completeSignOut();
      }
      expect(seen.signal!.aborted).toBe(true);
      expect(store.getSnapshot()).toEqual({ phase: "idle" });

      started.resolve({ state: "accepted" });
      await Promise.resolve();
      await Promise.resolve();
      expect(store.getSnapshot()).toEqual({ phase: "idle" });
      expect(store.startingSubmissionId()).toBeNull();
    }
  });

  it("does not dismiss an unknown outcome or replace its File before reconciliation", async () => {
    const store = new UploadSessionStore();
    const file = new File(["audio"], "call.wav", { type: "audio/wav" });
    const pending = deferred<{ submissionId: string }>();
    const running = store.run(firstMeta, file, () => pending.promise);
    pending.reject(new TypeError("transport interrupted"));
    await expect(running).rejects.toThrow("transport interrupted");

    expect(store.getSnapshot()).toMatchObject({ phase: "interrupted" });
    expect(store.fileFor(firstMeta.intentId)).toBe(file);
    store.settle(firstMeta.intentId);
    expect(store.getSnapshot()).toMatchObject({ phase: "interrupted" });

    await expect(
      store.run(secondMeta, new File(["other"], "other.wav"), async () => ({
        submissionId: secondMeta.intentId,
      })),
    ).rejects.toBeInstanceOf(UploadReconciliationRequiredError);
    await expect(
      store.run(firstMeta, new File(["audio"], "call.wav"), async () => ({
        submissionId: firstMeta.intentId,
      })),
    ).rejects.toBeInstanceOf(UploadReconciliationRequiredError);
    await expect(
      store.run(
        { ...firstMeta, reportLanguage: "hi-Deva+en" },
        file,
        async () => ({ submissionId: firstMeta.intentId }),
      ),
    ).rejects.toBeInstanceOf(UploadReconciliationRequiredError);
    expect(store.getSnapshot()).toMatchObject({ phase: "interrupted" });
  });

  it("keeps the browser leave guard until an unknown result is reconciled", async () => {
    const store = new UploadSessionStore();
    const remove = vi.spyOn(window, "removeEventListener");
    const file = new File(["audio"], "call.wav");
    const pending = deferred<{ submissionId: string }>();
    const running = store.run(firstMeta, file, () => pending.promise);
    pending.reject(new TypeError("transport interrupted"));
    await expect(running).rejects.toThrow("transport interrupted");

    expect(store.getSnapshot()).toMatchObject({
      phase: "interrupted",
      reconciliation: "unknown",
    });
    expect(remove).not.toHaveBeenCalledWith(
      "beforeunload",
      expect.any(Function),
    );

    store.markMissing(firstMeta.intentId);
    expect(store.getSnapshot()).toMatchObject({
      phase: "interrupted",
      reconciliation: "missing",
    });
    expect(remove).toHaveBeenCalledWith("beforeunload", expect.any(Function));
    remove.mockRestore();
  });

  it("retains the source digest when a PUT ends with an unknown result", async () => {
    const store = new UploadSessionStore();
    const sourceSha256 = "a".repeat(64);
    const file = new File(["audio"], "call.wav");
    store.observeAccount({
      status: "unauthenticated",
      authenticated: false,
      context: null,
    });

    const running = store.run(firstMeta, file, async () => {
      store.sourceDigest(firstMeta.intentId, sourceSha256);
      throw new TypeError("transport interrupted");
    });
    await expect(running).rejects.toThrow("transport interrupted");

    expect(store.getSnapshot()).toMatchObject({
      phase: "interrupted",
      intentId: firstMeta.intentId,
      sourceSha256,
      reconciliation: "unknown",
    });
    expect(store.canReconcile(firstMeta.intentId)).toBe(true);
  });

  it("clears the retained File only after a same-intent reconciliation succeeds", async () => {
    const store = new UploadSessionStore();
    const file = new File(["audio"], "call.wav", { type: "audio/wav" });
    const pending = deferred<{ submissionId: string }>();
    const first = store.run(firstMeta, file, () => pending.promise);
    pending.reject(new TypeError("lost connection"));
    await expect(first).rejects.toThrow("lost connection");

    const recovered = await store.run(firstMeta, file, async () => ({
      submissionId: firstMeta.intentId,
    }));
    expect(recovered.submissionId).toBe(firstMeta.intentId);
    expect(store.getSnapshot()).toMatchObject({
      phase: "saved",
      submissionId: firstMeta.intentId,
    });
    expect(store.fileFor(firstMeta.intentId)).toBeNull();

    store.settle(firstMeta.intentId);
    expect(store.getSnapshot()).toEqual({ phase: "idle" });
  });

  it("revokes the retained File and transport when the confirmed account changes", async () => {
    const store = new UploadSessionStore();
    const file = new File(["audio"], "call.wav");
    store.observeAccount({
      status: "ready",
      authenticated: true,
      context: {
        personId: "person-a",
        sessionId: "session-a",
        tenantId: "tenant-a",
      },
    });
    const running = store.run(
      firstMeta,
      file,
      (signal) =>
        new Promise<{ submissionId: string }>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(new Error("aborted")), {
            once: true,
          });
        }),
    );
    expect(store.fileFor(firstMeta.intentId)).toBe(file);
    store.observeAccount({
      status: "ready",
      authenticated: true,
      context: {
        personId: "person-b",
        sessionId: "session-b",
        tenantId: "tenant-b",
      },
    });
    await expect(running).rejects.toBeInstanceOf(UploadCancelledError);
    expect(store.fileFor(firstMeta.intentId)).toBeNull();
    expect(store.getSnapshot()).toEqual({
      phase: "account_changed",
      viewed: false,
    });
  });

  describe("report-ready reconciliation", () => {
    const owner = { personId: "p1", sessionId: "s1", tenantId: "t1" };
    const other = { personId: "p2", sessionId: "s2", tenantId: "t1" };
    const signedIn = (context: typeof owner) => ({
      status: "ready",
      authenticated: true,
      context,
    });

    it("keeps the status through acceptance and clears it only for the same call and owner", async () => {
      const store = new UploadSessionStore();
      store.observeAccount(signedIn(owner));
      const started = deferred<AnalysisStartSettled>();
      await store.run(
        firstMeta,
        new File(["audio"], "call.wav"),
        async () => ({ submissionId: firstMeta.intentId }),
        () => started.promise,
      );
      await vi.waitFor(() =>
        expect(store.startingSubmissionId()).toBe(firstMeta.intentId),
      );

      // A pending start is never dropped, even by a ready report.
      store.settleReportReady(firstMeta.intentId, owner);
      expect(store.getSnapshot()).toMatchObject({ phase: "saved" });

      started.resolve({ state: "accepted" });
      await vi.waitFor(() =>
        expect(store.getSnapshot()).toMatchObject({
          analysis: { state: "accepted" },
        }),
      );
      // An unrelated older call being ready says nothing about this upload.
      store.settleReportReady(secondMeta.intentId, owner);
      // A read for a different identity cannot confirm this upload.
      store.settleReportReady(firstMeta.intentId, other);
      expect(store.getSnapshot()).toMatchObject({
        phase: "saved",
        submissionId: firstMeta.intentId,
        analysis: { state: "accepted" },
      });

      store.settleReportReady(firstMeta.intentId, owner);
      expect(store.getSnapshot()).toEqual({ phase: "idle" });
    });

    it("does not clear an upload whose starting identity was never confirmed", async () => {
      const store = new UploadSessionStore();
      await store.run(
        firstMeta,
        new File(["audio"], "call.wav"),
        async () => ({ submissionId: firstMeta.intentId }),
      );
      store.observeAccount(signedIn(owner));
      store.settleReportReady(firstMeta.intentId, owner);
      expect(store.getSnapshot()).toMatchObject({
        phase: "saved",
        submissionId: firstMeta.intentId,
      });
    });

    it("never clears an in-flight, unconfirmed or account-changed state", async () => {
      const store = new UploadSessionStore();
      store.observeAccount(signedIn(owner));
      const file = new File(["audio"], "call.wav");
      const pending = deferred<{ submissionId: string }>();
      const running = store.run(firstMeta, file, () => pending.promise);
      store.markSending(firstMeta.intentId);

      store.settleReportReady(firstMeta.intentId, owner);
      expect(store.getSnapshot()).toMatchObject({ phase: "uploading" });
      expect(store.fileFor(firstMeta.intentId)).toBe(file);

      pending.reject(new TypeError("transport interrupted"));
      await expect(running).rejects.toThrow("transport interrupted");
      store.settleReportReady(firstMeta.intentId, owner);
      expect(store.getSnapshot()).toMatchObject({
        phase: "interrupted",
        reconciliation: "unknown",
      });

      store.observeAccount(signedIn(other));
      expect(store.getSnapshot()).toEqual({
        phase: "account_changed",
        viewed: false,
      });
      store.settleReportReady(firstMeta.intentId, other);
      store.settleReportReady(firstMeta.intentId, owner);
      expect(store.getSnapshot()).toEqual({
        phase: "account_changed",
        viewed: false,
      });
    });
  });

  it("requires explicit confirmation to sign out with an unresolved upload", async () => {
    const store = new UploadSessionStore();
    const file = new File(["audio"], "call.wav");
    const pending = deferred<{ submissionId: string }>();
    const running = store.run(firstMeta, file, () => pending.promise);
    expect(store.beginSignOut()).toBe(false);
    expect(store.requiresSignOutConfirmation()).toBe(true);
    pending.reject(new TypeError("transport interrupted"));
    await expect(running).rejects.toThrow("transport interrupted");
    expect(store.beginSignOut()).toBe(false);
    expect(store.beginSignOut(true)).toBe(true);
    store.completeSignOut();
    expect(store.getSnapshot()).toEqual({ phase: "idle" });
    expect(store.fileFor(firstMeta.intentId)).toBeNull();
  });
});
