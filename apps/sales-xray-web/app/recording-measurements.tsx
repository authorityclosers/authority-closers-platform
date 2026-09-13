"use client";

import { useEffect, useState } from "react";
import { AudioLines, RotateCcw } from "lucide-react";
import { encodeConversationId } from "./report-contract";
import {
  parseSavedMeasurements,
  type MeasurementSeries,
  type SavedMeasurements,
} from "./measurement-contract";
import styles from "./recording-measurements.module.css";

const clock = (ms: number) =>
  `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;
const measured = (value: number | null, unit: string) =>
  value === null ? "Not available" : `${value.toFixed(1)} ${unit}`;

function MeasurementChart({
  series,
  duration,
}: {
  series: MeasurementSeries;
  duration: number;
}) {
  const [cursor, setCursor] = useState(0);
  const points = series.points;
  const values = points.flatMap((point) =>
    point.value === null ? [] : [point.value],
  );
  if (!values.length)
    return (
      <p className={styles.note}>
        No usable values for this measurement. Missing values are not zero.
      </p>
    );
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;
  const y = (value: number) => 100 - ((value - low) / span) * 84;
  const x = (ms: number) => 36 + (ms / duration) * 720;
  const path = points
    .map((point, index) =>
      point.value === null
        ? ""
        : `${index === 0 || points[index - 1].value === null ? "M" : "L"}${x(point.start_ms)},${y(point.value)}`,
    )
    .join(" ");
  const selected = points[Math.min(cursor, points.length - 1)];
  const label =
    series.measurement === "dbfs" ? "Recorded level" : "Pitch estimate";
  return (
    <div className={styles.chart}>
      <div className={styles.chartCaption}>
        <strong>{label}</strong>
        <output aria-live="polite">
          {clock(selected.start_ms)} · {measured(selected.value, series.unit)}
        </output>
      </div>
      <svg
        viewBox="0 0 780 136"
        role="img"
        aria-label={`${label} over the decoded recording. Displayed range ${low.toFixed(1)} to ${high.toFixed(1)} ${series.unit}. Missing values remain gaps.`}
      >
        <path d="M36 16H756 M36 58H756 M36 100H756" className={styles.grid} />
        <text x="30" y="20" textAnchor="end">
          {high.toFixed(0)}
        </text>
        <text x="30" y="104" textAnchor="end">
          {low.toFixed(0)}
        </text>
        <path d={path} className={styles.line} />
        {points.map((point, index) =>
          point.value !== null &&
          (index === 0 || points[index - 1].value === null) &&
          (index === points.length - 1 || points[index + 1].value === null) ? (
            <circle
              key={point.start_ms}
              cx={x(point.start_ms)}
              cy={y(point.value)}
              r="2.5"
              className={styles.point}
            />
          ) : null,
        )}
        <path d={`M${x(selected.start_ms)} 12V104`} className={styles.cursor} />
        {selected.value !== null && (
          <circle
            cx={x(selected.start_ms)}
            cy={y(selected.value)}
            r="4"
            className={styles.point}
          />
        )}
        <text x="36" y="128">
          0:00
        </text>
        <text x="756" y="128" textAnchor="end">
          {clock(duration)}
        </text>
      </svg>
      <input
        type="range"
        min="0"
        max={points.length - 1}
        step="1"
        value={Math.min(cursor, points.length - 1)}
        onChange={(event) => setCursor(Number(event.target.value))}
        aria-label={`Inspect ${label.toLowerCase()} over time`}
        aria-valuetext={`${clock(selected.start_ms)}, ${measured(selected.value, series.unit)}`}
      />
      <p className={styles.note}>
        Move through the saved overview. This chart uses the decoded audio
        clock; it does not control playback.
      </p>
    </div>
  );
}

function MeasurementContent({ data }: { data: SavedMeasurements }) {
  const [channelIndex, setChannelIndex] = useState(0);
  const [kind, setKind] = useState<"dbfs" | "f0_hz">("dbfs");
  const channel = data.channels[channelIndex] ?? data.channels[0];
  const series = channel.series.find((item) => item.measurement === kind)!;
  return (
    <>
      {data.channels.length > 1 && (
        <label className={styles.select}>
          Audio channel
          <select
            value={channelIndex}
            onChange={(event) => setChannelIndex(Number(event.target.value))}
          >
            {data.channels.map((item, index) => (
              <option key={item.channel_index} value={index}>
                Channel {item.channel_index + 1}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className={styles.metrics}>
        <div>
          <span>Typical recorded level</span>
          <strong>{measured(channel.level, "dBFS")}</strong>
          <small>Median of usable audio windows</small>
        </div>
        <div>
          <span>Typical pitch estimate</span>
          <strong>{measured(channel.pitch, "Hz")}</strong>
          <small>
            {channel.pitchCoverage === null
              ? "Estimate coverage is unavailable"
              : `Estimate available in ${(channel.pitchCoverage * 100).toFixed(1)}% of windows`}
          </small>
        </div>
      </div>
      <div
        className={styles.switcher}
        role="group"
        aria-label="Audio measurement"
      >
        <button
          type="button"
          aria-pressed={kind === "dbfs"}
          onClick={() => setKind("dbfs")}
        >
          Sound level
        </button>
        <button
          type="button"
          aria-pressed={kind === "f0_hz"}
          onClick={() => setKind("f0_hz")}
        >
          Pitch estimate
        </button>
      </div>
      <MeasurementChart
        key={`${channel.channel_index}:${kind}`}
        series={series}
        duration={data.durationMs}
      />
      <p className={styles.note}>
        Audio channels are not speaker identities. These measurements describe
        the recording, not emotion, confidence or sales ability. Microphones and
        recording settings affect the values.
      </p>
    </>
  );
}

export function RecordingMeasurements({
  recordingId,
  sourceSha256,
}: {
  recordingId: string;
  sourceSha256: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    data?: SavedMeasurements;
    error?: string;
  }>({});
  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    let active = true;
    async function read() {
      try {
        const id = encodeConversationId(recordingId, "recording_id");
        const response = await fetch(
          `/v1/conversation/recordings/${id}/measurements`,
          {
            credentials: "same-origin",
            cache: "no-store",
            signal: controller.signal,
          },
        );
        if (!response.ok) throw new Error("unavailable");
        const raw = await response.text();
        if (raw.length > 1_000_000) throw new Error("oversized");
        const data = parseSavedMeasurements(JSON.parse(raw), {
          recordingId,
          sourceSha256,
        });
        if (active) setState({ data });
      } catch {
        if (active)
          setState({
            error:
              "Saved sound measurements are unavailable for this call. Your sales report is still available.",
          });
      }
    }
    void read();
    return () => {
      active = false;
      controller.abort();
    };
  }, [expanded, attempt, recordingId, sourceSha256]);
  // The parent keys this view by recording/source. Also refuse stale data here.
  const data =
    state.data?.recordingId === recordingId &&
    state.data.sourceSha256 === sourceSha256
      ? state.data
      : undefined;
  return (
    <details
      className={styles.panel}
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary>
        <AudioLines size={18} aria-hidden="true" />
        <span>
          Sound of the recording
          <small>Explore saved sound level and pitch estimates</small>
        </span>
      </summary>
      <div className={styles.body}>
        {!data && !state.error && (
          <p role="status">Loading saved measurements…</p>
        )}
        {state.error && (
          <div role="status">
            <p>{state.error}</p>
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setState({});
                setAttempt((value) => value + 1);
              }}
            >
              <RotateCcw size={14} aria-hidden="true" /> Try loading again
            </button>
          </div>
        )}
        {data && (
          <MeasurementContent
            key={`${recordingId}:${sourceSha256}`}
            data={data}
          />
        )}
      </div>
    </details>
  );
}
