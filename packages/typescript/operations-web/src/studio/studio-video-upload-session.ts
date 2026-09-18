import { hashBlobSha256 } from "@ac/ui/blob-sha256";
import { AdminApiProblem, newIdempotencyKey } from "../admin-api";
import {
  completeStudioVideoUpload,
  createStudioVideoUpload,
  loadStudioUploadStatus,
  putStudioVideoBytes,
  studioUploadRequestSchema,
  type StudioUploadIntent,
  type StudioUploadRequest,
  type StudioUploadStatus,
} from "./studio-video-upload-api";

export type UploadStage =
  | "idle"
  | "preparing"
  | "admitting"
  | "uploading"
  | "verifying"
  | "processing"
  | "ready"
  | "failed"
  | "retired"
  | "paused"
  | "error"
  | "denied"
  | "rejected";
export type UploadSnapshot = Readonly<{
  stage: UploadStage;
  filename: string;
  bytes: number;
  fraction: number | null;
  busy: boolean;
  pending: boolean;
  needsFile: boolean;
  message: string;
  status: StudioUploadStatus | null;
}>;
export const emptyUpload: UploadSnapshot = {
  stage: "idle",
  filename: "",
  bytes: 0,
  fraction: null,
  busy: false,
  pending: false,
  needsFile: false,
  message: "",
  status: null,
};
const terminalStates = ["ready", "failed", "retired"];
export function uploadAcceptsFile(snapshot: UploadSnapshot) {
  return (
    !snapshot.busy &&
    (snapshot.needsFile ||
      (!snapshot.pending &&
        (["idle", "ready", "failed", "retired", "rejected"].includes(
          snapshot.stage,
        ) ||
          (snapshot.stage === "denied" &&
            (snapshot.status === null ||
              terminalStates.includes(snapshot.status.state))))))
  );
}
let scope = "";
const sessions = new Map<string, StudioUploadSession>();
const warnPending = (event: BeforeUnloadEvent) => {
  event.preventDefault();
  event.returnValue = "";
};
function refreshPendingGuard() {
  if (typeof window === "undefined") return;
  window.removeEventListener("beforeunload", warnPending);
  if (
    [...sessions.values()].some(
      (session) => session.getSnapshot().pending || session.getSnapshot().busy,
    )
  )
    window.addEventListener("beforeunload", warnPending);
}

/** Memory-only intent. A newly verified tenant/person/session destroys the old scope. */
export function activateStudioUploadScope(context: string) {
  if (typeof window === "undefined" || context === scope) return;
  for (const session of sessions.values()) session.dispose();
  sessions.clear();
  scope = context;
  refreshPendingGuard();
}
export function studioUploadSession(
  context: string,
  programId: string,
): StudioUploadSession {
  if (!context || scope !== context)
    throw new Error("Confirm your current editing session.");
  let session = sessions.get(programId);
  if (!session) {
    if (sessions.size >= 20) {
      const reusable = [...sessions.entries()].find(([, item]) =>
        item.canEvict(),
      );
      if (reusable) {
        reusable[1].dispose();
        sessions.delete(reusable[0]);
      } else
        throw new Error("Finish an earlier upload before starting another.");
    }
    session = new StudioUploadSession(() => scope === context, programId);
    sessions.set(programId, session);
  }
  return session;
}

/** Apply only a freshly verified capability result, never a failed session read. */
export function restrictStudioUploadScope(
  context: string,
  allowed: (programId: string) => boolean,
) {
  if (!context || context !== scope) return;
  for (const [programId, session] of sessions)
    if (!allowed(programId)) session.revokeSource();
}

