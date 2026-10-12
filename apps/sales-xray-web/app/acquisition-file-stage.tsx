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

import { AnalysisWave, CALL_WAVE_TRANSITION } from "./analysis-wave";
import { useFileWave } from "./analysis-wave-file";
import { formatClock } from "./lightbox/time";
import styles from "./acquisition-file-stage.module.css";

const PAGE_SIZE = 2;
const SUPPORTED_AUDIO =
  /\.(mp3|mpeg|wav|m4a|m4b|mp4|mov|ogg|flac|amr|awb|aac|3gp|3ga|webm|opus|mkv|mka|aiff|aif|aifc)$/i;

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
  // The chosen call's own wave, measured here before anything is sent.
  const wave = useFileWave(activeFile);
  const hasFiles = files.length > 0;
  const limits = [
    "Audio or video recordings",
    maxBytes !== undefined && maxBytes > 0
      ? `up to ${Math.floor(maxBytes / 1_000_000)} MB`
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
              ? "Drop your recordings here"
              : hasFiles
                ? "Add another recording"
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
          accept="audio/*,video/*,.mp3,.mpeg,.wav,.m4a,.m4b,.mp4,.mov,.ogg,.flac,.amr,.awb,.aac,.3gp,.3ga,.webm,.opus,.mkv,.mka,.aiff,.aif,.aifc"
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
              Audio or video recordings
            </span>
            {maxBytes !== undefined && maxBytes > 0 ? (
              <span>
                <HardDrive size={16} aria-hidden="true" />
                Up to {Math.floor(maxBytes / 1_000_000)} MB
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
              const length =
                selected && wave
                  ? formatClock(wave.duration_ms).replace(/^0(?=\d:)/, "")
                  : null;
              const overLength =
                selected &&
                wave !== null &&
                maxMinutes !== undefined &&
                maxMinutes > 0 &&
                wave.duration_ms > maxMinutes * 60_000;
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
                      {length ? ` · ${length}` : ""}
                      {oversized
                        ? " · Over size limit"
                        : unsupported
                          ? " · Unsupported format"
                          : overLength
                            ? ` · Longer than ${maxMinutes} min`
                            : " · Recording"}
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
                  {selected && selectable ? (
                    // Room kept from the start: the quiet motif reshapes
                    // into this call's wave once it is measured.
                    <span className={styles.fileWave}>
                      <AnalysisWave
                        envelope={wave}
                        played={0}
                        state={wave ? "still" : "idle"}
                        compact
                        transitionName={CALL_WAVE_TRANSITION}
                      />
                    </span>
                  ) : null}
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
