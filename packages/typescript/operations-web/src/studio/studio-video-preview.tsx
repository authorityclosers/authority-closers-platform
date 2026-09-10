"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ActionButton } from "@ac/ui";
import { Film, LoaderCircle, Play, RefreshCw, X } from "lucide-react";
import { AdminApiProblem } from "../admin-api";
import {
  loadStudioVideoPreview,
  type StudioVideoPreviewDescriptor,
  type StudioVideoPreviewIdentity,
} from "./studio-video-preview-api";
import styles from "./studio-video-preview.module.css";

type Props = StudioVideoPreviewIdentity & {
  label: string;
  recoveryContext: string;
};

/** A private editing preview, not a learner playback/progress session. */
export function StudioVideoPreview(props: Props) {
  return (
    <PreviewSession
      key={`${props.recoveryContext}:${props.programId}:${props.assetId}:${props.versionId}`}
      {...props}
    />
  );
}

function PreviewSession({ label, recoveryContext, ...identity }: Props) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [source, setSource] = useState<StudioVideoPreviewDescriptor | null>(
    null,
  );
  const [error, setError] = useState("");
  const [waiting, setWaiting] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const stage = useRef<HTMLElement>(null);

  function preserveMediaFocus() {
    const element = video.current;
    if (
      element &&
      (document.activeElement === element ||
        element.contains(document.activeElement))
    ) {
      stage.current?.focus();
    }
  }

  useEffect(() => {
    if (!open || !recoveryContext) return;
    const controller = new AbortController();
    let active = true;
    const timer = setTimeout(() => {
      if (active) setError("The preview took too long to respond. Try again.");
      controller.abort();
    }, 12_000);
    void loadStudioVideoPreview(identity, { signal: controller.signal })
      .then((result) => {
        if (active && !controller.signal.aborted) {
          setSource(result);
          setWaiting(true);
        }
      })
      .catch((failure: unknown) => {
        if (!active) return;
        setError(
          failure instanceof AdminApiProblem &&
            [401, 403, 404, 410].includes(failure.status)
            ? "Preview access changed. Reopen the course or sign in again."
            : failure instanceof AdminApiProblem && failure.status === 503
              ? "Video preview is not enabled in this workspace yet."
              : "The preview couldn’t load. Check your connection and try again.",
        );
      })
      .finally(() => clearTimeout(timer));
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
    // The public wrapper remounts on identity/session changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, attempt]);

  useEffect(() => {
    if (!source || !waiting) return;
    const timer = setTimeout(() => {
      preserveMediaFocus();
      setSource(null);
      setWaiting(false);
      setError("The video is taking too long to load. Try the preview again.");
    }, 20_000);
    return () => clearTimeout(timer);
  }, [source, waiting]);

  useEffect(() => {
    const element = video.current;
    return () => {
      if (!element) return;
      element.pause();
      element.removeAttribute("src");
      element.load();
    };
  }, [source]);

  function retry() {
    stage.current?.focus();
    setSource(null);
    setError("");
    setWaiting(false);
    setAttempt((value) => value + 1);
  }
  function close() {
    setOpen(false);
    setSource(null);
    setWaiting(false);
    setError("");
    trigger.current?.focus();
  }
  return (
    <div className={styles.preview}>
      <button
        ref={trigger}
        type="button"
        className={styles.trigger}
        disabled={!recoveryContext}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <Play size={16} aria-hidden="true" />{" "}
        {open ? "Hide preview" : "Preview video"}
      </button>
      {open ? (
        <section
          ref={stage}
          tabIndex={-1}
          id={id}
          className={styles.stage}
          aria-label={`Video preview: ${label}`}
        >
          <header className={styles.header}>
            <span>
              <Film size={17} aria-hidden="true" />
              <strong>{label}</strong>
            </span>
            <button
              type="button"
              className={styles.close}
              aria-label="Close video preview"
              onClick={close}
            >
              <X size={18} aria-hidden="true" />
            </button>
          </header>
          {source ? (
            <div className={styles.screen}>
              <video
                ref={video}
                src={source.preview_href}
                controls
                playsInline
                preload="metadata"
                aria-label={`Preview ${label}`}
                onLoadedMetadata={() => setWaiting(false)}
                onError={() => {
                  preserveMediaFocus();
                  setSource(null);
                  setWaiting(false);
                  setError(
                    "This video couldn’t play. Reload the preview to check access and try again.",
                  );
                }}
              />
              {waiting ? (
                <p className={styles.loading} role="status">
                  <LoaderCircle
                    size={18}
                    className={styles.spinner}
                    aria-hidden="true"
                  />{" "}
                  Loading video…
                </p>
              ) : null}
            </div>
          ) : error ? (
            <div className={styles.message}>
              <p role="alert">{error}</p>
              <ActionButton variant="secondary" onClick={retry}>
                <RefreshCw size={16} aria-hidden="true" /> Retry preview
              </ActionButton>
            </div>
          ) : (
            <p className={styles.message} role="status">
              <LoaderCircle
                size={18}
                className={styles.spinner}
                aria-hidden="true"
              />{" "}
              Checking preview access…
            </p>
          )}
          <p className={styles.note}>
            Preview only · doesn’t publish or record learner progress.
          </p>
        </section>
      ) : null}
    </div>
  );
}
