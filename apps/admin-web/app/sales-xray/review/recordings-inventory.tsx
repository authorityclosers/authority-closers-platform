"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { CircleAlert, FileAudio, Search } from "lucide-react";

import { Badge, Button, Empty, Panel, Skeleton, kitStyles } from "../../ui/kit";
import { loadAdminRecordings, type AdminRecording } from "./recordings-api";
import styles from "./reviewers.module.css";
import { istStamp } from "../../lib/time";

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
  return istStamp(value, value);
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

function formatUsage(usage: Record<string, number> | null): string {
  if (!usage) return "No usage receipt";
  const total = usage.total_tokens ?? usage.totalTokenCount;
  if (total !== undefined) return `${total.toLocaleString()} tokens`;
  const input = usage.prompt_tokens ?? usage.promptTokenCount;
  const output = usage.completion_tokens ?? usage.candidatesTokenCount;
  if (input !== undefined || output !== undefined) {
    return `${(input ?? 0).toLocaleString()} in · ${(output ?? 0).toLocaleString()} out`;
  }
  return "Counters recorded";
}

function formatUsageEstimate(
  state: AdminRecording["cost"]["usage_estimate_state"],
  value: number | null,
  fxRate: number | null,
  sourceDate: string | null,
): string {
  if (value !== null) {
    const qualifier =
      fxRate !== null && sourceDate !== null
        ? ` · planning @ ₹${fxRate}/USD · source ${sourceDate}`
        : "";
    return `${state === "partial" ? "Partial · " : ""}${formatCost(value)}${qualifier}`;
  }
  if (state === "rate_unavailable") return "Unavailable · no approved rate";
  if (state === "usage_unavailable") return "Unavailable · no usage receipt";
  return "—";
}

function statusLabel(value: AdminRecording["status"]): string {
  return value.replaceAll("_", " ");
}

function recordingStatus(recording: AdminRecording): string {
  if (recording.status === "completed" && !recording.report.available) {
    return "Report pending";
  }
  return statusLabel(recording.status);
}

