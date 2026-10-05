"use client";

import { Play } from "lucide-react";
import { useId, useMemo } from "react";

import type { CallMap, EvidenceRef } from "./call-map-contract";
import {
  computeCallMetrics,
  quietFrom,
  timePromiseOverrun,
  type Monologue,
} from "./call-metrics";
import { formatClock } from "./lightbox/time";
import type { Transcript } from "./report-contract";
import styles from "./overview-call-visuals.module.css";

function smooth(points: Array<[number, number]>): string {
  if (points.length < 2) return "";
  let path = `M${points[0][0]},${points[0][1]}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const [x0, y0] = points[Math.max(0, index - 1)];
    const [x1, y1] = points[index];
    const [x2, y2] = points[index + 1];
    const [x3, y3] = points[Math.min(points.length - 1, index + 2)];
    path += ` C${x1 + (x2 - x0) / 6},${y1 + (y2 - y0) / 6} ${x2 - (x3 - x1) / 6},${y2 - (y3 - y1) / 6} ${x2},${y2}`;
  }
  return path;
}

function shareChartSegments(series: Array<number | null>) {
  const segments: Array<Array<[number, number]>> = [];
  series.forEach((share, index) => {
    if (share === null) return;
    const point: [number, number] = [index * 20 + 10, 56 - share * 48];
    const current = segments.at(-1);
    if (index === 0 || series[index - 1] === null || !current) {
      segments.push([point]);
    } else {
      current.push(point);
    }
  });
  return segments;
}

function resolveEvidenceStartMs(
  evidence: EvidenceRef[] | undefined,
  transcript: Transcript,
): number | null {
  if (!evidence || evidence.length === 0) return null;
  const targetId = evidence[0].segment_id;
  const segment = transcript.segments.find((s) => s.id === targetId);
  return segment ? segment.start_ms : null;
}

function PlayControl({
  startMs,
  onSeek,
  label,
}: {
  startMs: number | null;
  onSeek: (ms: number) => void;
  label?: string;
}) {
  if (startMs === null) return null;
  return (
    <button
      type="button"
      className={styles.playButton}
      onClick={() => onSeek(startMs)}
      aria-label={
        label
          ? `Play ${label} at ${formatClock(startMs)}`
          : `Play from ${formatClock(startMs)}`
      }
    >
      <Play size={11} aria-hidden="true" />
      <span>{label ?? formatClock(startMs)}</span>
    </button>
  );
}

export function OverviewCallVisuals({
  transcript,
  callMap = null,
  onSeek,
}: {
  transcript: Transcript;
  callMap?: CallMap | null;
  onSeek: (ms: number) => void;
}) {
  const metrics = useMemo(
    () => computeCallMetrics(transcript.segments, transcript.duration_ms),
    [transcript],
  );

  const overrun = useMemo(
    () =>
      timePromiseOverrun(
        callMap?.time_promise ?? null,
        transcript.segments,
        metrics.time_used_ms,
      ),
    [callMap?.time_promise, transcript.segments, metrics.time_used_ms],
  );

  const chartGradientId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const speakerEntries = Object.entries(metrics.speakers);

  return (
    <div className={styles.visualsRoot} data-overview-call-visuals>
      {/* System cards: always visible with transcript data */}
      <section className={styles.section} aria-label="System call measurements">
        <header className={styles.sectionHeader}>
          <h3 className={styles.sectionTitle}>Call measurements</h3>
          <span className={styles.sectionSubtitle}>
            Measured from transcript timing
          </span>
        </header>

        {/* Time used */}
        <div className={styles.summaryRow}>
          <div className={styles.summaryPill}>
            <span>
              {transcript.duration_ms && transcript.duration_ms > 0
                ? "Call length"
                : "Timed transcript span"}
            </span>
            <b>
              {metrics.time_used_ms > 0
                ? formatClock(metrics.time_used_ms)
                : "Unavailable"}
            </b>
          </div>
        </div>
        <p className={styles.measurementMeaning}>
          Talk share compares each speaker’s timed transcript segments. Gaps
          between segments are excluded; overlapping speakers count separately.
          Questions count question marks in the transcript. Listen to confirm.
        </p>

        {/* Talk time, talk share, 60s engagement curve, and questions for every speaker */}
        <div className={styles.speakerCardsGrid}>
          {speakerEntries.map(([speakerId, sMetrics]) => {
            const series: Array<number | null> = metrics.curve.map(
              (bin) => bin.shares[speakerId] ?? null,
            );
            const segments = shareChartSegments(series);
            const quiet = quietFrom(metrics, speakerId);
            const quietMinute =
              quiet !== null ? Math.floor(quiet.start_ms / 60000) + 1 : null;
            const quietX =
              quiet !== null
                ? Math.floor(quiet.start_ms / 60000) * 20 + 10
                : null;
            const svgWidth = Math.max(160, series.length * 20);

            return (
              <div key={speakerId} className={styles.speakerCard}>
                <div className={styles.speakerHeader}>
                  <h4 className={styles.speakerLabel}>{speakerId}</h4>
                  <div className={styles.speakerMetricsGroup}>
                    <span className={styles.metricBadge}>
                      <strong>
                        {sMetrics.talk_share !== null &&
                        sMetrics.talk_share !== undefined
                          ? `${Math.round(sMetrics.talk_share * 100)}%`
                          : "unavailable"}
                      </strong>{" "}
                      talk share
                    </span>
                    <span className={styles.metricBadge}>
                      Questions:{" "}
                      <strong>
                        {sMetrics.questions !== null &&
                        sMetrics.questions !== undefined
                          ? sMetrics.questions
                          : "unavailable"}
                      </strong>
                    </span>
                  </div>
                </div>

                {/* 60-second engagement curve */}
                <div className={styles.chartContainer}>
                  <div className={styles.chartMeta}>
                    <span className={styles.chartMetaTitle}>
                      Talk share by minute
                    </span>
                    {quiet !== null && quietMinute !== null ? (
                      <span
                        className={styles.quietTag}
                        data-recovered={quiet.recovered ? "true" : undefined}
                      >
                        Quiet start: min {quietMinute} ·{" "}
                        {quiet.recovered ? "recovered" : "unrecovered"}
                      </span>
                    ) : null}
                  </div>

                  <div className={styles.chartScroll}>
                    <svg
                      viewBox={`0 0 ${svgWidth} 64`}
                      preserveAspectRatio="none"
                      className={styles.chartSvg}
                      aria-hidden="true"
                    >
                      <defs>
                        <linearGradient
                          id={`${chartGradientId}-${speakerId}`}
                          x1="0"
                          y1="0"
                          x2="0"
                          y2="1"
                        >
                          <stop
                            offset="0%"
                            stopColor="var(--lx-teal)"
                            stopOpacity="0.4"
                          />
                          <stop
                            offset="100%"
                            stopColor="var(--lx-teal)"
                            stopOpacity="0.02"
                          />
                        </linearGradient>
                      </defs>

                      {segments.map((points, idx) => {
                        const line = smooth(points);
                        if (!line) {
                          return (
                            <circle
                              key={idx}
                              cx={points[0][0]}
                              cy={points[0][1]}
                              r="2.5"
                              className={styles.chartDot}
                            />
                          );
                        }
                        const area = `${line} L${points.at(-1)![0]},60 L${points[0][0]},60 Z`;
                        return (
                          <g key={idx}>
                            <path
                              d={area}
                              fill={`url(#${chartGradientId}-${speakerId})`}
                            />
                            <path
                              d={line}
                              className={styles.chartLine}
                              vectorEffect="non-scaling-stroke"
                            />
                          </g>
                        );
                      })}

                      {quietX !== null && quietMinute !== null ? (
                        <g>
                          <line
                            x1={quietX}
                            y1={4}
                            x2={quietX}
                            y2={60}
                            className={styles.quietMarkerLine}
                          />
                          <text
                            x={quietX + 4}
                            y={14}
                            className={styles.quietMarkerText}
                          >
                            Min {quietMinute}
                          </text>
                        </g>
                      ) : null}
                    </svg>

                    <div className={styles.srOnly}>
                      Talk-share curve for speaker {speakerId} across{" "}
                      {series.length} minutes.
                      {quiet !== null && quietMinute !== null
                        ? ` Quiet run starts at minute ${quietMinute}, ${
                            quiet.recovered
                              ? "labeled recovered."
                              : "not recovered."
                          }`
                        : " No quiet run detected."}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <details className={styles.timingDetails}>
          <summary>Talk time and longest monologues</summary>
          <div className={styles.timingBody}>
            <dl className={styles.talkTimes}>
              {speakerEntries.map(([speakerId, speaker]) => (
                <div key={speakerId}>
                  <dt>{speakerId}</dt>
                  <dd>Talk time: {formatClock(speaker.talk_ms)}</dd>
                </div>
              ))}
            </dl>
            <p className={styles.measurementMeaning}>
              Times come from transcript segments, which can include pauses.
              Longest monologues join the same speaker’s turns across gaps of up
              to 2 seconds when no other speaker starts between them. Quiet
              markers mean under 10% talk share for 3 minutes; recovered means a
              later minute reaches 25%.
            </p>
            {metrics.monologues.length > 0 ? (
              <div>
                <header
                  className={styles.sectionHeader}
                  style={{ marginBottom: 8 }}
                >
                  <h4 className={styles.detailTitle}>Longest monologues</h4>
                </header>
                <div className={styles.monologuesGrid}>
                  {metrics.monologues.map((m: Monologue, idx: number) => {
                    const durationMs = m.end_ms - m.start_ms;
                    return (
                      <div
                        key={`${m.speaker_id}-${m.start_ms}-${idx}`}
                        className={styles.monologueCard}
                      >
                        <div className={styles.monologueInfo}>
                          <span className={styles.monologueSpeaker}>
                            {m.speaker_id}
                          </span>
                          <span className={styles.monologueTimes}>
                            {formatClock(m.start_ms)} – {formatClock(m.end_ms)}{" "}
                            ({formatClock(durationMs)})
                          </span>
                        </div>
                        <PlayControl
                          startMs={m.start_ms}
                          onSeek={onSeek}
                          label={`Play ${formatClock(m.start_ms)}`}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>
        </details>
      </section>

      {/* When callMap is non-null */}
      {callMap !== null ? (
        <section
          className={styles.callMapSection}
          aria-label="Call map AI visual readings"
        >
          {/* Verdict line */}
          <div className={styles.verdictBanner}>
            <span className={styles.verdictLabel}>Verdict</span>
            <p className={styles.verdictText}>{callMap.verdict_line}</p>
          </div>

          {/* Timeline phase names at start_ms */}
          {callMap.phases.length > 0 ? (
            <div className={styles.detailCard}>
              <h4 className={styles.detailTitle}>Timeline phases</h4>
              <div className={styles.phasesRow}>
                {callMap.phases.map((phase, idx) => (
                  <div
                    key={`${phase.name}-${idx}`}
                    className={styles.phaseCard}
                  >
                    <span className={styles.phaseName}>{phase.name}</span>
                    <button
                      type="button"
                      className={styles.playButton}
                      onClick={() => onSeek(phase.start_ms)}
                      aria-label={`Play ${phase.name} phase at ${formatClock(phase.start_ms)}`}
                    >
                      <Play size={11} aria-hidden="true" />
                      <span>{formatClock(phase.start_ms)}</span>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* Outcome kind and next-step rung */}
          <div className={styles.detailCard}>
            <h4 className={styles.detailTitle}>Outcome & Next steps</h4>
            <div className={styles.outcomeRow}>
              <div className={styles.keyVal}>
                <small>Outcome kind</small>
                <b>{callMap.outcome.kind}</b>
              </div>
              <div className={styles.keyVal}>
                <small>Next-step rung</small>
                <b>{callMap.outcome.next_step_rung}</b>
              </div>
              <PlayControl
                startMs={resolveEvidenceStartMs(
                  callMap.outcome.evidence,
                  transcript,
                )}
                onSeek={onSeek}
              />
            </div>
          </div>

          {/* Forward and risk signals */}
          {callMap.signals.length > 0 ? (
            <div className={styles.detailCard}>
              <h4 className={styles.detailTitle}>Signals</h4>
              <div className={styles.signalsGrid}>
                {callMap.signals.map((signal, idx) => (
                  <div key={idx} className={styles.signalCard}>
                    <div className={styles.signalHeader}>
                      <span
                        className={styles.signalTag}
                        data-polarity={signal.polarity}
                      >
                        {signal.polarity === "forward"
                          ? "Forward signal"
                          : "Risk signal"}
                      </span>
                      <span className={styles.signalKind}>{signal.kind}</span>
                    </div>
                    <p className={styles.signalText}>{signal.text}</p>
                    <PlayControl
                      startMs={resolveEvidenceStartMs(
                        signal.evidence,
                        transcript,
                      )}
                      onSeek={onSeek}
                    />
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* Pains showing raised_by and linked addressed_by pitch item text */}
          {callMap.pains.length > 0 ? (
            <div className={styles.detailCard}>
              <h4 className={styles.detailTitle}>Customer pains</h4>
              <div className={styles.painsGrid}>
                {callMap.pains.map((pain) => {
                  const linkedPitch = pain.addressed_by
                    ? callMap.pitch_items.find(
                        (p) => p.id === pain.addressed_by,
                      )
                    : null;
                  return (
                    <div key={pain.id} className={styles.painCard}>
                      <div className={styles.painTop}>
                        <span className={styles.painRaised}>
                          Raised by: <b>{pain.raised_by}</b>
                        </span>
                        <span className={styles.painMeta}>
                          {pain.prospect_intensity} intensity · {pain.times}×
                        </span>
                      </div>
                      <p className={styles.painText}>{pain.text}</p>
                      <div className={styles.addressedBox}>
                        <small>Addressed by pitch item:</small>
                        <span>
                          {linkedPitch
                            ? linkedPitch.text
                            : (pain.addressed_by ?? "Not addressed")}
                        </span>
                      </div>
                      <PlayControl
                        startMs={resolveEvidenceStartMs(
                          pain.evidence,
                          transcript,
                        )}
                        onSeek={onSeek}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          {/* Pitch items */}
          {callMap.pitch_items.length > 0 ? (
            <div className={styles.detailCard}>
              <h4 className={styles.detailTitle}>Pitch items</h4>
              <div className={styles.pitchList}>
                {callMap.pitch_items.map((item) => (
                  <div key={item.id} className={styles.pitchCard}>
                    <div className={styles.pitchMeta}>
                      <span className={styles.pitchId}>{item.id}</span>
                      <span className={styles.pitchTime}>
                        {formatClock(item.start_ms)} –{" "}
                        {formatClock(item.end_ms)}
                      </span>
                    </div>
                    <p className={styles.pitchText}>{item.text}</p>
                    <PlayControl
                      startMs={resolveEvidenceStartMs(
                        item.evidence,
                        transcript,
                      )}
                      onSeek={onSeek}
                    />
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* Money: label, min/max, unit and period */}
          {callMap.money.length > 0 ? (
            <div className={styles.detailCard}>
              <h4 className={styles.detailTitle}>Money mentions</h4>
              <div className={styles.moneyGrid}>
                {callMap.money.map((m, idx) => (
                  <div key={idx} className={styles.moneyCard}>
                    <span className={styles.moneyLabel}>{m.label}</span>
                    <span className={styles.moneyValue}>
                      {m.value_min === m.value_max
                        ? `${m.value_min} ${m.unit}`
                        : `${m.value_min} – ${m.value_max} ${m.unit}`}
                      {m.period ? ` per ${m.period}` : ""}
                    </span>
                    <PlayControl
                      startMs={resolveEvidenceStartMs(m.evidence, transcript)}
                      onSeek={onSeek}
                    />
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* Claims including verifiable and seller_error */}
          {callMap.claims.length > 0 ? (
            <div className={styles.detailCard}>
              <h4 className={styles.detailTitle}>Claims</h4>
              <div className={styles.claimsGrid}>
                {callMap.claims.map((claim) => (
                  <div key={claim.id} className={styles.claimCard}>
                    <p className={styles.claimText}>{claim.text}</p>
                    <div className={styles.claimAttributes}>
                      <span>
                        Verifiable: <b>{claim.verifiable}</b>
                      </span>
                      {claim.seller_error ? (
                        <span>
                          Seller error: <b>{claim.seller_error}</b>
                        </span>
                      ) : null}
                    </div>
                    <PlayControl
                      startMs={resolveEvidenceStartMs(
                        claim.evidence,
                        transcript,
                      )}
                      onSeek={onSeek}
                    />
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* Qualification gaps and confirmed items */}
          <div className={styles.detailCard}>
            <h4 className={styles.detailTitle}>Qualification</h4>
            <div className={styles.qualSplit}>
              <div className={styles.qualCol}>
                <span className={styles.qualSubtitle}>Qualification gaps</span>
                <div className={styles.tagGroup}>
                  {callMap.qualification_gaps.length > 0 ? (
                    callMap.qualification_gaps.map((gap, idx) => (
                      <span key={idx} className={styles.gapTag}>
                        {gap}
                      </span>
                    ))
                  ) : (
                    <span className={styles.emptyText}>None</span>
                  )}
                </div>
              </div>
              <div className={styles.qualCol}>
                <span className={styles.qualSubtitle}>Confirmed items</span>
                <div className={styles.tagGroup}>
                  {callMap.qualification_confirmed.length > 0 ? (
                    callMap.qualification_confirmed.map((conf, idx) => (
                      <span key={idx} className={styles.confirmedChip}>
                        <span>{conf.item}</span>
                        <PlayControl
                          startMs={resolveEvidenceStartMs(
                            conf.evidence,
                            transcript,
                          )}
                          onSeek={onSeek}
                        />
                      </span>
                    ))
                  ) : (
                    <span className={styles.emptyText}>None</span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Time promised, time used and computed overrun */}
          <div className={styles.detailCard}>
            <h4 className={styles.detailTitle}>Time promise & Overrun</h4>
            <div className={styles.outcomeRow}>
              <div className={styles.keyVal}>
                <small>Time promised</small>
                <b>
                  {callMap.time_promise !== null
                    ? formatClock(callMap.time_promise.promised_ms)
                    : "unavailable"}
                </b>
              </div>
              <div className={styles.keyVal}>
                <small>Time used</small>
                <b>{formatClock(metrics.time_used_ms)}</b>
              </div>
              <div className={styles.keyVal}>
                <small>Computed overrun</small>
                <b>
                  {overrun !== null
                    ? overrun > 0
                      ? `${formatClock(overrun)} overrun`
                      : "No overrun"
                    : "unavailable"}
                </b>
              </div>
              {callMap.time_promise !== null ? (
                <PlayControl
                  startMs={resolveEvidenceStartMs(
                    callMap.time_promise.evidence,
                    transcript,
                  )}
                  onSeek={onSeek}
                />
              ) : null}
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
