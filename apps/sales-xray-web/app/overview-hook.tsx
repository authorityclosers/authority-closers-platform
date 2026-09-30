"use client";

import {
  ArrowRight,
  AudioLines,
  BookOpen,
  ChartNoAxesColumnIncreasing,
  Lightbulb,
  Play,
  Radar,
  TableProperties,
  Target,
  UserRound,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { talkShareSeries, voicesOf } from "./call-data";
import { formatClock } from "./lightbox/time";
import type {
  ReportEvidence,
  SalesReport,
  Transcript,
} from "./report-contract";
import { useReportNavigation } from "./report-reading-context";
import {
  afterPrice,
  confirmedRoles,
  promises,
  talkOvers,
  unansweredQuestions,
} from "./sales-signals";
import { speakerName, useSpeakerProfiles } from "./speaker-profiles";
import { getShellState } from "./shell/shell-store";
import styles from "./overview-hook.module.css";

const OUTCOME: Record<string, { label: string; tone: string }> = {
  closed: { label: "Closed", tone: "good" },
  follow_up: { label: "Follow-up set", tone: "good" },
  future_date: { label: "Talk again later", tone: "warn" },
  no_sale: { label: "No sale", tone: "bad" },
  disqualified: { label: "Not a fit", tone: "bad" },
  unclear: { label: "Outcome unclear", tone: "warn" },
};

const PURPOSE: Record<string, string> = {
  must_watch: "Must hear",
  watch: "Worth hearing",
  repeat: "Do this again",
};

function firstSentence(text: string) {
  const match = text.match(/^.*?[.!?।](\s|$)/u);
  return (match ? match[0] : text).trim();
}

/** Counts up to a real number once, calmly; still under reduced motion. */
function useCountUp(value: number) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const reduce = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (reduce || value <= 0) {
      const frame = requestAnimationFrame(() => setShown(value));
      return () => cancelAnimationFrame(frame);
    }
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / 700);
      setShown(Math.round(value * (1 - (1 - progress) ** 3)));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return shown;
}

function Count({ value }: { value: number }) {
  return <>{useCountUp(value)}</>;
}

function PlayChip({
  evidence,
  onSeek,
}: {
  evidence: ReportEvidence | undefined;
  onSeek: (ms: number) => void;
}) {
  if (!evidence) return null;
  return (
    <button
      type="button"
      className={styles.play}
      onClick={(event) => {
        event.stopPropagation();
        onSeek(evidence.start_ms);
      }}
      aria-label={`Play from ${formatClock(evidence.start_ms)}`}
    >
      <span className={styles.bars} aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      {formatClock(evidence.start_ms)}
    </button>
  );
}

/**
 * The prospect's share of the talk in each minute, as a filled line, with the
 * turning point marked. It shows where they leaned in and where they went quiet.
 */
function TalkRibbon({
  series,
  durationMs,
  marks,
  onSeek,
}: {
  series: Array<number | null>;
  durationMs: number;
  marks: Array<{ label: string; ms: number; tone: string }>;
  onSeek: (ms: number) => void;
}) {
  const width = series.length * 10;
  const points = series.map((share, index) => [
    index * 10 + 5,
    40 - (share ?? 0) * 36,
  ]);
  const line = points
    .map(([x, y], index) => `${index ? "L" : "M"}${x},${y}`)
    .join(" ");
  const area = `${line} L${points.at(-1)![0]},40 L${points[0][0]},40 Z`;
  return (
    <div className={styles.ribbon}>
      <svg
        viewBox={`0 0 ${width} 40`}
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path className={styles.ribbonArea} d={area} />
        <path
          className={styles.ribbonLine}
          d={line}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {marks
        .slice()
        .sort((a, b) => a.ms - b.ms)
        .reduce<Array<(typeof marks)[number] & { row: number }>>(
          (placed, mark) => {
            // A label too close to the one before it steps down a row.
            const previous = placed.at(-1);
            const close =
              previous !== undefined &&
              (mark.ms - previous.ms) / Math.max(1, durationMs) < 0.09;
            placed.push({ ...mark, row: close && previous.row === 0 ? 1 : 0 });
            return placed;
          },
          [],
        )
        .map((mark) => (
          <button
            key={mark.label}
            type="button"
            className={styles.mark}
            data-row={mark.row}
            data-tone={mark.tone}
            style={
              {
                left: `${Math.min(100, (mark.ms / Math.max(1, durationMs)) * 100)}%`,
              } as CSSProperties
            }
            onClick={() => onSeek(mark.ms)}
            title={`${mark.label} · ${formatClock(mark.ms)}`}
          >
            <span>{mark.label}</span>
          </button>
        ))}
      <span className={styles.ribbonAxis} aria-hidden="true">
        <span>00:00</span>
        <span>{formatClock(durationMs)}</span>
      </span>
    </div>
  );
}