function latestRunStatus(recording: AdminRecording): string {
  const run = recording.latest_run;
  if (!run) return "Not started";
  if (run.state === "completed" && !recording.report.available) {
    return run.provider_stages.length
      ? "Processing step complete"
      : "Audio checks complete";
  }
  return statusLabel(run.state);
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
  const canOpenReport = recording.report.available && recording.report.run_id;
  const ready = recording.status === "completed" && recording.report.available;
  return (
    <li className={styles.recording}>
      <span className={styles.recordingHead}>
        <span>
          <strong>{recording.owner.label}</strong>
          <small>
            {recording.owner.kind} recording · uploaded{" "}
            {formatDate(recording.uploaded_at)} ·{" "}
            {formatBytes(recording.source.bytes)}
          </small>
        </span>
        <Badge tone={ready ? "good" : "warn"}>
          {recordingStatus(recording)}
        </Badge>
      </span>
      <dl className={styles.facts}>
        <div>
          <dt>Duration</dt>
          <dd>{formatDuration(recording)}</dd>
        </div>
        <div>
          <dt>Latest run</dt>
          <dd>{latestRunStatus(recording)}</dd>
        </div>
        <div>
          <dt>Report</dt>
          <dd>
            {recording.report.recovery
              ? "Recovered draft · review blocked"
              : recording.report.review_eligible
                ? "Ready for review"
                : "Not ready"}
          </dd>
        </div>
        <div>
          <dt>Cost basis</dt>
          <dd>
            {recording.cost.scope === "current_plan"
              ? "Current plan"
              : "Recording total"}
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
        <div data-wide="">
          <dt>Usage estimate</dt>
          <dd>
            {formatUsageEstimate(
              recording.cost.usage_estimate_state,
              recording.cost.usage_estimate_paise,
              recording.cost.usage_estimate_fx_usd_to_inr,
              recording.cost.usage_estimate_source_date,
            )}
          </dd>
        </div>
        <div>
          <dt>Actual</dt>
          <dd>
            {recording.cost.actual_paise === null
              ? "Not settled"
              : formatCost(recording.cost.actual_paise)}
          </dd>
        </div>
      </dl>
      {recording.latest_run?.provider_stages.length ? (
        <div className={styles.stages}>
          <strong>Provider usage observed</strong>
          {recording.latest_run.provider_stages.map((stage) => (
            <span key={stage.run_id}>
              {stage.stage} · {stage.provider ?? "Provider unavailable"}
              {stage.model ? ` / ${stage.model}` : ""} ·{" "}
              {formatUsage(stage.usage)}
              {stage.cost_state === "reconciliation_required"
                ? " · charge pending reconciliation"
                : ""}
              {stage.usage_estimate_paise !== null
                ? ` · estimate ${formatCost(stage.usage_estimate_paise)} @ ₹${stage.pricing_snapshot?.usd_to_inr ?? "?"}/USD · source ${stage.pricing_snapshot?.source_date ?? "unknown"}`
                : stage.usage_estimate_basis === "provider_model_unverified"
                  ? " · estimate unavailable: returned model needs review"
                  : stage.usage_estimate_state === "rate_unavailable"
                    ? " · estimate unavailable: no approved rate"
                    : ""}
            </span>
          ))}
        </div>
      ) : null}
      <span className={styles.actions}>
        {canOpenReport ? (
          <>
            <Link
              className={kitStyles.button}
              data-variant="secondary"
              href={`/sales-xray/review/report/${encodeURIComponent(recording.report.run_id as string)}`}
            >
              Open report
            </Link>
            {canUseForReview ? (
              <Button
                variant="primary"
                onClick={() => onSelectRun(recording.report.run_id as string)}
              >
                Use for review / invite
              </Button>
            ) : (
              <small className={kitStyles.muted}>
                Recovered report is available for inspection; canonical review
                remains blocked.
              </small>
            )}
          </>
        ) : (
          <small className={kitStyles.muted}>
            Review and invite actions unlock after a verified report is saved.
          </small>
        )}
      </span>
      <details className={styles.tech}>
        <summary>Technical details</summary>
        <span>
          Recording <code>{recording.id}</code>
        </span>
        <span>
          Source <code>{recording.source.sha256}</code> ·{" "}
          {recording.source.content_type}
        </span>
        {recording.latest_run ? (
          <span>
            Run <code>{recording.latest_run.id}</code>
          </span>
        ) : null}
      </details>
    </li>
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
    <Panel
      title="Saved analyses"
      sub="Every retained learner and guest recording"
      foot={
        <span className={styles.foot}>
          <span>
            {appliedSearch
              ? `Results for “${appliedSearch}”`
              : "Newest recordings first"}
            . Reserved, estimated and settled costs stay separate.
          </span>
          {nextCursor ? (
            <Button
              disabled={isLoading}
              onClick={() => load(nextCursor, appliedSearch)}
            >
              Next page
            </Button>
          ) : null}
        </span>
      }
    >
      <form className={styles.search} onSubmit={submitSearch} role="search">
        <label className={kitStyles.srOnly} htmlFor="recording-search">
          Search recordings
        </label>
        <input
          id="recording-search"
          type="search"
          className={kitStyles.inlineInput}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Owner, source hash, type, or status"
          maxLength={120}
        />
        <Button type="submit" disabled={isLoading}>
          <Search size={14} aria-hidden="true" />
          Search
        </Button>
      </form>
      {state.status === "error" ? (
        <div className={styles.body}>
          <p className={styles.note} role="alert">
            <CircleAlert size={14} aria-hidden="true" />
            <span>{state.message}</span>
            <Button onClick={() => load(cursor, appliedSearch)}>Retry</Button>
          </p>
        </div>
      ) : null}
      {isLoading && state.items.length === 0 ? (
        <div className={styles.skeleton} role="status">
          <span className={kitStyles.srOnly}>Loading call inventory</span>
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} height={64} />
          ))}
        </div>
      ) : null}
      {state.status === "ready" && state.items.length === 0 ? (
        <Empty
          icon={FileAudio}
          title="No recordings match this search"
          text="Uploads appear here once the server records them."
        />
      ) : null}
      {state.items.length > 0 ? (
        <ul className={styles.recordings} aria-live="polite">
          {state.items.map((recording) => (
            <InventoryRow
              key={recording.id}
              recording={recording}
              onSelectRun={onSelectRun}
            />
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}
