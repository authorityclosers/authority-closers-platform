"use client";

import {
  ArrowRight,
  ArrowRightLeft,
  AudioLines,
  MessagesSquare,
  Ban,
  BookOpen,
  CalendarCheck,
  CalendarClock,
  ChartNoAxesColumnIncreasing,
  CornerDownRight,
  Check,
  CircleHelp,
  CircleX,
  Copy,
  Flag,
  Handshake,
  Headphones,
  Lightbulb,
  Play,
  Radar,
  TableProperties,
  Target,
  ThumbsUp,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import {
  useEffect,
  useId,
  useMemo,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { questionsAsked, talkShareSeries, voicesOf } from "./call-data";
import { formatClock } from "./lightbox/time";
import type {
  ReportEvidence,
  SalesReport,
  Transcript,
} from "./report-contract";
import { Emote, type EmoteName } from "./emote";
import { EntityText } from "./report-entities";
import { useReportNavigation } from "./report-reading-context";
import {
  afterPrice,
  confirmedRoles,
  promises,
  talkOvers,
  unansweredQuestions,
} from "./sales-signals";
import { getShellState } from "./shell/shell-store";
import { SpeakerAvatar } from "./speaker-avatar";
import { speakerName, useSpeakerProfiles } from "./speaker-profiles";
import styles from "./overview-hook.module.css";

export const OUTCOME: Record<
  string,
  { label: string; tone: string; Icon: LucideIcon; emote: EmoteName }
> = {
  closed: { label: "Deal closed", tone: "good", Icon: Handshake, emote: "handshake" },
  follow_up: { label: "Next step agreed", tone: "good", Icon: CalendarCheck, emote: "spiral-calendar" },
  future_date: { label: "Call back later", tone: "warn", Icon: CalendarClock, emote: "alarm-clock" },
  no_sale: { label: "No sale", tone: "bad", Icon: CircleX, emote: "cross-mark" },
  disqualified: { label: "Not a fit", tone: "bad", Icon: Ban, emote: "no-entry" },
  unclear: { label: "No clear next step", tone: "warn", Icon: CircleHelp, emote: "red-question-mark" },
};

const LISTEN: Record<
  string,
  {
    label: string;
    hint: string;
    tone: string;
    Icon: LucideIcon;
    emote: EmoteName;
  }
> = {
  must_watch: {
    label: "Must listen",
    hint: "The most important moment of the call",
    tone: "hot",
    Icon: Headphones,
    emote: "fire",
  },
  watch: {
    label: "Worth a listen",
    hint: "A moment to learn from",
    tone: "calm",
    Icon: Headphones,
    emote: "headphone",
  },
  repeat: {
    label: "You did this well",
    hint: "Do it again in your next call",
    tone: "good",
    Icon: ThumbsUp,
    emote: "clapping-hands",
  },
};

function firstSentence(text: string) {
  const match = text.match(/^.*?[.!?।](\s|$)/u);
  return (match ? match[0] : text).trim();
}

/** Counts up to a real number once; instant under reduced motion. */
function useCountUp(value: number) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const reduce = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    let frame = 0;
    if (reduce || value <= 0) {
      frame = requestAnimationFrame(() => setShown(value));
      return () => cancelAnimationFrame(frame);
    }
    const start = performance.now();
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

/** One voice's share of all talk between two times, or null when silent. */
function shareBetween(
  transcript: Transcript,
  voice: string,
  from: number,
  to: number,
) {
  let mine = 0;
  let all = 0;
  for (const segment of transcript.segments) {
    const overlap =
      Math.min(segment.end_ms, to) - Math.max(segment.start_ms, from);
    if (overlap <= 0) continue;
    all += overlap;
    if (segment.speaker_id === voice) mine += overlap;
  }
  return all > 0 ? mine / all : null;
}

const percent = (share: number | null) =>
  share === null ? "—" : `${Math.round(share * 100)}%`;

function PlayChip({
  evidence,
  onSeek,
  label,
}: {
  evidence: ReportEvidence | undefined;
  onSeek: (ms: number) => void;
  label?: string;
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
      <Play size={11} aria-hidden="true" />
      {label ?? formatClock(evidence.start_ms)}
    </button>
  );
}

function Section({
  title,
  hint,
  index,
  children,
  action,
}: {
  title: string;
  hint?: string;
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
        <span>
          <h3>{title}</h3>
          {hint ? <small>{hint}</small> : null}
        </span>
        {action}
      </header>
      {children}
    </section>
  );
}

/** A smooth path through the points (Catmull-Rom as Bézier curves). */
function smooth(points: Array<[number, number]>) {
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

function TalkChart({
  series,
  durationMs,
  turnMs,
  outcomeMs,
  mood,
  name,
  onSeek,
}: {
  series: Array<number | null>;
  durationMs: number;
  turnMs: number | null;
  outcomeMs: number | null;
  mood: "drop" | "rise" | "flat";
  name: string;
  onSeek: (ms: number) => void;
}) {
  const gradient = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const [hover, setHover] = useState<number | null>(null);
  const width = series.length * 20;
  const points: Array<[number, number]> = series.map((share, index) => [
    index * 20 + 10,
    56 - (share ?? 0) * 50,
  ]);
  const line = smooth(points);
  const area = `${line} L${points.at(-1)![0]},56 L${points[0][0]},56 Z`;
  const at = (ms: number) =>
    `${Math.min(100, (ms / Math.max(1, durationMs)) * 100)}%`;
  const ticks = [] as number[];
  for (let minute = 5; minute * 60_000 < durationMs; minute += 5)
    ticks.push(minute * 60_000);
  return (
    <div
      className={styles.chart}
      onPointerMove={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        const bin = Math.floor(
          ((event.clientX - box.left) / box.width) * series.length,
        );
        setHover(bin >= 0 && bin < series.length ? bin : null);
      }}
      onPointerLeave={() => setHover(null)}
    >
      {turnMs !== null ? (
        <>
          <span
            className={styles.band}
            data-phase="before"
            style={{ left: 0, width: at(turnMs) }}
          />
          <span
            className={styles.band}
            data-phase="after"
            data-mood={mood}
            style={{ left: at(turnMs), right: 0 }}
          />
        </>
      ) : null}
      <svg
        viewBox={`0 0 ${width} 60`}
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <defs>
          <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" className={styles.stopTop} />
            <stop offset="100%" className={styles.stopBottom} />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#${gradient})`} />
        <path
          className={styles.chartLine}
          d={line}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {turnMs !== null ? (
        <button
          type="button"
          className={styles.switchLine}
          style={{ left: at(turnMs) }}
          onClick={() => onSeek(turnMs)}
        >
          <span>You switched · {formatClock(turnMs)}</span>
        </button>
      ) : null}
      {outcomeMs !== null ? (
        <button
          type="button"
          className={styles.outcomeMark}
          aria-label={`Play the outcome · ${formatClock(outcomeMs)}`}
          title={`Play the outcome · ${formatClock(outcomeMs)}`}
          style={{ left: at(outcomeMs) }}
          onClick={() => onSeek(outcomeMs)}
        >
          <Flag size={11} aria-hidden="true" />
        </button>
      ) : null}
      {hover !== null ? (
        <span
          className={styles.tip}
          style={{ left: `${((hover + 0.5) / series.length) * 100}%` }}
        >
          Minute {hover + 1}: {name} {percent(series[hover])}
        </span>
      ) : null}
      <span className={styles.axis} aria-hidden="true">
        <span style={{ left: 0 }}>0</span>
        {ticks.map((ms) => (
          <span key={ms} style={{ left: at(ms) }}>
            {ms / 60_000} min
          </span>
        ))}
      </span>
    </div>
  );
}

/**
 * The first screen of a report: how the call ended, how it went, what to
 * listen to, the missed chances and one thing for the next call. Written
 * parts come from the saved report; charts and counts are measured.
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
  const go = (section: string) => navigate?.(section);
  const overview = report.overview;
  const outcome = overview?.outcome ?? null;
  const outcomeStyle = outcome ? OUTCOME[outcome.kind] : null;
  const headline = overview?.diagnosis?.text ?? firstSentence(report.summary);
  const change = overview?.conversation_change ?? null;
  const focus = overview?.next_call_focus ?? null;
  const [copied, setCopied] = useState<number | null>(null);

  const { profiles } = useSpeakerProfiles(callId);
  const accountName = getShellState().profileName;
  const voices = useMemo(() => voicesOf(transcript), [transcript]);
  const roles = confirmedRoles(
    voices,
    Object.fromEntries(voices.map((id) => [id, profiles[id]?.role])),
  );
  const person = (id: string | null | undefined) => {
    if (!id || !voices.includes(id)) return null;
    const voice = voices.indexOf(id);
    return {
      voice,
      name: speakerName(voice, profiles[id], accountName),
      avatar: (size: number) => (
        <SpeakerAvatar
          voice={voice}
          profile={profiles[id]}
          youName={accountName}
          size={size}
        />
      ),
    };
  };
  const speakerOf = (evidence: ReportEvidence | undefined) =>
    person(
      transcript.segments.find((segment) => segment.id === evidence?.segment_id)
        ?.speaker_id,
    );
  const prospect = person(roles?.prospect);
  const seller = person(roles?.seller);

  const durationMs = transcript.duration_ms;
  const turnMs = change?.change.evidence[0]?.start_ms ?? null;
  const series = useMemo(
    () => (roles ? talkShareSeries(transcript, roles.prospect) : []),
    // roles comes from saved profiles; its prospect id is the real input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [transcript, roles?.prospect],
  );
  const before =
    roles && turnMs !== null
      ? shareBetween(transcript, roles.prospect, 0, turnMs)
      : null;
  const after =
    roles && turnMs !== null
      ? shareBetween(transcript, roles.prospect, turnMs, durationMs)
      : null;
  const mood: "drop" | "rise" | "flat" =
    before === null || after === null
      ? "flat"
      : after < before - 0.08
        ? "drop"
        : after > before + 0.08
          ? "rise"
          : "flat";

  const listen = useMemo(() => {
    const picks = (overview?.rewatch ?? []).map((item) => ({
      ...LISTEN[item.purpose],
      text: item.text,
      evidence: item.evidence[0],
    }));
    if (picks.length) return picks.slice(0, 3);
    return report.strengths
      .filter((finding) => finding.evidence.length)
      .slice(0, 3)
      .map((finding) => ({
        ...LISTEN.repeat,
        text: finding.title,
        evidence: finding.evidence[0],
      }));
  }, [overview, report.strengths]);

  const missed = (overview?.missed_details ?? []).slice(0, 2);

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
      Icon: AudioLines,
      count: findings,
      unit: "findings",
    },
    {
      id: "prospect",
      label: "Prospect",
      Icon: UserRound,
      count: overview?.prospect_interpretations.length ?? 0,
      unit: "reads",
    },
    {
      id: "signals",
      label: "Call signals",
      Icon: Radar,
      count: signals
        ? signals.unanswered + signals.overs + signals.promised
        : 0,
      unit: "signals",
    },
    {
      id: "skills",
      label: "Sales skills",
      Icon: ChartNoAxesColumnIncreasing,
      count: observed,
      unit: "checked",
    },
    {
      id: "next-call-plan",
      label: "Next-call plan",
      Icon: Lightbulb,
      count: report.improvements.length,
      unit: "steps",
    },
    {
      id: "transcript",
      label: "Transcript",
      Icon: BookOpen,
      count: transcript.segments.length,
      unit: "lines",
    },
    {
      id: "raw-data",
      label: "Raw data",
      Icon: TableProperties,
      count: 0,
      unit: "",
    },
  ];

  const beforePhase = {
    mood: "neutral",
    title: before === null ? "How it started" : "Before the switch",
    Face: MessagesSquare,
  };
  const afterPhase = {
    mood: "neutral",
    title: after === null ? "What happened next" : "After the switch",
    Face: MessagesSquare,
  };
  // Count each seller question, even when one segment contains several.
  const asked = (from: number, to: number) =>
    roles
      ? questionsAsked(transcript).filter(
          (row) =>
            row.segment.speaker_id === roles.seller &&
            row.segment.start_ms >= from &&
            row.segment.start_ms < to,
        ).length
      : null;
  const minutes = (ms: number) => `${Math.max(1, Math.round(ms / 60000))} min`;
  const askedBefore = turnMs !== null ? asked(0, turnMs) : null;
  const askedAfter = turnMs !== null ? asked(turnMs, durationMs) : null;
  const talkLabel = prospect ? `${prospect.name} talked` : "They talked";
  // Every card has the same two measured tiles: their talk share and your
  // questions. The switch card shows both as before → after.
  const stats = (
    share: number | null,
    questions: number | null,
  ): Array<{ value: ReactNode; label: string }> =>
    share === null || questions === null
      ? []
      : [
          { value: percent(share), label: talkLabel },
          { value: questions, label: "questions you asked" },
        ];
  const shift = (from: ReactNode, to: ReactNode) => (
    <>
      {from}
      <ArrowRight size={13} aria-hidden="true" />
      {to}
    </>
  );
  const phases = change
    ? [
        {
          key: "before",
          label: turnMs !== null ? `At first · ${minutes(turnMs)}` : "At first",
          ...beforePhase,
          note: change.before,
          stats: stats(before, askedBefore),
          cta: "Hear how it started",
        },
        {
          key: "switch",
          label:
            turnMs !== null
              ? `The switch · ${formatClock(turnMs)}`
              : "The switch",
          mood: "pivot",
          title: "The moment it changed",
          Face: ArrowRightLeft,
          note: change.change,
          stats:
            before !== null &&
            after !== null &&
            askedBefore !== null &&
            askedAfter !== null
              ? [
                  {
                    value: shift(percent(before), percent(after)),
                    label: prospect ? `${prospect.name}'s talk` : "Their talk",
                  },
                  {
                    value: shift(askedBefore, askedAfter),
                    label: "your questions",
                  },
                ]
              : [],
          cta: "Hear the switch",
        },
        {
          key: "after",
          label:
            turnMs !== null
              ? `After that · ${minutes(durationMs - turnMs)}`
              : "After that",
          ...afterPhase,
          note: change.after,
          stats: stats(after, askedAfter),
          cta: "Hear what happened next",
        },
      ]
    : [];

  return (
    <div className={styles.hook} data-overview-hook>
      <div className={styles.hero}>
        <div className={styles.verdict}>
          <div className={styles.people}>
            {outcomeStyle ? (
              <span className={styles.outcome} data-tone={outcomeStyle.tone}>
                <Emote name={outcomeStyle.emote} size={17} />
                {outcomeStyle.label}
              </span>
            ) : null}
            {seller && prospect ? (
              <span className={styles.duo}>
                {seller.avatar(22)}
                <span>{seller.name}</span>
                <span className={styles.with}>with</span>
                {prospect.avatar(22)}
                <span>{prospect.name}</span>
              </span>
            ) : null}
          </div>
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
              <EntityText text={outcome.text} />
              <PlayChip
                evidence={outcome.evidence[0]}
                onSeek={onSeek}
                label={`Hear it · ${formatClock(outcome.evidence[0]?.start_ms ?? 0)}`}
              />
            </p>
          ) : null}
        </div>

        {change ? (
          <div className={styles.flow}>
            <div className={styles.flowHead}>
              <b>How the call went</b>
              {prospect && before !== null && after !== null ? (
                <span className={styles.delta} data-mood={mood}>
                  {prospect.avatar(18)}
                  {prospect.name} talked <strong>{percent(before)}</strong>{" "}
                  before the switch
                  <ArrowRight size={13} aria-hidden="true" />
                  <strong>{percent(after)}</strong> after
                </span>
              ) : null}
            </div>
            {series.length > 1 && prospect ? (
              <TalkChart
                series={series}
                durationMs={durationMs}
                turnMs={turnMs}
                outcomeMs={outcome?.evidence[0]?.start_ms ?? null}
                mood={mood}
                name={prospect.name}
                onSeek={onSeek}
              />
            ) : (
              <button
                type="button"
                className={styles.askRoles}
                onClick={() => go("signals")}
              >
                Mark who the prospect is to see how much they talked through the
                call
                <ArrowRight size={13} aria-hidden="true" />
              </button>
            )}
            <ol className={styles.phases}>
              {phases.map((phase, index) => (
                <li
                  key={phase.key}
                  data-phase={phase.key}
                  data-feel={phase.key === "switch" ? "pivot" : undefined}
                  style={{ "--i": index } as CSSProperties}
                >
                  <div className={styles.phaseHead}>
                    <span className={styles.face} aria-hidden="true">
                      <phase.Face size={18} />
                    </span>
                    <span>
                      <small>{phase.label}</small>
                      <b>{phase.title}</b>
                    </span>
                  </div>
                  {phase.stats.length ? (
                    <div className={styles.stats}>
                      {phase.stats.map((stat) => (
                        <span key={stat.label} className={styles.stat}>
                          <b>{stat.value}</b>
                          <small>{stat.label}</small>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <p className={styles.phaseText}>
                    <EntityText text={phase.note.text} />
                  </p>
                  {phase.note.evidence[0] ? (
                    <button
                      type="button"
                      className={styles.phaseCta}
                      onClick={() => onSeek(phase.note.evidence[0].start_ms)}
                    >
                      <Play size={13} aria-hidden="true" />
                      {phase.cta}
                      <span>
                        {formatClock(phase.note.evidence[0].start_ms)}
                      </span>
                    </button>
                  ) : null}
                </li>
              ))}
            </ol>
            {change.possible_effect ? (
              <p className={styles.effectRow}>
                <CornerDownRight size={15} aria-hidden="true" />
                <span>
                  <b>What it may have caused</b>{" "}
                  <EntityText text={change.possible_effect} />
                </span>
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      {listen.length ? (
        <Section
          title="Listen to these"
          hint="Tap a card to play that moment of the call"
          index={1}
        >
          <div className={styles.listen}>
            {listen.map((item, index) => {
              const who = speakerOf(item.evidence);
              const length = item.evidence
                ? Math.max(
                    1,
                    Math.round(
                      (item.evidence.end_ms - item.evidence.start_ms) / 1000,
                    ),
                  )
                : null;
              return (
                <button
                  key={`${item.label}-${index}`}
                  type="button"
                  className={styles.clip}
                  data-tone={item.tone}
                  style={{ "--i": index } as CSSProperties}
                  onClick={() =>
                    item.evidence && onSeek(item.evidence.start_ms)
                  }
                  aria-label={`Play: ${item.text}`}
                >
                  <span className={styles.bigPlay} aria-hidden="true">
                    <Play size={18} />
                  </span>
                  <span className={styles.clipBody}>
                    <span className={styles.tag}>
                      <Emote name={item.emote} size={15} />
                      {item.label}
                      <em>{item.hint}</em>
                    </span>
                    <b className={styles.clipTitle}>
                      <EntityText text={item.text} />
                    </b>
                    {item.evidence ? (
                      <span className={styles.who}>
                        {who ? who.avatar(18) : null}
                        <q>{item.evidence.quote}</q>
                      </span>
                    ) : null}
                    {item.evidence ? (
                      <span className={styles.clipMeta}>
                        <span className={styles.mini} aria-hidden="true">
                          <i
                            style={{
                              left: `${(item.evidence.start_ms / Math.max(1, durationMs)) * 100}%`,
                            }}
                          />
                        </span>
                        {formatClock(item.evidence.start_ms)}
                        {length ? ` · ${length} s` : ""}
                      </span>
                    ) : null}
                  </span>
                </button>
              );
            })}
          </div>
        </Section>
      ) : null}

      {missed.length ? (
        <Section
          title="Missed chances"
          hint="What they said, what you said, and a better answer to use"
          index={2}
        >
          <div className={styles.missed}>
            {missed.map((item, index) => {
              const them =
                speakerOf(item.prospect_signal.evidence[0]) ?? prospect;
              const you = speakerOf(item.closer_response.evidence[0]) ?? seller;
              const at = item.prospect_signal.evidence[0]?.start_ms;
              return (
                <article
                  key={index}
                  className={styles.miss}
                  style={{ "--i": index } as CSSProperties}
                >
                  <header>
                    <Flag size={13} aria-hidden="true" />
                    Missed chance
                    {at !== undefined ? ` at ${formatClock(at)}` : ""}
                  </header>
                  <div className={styles.msg} data-side="them">
                    {them ? them.avatar(26) : null}
                    <div className={styles.bubble}>
                      <small>{them?.name ?? "They"} said</small>
                      <q>
                        {item.prospect_signal.evidence[0]?.quote ??
                          item.prospect_signal.text}
                      </q>
                      <PlayChip
                        evidence={item.prospect_signal.evidence[0]}
                        onSeek={onSeek}
                      />
                    </div>
                  </div>
                  <div className={styles.msg} data-side="you">
                    <div className={styles.bubble}>
                      <small>{you?.name ?? "You"} said</small>
                      <q>
                        {item.closer_response.evidence[0]?.quote ??
                          item.closer_response.text}
                      </q>
                      <PlayChip
                        evidence={item.closer_response.evidence[0]}
                        onSeek={onSeek}
                      />
                    </div>
                    {you ? you.avatar(26) : null}
                  </div>
                  <div className={styles.better}>
                    <span className={styles.betterHead}>
                      <Lightbulb size={14} aria-hidden="true" />
                      Better answer
                      <button
                        type="button"
                        className={styles.copy}
                        onClick={() => {
                          void navigator.clipboard
                            ?.writeText(item.follow_up)
                            .then(() => {
                              setCopied(index);
                              window.setTimeout(() => setCopied(null), 1400);
                            });
                        }}
                      >
                        {copied === index ? (
                          <Check size={12} aria-hidden="true" />
                        ) : (
                          <Copy size={12} aria-hidden="true" />
                        )}
                        {copied === index ? "Copied" : "Copy"}
                      </button>
                    </span>
                    <q>
                      <EntityText text={item.follow_up} />
                    </q>
                    {item.potential_impact ? (
                      <small className={styles.why}>
                        Why it matters:{" "}
                        <EntityText text={item.potential_impact} />
                      </small>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        </Section>
      ) : null}

      <div className={styles.split}>
        <Section
          title="Signals from the call"
          hint="Measured from the call's timing and words"
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
                <Emote name="red-question-mark" size={18} className={styles.chipEmote} />
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
                <Emote name="speaking-head" size={18} className={styles.chipEmote} />
                <b>
                  <Count value={signals.overs} />
                </b>{" "}
                times you talked over them
              </button>
              <button type="button" onClick={() => go("signals")}>
                <Emote name="hourglass-not-done" size={18} className={styles.chipEmote} />
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
                <Emote name="handshake" size={18} className={styles.chipEmote} />
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
                <b>
                  <EntityText text={focus.behavior} />
                </b>
                <small>
                  <EntityText text={focus.target} />
                </small>
              </span>
              <ArrowRight size={15} aria-hidden="true" />
            </button>
          </Section>
        ) : null}
      </div>

      <Section title="Explore the call" index={5}>
        <div className={styles.doors}>
          {doors.map(({ id, label, Icon, count, unit }, index) => (
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
