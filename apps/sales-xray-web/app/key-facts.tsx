"use client";

import { useMemo } from "react";
import { numbersHeard, priceTalk, timePromise, voicesOf } from "./call-data";
import { formatClock } from "./lightbox/time";
import type { SalesReport, Transcript } from "./report-contract";
import { speakerName, useSpeakerProfiles } from "./speaker-profiles";
import { useReportDocument } from "./report-reading-context";
import { ProspectReportFacts } from "./prospect-report-facts";
import styles from "./key-facts.module.css";

/** Editable facts belong to the server profile. Call measurements stay source-only. */
export function KeyFacts({
  callId,
  transcript,
  durationMs,
  onSeek,
}: {
  callId: string | null;
  transcript: Transcript;
  report: SalesReport;
  durationMs: number;
  onSeek: (ms: number) => void;
}) {
  const documentView = useReportDocument();
  const { profiles } = useSpeakerProfiles(callId);
  const voices = useMemo(() => voicesOf(transcript), [transcript]);
  const promise = useMemo(() => timePromise(transcript), [transcript]);
  const price = useMemo(() => priceTalk(transcript), [transcript]);
  const numbers = useMemo(
    () =>
      numbersHeard(transcript).filter(
        (item, i, all) =>
          (item.kind === "money" || item.kind === "percent") &&
          all.findIndex(
            (other) =>
              other.segment.id === item.segment.id &&
              other.spoken === item.spoken,
          ) === i,
      ),
    [transcript],
  );
  const people = voices
    .filter((id) => profiles[id]?.name.trim() || profiles[id]?.role)
    .map((id) => speakerName(voices.indexOf(id), profiles[id], ""));
  const source = (ms: number) =>
    documentView ? (
      <span>{formatClock(ms)}</span>
    ) : (
      <button
        type="button"
        className={styles.heard}
        onClick={() => onSeek(ms)}
        aria-label={`Play from ${formatClock(ms)}`}
      >
        {formatClock(ms)}
      </button>
    );
  return (
    <section className={styles.facts} aria-label="Key facts">
      <header className={styles.head}>
        <div>
          <h3>Key facts</h3>
          <p>Edit the linked prospect profile. A person’s edit stays locked.</p>
        </div>
      </header>
      <ProspectReportFacts callId={callId} readOnly={documentView} />
      <details className={styles.measurements}>
        <summary>Facts heard in this call</summary>
        <dl>
          <div className={styles.row}>
            <dt>Who is on the call</dt>
            <dd>{people.length ? people.join(" · ") : "Not named yet"}</dd>
          </div>
          <div className={styles.row}>
            <dt>Time asked for</dt>
            <dd>
              {promise ? (
                <>
                  Up to {promise.upToMinutes} min · call took{" "}
                  {Math.round(durationMs / 60000)} min{" "}
                  {promise.segments.map((segment) => (
                    <span key={segment.id}>{source(segment.start_ms)}</span>
                  ))}
                </>
              ) : (
                "No supported time request was found."
              )}
            </dd>
          </div>
          <div className={styles.row}>
            <dt>Price discussion</dt>
            <dd>
              {price.length ? (
                <>
                  Came up{" "}
                  {price.slice(0, 3).map((segment) => (
                    <span key={segment.id}>{source(segment.start_ms)}</span>
                  ))}
                </>
              ) : (
                "No supported price mention was found."
              )}
            </dd>
          </div>
        </dl>
        <h4>Money and percentages heard</h4>
        {numbers.length ? (
          numbers.slice(0, 10).map((number) => (
            <div className={styles.number} key={number.id}>
              <b>{number.spoken}</b>
              {source(number.segment.start_ms)}
              <q>{number.segment.text}</q>
            </div>
          ))
        ) : (
          <p>No supported currency or percentage mention was found.</p>
        )}
      </details>
    </section>
  );
}
