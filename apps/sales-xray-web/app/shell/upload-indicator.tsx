"use client";

import { X } from "lucide-react";
import Link from "next/link";
import type { MouseEvent } from "react";

import { useUploadSession, useUploadSnapshot } from "../hooks/upload-session";
import { Glyph } from "../lightbox/glyph";
import styles from "./upload-indicator.module.css";

function fileSizeLabel(bytes: number) {
  if (bytes < 1048576) return `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

/**
 * The minimized state of an upload owned by the root layout, shown on views
 * that do not display it themselves. It reports transport facts only: bytes in
 * flight, the server-bound call, or an unconfirmed outcome.
 */
export function UploadIndicator({
  onOpenIntake,
}: {
  /** Lets the mounted studio show the live upload in place of another call. */
  onOpenIntake?: () => void;
}) {
  const store = useUploadSession();
  const snapshot = useUploadSnapshot();
  if (
    !store ||
    snapshot.phase === "idle" ||
    (snapshot.phase !== "account_changed" && snapshot.viewed)
  )
    return null;
  if (snapshot.phase === "account_changed")
    return (
      <aside
        className={styles.indicator}
        aria-label="Upload status"
        data-upload-indicator="account_changed"
      >
        <span className={styles.mark} aria-hidden="true">
          <Glyph name="retry" size={18} />
        </span>
        <div className={styles.copy} role="status" aria-live="polite">
          <strong>Upload state cleared after an account change</strong>
          <span className={styles.note}>
            Check Calls under the account that started it before uploading
            again.
          </span>
        </div>
        <div className={styles.actions}>
          <Link className={styles.action} href="/calls">
            Open Calls
          </Link>
        </div>
      </aside>
    );
  const upload = snapshot;
  const analysis = upload.phase === "saved" ? upload.analysis : undefined;
  const starting =
    analysis?.state === "checking" || analysis?.state === "starting";
  const settle = () => store.settle(upload.intentId);
  const openIntake = (event: MouseEvent<HTMLAnchorElement>) => {
    if (upload.phase === "interrupted") settle();
    if (!onOpenIntake) return;
    event.preventDefault();
    onOpenIntake();
  };
  const callHref = (id: string) => {
    const url = new URL(upload.homeHref, "https://sales-xray.invalid");
    url.searchParams.delete("new");
    url.searchParams.set("call", id);
    return `${url.pathname}${url.search}`;
  };
  return (
    <aside
      className={styles.indicator}
      aria-label="Upload status"
      data-upload-indicator={upload.phase}
      data-analysis-start={analysis?.state}
    >
      <span className={styles.mark} aria-hidden="true">
        {upload.phase === "preparing" ||
        upload.phase === "uploading" ||
        starting ? (
          <span className={styles.live} />
        ) : (
          <Glyph
            name={upload.phase === "saved" ? "saved" : "retry"}
            size={18}
          />
        )}
      </span>
      <div className={styles.copy} role="status" aria-live="polite">
        <strong>
          {upload.phase === "preparing"
            ? "Preparing private upload"
            : upload.phase === "uploading"
              ? "Uploading privately"
              : analysis?.state === "checking"
                ? "Checking recording"
                : analysis?.state === "starting"
                  ? "Starting analysis"
                  : analysis?.state === "accepted"
                    ? "Analysis started"
                    : analysis?.state === "needs_action"
                      ? "Recording saved · needs action"
                      : upload.phase === "saved"
                        ? "Upload saved"
                        : "Upload not confirmed"}
        </strong>
        <span className={styles.name} title={upload.fileName}>
          {upload.fileName}
        </span>
        <span className={styles.note}>
          {upload.phase === "preparing"
            ? `${fileSizeLabel(upload.totalBytes)} · preparing your recording`
            : upload.phase === "uploading"
              ? `${fileSizeLabel(upload.totalBytes)} · keep this tab open until it’s saved`
              : analysis?.state === "checking"
                ? "Saved. The server is checking the file before analysis starts."
                : analysis?.state === "starting"
                  ? "Saved. Starting the analysis you approved."
                  : analysis?.state === "accepted"
                    ? "Your report will appear in Calls when it’s ready."
                    : analysis?.state === "needs_action"
                      ? analysis.message
                      : upload.phase === "saved"
                        ? "The server has your recording."
                        : upload.reconciliation === "missing"
                          ? "The server did not find it. Review current consent before trying again."
                          : "Check whether it arrived before uploading again."}
        </span>
      </div>
      <div className={styles.actions}>
        {upload.phase === "saved" ? (
          <Link
            className={styles.action}
            href={callHref(upload.submissionId)}
            onClick={settle}
          >
            Open call
          </Link>
        ) : (
          <Link
            className={styles.action}
            href={upload.homeHref}
            onClick={openIntake}
          >
            {upload.phase === "preparing" || upload.phase === "uploading"
              ? "View upload"
              : "Check upload"}
          </Link>
        )}
        {upload.phase === "saved" && !starting ? (
          <button
            type="button"
            className={styles.dismiss}
            aria-label="Dismiss upload status"
            onClick={settle}
          >
            <X size={16} aria-hidden="true" />
          </button>
        ) : null}
      </div>
    </aside>
  );
}