function Section({
  title,
  index,
  children,
  action,
}: {
  title: string;
  index: number;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section
      className={styles.section}
      style={{ "--i": index } as CSSProperties}
    >
      <header>
        <h3>{title}</h3>
        {action}
      </header>
      {children}
    </section>
  );
}

/**
 * The first screen of a report: what happened, where it turned, what to hear,
 * where it slipped and one thing for the next call, then doors into every tab.
 * Everything comes from the saved report and transcript; nothing is generated.
 */
export function OverviewHook({
  report,
  transcript,
  callId,
  onSeek,
}: {
  report: SalesReport;
  transcript: Transcript;
  callId: string | null;
  onSeek: (ms: number) => void;
}) {
  const navigate = useReportNavigation();
  const overview = report.overview;
  const outcome = overview?.outcome ?? null;
  const outcomeStyle = outcome ? OUTCOME[outcome.kind] : null;
  const headline = overview?.diagnosis?.text ?? firstSentence(report.summary);
  const change = overview?.conversation_change ?? null;
  const focus = overview?.next_call_focus ?? null;

  const hear = useMemo(() => {
    const rewatch = (overview?.rewatch ?? []).map((item) => ({
      label: PURPOSE[item.purpose] ?? "Worth hearing",
      text: item.text,
      evidence: item.evidence[0],
      tone:
        item.purpose === "repeat"
          ? "good"
          : item.purpose === "must_watch"
            ? "hot"
            : "calm",
    }));
    if (rewatch.length) return rewatch.slice(0, 3);
    return report.strengths
      .filter((finding) => finding.evidence.length)
      .slice(0, 3)
      .map((finding) => ({
        label: "Do this again",
        text: finding.title,
        evidence: finding.evidence[0],
        tone: "good",
      }));
  }, [overview, report.strengths]);

  const slips = (overview?.missed_details ?? []).slice(0, 2);

  const { profiles } = useSpeakerProfiles(callId);
  const voices = useMemo(() => voicesOf(transcript), [transcript]);
  const roles = confirmedRoles(
    voices,
    Object.fromEntries(voices.map((id) => [id, profiles[id]?.role])),
  );
  const signals = useMemo(() => {
    if (!roles) return null;
    const price = afterPrice(transcript, roles)[0];
    return {
      unanswered: unansweredQuestions(transcript, roles).length,
      overs: talkOvers(transcript, roles).length,
      silence: price?.silence_ms ?? null,
      promised: promises(transcript, roles).length,
    };
    // roles comes from saved profiles; its two ids are the real inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transcript, roles?.seller, roles?.prospect]);

  const go = (section: string) => navigate?.(section);
  const durationMs = transcript.duration_ms;
  const series = useMemo(
    () => (roles ? talkShareSeries(transcript, roles.prospect) : []),
    // roles comes from saved profiles; its prospect id is the real input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [transcript, roles?.prospect],
  );
  const marks = [
    ...(change
      ? (
          [
            ["Before", change.before.evidence[0], "calm"],
            ["Turn", change.change.evidence[0], "hot"],
            ["After", change.after.evidence[0], "good"],
          ] as const
        )
          .filter(([, evidence]) => evidence)
          .map(([label, evidence, tone]) => ({
            label,
            ms: evidence!.start_ms,
            tone,
          }))
      : []),
    ...(outcome?.evidence[0]
      ? [{ label: "Outcome", ms: outcome.evidence[0].start_ms, tone: "good" }]
      : []),
  ];
  const prospectName = roles
    ? speakerName(
        voices.indexOf(roles.prospect),
        profiles[roles.prospect],
        getShellState().profileName,
      )
    : null;
  const observed = report.dimensions.filter(
    (item) => item.status === "observed",
  ).length;
  const findings =
    report.strengths.length +
    report.missed_opportunities.length +
    report.improvements.length +
    report.objection_analysis.length +
    report.closing_analysis.length;

  const doors = [
    {
      id: "moments",
      label: "Moments",
      icon: AudioLines,
      count: findings,
      unit: "findings",
    },
    {
      id: "prospect",
      label: "Prospect",
      icon: UserRound,
      count: overview?.prospect_interpretations.length ?? 0,
      unit: "reads",
    },
    {
      id: "signals",
      label: "Call signals",
      icon: Radar,
      count: signals
        ? signals.unanswered + signals.overs + signals.promised
        : 0,
      unit: "signals",
    },
    {
      id: "skills",
      label: "Sales skills",
      icon: ChartNoAxesColumnIncreasing,
      count: observed,
      unit: "checked",
    },
    {
      id: "next-call-plan",
      label: "Next-call plan",
      icon: Lightbulb,
      count: report.improvements.length,
      unit: "steps",
    },
    {
      id: "transcript",
      label: "Transcript",
      icon: BookOpen,
      count: transcript.segments.length,
      unit: "lines",
    },
    {
      id: "raw-data",
      label: "Raw data",
      icon: TableProperties,
      count: 0,
      unit: "",
    },
  ];

  return (
    <div className={styles.hook} data-overview-hook>
      <div className={styles.hero}>
        <div className={styles.verdict}>
          {outcomeStyle ? (
            <span className={styles.outcome} data-tone={outcomeStyle.tone}>
              <i aria-hidden="true" />
              {outcomeStyle.label}
            </span>
          ) : null}
          <p className={styles.headline}>
            {headline.split(" ").map((word, index) => (
              <span
                key={`${word}-${index}`}
                style={{ "--w": index } as CSSProperties}
              >
                {word}{" "}
              </span>
            ))}
          </p>
          {outcome ? (
            <p className={styles.outcomeText}>
              {outcome.text}
              <PlayChip evidence={outcome.evidence[0]} onSeek={onSeek} />
            </p>
          ) : null}
          {series.length > 1 ? (
            <div className={styles.ribbonWrap}>
              <small>
                {prospectName}&apos;s share of the talk, minute by minute
              </small>
              <TalkRibbon
                series={series}
                durationMs={durationMs}
                marks={marks}
                onSeek={onSeek}
              />
            </div>
          ) : null}
        </div>
        {change ? (
          <div className={styles.turn} aria-label="Where the call turned">
            <b className={styles.turnTitle}>Where the call turned</b>
            <ol>
              {(
                [
                  ["Before", change.before],
                  ["The turn", change.change],
                  ["After", change.after],
                ] as const
              ).map(([label, note], index) => (
                <li
                  key={label}
                  style={{ "--i": index } as CSSProperties}
                  data-step={index}
                >
                  <span className={styles.dot} aria-hidden="true" />
                  <small>{label}</small>
                  <span className={styles.turnText}>{note.text}</span>
                  <PlayChip evidence={note.evidence[0]} onSeek={onSeek} />
                </li>
              ))}
            </ol>
          </div>
        ) : null}
      </div>

      {hear.length ? (
        <Section title="Hear these first" index={1}>
          <div className={styles.hear}>
            {hear.map((item, index) => (
              <button
                key={`${item.label}-${index}`}
                type="button"
                className={styles.moment}
                data-tone={item.tone}
                style={{ "--i": index } as CSSProperties}
                onClick={() => item.evidence && onSeek(item.evidence.start_ms)}
              >
                <span className={styles.momentTop}>
                  <em>{item.label}</em>
                  {item.evidence ? (
                    <span className={styles.time}>
                      <Play size={11} aria-hidden="true" />
                      {formatClock(item.evidence.start_ms)}
                    </span>
                  ) : null}
                </span>
                <span className={styles.momentText}>{item.text}</span>
                {item.evidence ? (
                  <q className={styles.quote}>{item.evidence.quote}</q>
                ) : null}
              </button>
            ))}
          </div>
        </Section>
      ) : null}

      {slips.length ? (
        <Section title="Where it slipped" index={2}>
          <div className={styles.slips}>
            {slips.map((slip, index) => (
              <article
                key={index}
                className={styles.slip}
                style={{ "--i": index } as CSSProperties}
              >
                <div className={styles.bubble} data-side="them">
                  <small>They said</small>
                  <q>
                    {slip.prospect_signal.evidence[0]?.quote ??
                      slip.prospect_signal.text}
                  </q>
                  <PlayChip
                    evidence={slip.prospect_signal.evidence[0]}
                    onSeek={onSeek}
                  />
                </div>
                <ArrowRight
                  className={styles.arrow}
                  size={16}
                  aria-hidden="true"
                />
                <div className={styles.bubble} data-side="you">
                  <small>You said</small>
                  <q>
                    {slip.closer_response.evidence[0]?.quote ??
                      slip.closer_response.text}
                  </q>
                  <PlayChip
                    evidence={slip.closer_response.evidence[0]}
                    onSeek={onSeek}
                  />
                </div>
                <p className={styles.better}>
                  <b>Try next time</b>
                  {slip.follow_up}
                </p>
              </article>
            ))}
          </div>
        </Section>
      ) : null}

      <div className={styles.split}>
        <Section
          title="Signals from the call"
          index={3}
          action={
            <button
              type="button"
              className={styles.more}
              onClick={() => go("signals")}
            >
              Open <ArrowRight size={13} aria-hidden="true" />
            </button>
          }
        >
          {signals ? (
            <div className={styles.chips}>
              <button
                type="button"
                onClick={() => go("signals")}
                data-hot={signals.unanswered ? "" : undefined}
              >
                <b>
                  <Count value={signals.unanswered} />
                </b>{" "}
                questions may be unanswered
              </button>
              <button
                type="button"
                onClick={() => go("signals")}
                data-hot={signals.overs ? "" : undefined}
              >
                <b>
                  <Count value={signals.overs} />
                </b>{" "}
                times you talked over them
              </button>
              <button type="button" onClick={() => go("signals")}>
                <b>
                  {signals.silence === null
                    ? "—"
                    : signals.silence < 1000
                      ? "<1 s"
                      : `${Math.round(signals.silence / 1000)} s`}
                </b>{" "}
                silence after a price or budget mention
              </button>
              <button type="button" onClick={() => go("signals")}>
                <b>
                  <Count value={signals.promised} />
                </b>{" "}
                promises to keep
              </button>
            </div>
          ) : (
            <button
              type="button"
              className={styles.askRoles}
              onClick={() => go("signals")}
            >
              Tell us which voice is the salesperson to see talk-overs,
              unanswered questions and promises{" "}
              <ArrowRight size={13} aria-hidden="true" />
            </button>
          )}
        </Section>

        {focus ? (
          <Section title="Next call: one thing" index={4}>
            <button
              type="button"
              className={styles.focus}
              onClick={() => go("next-call-plan")}
            >
              <Target size={18} aria-hidden="true" />
              <span>
                <b>{focus.behavior}</b>
                <small>{focus.target}</small>
              </span>
              <ArrowRight size={15} aria-hidden="true" />
            </button>
          </Section>
        ) : null}
      </div>

      <Section title="Explore the call" index={5}>
        <div className={styles.doors}>
          {doors.map(({ id, label, icon: Icon, count, unit }, index) => (
            <button
              key={id}
              type="button"
              className={styles.door}
              style={{ "--i": index } as CSSProperties}
              onClick={() => go(id)}
            >
              <Icon size={18} aria-hidden="true" />
              <b>{label}</b>
              {unit ? (
                <small>
                  <Count value={count} /> {unit}
                </small>
              ) : (
                <small>Every number, list and source</small>
              )}
            </button>
          ))}
        </div>
      </Section>
    </div>
  );
}
