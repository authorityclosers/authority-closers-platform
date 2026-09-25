"use client";

import {
  createContext,
  useContext,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

export type UploadMeta = Readonly<{
  intentId: string;
  fileName: string;
  totalBytes: number;
  /** The report language chosen with the consent; an adopting view keeps it. */
  reportLanguage: string | null;
  /** The intake that owns the upload, for links back to it. */
  homeHref: string;
  /** Filled after hashing locally, before the source PUT begins. */
  sourceSha256: string | null;
}>;

type ActiveUpload = UploadMeta &
  (
    | Readonly<{ phase: "preparing" }>
    | Readonly<{ phase: "uploading" }>
    | Readonly<{ phase: "saved"; submissionId: string }>
    | Readonly<{
        phase: "interrupted";
        reconciliation: "unknown" | "missing";
      }>
  );

export type UploadSnapshot =
  | Readonly<{ phase: "idle" }>
  | (ActiveUpload & Readonly<{ viewed: boolean }>)
  | Readonly<{ phase: "account_changed"; viewed: false }>;

export type UploadAccountObservation = Readonly<{
  status: string;
  authenticated: boolean | null;
  context: Readonly<{
    personId: string;
    sessionId: string;
    tenantId: string;
  }> | null;
}>;

export class UploadCancelledError extends Error {
  constructor() {
    super("upload_cancelled");
    this.name = "UploadCancelledError";
  }
}

export class UploadInProgressError extends Error {
  constructor() {
    super("upload_in_progress");
    this.name = "UploadInProgressError";
  }
}

export class UploadReconciliationRequiredError extends Error {
  constructor() {
    super("upload_reconciliation_required");
    this.name = "UploadReconciliationRequiredError";
  }
}

const IDLE: UploadSnapshot = Object.freeze({ phase: "idle" });

/**
 * Owns the one live source upload for this document. It is mounted by the root
 * layout, which persists across App Router client navigation, so the transport
 * is not aborted when the view that started it unmounts. A full reload still
 * ends it: while bytes are in flight the store asks the browser to confirm
 * leaving. It records only transport facts; it never infers analysis progress.
 */
export class UploadSessionStore {
  private snapshot: UploadSnapshot = IDLE;
  private readonly listeners = new Set<() => void>();
  private controller: AbortController | null = null;
  private live: Promise<unknown> | null = null;
  private retainedFile: Readonly<{ intentId: string; file: File }> | null = null;
  private viewers = 0;
  private accountKey: string | null = null;
  private accountObserved = false;
  private uploadOwnerKey: string | null = null;
  private uploadOwnerObserved = false;
  private signOutLocked = false;

  private readonly confirmLeave = (event: BeforeUnloadEvent) => {
    event.preventDefault();
    // Older browsers show the prompt only when a return value is set.
    event.returnValue = "";
  };

  readonly subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  readonly getSnapshot = () => this.snapshot;

  /** Bind transport memory to the existing server-confirmed workspace. */
  observeAccount(observation: UploadAccountObservation) {
    const nextKey = observation.context
      ? JSON.stringify([
          observation.context.personId,
          observation.context.sessionId,
          observation.context.tenantId,
        ])
      : observation.status === "unauthenticated"
        ? null
        : undefined;
    // Loading, chooser and unavailable states do not establish a different
    // identity. Keep the last confirmed binding until the server resolves it.
    if (nextKey === undefined) return;
    if (!this.accountObserved) {
      this.accountObserved = true;
      this.accountKey = nextKey;
      return;
    }
    if (nextKey === this.accountKey) return;
    this.accountKey = nextKey;
    if (
      this.snapshot.phase === "preparing" ||
      this.snapshot.phase === "uploading" ||
      this.snapshot.phase === "interrupted"
    ) {
      const currentController = this.controller;
      this.controller = null;
      this.live = null;
      this.retainedFile = null;
      this.uploadOwnerKey = null;
      this.uploadOwnerObserved = false;
      this.guardUnload(false);
      this.publishAccountChanged();
      // Invalidate the task's completion handler before aborting it so an
      // old-account response cannot replace the explicit warning.
      currentController?.abort();
    } else if (this.snapshot.phase === "saved") {
      this.retainedFile = null;
      this.publish(null);
    }
  }

  requiresSignOutConfirmation() {
    return (
      this.snapshot.phase === "preparing" ||
      this.snapshot.phase === "uploading" ||
      this.snapshot.phase === "interrupted" ||
      this.snapshot.phase === "account_changed"
    );
  }

  beginSignOut(confirmedUnresolved = false): boolean {
    if (this.signOutLocked) return false;
    if (this.requiresSignOutConfirmation() && !confirmedUnresolved)
      return false;
    this.signOutLocked = true;
    return true;
  }

  cancelSignOut() {
    this.signOutLocked = false;
  }

  /** Called only after the canonical logout endpoint confirms 204. */
  completeSignOut() {
    const currentController = this.controller;
    this.controller = null;
    this.live = null;
    this.retainedFile = null;
    this.accountKey = null;
    this.accountObserved = true;
    this.uploadOwnerKey = null;
    this.uploadOwnerObserved = false;
    this.signOutLocked = false;
    this.guardUnload(false);
    this.publish(null);
    currentController?.abort();
  }

  /** Starts the transport. Only one upload may be live at a time. */
  run<T extends { submissionId: string }>(
    meta: UploadMeta,
    file: File,
    task: (signal: AbortSignal) => Promise<T>,
  ): Promise<T> {
    if (this.signOutLocked)
      return Promise.reject(new UploadInProgressError());
    if (
      this.snapshot.phase === "preparing" ||
      this.snapshot.phase === "uploading"
    )
      return Promise.reject(new UploadInProgressError());
    if (this.snapshot.phase === "interrupted") {
      if (
        this.snapshot.intentId !== meta.intentId ||
        this.snapshot.fileName !== meta.fileName ||
        this.snapshot.totalBytes !== meta.totalBytes ||
        this.snapshot.reportLanguage !== meta.reportLanguage ||
        this.snapshot.homeHref !== meta.homeHref ||
        this.retainedFile?.intentId !== meta.intentId ||
        this.retainedFile.file !== file
      )
        return Promise.reject(new UploadReconciliationRequiredError());
    }
    const controller = new AbortController();
    this.controller = controller;
    this.uploadOwnerKey = this.accountKey;
    this.uploadOwnerObserved = this.accountObserved;
    this.retainedFile = { intentId: meta.intentId, file };
    this.publish({ ...meta, phase: "preparing" });
    this.guardUnload(true);
    const live = Promise.resolve()
      .then(() => {
        if (controller.signal.aborted) throw new UploadCancelledError();
        return task(controller.signal);
      })
      .then(
        (result) => {
          if (this.controller === controller) {
            this.retainedFile = null;
            this.finish({
              ...this.latestMeta(meta),
              phase: "saved",
              submissionId: result.submissionId,
            });
          }
          return result;
        },
        (error: unknown) => {
          const cancelled = controller.signal.aborted;
          if (this.controller === controller)
            this.finish({
              ...this.latestMeta(meta),
              phase: "interrupted",
              reconciliation: "unknown",
            });
          throw cancelled ? new UploadCancelledError() : error;
        },
      );
    this.live = live;
    // Views attach their own handlers; this keeps an unobserved rejection quiet.
    live.catch(() => {});
    return live;
  }

  /** The live transport of an upload started by an earlier view. */
  adopt(intentId: string): Promise<unknown> | null {
    return (this.snapshot.phase === "preparing" ||
      this.snapshot.phase === "uploading") &&
      this.snapshot.intentId === intentId
      ? this.live
      : null;
  }

  /** The selected File remains in memory while the outcome is unresolved. */
  fileFor(intentId: string): File | null {
    if (
      this.snapshot.phase === "idle" ||
      this.snapshot.phase === "saved" ||
      this.snapshot.phase === "account_changed" ||
      this.snapshot.intentId !== intentId ||
      this.retainedFile?.intentId !== intentId
    )
      return null;
    return this.retainedFile.file;
  }

  canReconcile(intentId: string) {
    return (
      this.snapshot.phase === "interrupted" &&
      this.snapshot.intentId === intentId &&
      this.accountObserved &&
      this.uploadOwnerObserved &&
      this.accountKey === this.uploadOwnerKey
    );
  }

  sourceDigest(intentId: string, sha256: string) {
    if (
      (this.snapshot.phase === "preparing" ||
        this.snapshot.phase === "uploading" ||
        this.snapshot.phase === "interrupted") &&
      this.snapshot.intentId === intentId
    )
      this.publish({ ...this.snapshot, sourceSha256: sha256 });
  }

  markReconciled(intentId: string, submissionId: string) {
    const current = this.snapshot;
    if (
      (current.phase !== "preparing" &&
        current.phase !== "uploading" &&
        current.phase !== "interrupted") ||
      current.intentId !== intentId
    )
      return;
    this.retainedFile = null;
    this.controller = null;
    this.live = null;
    this.guardUnload(false);
    this.publish({ ...current, phase: "saved", submissionId });
  }

  markMissing(intentId: string) {
    const current = this.snapshot;
    if (
      (current.phase !== "preparing" &&
        current.phase !== "uploading" &&
        current.phase !== "interrupted") ||
      current.intentId !== intentId
    )
      return;
    this.controller = null;
    this.live = null;
    this.guardUnload(false);
    this.publish({ ...current, phase: "interrupted", reconciliation: "missing" });
  }

  /** Aborts the transport. The outcome stays unknown until it is read back. */
  cancel(intentId: string) {
    if (
      (this.snapshot.phase === "preparing" ||
        this.snapshot.phase === "uploading") &&
      this.snapshot.intentId === intentId
    )
      this.controller?.abort();
  }

  markSending(intentId: string) {
    const current = this.snapshot;
    if (current.phase === "preparing" && current.intentId === intentId)
      this.publish({ ...current, phase: "uploading" });
  }

  /** Clears a finished outcome once a view has shown or applied it. */
  settle(intentId: string) {
    if (
      this.snapshot.phase === "saved" &&
      this.snapshot.intentId === intentId
    ) {
      this.retainedFile = null;
      this.uploadOwnerKey = null;
      this.uploadOwnerObserved = false;
      this.publish(null);
    }
  }

  /** A view that shows the upload itself hides the minimized indicator. */
  view(): () => void {
    this.viewers += 1;
    this.refreshViewed();
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.viewers -= 1;
      this.refreshViewed();
    };
  }

  private finish(next: ActiveUpload) {
    this.controller = null;
    this.live = null;
    // A failed transport does not prove that the server rejected the bytes.
    // Keep the native leave prompt until a safe read resolves that ambiguity.
    this.guardUnload(
      next.phase === "interrupted" && next.reconciliation === "unknown",
    );
    this.publish(next);
  }

  private latestMeta(meta: UploadMeta): UploadMeta {
    const current = this.snapshot;
    return current.phase !== "idle" &&
      current.phase !== "account_changed" &&
      current.intentId === meta.intentId
      ? { ...meta, sourceSha256: current.sourceSha256 ?? meta.sourceSha256 }
      : meta;
  }

  private guardUnload(active: boolean) {
    if (typeof window === "undefined") return;
    if (active) window.addEventListener("beforeunload", this.confirmLeave);
    else window.removeEventListener("beforeunload", this.confirmLeave);
  }

  private publish(next: ActiveUpload | null) {
    this.snapshot = next ? { ...next, viewed: this.viewers > 0 } : IDLE;
    for (const listener of [...this.listeners]) listener();
  }

  private publishAccountChanged() {
    this.snapshot = { phase: "account_changed", viewed: false };
    for (const listener of [...this.listeners]) listener();
  }

  private refreshViewed() {
    const current = this.snapshot;
    const viewed = this.viewers > 0;
    if (
      current.phase === "idle" ||
      current.phase === "account_changed" ||
      current.viewed === viewed
    )
      return;
    this.snapshot = { ...current, viewed };
    for (const listener of [...this.listeners]) listener();
  }
}

const UploadSessionContext = createContext<UploadSessionStore | null>(null);

export function UploadSessionProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => new UploadSessionStore());
  return (
    <UploadSessionContext.Provider value={store}>
      {children}
    </UploadSessionContext.Provider>
  );
}

/** Null where no root provider exists, such as the learner-web embed. */
export function useUploadSession() {
  return useContext(UploadSessionContext);
}

const subscribeNowhere = () => () => {};
const idleSnapshot = () => IDLE;

export function useUploadSnapshot(): UploadSnapshot {
  const store = useUploadSession();
  return useSyncExternalStore(
    store ? store.subscribe : subscribeNowhere,
    store ? store.getSnapshot : idleSnapshot,
    idleSnapshot,
  );
}
