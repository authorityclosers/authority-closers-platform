"use client";

/* The preview is a local blob URL and the eventual URL is provider-owned. */
/* eslint-disable @next/next/no-img-element */

import {
  Camera,
  CheckCircle2,
  CircleAlert,
  Crop,
  LoaderCircle,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  clampAvatarCrop,
  unavailableAvatarUploadPort,
  validateAvatarFile,
  type AvatarCrop,
  type AvatarPresentation,
  type AvatarUploadPort,
  type AvatarUploadResult,
} from "../lib/avatar-upload";
import styles from "./avatar-crop-dialog.module.css";

export type AvatarCropDialogProps = {
  displayName: string;
  profileRevision?: string | number | null;
  currentAvatar?: AvatarPresentation | null;
  adapter?: AvatarUploadPort;
  onClose: () => void;
  onSuccess?: (avatar: AvatarPresentation) => void;
};

type DialogStatus =
  | { status: "idle" }
  | { status: "uploading" }
  | { status: "processing"; stage: string }
  | { status: "success" }
  | { status: "error"; message: string };

function initialsFor(displayName: string): string {
  return (
    displayName
      .split(" ")
      .map((part) => part[0])
      .filter(Boolean)
      .slice(0, 2)
      .join("")
      .toUpperCase() || "AC"
  );
}

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
  };
}

export function AvatarCropDialog({
  displayName,
  profileRevision,
  currentAvatar,
  adapter = unavailableAvatarUploadPort,
  onClose,
  onSuccess,
}: AvatarCropDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [crop, setCrop] = useState<AvatarCrop>({
    scale: 1,
    offsetX: 0,
    offsetY: 0,
  });
  const [status, setStatus] = useState<DialogStatus>({ status: "idle" });
  const dialogRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    dialogRef.current?.querySelector<HTMLElement>("button, input")?.focus();
    const dialog = dialogRef.current;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
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
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  function chooseFile(nextFile: File | null) {
    const validation = validateAvatarFile(nextFile);
    if (!nextFile || !validation.ok) {
      setFile(null);
      setFileError(
        validation.ok
          ? "Choose an image to preview your avatar."
          : validation.message,
      );
      setStatus({ status: "idle" });
      return;
    }

    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setFile(nextFile);
    setPreviewUrl(URL.createObjectURL(nextFile));
    setFileError(null);
    setCrop({ scale: 1, offsetX: 0, offsetY: 0 });
    setStatus({ status: "idle" });
  }

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    chooseFile(event.target.files?.[0] ?? null);
    event.target.value = "";
  }

  async function submitAvatar() {
    if (!file || status.status === "uploading") {
      if (!file) setFileError("Choose an image before uploading.");
      return;
    }

    setStatus({ status: "uploading" });
    let result: AvatarUploadResult;
    try {
      result = await adapter.upload({
        file,
        crop: clampAvatarCrop(crop),
        profileRevision,
      });
    } catch {
      setStatus({
        status: "error",
        message:
          "The avatar service could not finish this request. Your current avatar is unchanged.",
      });
      return;
    }

    if (result.status === "processing") {
      setStatus({ status: "processing", stage: describeStage(result.stage) });
      return;
    }
    if (result.status === "success") {
      setStatus({ status: "success" });
      onSuccess?.(result.avatar);
      return;
    }
    setStatus({ status: "error", message: resultMessage(result) });
  }

  const isBusy = status.status === "uploading";
  const currentPreview = currentAvatar?.deliveryUrl;

  return (
    <div className={styles.overlay} role="presentation" onMouseDown={onClose}>
      <div
        className={styles.dialog}
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="avatar-dialog-title"
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className={styles.header}>
          <div>
            <p className={styles.eyebrow}>Profile photo</p>
            <h2 id="avatar-dialog-title">Adjust your avatar</h2>
            <p className={styles.description}>
              Preview a square crop. Your current avatar stays in place until
              the server confirms a new revision.
            </p>
          </div>
          <button
            className={styles.closeButton}
            type="button"
            onClick={onClose}
            aria-label="Close avatar editor"
          >
            <X size={19} aria-hidden="true" />
          </button>
        </header>

        <div className={styles.body}>
          <div className={styles.previewColumn}>
            <div className={styles.previewFrame} aria-label="Avatar preview">
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
          </div>

          <div className={styles.controls}>
            <div className={styles.filePicker}>
              <label className={styles.fileButton}>
                <Camera size={17} aria-hidden="true" />
                Choose an image
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={handleFileChange}
                />
              </label>
              <p className={styles.hint} id="avatar-file-hint">
                JPEG, PNG, or WebP. Final size and security checks belong to the
                profile service.
              </p>
            </div>

            {fileError ? (
              <p className={styles.error} role="alert">
                <CircleAlert size={16} aria-hidden="true" />
                {fileError}
              </p>
            ) : null}

            <fieldset className={styles.cropControls} disabled={!previewUrl}>
              <legend>
                <Crop size={15} aria-hidden="true" /> Crop controls
              </legend>
              <label>
                <span>Zoom</span>
                <output>{crop.scale.toFixed(2)}×</output>
                <input
                  type="range"
                  min="1"
                  max="2"
                  step="0.05"
                  value={crop.scale}
                  onChange={(event) =>
                    setCrop((current) => ({
                      ...current,
                      scale: Number(event.target.value),
                    }))
                  }
                  aria-describedby="avatar-crop-hint"
                />
              </label>
              <label>
                <span>Horizontal position</span>
                <output>{crop.offsetX}%</output>
                <input
                  type="range"
                  min="-25"
                  max="25"
                  step="1"
                  value={crop.offsetX}
                  onChange={(event) =>
                    setCrop((current) => ({
                      ...current,
                      offsetX: Number(event.target.value),
                    }))
                  }
                  aria-describedby="avatar-crop-hint"
                />
              </label>
              <label>
                <span>Vertical position</span>
                <output>{crop.offsetY}%</output>
                <input
                  type="range"
                  min="-25"
                  max="25"
                  step="1"
                  value={crop.offsetY}
                  onChange={(event) =>
                    setCrop((current) => ({
                      ...current,
                      offsetY: Number(event.target.value),
                    }))
                  }
                  aria-describedby="avatar-crop-hint"
                />
              </label>
              <p className={styles.hint} id="avatar-crop-hint">
                Use the sliders with a keyboard if dragging is not comfortable.
              </p>
            </fieldset>

            {previewUrl && status.status === "idle" ? (
              <p className={styles.localOnly} role="status">
                Local preview only. Nothing has been uploaded.
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
                onClick={onClose}
                disabled={isBusy}
              >
                Cancel
              </button>
              <button
                className={styles.submitButton}
                type="button"
                onClick={() => void submitAvatar()}
                disabled={!file || isBusy || status.status === "success"}
                aria-describedby="avatar-upload-note"
              >
                <Upload size={16} aria-hidden="true" />
                {isBusy ? "Checking availability…" : "Upload avatar"}
              </button>
            </div>
            <p className={styles.uploadNote} id="avatar-upload-note">
              The default adapter is preview-only. A connected profile service
              must validate, process, and confirm the new revision.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
