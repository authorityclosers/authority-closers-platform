"use client";

import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { ActionButton } from "@ac/ui";
import { AdminApiProblem } from "../admin-api";
import {
  Check,
  CloudUpload,
  FileVideo,
  LoaderCircle,
  Pause,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import {
  loadStudioUploadCapability,
  type StudioUploadCapability,
} from "./studio-video-upload-api";
import {
  activateStudioUploadScope,
  emptyUpload,
  studioUploadSession,
  uploadAcceptsFile,
  type StudioUploadSession,
  type UploadStage,
} from "./studio-video-upload-session";
import panel from "./studio-video-panel.module.css";
import styles from "./studio-video-upload.module.css";
import { StudioVideoPreview } from "./studio-video-preview";

type Props = {
  programId: string;
  recoveryContext: string;
  canWrite: boolean;
  disabled?: boolean;
  onPendingChange?: (pending: boolean) => void;
  onReady?: () => void;
};
const titles: Record<UploadStage, string> = {
  idle: "Add a course video",
  preparing: "Checking your file",
  admitting: "Preparing a secure upload",
  uploading: "Uploading your video",
  verifying: "Checking the uploaded video",
  processing: "Preparing playback",
  ready: "Your video is ready",
  failed: "This video couldn’t be processed",
  retired: "This video is no longer available",
  paused: "Upload paused",
  error: "Let’s check your upload",
  denied: "Restore your editing access",
  rejected: "Choose another video",
};
export function videoFileSize(bytes: number) {
  return bytes >= 1_000_000_000
    ? `${(bytes / 1_000_000_000).toFixed(1)} GB`
    : `${Math.max(0.1, bytes / 1_000_000).toFixed(1)} MB`;
}
const noopSubscribe = () => () => {};
const emptySnapshot = () => emptyUpload;

export function StudioVideoUpload(props: Props) {
  if (!props.canWrite || !props.recoveryContext) return null;
  return (
    <UploadSessionView
      key={`${props.recoveryContext}:${props.programId}`}
      {...props}
    />
  );
}

function UploadSessionView({
  programId,
  recoveryContext,
  disabled = false,
  onPendingChange,
  onReady,
}: Props) {
  const id = useId();
  const [session, setSession] = useState<StudioUploadSession | null>(null);
  const [sessionError, setSessionError] = useState("");
  const [capability, setCapability] = useState<StudioUploadCapability | null>(
    null,
  );
  const [capabilityError, setCapabilityError] = useState("");
  const [check, setCheck] = useState(0);
  const [checking, setChecking] = useState(true);
  const input = useRef<HTMLInputElement>(null);
  const callbacks = useRef({ onPendingChange, onReady });
  const notified = useRef<string | null>(null);
  useLayoutEffect(() => {
    callbacks.current = { onPendingChange, onReady };
  }, [onPendingChange, onReady]);
  const snapshot = useSyncExternalStore(
    session?.subscribe ?? noopSubscribe,
    session?.getSnapshot ?? emptySnapshot,
    emptySnapshot,
  );

  useLayoutEffect(() => {
    let mounted = true;
    activateStudioUploadScope(recoveryContext);
    try {
      const current = studioUploadSession(recoveryContext, programId);
      // Attach the external memory-only session after commit, never during render.
      queueMicrotask(() => {
        if (mounted) setSession(current);
      });
      return () => {
        mounted = false;
        current.pause();
        callbacks.current.onPendingChange?.(false);
      };
    } catch {
      queueMicrotask(() => {
        if (mounted)
          setSessionError(
            "Finish an earlier upload in this tab before starting another.",
          );
      });
      return () => {
        mounted = false;
      };
    }
  }, [recoveryContext, programId]);
  useEffect(() => {
    const controller = new AbortController();
    void loadStudioUploadCapability(programId, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setCapability(result);
      })
      .catch((error) => {
        if (
          !controller.signal.aborted &&
          error instanceof AdminApiProblem &&
          [401, 403, 404, 410].includes(error.status)
        )
          session?.revokeSource();
        if (!controller.signal.aborted)
          setCapabilityError(
            "Upload availability couldn’t be checked. Reopen the course or try again.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setChecking(false);
      });
    return () => controller.abort();
  }, [programId, check, session]);
  useEffect(() => {
    callbacks.current.onPendingChange?.(snapshot.pending || snapshot.busy);
    if (!snapshot.pending && !snapshot.busy) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [snapshot.pending, snapshot.busy]);
  useEffect(() => {
    if (
      snapshot.stage === "ready" &&
      snapshot.status &&
      notified.current !== snapshot.status.version_id
    ) {
      notified.current = snapshot.status.version_id;
      callbacks.current.onReady?.();
    }
    if (
      snapshot.stage !== "processing" ||
      snapshot.busy ||
      !capability?.available
    )
      return;
    const timer = setTimeout(() => {
      if (document.visibilityState !== "hidden") void session?.check();
    }, 10_000);
    const visible = () => {
      if (document.visibilityState === "visible") void session?.check();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [snapshot, session, capability]);

  const ready = capability?.available && !checking;
  const hidden = snapshot.stage === "denied" || !ready;
  const canChoose =
    ready && !!session && !disabled && uploadAcceptsFile(snapshot);
  const active = ["preparing", "admitting", "uploading", "verifying"].includes(
    snapshot.stage,
  );
  async function choose(file: File | undefined) {
    if (!file || !canChoose || !capability?.max_source_bytes) return;
    await session?.start(file, capability.max_source_bytes);
  }
  return (
    <section
      className={`${panel.panel} ${styles.upload}`}
      data-stage={snapshot.stage}
      aria-labelledby={`${id}-title`}
    >
      <div className={styles.heading}>
        <span className={styles.mark} aria-hidden="true">
          {snapshot.stage === "ready" ? (
            <Check size={24} />
          ) : (
            <CloudUpload size={24} />
          )}
        </span>
        <div>
          <span className={panel.eyebrow}>Media for lessons</span>
          <h3 id={`${id}-title`}>
            {hidden ? "Add a course video" : titles[snapshot.stage]}
          </h3>
          <p className={styles.subheading}>
            Upload once, then connect the ready video to a lesson.
          </p>
        </div>
        {canChoose ? (
          <ActionButton
            variant="secondary"
            onClick={() => input.current?.click()}
          >
            <CloudUpload size={17} aria-hidden="true" />{" "}
            {snapshot.needsFile ? "Select the same video" : "Choose video"}
          </ActionButton>
        ) : null}
      </div>
      {checking ? (
        <p role="status" className={panel.loading}>
          <LoaderCircle
            className={panel.spinner}
            size={16}
            aria-hidden="true"
          />{" "}
          Checking upload availability…
        </p>
      ) : capabilityError ? (
        <div>
          <p role="alert" className={panel.error}>
            {capabilityError}
          </p>
          <ActionButton
            variant="quiet"
            onClick={() => {
              setChecking(true);
              setCapability(null);
              setCapabilityError("");
              setCheck((value) => value + 1);
            }}
          >
            Check upload availability
          </ActionButton>
        </div>
      ) : !capability?.available ? (
        <p className={panel.muted}>
          Video uploads aren’t available in this workspace yet. You can still
          choose an existing ready video for a lesson.
        </p>
      ) : (
        <>
          <input
            ref={input}
            className={styles.fileInput}
            type="file"
            accept="video/mp4,video/webm"
            aria-label="Choose a course video"
            disabled={!canChoose}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              void choose(file);
            }}
          />
          {sessionError ? (
            <p role="alert" className={panel.error}>
              {sessionError}
            </p>
          ) : null}
          {snapshot.stage === "ready" && snapshot.status ? (
            <StudioVideoPreview
              programId={programId}
              assetId={snapshot.status.asset_id}
              versionId={snapshot.status.version_id}
              label={snapshot.status.label}
              recoveryContext={recoveryContext}
            />
          ) : null}
          {snapshot.stage === "idle" || snapshot.stage === "rejected" ? (
            <p className={panel.muted}>
              MP4 or WebM, up to {videoFileSize(capability.max_source_bytes!)}.
              Upload once, then choose the video for a lesson.
            </p>
          ) : null}
          {!hidden && snapshot.filename ? (
            <div className={styles.file}>
              <FileVideo size={22} aria-hidden="true" />
              <div>
                <strong>{snapshot.filename}</strong>
                <span>{videoFileSize(snapshot.bytes)}</span>
              </div>
              {snapshot.stage === "ready" ? (
                <ShieldCheck size={20} aria-label="Ready" />
              ) : null}
            </div>
          ) : null}
          {active && snapshot.busy ? (
            <div className={styles.meter}>
              <progress
                aria-label={
                  snapshot.stage === "preparing"
                    ? "File check progress"
                    : titles[snapshot.stage]
                }
                max={1}
                value={snapshot.fraction ?? undefined}
              />
              <p className={panel.muted}>
                {snapshot.stage === "preparing"
                  ? `${Math.round((snapshot.fraction ?? 0) * 100)}% checked`
                  : snapshot.stage === "uploading"
                    ? "Keep this tab open while your file transfers."
                    : "This can take a moment. Your file stays private."}
              </p>
            </div>
          ) : null}
          {snapshot.stage === "processing" ? (
            <p role="status" className={panel.loading}>
              <LoaderCircle
                className={panel.spinner}
                size={16}
                aria-hidden="true"
              />{" "}
              Your upload is saved. We’re preparing playback; you can keep
              editing.
            </p>
          ) : null}
          {snapshot.stage === "ready" ? (
            <p role="status" className={panel.notice}>
              Ready in your video library. Choose it in a lesson and approve
              that selection before learners can watch it.
            </p>
          ) : null}
          {snapshot.stage === "failed" || snapshot.stage === "retired" ? (
            <p role="status" className={panel.error}>
              This file is not available for lessons. Check that the video plays
              on your device, then choose another file.
            </p>
          ) : null}
          {snapshot.message ? (
            <p role="alert" className={panel.error}>
              {snapshot.message}
            </p>
          ) : null}
          <div className={styles.actions}>
            {snapshot.busy && active ? (
              <ActionButton variant="quiet" onClick={() => session?.pause()}>
                <Pause size={16} aria-hidden="true" /> Pause upload
              </ActionButton>
            ) : null}
            {snapshot.pending && !snapshot.busy ? (
              <ActionButton
                disabled={disabled}
                onClick={() => void session?.resume()}
              >
                <RefreshCw size={16} aria-hidden="true" /> Resume same upload
              </ActionButton>
            ) : null}
            {!snapshot.busy &&
            snapshot.status &&
            ["processing", "error", "denied"].includes(snapshot.stage) ? (
              <ActionButton
                variant="quiet"
                disabled={disabled}
                onClick={() => void session?.check()}
              >
                Check video status
              </ActionButton>
            ) : null}
          </div>
          {snapshot.pending ? (
            <p className={styles.privacy}>
              Keep this tab open to recover this exact upload. Closing it loses
              the local file selection, not any upload already received by the
              server.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
