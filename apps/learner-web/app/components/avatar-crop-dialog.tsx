"use client";

/* The preview is a local blob URL and the eventual URL is provider-owned. */
/* eslint-disable @next/next/no-img-element */

import {
  Camera,
  CheckCircle2,
  CircleAlert,
  LoaderCircle,
  Move,
  RotateCcw,
  Upload,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import {
  clampAvatarCrop,
  unavailableAvatarUploadPort,
  validateAvatarFile,
  type AvatarCrop,
  type AvatarImageDimensions,
  type AvatarPresentation,
  type AvatarUploadPort,
  type AvatarUploadResult,
  type AvatarUploadTerminalResult,
} from "../lib/avatar-upload";
import { initialsForDisplayName } from "../lib/profile-identity";
import styles from "./avatar-crop-dialog.module.css";

export type AvatarCropDialogProps = {
  displayName: string;
  profileRevision?: string | number | null;
  currentAvatar?: AvatarPresentation | null;
  adapter?: AvatarUploadPort;
  cropShape?: "circle" | "square";
  onClose: () => void;
  onSuccess?: (avatar: AvatarPresentation) => void;
};

type DialogStatus =
  | { status: "idle" }
  | { status: "validating" }
  | { status: "uploading" }
  | { status: "processing"; operationId: string; stage: string }
  | { status: "success" }
  | { status: "error"; message: string };

/**
 * An adapter result is only allowed to commit while the request and dialog
 * are still live. This keeps custom/provider adapters fail-closed even when
 * they resolve after their caller's AbortSignal has fired.
 */
export function canCommitAvatarResult(
  signal: Pick<AbortSignal, "aborted">,
  mounted: boolean,
): boolean {
  return mounted && !signal.aborted;
}

export const initialsFor = initialsForDisplayName;

export const DEFAULT_AVATAR_CROP: AvatarCrop = {
  scale: 1,
  offsetX: 0,
  offsetY: 0,
};

function describeStage(stage: string): string {
  return stage === "validating"
    ? "Checking the image"
    : stage === "processing"
      ? "Processing the image"
      : "Avatar is ready";
}

function resultMessage(result: AvatarUploadResult): string {
  if (result.status === "not_available") {
    return "Avatar upload is not connected in this slice. Your current avatar is unchanged.";
  }
  if (result.status === "retryable_error") return result.message;
  if (result.status === "terminal_error") return result.message;
  return "Avatar upload is not available yet.";
}

function previewStyle(crop: AvatarCrop): React.CSSProperties {
  return {
    transform: `translate(${crop.offsetX}%, ${crop.offsetY}%) scale(${crop.scale})`,
    transformOrigin: "center",
  };
}

export function applyAvatarGesture(
  crop: AvatarCrop,
  deltaXPercent: number,
  deltaYPercent: number,
  scaleRatio = 1,
  sourceDimensions?: AvatarImageDimensions,
): AvatarCrop {
  return clampAvatarCrop(
    {
      scale: crop.scale * scaleRatio,
      offsetX: crop.offsetX + deltaXPercent,
      offsetY: crop.offsetY + deltaYPercent,
    },
    sourceDimensions,
  );
}

/**
 * Keyboard fallback for the direct-manipulation stage. Arrow keys move the
 * image, +/- zoom it, and Home restores the neutral framing. Returning null
 * keeps unrelated keys available to the dialog and assistive technology.
 */
export function applyAvatarKeyboard(
  crop: AvatarCrop,
  key: string,
  accelerated = false,
  sourceDimensions?: AvatarImageDimensions,
): AvatarCrop | null {
  const movement = accelerated ? 5 : 2;
  switch (key) {
    case "ArrowLeft":
      return applyAvatarGesture(crop, -movement, 0, 1, sourceDimensions);
    case "ArrowRight":
      return applyAvatarGesture(crop, movement, 0, 1, sourceDimensions);
    case "ArrowUp":
      return applyAvatarGesture(crop, 0, -movement, 1, sourceDimensions);
    case "ArrowDown":
      return applyAvatarGesture(crop, 0, movement, 1, sourceDimensions);
    case "+":
    case "=":
      return applyAvatarGesture(crop, 0, 0, 1.06, sourceDimensions);
    case "-":
    case "_":
      return applyAvatarGesture(crop, 0, 0, 0.94, sourceDimensions);
    case "Home":
    case "0":
      return { ...DEFAULT_AVATAR_CROP };
    default:
      return null;
  }
}

function isDefaultAvatarCrop(crop: AvatarCrop): boolean {
  return (
    crop.scale === DEFAULT_AVATAR_CROP.scale &&
    crop.offsetX === DEFAULT_AVATAR_CROP.offsetX &&
    crop.offsetY === DEFAULT_AVATAR_CROP.offsetY
  );
}

type PointerPoint = { x: number; y: number };
type GestureSnapshot = {
  centroid: PointerPoint;
  distance: number | null;
  crop: AvatarCrop;
};

function gestureSnapshot(
  pointers: ReadonlyMap<number, PointerPoint>,
  crop: AvatarCrop,
): GestureSnapshot | null {
  const points = Array.from(pointers.values());
  if (points.length === 0) return null;
  const first = points[0];
  const second = points[1];
  if (!second) return { centroid: first, distance: null, crop };
  return {
    centroid: {
      x: (first.x + second.x) / 2,
      y: (first.y + second.y) / 2,
    },
    distance: Math.hypot(second.x - first.x, second.y - first.y),
    crop,
  };
}

function readImageDimensions(
  source: string,
): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () =>
      resolve({ width: image.naturalWidth, height: image.naturalHeight });
    image.onerror = () => reject(new Error("image_dimensions_unreadable"));
    image.src = source;
  });
}

