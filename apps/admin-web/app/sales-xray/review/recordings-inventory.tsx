"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { CircleAlert, FileAudio, LoaderCircle, Search } from "lucide-react";

import { SectionHeading } from "../../components/ops-primitives";
import { loadAdminRecordings, type AdminRecording } from "./recordings-api";
import styles from "./review-workspace.module.css";

type InventoryState =
  | { status: "loading"; items: readonly AdminRecording[] }
  | { status: "ready"; items: readonly AdminRecording[] }
  | {
      status: "error";
      items: readonly AdminRecording[];
      message: string;
      retryable: boolean;
    };

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatBytes(value: number): string {
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(recording: AdminRecording): string {
  if (recording.duration.milliseconds !== null) {
    const seconds = Math.round(recording.duration.milliseconds / 1000);
    return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  }
  if (recording.duration.seconds !== null) {
    return `Up to ${Math.ceil(recording.duration.seconds / 60)}m`;
  }
  return "Not measured";
}

function formatCost(value: number | null): string {
  return value === null ? "—" : `₹${(value / 100).toFixed(2)}`;
}

function statusLabel(value: AdminRecording["status"]): string {
  return value.replaceAll("_", " ");
}

function InventoryRow({
  recording,
  onSelectRun,
}: {
  recording: AdminRecording;
  onSelectRun: (runId: string) => void;
}) {
  const canUseForReview =
    recording.report.available &&
    recording.report.review_eligible &&
    recording.report.run_id;
  return (
    <article className={styles.assignmentCard}>
      <div className={styles.assignmentCardHeader}>
        <div>
          <span className={styles.eyebrow}>
            {recording.owner.kind} recording
          </span>
          <h3>{recording.owner.label}</h3>
          <p className={styles.panelIntro}>
            Uploaded {formatDate(recording.uploaded_at)} ·{" "}
            {formatBytes(recording.source.bytes)}
          </p>
        </div>
        <span
          className={`${styles.pill} ${recording.status === "completed" ? styles.pillSuccess : styles.pillPending}`}
        >
          {statusLabel(recording.status)}
        </span>
      </div>
      <dl className={styles.assignmentFacts}>
        <div>
          <dt>Duration</dt>
          <dd>{formatDuration(recording)}</dd>
        </div>
        <div>
          <dt>Latest run</dt>
          <dd>
            {recording.latest_run
              ? statusLabel(recording.latest_run.state)
              : "Not started"}
          </dd>
        </div>
        <div>
          <dt>Reserved</dt>
          <dd>{formatCost(recording.cost.reservation_paise)}</dd>
        </div>
        <div>
          <dt>Estimate</dt>
          <dd>{formatCost(recording.cost.estimate_paise)}</dd>
        </div>
        <div>
          <dt>Actual</dt>
          <dd>
            {recording.cost.actual_paise === null
              ? "Not settled"
              : formatCost(recording.cost.actual_paise)}
          </dd>
        </div>
        <div>
          <dt>Report</dt>
          <dd>
            {recording.report.available ? "Ready for review" : "Not ready"}
          </dd>
        </div>
      </dl>
      <div className={styles.assignmentActions}>
        {canUseForReview ? (
          <button
            className="button button-secondary"
            type="button"
            onClick={() => onSelectRun(recording.report.run_id as string)}
          >
            Use for review / invite
          </button>
        ) : (
          <span className={styles.panelIntro}>
            Review and invite actions unlock after a verified report is saved.
          </span>
        )}
      </div>
      <details className={styles.lineage}>
        <summary>Technical details</summary>
        <span>
          <strong>Recording</strong> <code>{recording.id}</code>
        </span>
        <span>
          <strong>Source</strong> <code>{recording.source.sha256}</code> ·{" "}
          {recording.source.content_type}
        </span>
        {recording.latest_run ? (
          <span>
            <strong>Run</strong> <code>{recording.latest_run.id}</code>
          </span>
        ) : null}
      </details>
    </article>
  );
}

export function RecordingsInventory({
  onSelectRun,
}: {
  onSelectRun: (runId: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [state, setState] = useState<InventoryState>({
    status: "loading",
    items: [],
  });
  const requestRef = useRef(0);

  const load = useCallback(
    (nextCursorValue: string | null, query: string, showLoading = true) => {
      const request = ++requestRef.current;
      const controller = new AbortController();
      if (showLoading) {
        setState((current) => ({ status: "loading", items: current.items }));
      }
      void loadAdminRecordings({
        limit: 25,
        cursor: nextCursorValue,
        search: query,
        signal: controller.signal,
      }).then(
        (payload) => {
          if (request !== requestRef.current) return;
          setCursor(nextCursorValue);
          setNextCursor(payload.next_cursor);
          setState({ status: "ready", items: payload.items });
        },
        (error: unknown) => {
          if (request !== requestRef.current || controller.signal.aborted)
            return;
          setState((current) => ({
            status: "error",
            items: current.items,
            message:
              error instanceof Error
                ? error.message
                : "The recording inventory could not be loaded.",
            retryable: true,
          }));
        },
      );
      return () => controller.abort();
    },
    [],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => load(null, "", false), 0);
    return () => {
      window.clearTimeout(timer);
      requestRef.current += 1;
    };
  }, [load]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = search.trim();
    setAppliedSearch(next);
    load(null, next);
  }

  const isLoading = state.status === "loading";
  return (
    <section className={styles.panel} aria-labelledby="recordings-title">
      <SectionHeading
        eyebrow="All authorized recordings"
        id="recordings-title"
        title="Call inventory"
        body="Search every retained learner and guest recording. Costs stay split between reservation, estimate, and settled actuals."
      />
      <form className={styles.searchRow} onSubmit={submitSearch}>
        <label className={styles.searchField} htmlFor="recording-search">
          <Search size={16} aria-hidden="true" />
          <span className="sr-only">Search recordings</span>
          <input
            id="recording-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Owner, source hash, type, or status"
            maxLength={120}
          />
        </label>
        <button
          className="button button-secondary"
          type="submit"
          disabled={isLoading}
        >
          Search
        </button>
      </form>
      {state.status === "error" ? (
        <div className={styles.inlineError} role="alert">
          <CircleAlert size={16} aria-hidden="true" />
          <span>{state.message}</span>
          <button
            className="button button-secondary"
            type="button"
            onClick={() => load(cursor, appliedSearch)}
          >
            Retry
          </button>
        </div>
      ) : null}
      {isLoading && state.items.length === 0 ? (
        <div className={styles.queueState} role="status">
          <LoaderCircle size={26} className="spin" aria-hidden="true" />
          <strong>Loading call inventory</strong>
          <p>Checking the latest retained recordings and run receipts.</p>
        </div>
      ) : null}
      {!isLoading && state.items.length === 0 ? (
        <div className={styles.emptyState} role="status">
          <FileAudio size={25} aria-hidden="true" />
          <strong>No recordings match this search</strong>
          <p>
            Uploads appear here after the server records their authorized
            admission.
          </p>
        </div>
      ) : null}
      {state.items.length > 0 ? (
        <div className={styles.queueList} aria-live="polite">
          {state.items.map((recording) => (
            <InventoryRow
              key={recording.id}
              recording={recording}
              onSelectRun={onSelectRun}
            />
          ))}
        </div>
      ) : null}
      <div className={styles.pagination}>
        <span className={styles.panelIntro}>
          {appliedSearch
            ? `Results for “${appliedSearch}”`
            : "Newest recordings first"}
        </span>
        {nextCursor ? (
          <button
            className="button button-secondary"
            type="button"
            disabled={isLoading}
            onClick={() => load(nextCursor, appliedSearch)}
          >
            Next page
          </button>
        ) : null}
      </div>
    </section>
  );
}
