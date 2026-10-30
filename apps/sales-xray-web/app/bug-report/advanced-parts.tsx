"use client";

/**
 * The advanced reporter's panel sections (owner, 31 Oct 2026): the steps to
 * reproduce (filled from the app's trail, editable), the files that go with
 * the report (drop, paste or choose; pictures, short screen recordings, logs)
 * and "Captured for you", folded, showing exactly what goes with it.
 */

import { ChevronRight, FileText, Paperclip, Plus, X } from "lucide-react";
import { useRef, useState } from "react";

import type { Captured } from "./advanced-telemetry";
import styles from "./advanced-reporter.module.css";

// ---------- Files ----------

export type Attachment = Readonly<{
  id: number;
  file: File;
  kind: "image" | "video" | "file";
  url: string;
}>;

export const FILE_LIMITS = {
  count: 6,
  imageBytes: 4 * 1024 * 1024,
  videoBytes: 20 * 1024 * 1024,
  videoSeconds: 90,
  fileBytes: 2 * 1024 * 1024,
} as const;

export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
export const VIDEO_TYPES = ["video/webm", "video/mp4"];
export const FILE_TYPES = [
  "text/plain",
  "text/csv",
  "application/json",
  "application/pdf",
];
const ACCEPT = [
  ...IMAGE_TYPES,
  ...VIDEO_TYPES,
  ...FILE_TYPES,
  ".log",
  ".txt",
].join(",");

export function kindOf(file: File): Attachment["kind"] | null {
  const type = file.type.split(";")[0] ?? "";
  if (IMAGE_TYPES.includes(type)) return "image";
  if (VIDEO_TYPES.includes(type)) return "video";
  if (FILE_TYPES.includes(type) || /\.(log|txt)$/i.test(file.name))
    return "file";
  return null;
}

function seconds(file: File): Promise<number> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.preload = "metadata";
    video.onloadedmetadata = () => {
      URL.revokeObjectURL(url);
      resolve(Number.isFinite(video.duration) ? video.duration : 0);
    };
    video.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(0);
    };
    video.src = url;
  });
}

/** Why a file cannot go, in words, or null when it can. */
export async function fileProblem(
  file: File,
  count: number,
): Promise<string | null> {
  if (count >= FILE_LIMITS.count)
    return `Up to ${FILE_LIMITS.count} files go with a report.`;
  const kind = kindOf(file);
  if (!kind)
    return "Add pictures, screen recordings (WebM or MP4), or text, PDF or log files.";
  if (kind === "image" && file.size > FILE_LIMITS.imageBytes)
    return "Choose a picture under 4 MB.";
  if (kind === "file" && file.size > FILE_LIMITS.fileBytes)
    return "Choose a file under 2 MB.";
  if (kind === "video") {
    if (file.size > FILE_LIMITS.videoBytes)
      return "Choose a recording under 20 MB.";
    if ((await seconds(file)) > FILE_LIMITS.videoSeconds) {
      return "Keep a recording under a minute and a half.";
    }
  }
  return null;
}

