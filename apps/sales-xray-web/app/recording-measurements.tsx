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
import { MEASUREMENT_COPY, type MeasurementLanguage } from "./measurement-copy";

const clock = (ms: number) =>
  `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;
const measured = (value: number | null, unit: string, unavailable: string) =>
  value === null ? unavailable : `${value.toFixed(1)} ${unit}`;

function MeasurementChart({
  series,
  duration,
  language,
}: {
  series: MeasurementSeries;
  duration: number;
  language: MeasurementLanguage;
}) {
  const copy = MEASUREMENT_COPY[language];
  const [cursor, setCursor] = useState(0);
  const points = series.points;
  const values = points.flatMap((point) =>
    point.value === null ? [] : [point.value],
  );
  if (!values.length) return <p className={styles.note}>{copy.noValues}</p>;
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
  const label = series.measurement === "dbfs" ? copy.level : copy.pitch;
  return (
    <div className={styles.chart}>
      <div className={styles.chartCaption}>
        <strong>{label}</strong>
        <output aria-live="polite">
          {clock(selected.start_ms)} ·{" "}
          {measured(selected.value, series.unit, copy.unavailable)}
        </output>
      </div>
      <svg
        viewBox="0 0 780 136"
        role="img"
        aria-label={copy.chartRange
          .replace("{label}", label)
          .replace("{low}", low.toFixed(1))
          .replace("{high}", high.toFixed(1))
          .replace("{unit}", series.unit)}
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
        aria-label={
          series.measurement === "dbfs" ? copy.inspectLevel : copy.inspectPitch
        }
        aria-valuetext={`${clock(selected.start_ms)}, ${measured(selected.value, series.unit, copy.unavailable)}`}
      />
      <p className={styles.note}>{copy.clockNote}</p>
    </div>
  );
}

function MeasurementContent({
  data,
  language,
}: {
  data: SavedMeasurements;
  language: MeasurementLanguage;
}) {
  const copy = MEASUREMENT_COPY[language];
  const [channelIndex, setChannelIndex] = useState(0);
  const [kind, setKind] = useState<"dbfs" | "f0_hz">("dbfs");
  const channel = data.channels[channelIndex] ?? data.channels[0];
  const series = channel.series.find((item) => item.measurement === kind)!;
  return (
    <>
      {data.channels.length > 1 && (
        <label className={styles.select}>
          {copy.channel}
          <select
            value={channelIndex}
            onChange={(event) => setChannelIndex(Number(event.target.value))}
          >
            {data.channels.map((item, index) => (
              <option key={item.channel_index} value={index}>
                {copy.channel} {item.channel_index + 1}
              </option>
            ))}
          </select>
        </label>
      )}
      {data.channels.length > 1 && (
        <p className={styles.printChannel}>
          {copy.channel} {channel.channel_index + 1}
        </p>
      )}
      <div className={styles.metrics}>
        <div>
          <span>{copy.typicalLevel}</span>
          <strong>{measured(channel.level, "dBFS", copy.unavailable)}</strong>
          <small>{copy.median}</small>
        </div>
        <div>
          <span>{copy.typicalPitch}</span>
          <strong>{measured(channel.pitch, "Hz", copy.unavailable)}</strong>
          <small>
            {channel.pitchCoverage === null
              ? copy.noCoverage
              : copy.coverage.replace(
                  "{value}",
                  (channel.pitchCoverage * 100).toFixed(1),
                )}
          </small>
        </div>
      </div>
      <div
        className={styles.switcher}
        role="group"
        aria-label={copy.measurement}
      >
        <button
          type="button"
          aria-pressed={kind === "dbfs"}
          onClick={() => setKind("dbfs")}
        >
          {copy.soundLevel}
        </button>
        <button
          type="button"
          aria-pressed={kind === "f0_hz"}
          onClick={() => setKind("f0_hz")}
        >
          {copy.pitch}
        </button>
      </div>
      <MeasurementChart
        key={`${channel.channel_index}:${kind}`}
        series={series}
        duration={data.durationMs}
        language={language}
      />
      <p className={styles.note}>{copy.meaning}</p>
    </>
  );
}

export function RecordingMeasurements({
  recordingId,
  sourceSha256,
  language = "en",
}: {
  recordingId: string;
  sourceSha256: string;
  language?: MeasurementLanguage;
}) {
  const copy = MEASUREMENT_COPY[language];
  const [expanded, setExpanded] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    data?: SavedMeasurements;
    error?: boolean;
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
            error: true,
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
          {copy.title}
          <small>{copy.intro}</small>
        </span>
      </summary>
      <div className={styles.body}>
        {!data && !state.error && <p role="status">{copy.loading}</p>}
        {state.error && (
          <div role="status">
            <p>{copy.error}</p>
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setState({});
                setAttempt((value) => value + 1);
              }}
            >
              <RotateCcw size={14} aria-hidden="true" /> {copy.retry}
            </button>
          </div>
        )}
        {data && (
          <MeasurementContent
            key={`${recordingId}:${sourceSha256}`}
            data={data}
            language={language}
          />
        )}
      </div>
    </details>
  );
}