function subscribeOnline(listener: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener("online", listener);
  window.addEventListener("offline", listener);
  return () => {
    window.removeEventListener("online", listener);
    window.removeEventListener("offline", listener);
  };
}

function getOnlineSnapshot(): boolean {
  return typeof navigator === "undefined" ? true : navigator.onLine !== false;
}

function getServerOnlineSnapshot(): boolean {
  return true;
}

async function withBoundedSignal<T>(
  parentSignal: AbortSignal,
  timeoutMs: number,
  action: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const requestController = new AbortController();
  let timedOut = false;
  let rejectCancellation: ((reason?: unknown) => void) | undefined;
  const cancellation = new Promise<T>((_, reject) => {
    rejectCancellation = reject;
  });
  const onParentAbort = () => requestController.abort();
  const onRequestAbort = () => {
    rejectCancellation?.(
      timedOut
        ? new Error("avatar_request_timeout")
        : new DOMException("The operation was aborted.", "AbortError"),
    );
  };
  const timeout = globalThis.setTimeout(() => {
    timedOut = true;
    requestController.abort();
  }, timeoutMs);
  parentSignal.addEventListener("abort", onParentAbort, { once: true });
  requestController.signal.addEventListener("abort", onRequestAbort, {
    once: true,
  });
  try {
    if (parentSignal.aborted) {
      throw new DOMException("The operation was aborted.", "AbortError");
    }
    const result = await Promise.race([
      action(requestController.signal),
      cancellation,
    ]);
    if (parentSignal.aborted) {
      throw new DOMException("The operation was aborted.", "AbortError");
    }
    if (timedOut) throw new Error("avatar_request_timeout");
    return result;
  } finally {
    globalThis.clearTimeout(timeout);
    parentSignal.removeEventListener("abort", onParentAbort);
    requestController.signal.removeEventListener("abort", onRequestAbort);
  }
}

