import { describe, expect, it, vi } from "vitest";

import {
  UploadCancelledError,
  UploadInProgressError,
  UploadReconciliationRequiredError,
  UploadSessionStore,
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
    expect(remove).toHaveBeenCalledWith(
      "beforeunload",
      expect.any(Function),
    );
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
    const running = store.run(firstMeta, file, (signal) =>
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
