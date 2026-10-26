"use client";

/**
 * Recordings an app (Pulse) sent for this person (owner, 25 Oct 2026). They wait
 * here until the person adds one: it then goes through the usual upload, with
 * the same terms, allowance and plan as a file they pick, and lands on the lead
 * the app named. Or the person discards it. Sales X-Ray keeps them 7 days.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Inbox, Trash2 } from "lucide-react";

import styles from "./app-inbox.module.css";

const API = "/v1/sales-xray/app-uploads";
const READ: RequestInit = {
  credentials: "same-origin",
  cache: "no-store",
  redirect: "error",
  headers: { accept: "application/json" },
};

export type AppUpload = {
  id: string;
  app: string;
  title: string | null;
  fileName: string;
  mediaType: string;
  bytes: number;
  callAt: string | null;
};

export function parseAppUploads(value: unknown): AppUpload[] {
  if (!value || typeof value !== "object") return [];
  const list = (value as { uploads?: unknown }).uploads;
  if (!Array.isArray(list)) return [];
  const found: AppUpload[] = [];
  for (const raw of list) {
    if (!raw || typeof raw !== "object") continue;
    const item = raw as Record<string, unknown>;
    if (
      typeof item.id !== "string" ||
      typeof item.file_name !== "string" ||
      typeof item.media_type !== "string" ||
      typeof item.bytes !== "number"
    )
      continue;
    found.push({
      id: item.id,
      app: typeof item.app === "string" ? item.app : "An app",
      title: typeof item.title === "string" ? item.title : null,
      fileName: item.file_name,
      mediaType: item.media_type,
      bytes: item.bytes,
      callAt: typeof item.call_at === "string" ? item.call_at : null,
    });
  }
  return found;
}

const EXTENSIONS: Record<string, string> = {
  "audio/mpeg": "mp3",
  "audio/mp3": "mp3",
  "audio/mp4": "m4a",
  "audio/x-m4a": "m4a",
  "audio/aac": "aac",
  "audio/wav": "wav",
  "audio/x-wav": "wav",
  "audio/ogg": "ogg",
  "audio/opus": "opus",
  "audio/webm": "webm",
  "audio/amr": "amr",
  "audio/3gpp": "3gp",
  "audio/flac": "flac",
  "video/mp4": "mp4",
  "video/webm": "webm",
  "video/quicktime": "mov",
  "video/3gpp": "3gp",
};

/** The file name the uploader accepts: it checks the extension. */
export function uploadFileName(upload: AppUpload): string {
  if (/\.[a-z0-9]{2,4}$/i.test(upload.fileName)) return upload.fileName;
  return `${upload.fileName}.${EXTENSIONS[upload.mediaType] ?? "mp3"}`;
}

const size = (bytes: number) =>
  bytes >= 1_000_000
    ? `${(bytes / 1_000_000).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1000))} KB`;

/**
 * The inbox strip for the upload card. ``onFile`` hands a recording to the
 * uploader; ``submissionId`` is the call the uploader made from the last file
 * handed over, so the app's recording is marked as added (and put on its lead).
 */
export function AppInbox({
  disabled,
  onFile,
  submissionId,
}: {
  disabled: boolean;
  onFile: (file: File) => void;
  submissionId: string | null;
}) {
  const [uploads, setUploads] = useState<AppUpload[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState("");
  const handed = useRef<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await fetch(API, { ...READ, signal });
      if (!response.ok) return;
      setUploads(parseAppUploads(await response.json()));
    } catch {
      // The inbox is an extra: the uploader works without it.
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetch(API, { ...READ, signal: controller.signal })
      .then(async (response) => {
        if (response.ok) setUploads(parseAppUploads(await response.json()));
      })
      .catch(() => {
        // The inbox is an extra: the uploader works without it.
      });
    return () => controller.abort();
  }, []);

  // The uploader made a call from the recording handed over: mark it added.
  useEffect(() => {
    const id = handed.current;
    if (!id || !submissionId) return;
    let stopped = false;
    let tries = 0;
    const mark = async () => {
      while (!stopped && tries < 24) {
        tries += 1;
        try {
          const response = await fetch(`${API}/${id}/imported`, {
            ...READ,
            method: "POST",
            headers: {
              accept: "application/json",
              "content-type": "application/json",
            },
            body: JSON.stringify({ submission_id: submissionId }),
          });
          // 409 until the upload has reached the server; then it's added.
          if (response.ok) {
            handed.current = null;
            setUploads((current) => current.filter((item) => item.id !== id));
            return;
          }
          if (response.status !== 409) return;
        } catch {
          // try again shortly
        }
        await new Promise((resolve) => setTimeout(resolve, 5000));
      }
    };
    void mark();
    return () => {
      stopped = true;
    };
  }, [submissionId]);

  async function add(upload: AppUpload) {
    setBusy(upload.id);
    setProblem("");
    try {
      const response = await fetch(`${API}/${upload.id}/file`, READ);
      if (!response.ok) {
        setProblem("That recording is no longer kept.");
        await load();
        return;
      }
      const blob = await response.blob();
      handed.current = upload.id;
      onFile(
        new File([blob], uploadFileName(upload), { type: upload.mediaType }),
      );
    } catch {
      setProblem("That recording didn't load. Try again.");
    } finally {
      setBusy(null);
    }
  }

  async function discard(upload: AppUpload) {
    setBusy(upload.id);
    try {
      await fetch(`${API}/${upload.id}/discard`, { ...READ, method: "POST" });
      setUploads((current) => current.filter((item) => item.id !== upload.id));
    } finally {
      setBusy(null);
    }
  }

  if (!uploads.length) return null;
  return (
    <section className={styles.inbox} aria-label="Recordings sent to you">
      <p className={styles.head}>
        <Inbox size={16} aria-hidden="true" />
        From {uploads[0].app}: {uploads.length} recording
        {uploads.length === 1 ? "" : "s"} for you
      </p>
      <ul className={styles.list}>
        {uploads.map((upload) => (
          <li key={upload.id} className={styles.item}>
            <span className={styles.name}>
              {upload.title ?? upload.fileName}
              <small>
                {size(upload.bytes)}
                {upload.callAt
                  ? ` · ${new Date(upload.callAt).toLocaleString("en-GB", {
                      day: "numeric",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}`
                  : ""}
              </small>
            </span>
            <button
              type="button"
              className={styles.add}
              disabled={disabled || busy !== null}
              onClick={() => void add(upload)}
            >
              {busy === upload.id ? "Loading…" : "Add"}
            </button>
            <button
              type="button"
              className={styles.discard}
              aria-label={`Discard ${upload.title ?? upload.fileName}`}
              disabled={busy !== null}
              onClick={() => void discard(upload)}
            >
              <Trash2 size={14} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
      {problem ? <p className={styles.problem}>{problem}</p> : null}
    </section>
  );
}