export function AvatarCropDialog({
  displayName,
  profileRevision,
  currentAvatar,
  adapter = unavailableAvatarUploadPort,
  cropShape = "circle",
  onClose,
  onSuccess,
}: AvatarCropDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [imageDimensions, setImageDimensions] =
    useState<AvatarImageDimensions | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [crop, setCrop] = useState<AvatarCrop>({ ...DEFAULT_AVATAR_CROP });
  const [status, setStatus] = useState<DialogStatus>({ status: "idle" });
  const [dragActive, setDragActive] = useState(false);
  const isOnline = useSyncExternalStore(
    subscribeOnline,
    getOnlineSnapshot,
    getServerOnlineSnapshot,
  );
  const dialogRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const mountedRef = useRef(true);
  const selectionRef = useRef(0);
  const statusRef = useRef<DialogStatus>(status);
  const onSuccessRef = useRef(onSuccess);
  const focusOriginRef = useRef<HTMLElement | null>(null);
  const cropRef = useRef(crop);
  const pointersRef = useRef(new Map<number, PointerPoint>());
  const gestureRef = useRef<GestureSnapshot | null>(null);
  const activeAbortRef = useRef<AbortController | null>(null);
  const onCloseRef = useRef(onClose);
  const onlineRef = useRef(isOnline);

  useEffect(() => {
    cropRef.current = crop;
  }, [crop]);

  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  useEffect(() => {
    onSuccessRef.current = onSuccess;
  }, [onSuccess]);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    onlineRef.current = isOnline;
  }, [isOnline]);

  const closeDialog = useCallback(() => {
    activeAbortRef.current?.abort();
    activeAbortRef.current = null;
    onCloseRef.current();
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    focusOriginRef.current =
      document.activeElement instanceof HTMLElement &&
      !dialog.contains(document.activeElement)
        ? document.activeElement
        : null;

    const previouslyInert = new Map<HTMLElement, string | null>();
    const previouslyHidden = new Map<HTMLElement, string | null>();
    const shell = dialog.closest<HTMLElement>(".site-frame--learner");
    let branch: HTMLElement | null = dialog.parentElement;
    while (shell && branch && branch !== shell) {
      const parent = branch.parentElement;
      if (!parent) break;
      for (const sibling of Array.from(parent.children)) {
        if (sibling === branch || !(sibling instanceof HTMLElement)) continue;
        previouslyInert.set(sibling, sibling.getAttribute("inert"));
        previouslyHidden.set(sibling, sibling.getAttribute("aria-hidden"));
        sibling.setAttribute("inert", "");
        sibling.setAttribute("aria-hidden", "true");
      }
      branch = parent;
    }

    dialog.querySelector<HTMLElement>("button, input")?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeDialog();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyInert.forEach((value, element) => {
        if (value === null) element.removeAttribute("inert");
        else element.setAttribute("inert", value);
      });
      previouslyHidden.forEach((value, element) => {
        if (value === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", value);
      });
      focusOriginRef.current?.focus();
      focusOriginRef.current = null;
    };
  }, [closeDialog]);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      selectionRef.current += 1;
      activeAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (isOnline) return;
    activeAbortRef.current?.abort();
    queueMicrotask(() => {
      if (!mountedRef.current || onlineRef.current) return;
      if (
        statusRef.current.status === "uploading" ||
        statusRef.current.status === "processing"
      ) {
        setStatus({
          status: "error",
          message:
            "You’re offline. Reconnect before uploading; your current avatar is unchanged.",
        });
      }
    });
  }, [isOnline]);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  async function chooseFile(nextFile: File | null) {
    const selection = ++selectionRef.current;
    const validation = validateAvatarFile(nextFile);
    if (!nextFile || !validation.ok) {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setFile(null);
      setImageDimensions(null);
      setPreviewUrl(null);
      setFileError(
        validation.ok
          ? "Choose an image to preview your avatar."
          : validation.message,
      );
      setStatus({ status: "idle" });
      return;
    }

    let nextPreviewUrl: string;
    try {
      nextPreviewUrl = URL.createObjectURL(nextFile);
    } catch {
      setFile(null);
      setImageDimensions(null);
      setPreviewUrl(null);
      setFileError("This image could not be previewed. Choose another image.");
      setStatus({ status: "idle" });
      return;
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setFile(nextFile);
    setImageDimensions(null);
    setPreviewUrl(nextPreviewUrl);
    setFileError(null);
    setCrop({ ...DEFAULT_AVATAR_CROP });
    setStatus({ status: "validating" });

    try {
      const dimensions = await readImageDimensions(nextPreviewUrl);
      if (!mountedRef.current || selection !== selectionRef.current) {
        URL.revokeObjectURL(nextPreviewUrl);
        return;
      }
      const dimensionValidation = validateAvatarFile(nextFile, dimensions);
      if (!dimensionValidation.ok) {
        URL.revokeObjectURL(nextPreviewUrl);
        setFile(null);
        setImageDimensions(null);
        setPreviewUrl(null);
        setFileError(dimensionValidation.message);
        setStatus({ status: "idle" });
      } else {
        setImageDimensions(dimensions);
        setStatus({ status: "idle" });
      }
    } catch {
      if (!mountedRef.current || selection !== selectionRef.current) {
        URL.revokeObjectURL(nextPreviewUrl);
        return;
      }
      URL.revokeObjectURL(nextPreviewUrl);
      setFile(null);
      setImageDimensions(null);
      setPreviewUrl(null);
      setFileError(
        "The image dimensions could not be read. Choose another image.",
      );
      setStatus({ status: "idle" });
    }
  }

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    void chooseFile(event.target.files?.[0] ?? null);
    event.target.value = "";
  }

  function resetCrop() {
    if (!previewUrl || isBusy) return;
    setCrop({ ...DEFAULT_AVATAR_CROP });
  }

  function handlePreviewKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Enter" || event.key === " ") {
      if (!previewUrl && !isBusy) {
        event.preventDefault();
        fileInputRef.current?.click();
      } else if (event.key === " ") {
        event.preventDefault();
      }
      return;
    }
    if (!previewUrl || isBusy) return;
    const nextCrop = applyAvatarKeyboard(
      cropRef.current,
      event.key,
      event.shiftKey,
      imageDimensions ?? undefined,
    );
    if (!nextCrop) return;
    event.preventDefault();
    setCrop(nextCrop);
  }

  function beginPointerGesture(event: React.PointerEvent<HTMLDivElement>) {
    if (!previewUrl || isBusy) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    pointersRef.current.set(event.pointerId, {
      x: event.clientX,
      y: event.clientY,
    });
    gestureRef.current = gestureSnapshot(pointersRef.current, cropRef.current);
  }

  function updatePointerGesture(event: React.PointerEvent<HTMLDivElement>) {
    if (!previewUrl || !pointersRef.current.has(event.pointerId)) return;
    event.preventDefault();
    pointersRef.current.set(event.pointerId, {
      x: event.clientX,
      y: event.clientY,
    });
    const start = gestureRef.current;
    const current = gestureSnapshot(pointersRef.current, cropRef.current);
    if (!start || !current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const scaleRatio =
      start.distance && current.distance
        ? current.distance / start.distance
        : 1;
    setCrop(
      applyAvatarGesture(
        start.crop,
        ((current.centroid.x - start.centroid.x) / rect.width) * 100,
        ((current.centroid.y - start.centroid.y) / rect.height) * 100,
        scaleRatio,
        imageDimensions ?? undefined,
      ),
    );
  }

  function endPointerGesture(event: React.PointerEvent<HTMLDivElement>) {
    pointersRef.current.delete(event.pointerId);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    gestureRef.current = gestureSnapshot(pointersRef.current, cropRef.current);
  }

  async function submitAvatar() {
    if (
      !file ||
      !imageDimensions ||
      !isOnline ||
      status.status === "validating" ||
      status.status === "uploading" ||
      status.status === "processing"
    ) {
      if (!file) setFileError("Choose an image before uploading.");
      else if (!imageDimensions) {
        setFileError(
          "The image dimensions could not be confirmed. Choose another image.",
        );
      } else if (!isOnline) {
        setStatus({
          status: "error",
          message:
            "You’re offline. Reconnect before uploading; your current avatar is unchanged.",
        });
      }
      return;
    }

    setStatus({ status: "uploading" });
    const controller = new AbortController();
    activeAbortRef.current = controller;
    let result: AvatarUploadResult;
    try {
      result = await adapter.upload(
        {
          file,
          crop: clampAvatarCrop(crop, imageDimensions),
          sourceDimensions: imageDimensions,
          displayName,
          currentAvatar,
          profileRevision,
        },
        controller.signal,
      );
    } catch {
      if (!mountedRef.current) return;
      if (controller.signal.aborted) {
        setStatus(
          !onlineRef.current
            ? {
                status: "error",
                message:
                  "You’re offline. Reconnect before uploading; your current avatar is unchanged.",
              }
            : { status: "idle" },
        );
        return;
      }
      setStatus({
        status: "error",
        message:
          "The avatar service could not finish this request. Your current avatar is unchanged.",
      });
      return;
    } finally {
      if (activeAbortRef.current === controller) {
        activeAbortRef.current = null;
      }
    }

    if (!canCommitAvatarResult(controller.signal, mountedRef.current)) return;

    if (result.status === "processing") {
      setStatus({
        status: "processing",
        operationId: result.operationId,
        stage: describeStage(result.stage),
      });
      return;
    }
    if (result.status === "success") {
      setStatus({ status: "success" });
      onSuccessRef.current?.(result.avatar);
      return;
    }
    setStatus({ status: "error", message: resultMessage(result) });
  }

  const processingOperationId =
    status.status === "processing" ? status.operationId : null;

  useEffect(() => {
    if (!processingOperationId) return;
    const operationId = processingOperationId;
    const controller = new AbortController();
    activeAbortRef.current = controller;
    let active = true;
    let attempts = 0;
    let delay = 750;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const deadline = Date.now() + 45_000;

    function finish(result: AvatarUploadResult | AvatarUploadTerminalResult) {
      if (
        !active ||
        !canCommitAvatarResult(controller.signal, mountedRef.current)
      )
        return;
      if (result.status === "processing") {
        setStatus({
          status: "processing",
          operationId,
          stage: describeStage(result.stage),
        });
        return;
      }
      if (result.status === "success") {
        setStatus({ status: "success" });
        onSuccessRef.current?.(result.avatar);
        return;
      }
      setStatus({ status: "error", message: resultMessage(result) });
    }

    const awaitProcessing = adapter.awaitProcessing;
    if (awaitProcessing) {
      void withBoundedSignal(controller.signal, 45_000, (signal) =>
        awaitProcessing(operationId, signal, displayName),
      )
        .then(finish)
        .catch(() => {
          if (!active || controller.signal.aborted || !mountedRef.current)
            return;
          setStatus({
            status: "error",
            message:
              "Avatar processing could not be confirmed. Your current avatar is unchanged; try again later.",
          });
        })
        .finally(() => {
          if (activeAbortRef.current === controller) {
            activeAbortRef.current = null;
          }
        });
      return () => {
        active = false;
        controller.abort();
        if (timer) clearTimeout(timer);
        if (activeAbortRef.current === controller) {
          activeAbortRef.current = null;
        }
      };
    }

    const getStatus = adapter.getStatus;
    if (!getStatus) {
      queueMicrotask(() => {
        if (
          !active ||
          !canCommitAvatarResult(controller.signal, mountedRef.current)
        )
          return;
        setStatus({
          status: "error",
          message:
            "Avatar processing status is unavailable. Your current avatar is unchanged.",
        });
      });
      return () => {
        active = false;
        controller.abort();
        if (activeAbortRef.current === controller) {
          activeAbortRef.current = null;
        }
      };
    }

    function terminalStatusError(error: unknown): boolean {
      if (!error || typeof error !== "object" || !("status" in error)) {
        return false;
      }
      const status = (error as { status?: unknown }).status;
      return (
        typeof status === "number" &&
        [400, 401, 403, 404, 409, 413, 422].includes(status)
      );
    }

    function scheduleRetry() {
      if (!active || controller.signal.aborted || !mountedRef.current) return;
      const remaining = deadline - Date.now();
      if (attempts >= 12 || remaining <= 0) {
        setStatus({
          status: "error",
          message:
            "Avatar processing could not be confirmed in time. Your current avatar is unchanged; try again later.",
        });
        return;
      }
      timer = setTimeout(() => void poll(), Math.min(delay, remaining));
      delay = Math.min(5_000, delay * 2);
    }

    const poll = async () => {
      if (!active || controller.signal.aborted || !mountedRef.current) return;
      attempts += 1;
      try {
        const result = await withBoundedSignal(
          controller.signal,
          8_000,
          (signal) => getStatus(operationId, signal, displayName),
        );
        if (
          !active ||
          !canCommitAvatarResult(controller.signal, mountedRef.current)
        )
          return;
        if (result.status === "processing") {
          setStatus({
            status: "processing",
            operationId,
            stage: describeStage(result.stage),
          });
          scheduleRetry();
          return;
        }
        if (result.status === "success") {
          setStatus({ status: "success" });
          onSuccessRef.current?.(result.avatar);
          return;
        }
        if (result.status === "retryable_error") {
          setStatus({
            status: "processing",
            operationId,
            stage: "Status check unavailable; retrying safely",
          });
          scheduleRetry();
          return;
        }
        setStatus({ status: "error", message: resultMessage(result) });
      } catch (error) {
        if (!active || controller.signal.aborted || !mountedRef.current) return;
        if (terminalStatusError(error)) {
          setStatus({
            status: "error",
            message:
              "Avatar processing could not be confirmed for this profile. Your current avatar is unchanged.",
          });
          return;
        }
        setStatus({
          status: "processing",
          operationId,
          stage: "Status check unavailable; retrying safely",
        });
        scheduleRetry();
      }
    };

    void poll();
    return () => {
      active = false;
      controller.abort();
      if (timer) clearTimeout(timer);
      if (activeAbortRef.current === controller) {
        activeAbortRef.current = null;
      }
    };
  }, [adapter, displayName, processingOperationId]);

  const isBusy =
    status.status === "validating" ||
    status.status === "uploading" ||
    status.status === "processing";
  const currentPreview = currentAvatar?.deliveryUrl;

  return (
    <div
      className={styles.overlay}
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) closeDialog();
      }}
    >
      <div
        className={styles.dialog}
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="avatar-dialog-title"
        aria-describedby="avatar-dialog-description"
        aria-busy={isBusy}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className={styles.header}>
          <div>
            <p className={styles.eyebrow}>Profile photo</p>
            <h2 id="avatar-dialog-title">Adjust your avatar</h2>
            <p className={styles.description} id="avatar-dialog-description">
              Preview a {cropShape === "square" ? "square" : "circular"} crop.
              Your current avatar stays in place until the server confirms a new
              revision.
            </p>
          </div>
          <button
            className={styles.closeButton}
            type="button"
            onClick={closeDialog}
            aria-label="Close avatar editor"
          >
            <X size={19} aria-hidden="true" />
          </button>
        </header>

        <div className={styles.body}>
          <div className={styles.previewColumn}>
            <div
              className={`${styles.previewFrame} ${cropShape === "square" ? styles.previewFrameSquare : ""}${dragActive ? ` ${styles.previewFrameActive}` : ""}`}
              role="group"
              tabIndex={0}
              aria-label={`${cropShape === "square" ? "Square" : "Circular"} avatar crop preview`}
              aria-describedby="avatar-direct-manipulation-hint avatar-keyboard-hint"
              aria-disabled={isBusy}
              onDragEnter={(event) => {
                event.preventDefault();
                if (!isBusy) setDragActive(true);
              }}
              onDragOver={(event) => {
                event.preventDefault();
                if (!isBusy) event.dataTransfer.dropEffect = "copy";
              }}
              onDragLeave={(event) => {
                if (
                  !event.currentTarget.contains(event.relatedTarget as Node)
                ) {
                  setDragActive(false);
                }
              }}
              onDrop={(event) => {
                event.preventDefault();
                setDragActive(false);
                if (!isBusy)
                  void chooseFile(event.dataTransfer.files?.[0] ?? null);
              }}
              onPointerDown={beginPointerGesture}
              onPointerMove={updatePointerGesture}
              onPointerUp={endPointerGesture}
              onPointerCancel={endPointerGesture}
              onKeyDown={handlePreviewKeyDown}
              onWheel={(event) => {
                if (!previewUrl || isBusy) return;
                event.preventDefault();
                setCrop((current) =>
                  applyAvatarGesture(
                    current,
                    0,
                    0,
                    event.deltaY < 0 ? 1.06 : 0.94,
                    imageDimensions ?? undefined,
                  ),
                );
              }}
            >
              {previewUrl ? (
                <img
                  src={previewUrl}
                  alt="Local avatar preview"
                  className={styles.previewImage}
                  style={previewStyle(crop)}
                />
              ) : currentPreview ? (
                <img
                  src={currentPreview}
                  alt={`${displayName}'s current avatar`}
                  className={styles.previewImage}
                />
              ) : (
                <span className={styles.initials} aria-hidden="true">
                  {initialsFor(displayName)}
                </span>
              )}
              <span className={styles.cropGuide} aria-hidden="true" />
            </div>
            <span className={styles.previewCaption}>
              {previewUrl ? "Local preview" : "Current avatar"}
            </span>
            <span
              className={styles.directManipulationHint}
              id="avatar-direct-manipulation-hint"
            >
              Drop a photo here. Drag to frame it; scroll or pinch to zoom.
            </span>
            <span className={styles.keyboardHint} id="avatar-keyboard-hint">
              Keyboard: focus the preview, then use arrow keys to move, +/− to
              zoom, or Home to reset.
            </span>
          </div>

          <div className={styles.controls}>
            <div className={styles.filePicker}>
              <label className={styles.fileButton}>
                <Camera size={17} aria-hidden="true" />
                {previewUrl ? "Choose a different image" : "Choose an image"}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={handleFileChange}
                  disabled={isBusy}
                  aria-invalid={fileError ? true : undefined}
                  aria-describedby={
                    fileError
                      ? "avatar-file-hint avatar-file-error"
                      : "avatar-file-hint"
                  }
                />
              </label>
              <p className={styles.hint} id="avatar-file-hint">
                JPEG, PNG, or WebP. The profile service validates type, size,
                and content before accepting it.
              </p>
            </div>

            {fileError ? (
              <p className={styles.error} id="avatar-file-error" role="alert">
                <CircleAlert size={16} aria-hidden="true" />
                {fileError}
              </p>
            ) : null}

            <div
              className={styles.cropTools}
              role="group"
              aria-label="Avatar framing tools"
            >
              <div className={styles.cropToolHeader}>
                <span className={styles.cropToolTitle}>
                  <Move size={15} aria-hidden="true" /> Frame your photo
                </span>
                <span
                  className={styles.cropReadout}
                  aria-live="polite"
                  aria-atomic="true"
                >
                  {crop.scale.toFixed(2)}× · {crop.offsetX}% / {crop.offsetY}%
                </span>
              </div>
              <button
                className={styles.resetButton}
                type="button"
                onClick={resetCrop}
                disabled={!previewUrl || isBusy || isDefaultAvatarCrop(crop)}
              >
                <RotateCcw size={15} aria-hidden="true" />
                Reset framing
              </button>
              <p className={styles.hint}>
                The crop stays local until you choose Upload avatar. Reset
                framing restores the original crop without changing the image.
              </p>
            </div>

            {previewUrl && status.status === "idle" ? (
              <p className={styles.localOnly} role="status">
                Local preview only. Nothing has been uploaded.
              </p>
            ) : null}
            {!isOnline ? (
              <p className={styles.offline} role="status" aria-live="polite">
                <CircleAlert size={16} aria-hidden="true" /> You’re offline.
                Your preview is retained; reconnect before uploading. Your
                current avatar is unchanged.
              </p>
            ) : null}
            {status.status === "processing" ? (
              <p className={styles.processing} role="status" aria-live="polite">
                <LoaderCircle size={16} aria-hidden="true" />
                {status.stage}. Your current avatar is unchanged until this
                finishes.
              </p>
            ) : null}
            {status.status === "success" ? (
              <p className={styles.success} role="status" aria-live="polite">
                <CheckCircle2 size={16} aria-hidden="true" /> Avatar updated.
              </p>
            ) : null}
            {status.status === "error" ? (
              <p className={styles.error} role="alert">
                <CircleAlert size={16} aria-hidden="true" /> {status.message}
              </p>
            ) : null}
            <div className={styles.actions}>
              <button
                className={styles.cancelButton}
                type="button"
                onClick={closeDialog}
              >
                Cancel
              </button>
              <button
                className={styles.submitButton}
                type="button"
                onClick={() => void submitAvatar()}
                disabled={
                  !file ||
                  !imageDimensions ||
                  !isOnline ||
                  isBusy ||
                  status.status === "success"
                }
                aria-describedby="avatar-upload-note"
              >
                <Upload size={16} aria-hidden="true" />
                {status.status === "validating"
                  ? "Checking image…"
                  : status.status === "uploading"
                    ? "Checking availability…"
                    : status.status === "processing"
                      ? "Waiting for processing…"
                      : "Upload avatar"}
              </button>
            </div>
            <p className={styles.uploadNote} id="avatar-upload-note">
              Uploads stay fail-closed until an approved profile service can
              validate, process, and confirm the new revision.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
