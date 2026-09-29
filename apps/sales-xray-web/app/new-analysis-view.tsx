"use client";

import { MoreHorizontal, Phone } from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";

import { acquisition } from "./acquisition-client";
import styles from "./new-analysis-view.module.css";

export type AnalysisItem = {
  id: string;
  callName: string;
  fileName: string;
  prospectName: string;
  companyName: string;
  date: string;
  time: string;
  duration: string;
  size: string;
  status: "Completed" | "Processing" | "Ready";
};

export type NewAnalysisViewProps = {
  onFileSelect?: (file: File) => void;
  disabled?: boolean;
};

export function NewAnalysisView({
  onFileSelect,
  disabled = false,
}: NewAnalysisViewProps) {
  const [dragging, setDragging] = useState(false);
  const [items, setItems] = useState<AnalysisItem[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (disabled) {
      return;
    }
    let controller: AbortController | null = new AbortController();
    void (async () => {
      try {
        const response = (await acquisition("/submissions", {
          signal: controller.signal,
        })) as { submissions?: Array<Record<string, unknown>> } | null;
        if (response?.submissions && response.submissions.length > 0) {
          const loaded: AnalysisItem[] = response.submissions
            .slice(0, 5)
            .map((sub, index) => {
              const label =
                typeof sub.label === "string" ? sub.label : `Call ${index + 1}`;
              const created =
                typeof sub.created_at === "string"
                  ? new Date(sub.created_at)
                  : new Date();
              const dateStr = created.toLocaleDateString("en-GB", {
                day: "numeric",
                month: "short",
                year: "numeric",
              });
              const timeStr = created.toLocaleTimeString("en-GB", {
                hour: "2-digit",
                minute: "2-digit",
              });
              const durSecs =
                typeof sub.duration_seconds === "number"
                  ? sub.duration_seconds
                  : 0;
              const durMin = Math.floor(durSecs / 60);
              const durRem = Math.floor(durSecs % 60);
              const durStr =
                durSecs > 0
                  ? `${durMin}:${durRem.toString().padStart(2, "0")}`
                  : "—";
              const sizeBytes =
                typeof sub.byte_size === "number" ? sub.byte_size : 0;
              const sizeStr =
                sizeBytes > 0
                  ? `${(sizeBytes / 1048576).toFixed(1)} MB`
                  : "—";
              return {
                id: typeof sub.id === "string" ? sub.id : `sub-${index}`,
                callName: label,
                fileName:
                  typeof sub.original_filename === "string"
                    ? sub.original_filename
                    : `${label}.mp3`,
                prospectName:
                  typeof sub.prospect_name === "string"
                    ? sub.prospect_name
                    : "Prospect",
                companyName:
                  typeof sub.company_name === "string"
                    ? sub.company_name
                    : "Workspace",
                date: dateStr,
                time: timeStr,
                duration: durStr,
                size: sizeStr,
                status: "Completed",
              };
            });
          setItems(loaded);
        }
      } catch {
        // Real submissions read failed or unauthenticated; leave items empty
      }
    })();
    return () => {
      controller?.abort();
      controller = null;
    };
  }, [disabled]);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file && onFileSelect && !disabled) {
      onFileSelect(file);
    }
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    if (!disabled && !dragging) setDragging(true);
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    if (!event.currentTarget.contains(event.relatedTarget as Node)) {
      setDragging(false);
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    const file = event.dataTransfer.files?.[0];
    if (file && onFileSelect) {
      onFileSelect(file);
    }
  }

  return (
    <div className={styles.container}>
      {/* Upload card */}
      <section className={styles.card} aria-labelledby="upload-card-heading">
        <header className={styles.cardHeader}>
          <h2 id="upload-card-heading" className={styles.cardTitle}>
            Upload a call recording
          </h2>
          <p className={styles.cardDescription}>
            Choose an audio file to get started. Your recording will be analyzed
            and a report will be generated.
          </p>
        </header>

        <div
          className={`${styles.dropZone}${dragging ? ` ${styles.dropZoneDragging}` : ""}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              fileInputRef.current?.click();
            }
          }}
          aria-label="Upload audio file dropzone"
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="audio/*,.mp3,.mpeg,.wav,.m4a,.ogg,.flac"
            style={{ display: "none" }}
            onChange={handleFileChange}
            disabled={disabled}
            aria-hidden="true"
          />

          <div className={styles.docIcon}>
            <svg
              width="44"
              height="48"
              viewBox="0 0 40 44"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M4 8C4 5.79086 5.79086 4 8 4H24L36 16V36C36 38.2091 34.2091 40 32 40H8C5.79086 40 4 38.2091 4 36V8Z"
                stroke="var(--lx-teal)"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M24 4V16H36"
                stroke="var(--lx-teal)"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M20 31V20M20 20L15 25M20 20L25 25"
                stroke="var(--lx-teal)"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>

          <p className={styles.dropPrompt}>Drag and drop an audio file here</p>

          <button
            type="button"
            className={styles.chooseButton}
            onClick={(event) => {
              event.stopPropagation();
              fileInputRef.current?.click();
            }}
            disabled={disabled}
          >
            Choose file
          </button>

          <p className={styles.formats}>
            MP3, MPEG, WAV, M4A, OGG or FLAC &nbsp;·&nbsp; Up to 32MB / 60 min
          </p>
        </div>
      </section>

      {/* Recent analyses card */}
      {items.length > 0 ? (
        <section className={styles.card} aria-labelledby="recent-card-heading">
          <header className={styles.recentHeader}>
            <h2 id="recent-card-heading" className={styles.cardTitle}>
              Recent analyses
            </h2>
            <Link href="/analysis/calls" className={styles.viewAll}>
              View all &gt;
            </Link>
          </header>

          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Call</th>
                  <th scope="col">Prospect</th>
                  <th scope="col">Date</th>
                  <th scope="col">Duration</th>
                  <th scope="col">Size</th>
                  <th scope="col">Status</th>
                  <th scope="col" aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <div className={styles.callCell}>
                        <div className={styles.callIcon} aria-hidden="true">
                          <Phone size={15} />
                        </div>
                        <div>
                          <div className={styles.primaryText}>{item.callName}</div>
                          <div className={styles.secondaryText}>{item.fileName}</div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className={styles.primaryText}>{item.prospectName}</div>
                      <div className={styles.secondaryText}>{item.companyName}</div>
                    </td>
                    <td>
                      <div className={styles.primaryText}>{item.date}</div>
                      <div className={styles.secondaryText}>{item.time}</div>
                    </td>
                    <td className={styles.metricText}>{item.duration}</td>
                    <td className={styles.metricText}>{item.size}</td>
                    <td>
                      <span className={styles.statusPill}>
                        <span className={styles.statusDot} aria-hidden="true">
                          ●
                        </span>
                        {item.status}
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className={styles.actionButton}
                        aria-label={`Options for ${item.callName}`}
                      >
                        <MoreHorizontal size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