const size = (bytes: number) =>
  bytes >= 1048576
    ? `${(bytes / 1048576).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;

export function FilesSection({
  files,
  onAdd,
  onRemove,
}: {
  files: readonly Attachment[];
  onAdd: (files: File[]) => void;
  onRemove: (id: number) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <section className={styles.section} aria-label="Files">
      <div className={styles.sectionHead}>
        <h3 className={styles.sectionTitle}>Files</h3>
        {files.length ? (
          <span className={styles.count}>{files.length}</span>
        ) : null}
      </div>
      {files.length ? (
        <ul className={styles.files}>
          {files.map((item) => (
            <li key={item.id} className={styles.fileTile}>
              {item.kind === "image" ? (
                // eslint-disable-next-line @next/next/no-img-element -- a local blob preview
                <img className={styles.fileThumb} src={item.url} alt="" />
              ) : item.kind === "video" ? (
                <video
                  className={styles.fileThumb}
                  src={item.url}
                  muted
                  preload="metadata"
                />
              ) : (
                <span className={styles.fileThumb} aria-hidden="true">
                  <FileText size={20} />
                </span>
              )}
              <span className={styles.fileName} title={item.file.name}>
                {item.file.name || "Pasted picture"}
              </span>
              <small className={styles.fileSize}>{size(item.file.size)}</small>
              <button
                type="button"
                className={styles.fileRemove}
                aria-label={`Remove ${item.file.name || "the pasted picture"}`}
                onClick={() => onRemove(item.id)}
              >
                <X size={14} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <button
        type="button"
        className={styles.drop}
        data-over={over || undefined}
        onClick={() => input.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOver(false);
          onAdd(Array.from(event.dataTransfer.files));
        }}
      >
        <Paperclip size={16} aria-hidden="true" />
        <span>
          <strong>Add files</strong>
          <small>
            Drop them here or paste a picture. Pictures, short screen
            recordings, logs.
          </small>
        </span>
      </button>
      <input
        ref={input}
        className={styles.file}
        type="file"
        multiple
        accept={ACCEPT}
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          onAdd(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
    </section>
  );
}

// ---------- Steps to reproduce ----------

export function StepsSection({
  steps,
  onChange,
}: {
  steps: readonly string[];
  onChange: (steps: string[]) => void;
}) {
  const list = useRef<HTMLOListElement>(null);
  const set = (index: number, value: string) =>
    onChange(steps.map((step, at) => (at === index ? value : step)));
  return (
    <section className={styles.section} aria-label="Steps to reproduce">
      <div className={styles.sectionHead}>
        <h3 className={styles.sectionTitle}>Steps to reproduce</h3>
      </div>
      {steps.length ? (
        <ol ref={list} className={styles.steps}>
          {steps.map((step, index) => (
            <li key={index} className={styles.step}>
              <span className={styles.stepNumber} aria-hidden="true">
                {index + 1}
              </span>
              <input
                className={styles.stepInput}
                aria-label={`Step ${index + 1}`}
                value={step}
                maxLength={200}
                placeholder="What did you do?"
                onChange={(event) => set(index, event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !(event.ctrlKey || event.metaKey)
                  ) {
                    // Enter adds the next step; Ctrl Enter still sends.
                    event.preventDefault();
                    event.stopPropagation();
                    const next = [...steps];
                    next.splice(index + 1, 0, "");
                    onChange(next);
                    window.setTimeout(() => {
                      list.current
                        ?.querySelectorAll("input")
                        [index + 1]?.focus();
                    }, 0);
                  }
                }}
              />
              <button
                type="button"
                className={styles.stepRemove}
                aria-label={`Remove step ${index + 1}`}
                onClick={() => onChange(steps.filter((_, at) => at !== index))}
              >
                <X size={14} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ol>
      ) : (
        <p className={styles.fine}>Say what you did, one step at a time.</p>
      )}
      <button
        type="button"
        className={styles.chip}
        onClick={() => {
          onChange([...steps, ""]);
          window.setTimeout(() => {
            const inputs = list.current?.querySelectorAll("input");
            inputs?.[inputs.length - 1]?.focus();
          }, 0);
        }}
      >
        <Plus size={15} aria-hidden="true" />
        Add a step
      </button>
    </section>
  );
}

// ---------- Captured for you ----------

const time = (iso: string) => {
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? ""
    : at.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
};

function Row({ label, value }: { label: string; value: string | undefined }) {
  if (!value) return null;
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

export function CapturedSection({ captured }: { captured: Captured | null }) {
  if (!captured) {
    return (
      <section className={styles.section} aria-label="Captured for you">
        <p className={styles.fine}>Gathering what the team needs…</p>
      </section>
    );
  }
  const { context, speed, errors, calls, trail } = captured;
  const device = context.device;
  const summary = [
    `${trail.length} app steps`,
    errors.length
      ? `${errors.length} problem${errors.length === 1 ? "" : "s"}`
      : "no problems",
    calls.length
      ? `${calls.length} slow or failed call${calls.length === 1 ? "" : "s"}`
      : "",
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <details className={styles.captured}>
      <summary>
        <ChevronRight
          size={16}
          aria-hidden="true"
          className={styles.capturedChevron}
        />
        <span>
          <strong>Captured for you</strong>
          <small>{summary}</small>
        </span>
      </summary>
      <div className={styles.capturedBody}>
        <dl className={styles.facts}>
          <Row label="Screen" value={captured.route} />
          <Row
            label="App"
            value={[
              context.app.channel === "android" ? "Android app" : "Web",
              context.app.release ? `release ${context.app.release}` : "",
              context.app.native_version
                ? `app ${context.app.native_version}`
                : "",
            ]
              .filter(Boolean)
              .join(" · ")}
          />
          <Row
            label="Device"
            value={[device.model, device.os, device.browser]
              .filter(Boolean)
              .join(" · ")}
          />
          <Row
            label="Screen size"
            value={`${device.viewport}${device.pixel_ratio ? ` at ${device.pixel_ratio}x` : ""}${device.theme ? ` · ${device.theme}` : ""}`}
          />
          <Row
            label="Network"
            value={[
              device.online === false ? "offline" : "online",
              device.connection,
            ]
              .filter(Boolean)
              .join(" · ")}
          />
          <Row label="Workspace and role" value="Added by the server" />
          <Row
            label="Speed"
            value={[
              speed.first_byte_ms !== undefined
                ? `first byte ${speed.first_byte_ms} ms`
                : "",
              speed.ready_ms !== undefined ? `ready ${speed.ready_ms} ms` : "",
              speed.largest_paint_ms !== undefined
                ? `largest paint ${speed.largest_paint_ms} ms`
                : "",
              speed.layout_shift !== undefined
                ? `layout shift ${speed.layout_shift}`
                : "",
              speed.memory_mb !== undefined
                ? `${speed.memory_mb} MB memory`
                : "",
              `page open ${Math.round(speed.page_age_s / 60)} min`,
            ]
              .filter(Boolean)
              .join(" · ")}
          />
        </dl>
        {errors.length ? (
          <div className={styles.factList}>
            <h4>Problems</h4>
            <ul>
              {errors.map((error, index) => (
                <li key={index}>
                  <span>{time(error.at)}</span>
                  <code>
                    {[
                      error.kind,
                      error.status ? String(error.status) : "",
                      error.method ?? "",
                      error.path ?? "",
                      error.message ?? "",
                      error.reference ? `ref ${error.reference}` : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                  </code>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {calls.length ? (
          <div className={styles.factList}>
            <h4>Slow or failed calls</h4>
            <ul>
              {calls.map((call, index) => (
                <li key={index}>
                  <span>{call.failed ? "failed" : `${call.ms} ms`}</span>
                  <code>
                    {[
                      call.method,
                      call.status,
                      call.path,
                      call.reference ? `ref ${call.reference}` : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                  </code>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {trail.length ? (
          <div className={styles.factList}>
            <h4>Last app steps</h4>
            <ul>
              {trail.slice(-50).map((step, index) => (
                <li key={index}>
                  <span>{time(step.at)}</span>
                  <code>
                    {[
                      step.event.replace(/^sx\./, ""),
                      ...Object.entries(step.detail ?? {}).map(
                        ([key, value]) => `${key}=${value}`,
                      ),
                    ].join(" ")}
                  </code>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className={styles.fine}>
          Never your calls, your messages or what you typed. Ids are taken out
          of addresses; the server checks it all again.
        </p>
      </div>
    </details>
  );
}
