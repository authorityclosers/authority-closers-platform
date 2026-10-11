"use client";

import {
  AudioLines,
  Check,
  Clock3,
  FileAudio,
  HardDrive,
  Plus,
  X,
} from "lucide-react";
import { useRef, useState, type ChangeEvent, type DragEvent } from "react";

import { AnalysisWave } from "./analysis-wave";
import styles from "./acquisition-file-stage.module.css";

const PAGE_SIZE = 2;
const SUPPORTED_AUDIO =
  /\.(mp3|mpeg|wav|m4a|ogg|flac|amr|awb|aac|3ga|webm|opus)$/i;

export type AcquisitionFileStageProps = Readonly<{
  files: readonly File[];
  selectedFile: File | null;
  onSelect: (file: File) => void;
  onRemove: (file: File) => void;
  onClear: () => void;
  onAddFiles: (files: FileList | File[]) => void;
  maxBytes?: number;
  maxMinutes?: number;
  disabled: boolean;
}>;

function fileSize(bytes: number): string {
  if (bytes < 1048576) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

export function AcquisitionFileStage({
  files,
  selectedFile,
  onSelect,
  onRemove,
  onClear,
  onAddFiles,
  maxBytes,
  maxMinutes,
  disabled,
}: AcquisitionFileStageProps) {
  const input = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [page, setPage] = useState(0);
  const pageCount = Math.ceil(files.length / PAGE_SIZE);
  const currentPage = Math.min(page, Math.max(0, pageCount - 1));
  const visibleFiles = files.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE,
  );
  const activeFile = files.find((file) => file === selectedFile) ?? null;
  const hasFiles = files.length > 0;
  const limits = [
    "MP3, WAV, M4A and common phone audio formats",
    maxBytes !== undefined && maxBytes > 0
      ? `up to ${Math.floor(maxBytes / 1048576)} MB`
      : null,
    maxMinutes !== undefined && maxMinutes > 0
      ? `${maxMinutes} min per call`
      : null,
  ].filter(Boolean);

  function addFiles(value: FileList | File[] | null) {
    if (disabled || !value || value.length === 0) return;
    onAddFiles(Array.from(value));
  }

  function chooseFromInput(event: ChangeEvent<HTMLInputElement>) {
    addFiles(event.target.files);
    event.target.value = "";
  }

  function drop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);
    addFiles(event.dataTransfer.files);
  }

  return (
    <div className={styles.stage} data-has-files={hasFiles}>
      <div
        className={styles.dropArea}
        data-drag-active={dragActive}
        role="group"
        aria-label="Add sales call audio files"
        onDragEnter={(event) => {
          event.preventDefault();
          if (!disabled) setDragActive(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) event.dataTransfer.dropEffect = "copy";
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node))
            setDragActive(false);
        }}
        onDrop={drop}
      >
        {hasFiles ? (
          <span className={styles.cloud} aria-hidden="true">
            <Plus size={21} />
          </span>
        ) : (
          // The call's wave from the first frame (owner's motif): quiet until
          // a file is dragged over, then it listens; analysis carries it on.
          <span className={styles.idleWave} aria-hidden="true">
            <AnalysisWave
              envelope={null}
              played={0}
              state={dragActive ? "arriving" : "idle"}
            />
          </span>
        )}
        <div className={styles.dropCopy}>
          <strong>
            {dragActive
              ? "Drop your audio files here"
              : hasFiles
                ? "Add another audio file"
                : "Drop your call recording here"}
          </strong>
          {hasFiles ? null : (
            <span
              className={styles.limits}
              aria-label="Supported audio file limits"
            >
              {limits.join(" · ")}
            </span>
          )}
          <button
            className={styles.browse}
            type="button"
            disabled={disabled}
            onClick={() => input.current?.click()}
          >
            {hasFiles ? "or click to browse" : "Choose a file"}
          </button>
        </div>
        <input
          ref={input}
          className={styles.fileInput}
          type="file"
          accept=".mp3,.mpeg,.wav,.m4a,.ogg,.flac,.amr,.awb,.aac,.3ga,.webm,.opus"
          multiple
          tabIndex={-1}
          aria-hidden="true"
          disabled={disabled}
          onChange={chooseFromInput}
        />
        {hasFiles ? (
          <div
            className={styles.facts}
            aria-label="Supported audio file limits"
          >
            <span>
              <FileAudio size={16} aria-hidden="true" />
              MP3, WAV, M4A and phone audio
            </span>
            {maxBytes !== undefined && maxBytes > 0 ? (
              <span>
                <HardDrive size={16} aria-hidden="true" />
                Up to {Math.floor(maxBytes / 1048576)} MB
              </span>
            ) : null}
            {maxMinutes !== undefined && maxMinutes > 0 ? (
              <span>
                <Clock3 size={16} aria-hidden="true" />
                {maxMinutes} min per call
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      {hasFiles ? (
        <div className={styles.selection}>
          <div className={styles.selectionHeader}>
            <div>
              <strong>
                {files.length} {files.length === 1 ? "file" : "files"} added
              </strong>
              <small>
                {activeFile
                  ? `${activeFile.name} selected for analysis`
                  : "Choose one file to analyse next"}
              </small>
            </div>
            <button
              className={styles.clear}
              type="button"
              disabled={disabled}
              onClick={onClear}
            >
              Clear all
            </button>
          </div>
          <ul className={styles.fileList} aria-label="Added audio files">
            {visibleFiles.map((file, index) => {
              const oversized = maxBytes !== undefined && file.size > maxBytes;
              const unsupported = !SUPPORTED_AUDIO.test(file.name);
              const selectable = !oversized && !unsupported;
              const selected = file === activeFile;
              return (
                <li
                  className={styles.fileCard}
                  data-selected={selected}
                  key={`${file.name}-${file.lastModified}-${currentPage * PAGE_SIZE + index}`}
                >
                  <span className={styles.fileIcon} aria-hidden="true">
                    <AudioLines size={23} />
                  </span>
                  <span className={styles.fileCopy}>
                    <strong title={file.name}>{file.name}</strong>
                    <small>
                      {fileSize(file.size)}
                      {oversized
                        ? " · Over size limit"
                        : unsupported
                          ? " · Unsupported format"
                          : " · Audio file"}
                    </small>
                  </span>
                  {selected ? (
                    <span className={styles.selectedBadge}>
                      <Check size={15} aria-hidden="true" />
                      Selected
                    </span>
                  ) : (
                    <button
                      className={styles.select}
                      type="button"
                      disabled={disabled || !selectable}
                      onClick={() => onSelect(file)}
                    >
                      Select
                    </button>
                  )}
                  <button
                    className={styles.remove}
                    type="button"
                    aria-label={`Remove ${file.name}`}
                    disabled={disabled}
                    onClick={() => onRemove(file)}
                  >
                    <X size={19} aria-hidden="true" />
                  </button>
                </li>
              );
            })}
          </ul>
          {pageCount > 1 ? (
            <div className={styles.pagination}>
              <button
                type="button"
                disabled={disabled || currentPage === 0}
                onClick={() => setPage(currentPage - 1)}
              >
                Previous
              </button>
              <span>
                Files {currentPage * PAGE_SIZE + 1}–
                {Math.min((currentPage + 1) * PAGE_SIZE, files.length)} of{" "}
                {files.length}
              </span>
              <button
                type="button"
                disabled={disabled || currentPage >= pageCount - 1}
                onClick={() => setPage(currentPage + 1)}
              >
                Next
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