/** Sequential commands with stable idempotency and source ownership across UI remounts. */
export class StudioUploadSession {
  private snapshot: UploadSnapshot = emptyUpload;
  private listeners = new Set<() => void>();
  private source: File | null = null;
  private body: StudioUploadRequest | null = null;
  private intent: StudioUploadIntent | null = null;
  private createKey = "";
  private completeKey = "";
  private completionRequested = false;
  private controller: AbortController | null = null;
  private disposed = false;
  private authorityRevoked = false;
  constructor(
    private current: () => boolean,
    private programId: string,
  ) {}
  getSnapshot = () => this.snapshot;
  canEvict = () =>
    this.listeners.size === 0 &&
    !this.snapshot.pending &&
    !this.snapshot.busy &&
    (uploadAcceptsFile(this.snapshot) ||
      terminalStates.includes(this.snapshot.status?.state ?? ""));
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private update(patch: Partial<UploadSnapshot>) {
    if (this.disposed || !this.current()) return;
    this.snapshot = { ...this.snapshot, ...patch };
    refreshPendingGuard();
    for (const listener of this.listeners) listener();
  }
  private requireCurrent(signal: AbortSignal) {
    signal.throwIfAborted();
    if (this.disposed || !this.current())
      throw new DOMException("Session changed", "AbortError");
  }
  async start(file: File, maximumBytes: number) {
    if (!uploadAcceptsFile(this.snapshot) || this.disposed || !this.current())
      return;
    if (this.snapshot.needsFile) {
      await this.reselect(file, maximumBytes);
      return;
    }
    if (
      !Number.isSafeInteger(maximumBytes) ||
      maximumBytes <= 0 ||
      file.size > maximumBytes
    ) {
      this.update({
        message: "This file exceeds the upload limit shown above.",
      });
      return;
    }
    try {
      studioUploadRequestSchema.parse({
        filename: file.name,
        content_type: file.type,
        content_length: file.size,
        checksum_sha256: "0".repeat(64),
      });
    } catch {
      this.update({
        message: "Choose a non-empty MP4 or WebM file with a valid filename.",
      });
      return;
    }
    try {
      this.createKey = newIdempotencyKey();
      this.completeKey = newIdempotencyKey();
    } catch {
      this.update({
        message:
          "A safe upload request couldn’t be created. Reload this workspace and try again.",
      });
      return;
    }
    this.source = file;
    this.body = null;
    this.intent = null;
    this.completionRequested = false;
    this.update({
      ...emptyUpload,
      stage: "preparing",
      filename: file.name,
      bytes: file.size,
      pending: true,
    });
    await this.resume();
  }
  pause() {
    this.controller?.abort();
  }
  revokeSource() {
    if (this.disposed) return;
    this.authorityRevoked = true;
    this.controller?.abort();
    this.source = null;
    const needsFile =
      !!this.body &&
      !this.completionRequested &&
      !["processing", "ready", "failed", "retired"].includes(
        this.snapshot.status?.state ?? "",
      );
    this.update({
      stage: "denied",
      needsFile,
      pending: this.body !== null && this.snapshot.pending,
      message:
        "Editing access changed. Your local file was released; restore access to check this request.",
    });
  }
  private async reselect(file: File, maximumBytes: number) {
    if (this.snapshot.busy || !this.body || this.disposed || !this.current())
      return;
    if (
      file.size > maximumBytes ||
      file.size !== this.body.content_length ||
      file.name.trim() !== this.body.filename ||
      file.type !== this.body.content_type
    ) {
      this.update({
        message:
          "Choose the same filename, format and size to recover this upload.",
      });
      return;
    }
    const controller = new AbortController();
    this.controller = controller;
    this.update({ stage: "preparing", busy: true, fraction: 0, message: "" });
    let matches = false;
    try {
      const checksum = await hashBlobSha256(file, {
        signal: controller.signal,
        onProgress: (fraction) => this.update({ fraction }),
      });
      this.requireCurrent(controller.signal);
      if (checksum !== this.body.checksum_sha256)
        this.update({
          stage: "paused",
          message:
            "This is a different file. Select the original video to resume the same upload.",
        });
      else {
        this.source = file;
        matches = true;
        this.update({ needsFile: false });
      }
    } catch (error) {
      this.failure(error, controller.signal);
    } finally {
      this.controller = null;
      this.update({ busy: false, fraction: null });
    }
    if (matches) await this.resume();
  }
  dispose() {
    this.disposed = true;
    this.controller?.abort();
    this.source = null;
    this.body = null;
    this.intent = null;
    this.snapshot = emptyUpload;
    this.listeners.clear();
  }
  private project(status: StudioUploadStatus) {
    const stage =
      status.state === "expected" || status.state === "uploading"
        ? "paused"
        : status.state;
    const terminal = ["ready", "failed", "retired"].includes(stage);
    if (terminal || stage === "processing") this.source = null;
    this.update({
      stage,
      status,
      fraction: null,
      needsFile:
        stage === "paused" && !this.source && !this.completionRequested,
      pending: stage === "paused",
      message: "",
    });
  }
  async check() {
    if (!this.intent || this.snapshot.busy || this.disposed || !this.current())
      return;
    const controller = new AbortController();
    this.controller = controller;
    this.update({ busy: true, message: "" });
    try {
      const status = await loadStudioUploadStatus(this.programId, this.intent, {
        signal: controller.signal,
      });
      this.requireCurrent(controller.signal);
      this.project(status);
    } catch (error) {
      this.failure(error, controller.signal);
    } finally {
      this.controller = null;
      this.update({ busy: false });
    }
  }
  private failure(error: unknown, signal: AbortSignal) {
    const denied =
      error instanceof AdminApiProblem &&
      [401, 403, 404, 410].includes(error.status);
    if (denied) this.revokeSource();
    this.update({
      stage:
        denied || this.authorityRevoked
          ? "denied"
          : signal.aborted
            ? this.snapshot.status?.state === "processing" &&
              !this.snapshot.pending
              ? "processing"
              : "paused"
            : "error",
      fraction: null,
      message: denied
        ? "Editing access could not be confirmed. Sign in again or reopen this course."
        : this.snapshot.status?.state === "processing" && !this.snapshot.pending
          ? "Playback preparation continues. Check the video status again in a moment."
          : signal.aborted
            ? "Stopped waiting. The server may still finish this request. Resume this same upload to check it."
            : "We couldn’t confirm the result. Retry this same upload; you won’t create a second copy.",
    });
  }
  async resume() {
    if (this.snapshot.busy || this.disposed || !this.current()) return;
    this.authorityRevoked = false;
    const controller = new AbortController();
    this.controller = controller;
    const { signal } = controller;
    this.update({ busy: true, pending: true, message: "" });
    try {
      if (!this.body) {
        if (!this.source) {
          this.update({
            stage: "paused",
            needsFile: true,
            message: "Select the same video file to continue this upload.",
          });
          return;
        }
        this.update({ stage: "preparing", fraction: 0 });
        const checksum = await hashBlobSha256(this.source, {
          signal,
          onProgress: (fraction) => this.update({ fraction }),
        });
        this.requireCurrent(signal);
        this.body = studioUploadRequestSchema.parse({
          filename: this.source.name,
          content_type: this.source.type,
          content_length: this.source.size,
          checksum_sha256: checksum,
        });
      }
      if (!this.intent) {
        this.update({ stage: "admitting", fraction: null });
        this.intent = await createStudioVideoUpload(
          this.programId,
          this.body,
          this.createKey,
          { signal },
        );
        this.requireCurrent(signal);
      }
      const status = await loadStudioUploadStatus(this.programId, this.intent, {
        signal,
      });
      this.requireCurrent(signal);
      if (!["expected", "uploading"].includes(status.state)) {
        this.project(status);
        return;
      }
      if (!this.completionRequested) {
        if (Date.parse(status.expires_at) <= Date.now()) {
          this.update({
            stage: "rejected",
            pending: false,
            message:
              "The upload window expired. Choose the file again to start a new upload.",
          });
          this.source = null;
          return;
        }
        if (!this.source) {
          this.update({
            stage: "paused",
            needsFile: true,
            message: "Select the same video file to continue this upload.",
          });
          return;
        }
        this.update({ stage: "uploading", fraction: null });
        await putStudioVideoBytes(
          this.programId,
          this.intent,
          this.source,
          this.body,
          {
            signal,
            startOffset: status.uploaded_bytes ?? 0,
            onProgress: (fraction) => this.update({ fraction }),
          },
        );
        this.requireCurrent(signal);
        this.completionRequested = true;
      }
      this.update({ stage: "verifying", fraction: null });
      await completeStudioVideoUpload(
        this.programId,
        this.intent,
        this.completeKey,
        { signal },
      );
      this.requireCurrent(signal);
      const result = await loadStudioUploadStatus(this.programId, this.intent, {
        signal,
      });
      this.requireCurrent(signal);
      this.project(result);
    } catch (error) {
      if (
        !this.intent &&
        this.snapshot.stage === "admitting" &&
        error instanceof AdminApiProblem &&
        [400, 413, 415, 422].includes(error.status)
      ) {
        this.source = null;
        this.update({
          stage: "rejected",
          pending: false,
          message:
            "This file was not accepted. Check the format and size, then choose another file.",
        });
      } else this.failure(error, signal);
    } finally {
      this.controller = null;
      this.update({ busy: false });
    }
  }
}
