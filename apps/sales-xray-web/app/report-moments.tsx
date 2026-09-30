"use client";

import { useMemo, useRef, useState, type CSSProperties } from "react";

import {
  Eye,
  Flag,
  Flame,
  Hand,
  Headphones,
  Lightbulb,
  Search,
  Sparkles,
  ThumbsUp,
  type LucideIcon,
} from "lucide-react";
import { formatClipRange, formatClock } from "./lightbox/time";
import type {
  Finding,
  ReportEvidence,
  SalesReport,
  Transcript,
} from "./report-contract";
import { RichText } from "./report-entities";
import {
  Card,
  Clip,
  Empty,
  Locked,
  Note,
  Script,
  Tag,
  useReportPeople,
  type Tone,
} from "./report-kit";
import {
  buildContextualSourcePlayback,
  type ContextualSourcePlayback,
} from "./source-playback-context";
import styles from "./report-moments.module.css";

type SourceKind =
  | "rewatch"
  | "strengths"
  | "improvements"
  | "missed_opportunities"
  | "objection_analysis"
  | "closing_analysis";

type SuppliedMoment = {
  id: string;
  kind: SourceKind;
  title: string;
  explanation?: string;
  purpose?: "must_watch" | "watch" | "repeat";
  evidence: ReportEvidence;
};

/** Plain-language labels for the supplied rewatch purpose. */
export const rewatchPurposeLabels = {
  must_watch: "Must watch",
  watch: "Worth a watch",
  repeat: "Repeat this",
} as const;

/**
 * One readable clock for a clip. A sub-second span is a single location, so
 * rounding never shows a false interval; seeking keeps the exact milliseconds.
 */
export function formatClipTime({
  start_ms,
  end_ms,
}: Pick<ReportEvidence, "start_ms" | "end_ms">) {
  return formatClipRange(start_ms, end_ms);
}

/** Preserve report order and each finding's provenance, including shared clips. */
function suppliedMoments(report: SalesReport): SuppliedMoment[] {
  if (report.overview) {
    return report.overview.rewatch.flatMap((note, index) =>
      note.evidence.map((evidence, excerpt) => ({
        id: `rewatch:${index}:${excerpt}`,
        kind: "rewatch" as const,
        title: note.text,
        purpose: note.purpose,
        evidence,
      })),
    );
  }
  const collections: [Exclude<SourceKind, "rewatch">, Finding[]][] = [
    ["strengths", report.strengths],
    ["improvements", report.improvements],
    ["missed_opportunities", report.missed_opportunities],
    ["objection_analysis", report.objection_analysis],
    ["closing_analysis", report.closing_analysis],
  ];
  return collections.flatMap(([kind, findings]) =>
    findings.flatMap((finding, index) =>
      finding.evidence.map((evidence, excerpt) => ({
        id: `${kind}:${index}:${excerpt}`,
        kind,
        title: finding.title,
        explanation: finding.explanation,
        evidence,
      })),
    ),
  );
}

/** One distinct replayable interval and every supplied finding that cites it. */
export type ReplayClip = { evidence: ReportEvidence; titles: string[] };

/**
 * The rewatch dataset (or, for older reports, every cited finding), grouped
 * by identical interval and ordered by time. The replay strip shares it.
 */
export function reportReplayClips(report: SalesReport): ReplayClip[] {
  const clips = new Map<string, ReplayClip>();
  for (const { evidence, title } of suppliedMoments(report)) {
    const key = `${evidence.segment_id}:${evidence.start_ms}:${evidence.end_ms}`;
    const clip = clips.get(key);
    if (!clip) clips.set(key, { evidence, titles: [title] });
    else if (!clip.titles.includes(title)) clip.titles.push(title);
  }
  return [...clips.values()].sort(
    (a, b) =>
      a.evidence.start_ms - b.evidence.start_ms ||
      a.evidence.end_ms - b.evidence.end_ms,
  );
}

/** Same dataset as the replay strip; repeated citations keep their contexts. */
export function countReportMoments(report: SalesReport): number {
  return reportReplayClips(report).length;
}

const sameClip = (a: ReportEvidence, b: ReportEvidence) =>
  a.segment_id === b.segment_id &&
  a.start_ms === b.start_ms &&
  a.end_ms === b.end_ms;

// ------------------------------------------------------------------ timeline

type Kind = "good" | "change" | "missed" | "objection" | "closing" | "listen";

const KINDS: Record<
  Kind,
  { label: string; filter: string; tone: Tone; icon: LucideIcon }
> = {
  good: {
    label: "Did well",
    filter: "Did well",
    tone: "strength",
    icon: ThumbsUp,
  },
  change: {
    label: "To change",
    filter: "To change",
    tone: "change",
    icon: Lightbulb,
  },
  missed: {
    label: "Missed chance",
    filter: "Missed",
    tone: "missed",
    icon: Eye,
  },
  objection: {
    label: "Pushback",
    filter: "Pushback",
    tone: "objection",
    icon: Hand,
  },
  closing: {
    label: "Closing",
    filter: "Closing",
    tone: "closing",
    icon: Flag,
  },
  listen: {
    label: "Worth a listen",
    filter: "Listen",
    tone: "info",
    icon: Headphones,
  },
};

const LISTEN_LABEL = {
  must_watch: "Must listen",
  watch: "Worth a listen",
  repeat: "Do this again",
} as const;

export type TimelineMoment = {
  id: string;
  kind: Kind;
  title: string;
  explanation?: string;
  evidence: ReportEvidence[];
  listen?: keyof typeof LISTEN_LABEL;
  golden?: string;
  why?: string;
  tryThis?: string;
  betterAnswer?: string;
  impact?: string;
};

/**
 * Every moment the report points to, one per finding (at its first cited
 * clip), in call order. Rewatch picks join the finding that cites the same
 * clip as a "Must listen" mark; a pick no finding cites stands on its own.
 * Nothing is added that the report did not say.
 */
export function timelineMoments(report: SalesReport): TimelineMoment[] {
  const detail = report.overview;
  const moments: TimelineMoment[] = [];
  const from = (
    kind: Kind,
    findings: Finding[],
    prefix: string,
    extra: (index: number) => Partial<TimelineMoment> = () => ({}),
  ) =>
    findings.forEach((finding, index) => {
      if (!finding.evidence.length) return;
      moments.push({
        id: `${prefix}:${index}`,
        kind,
        title: finding.title,
        explanation: finding.explanation,
        evidence: finding.evidence,
        ...extra(index),
      });
    });
  from("good", report.strengths, "strength", (index) => {
    const golden = detail?.golden_moments.find(
      (g) => g.strength_index === index,
    );
    return {
      golden: golden?.why_effective,
      why: detail?.strength_details.find((d) => d.finding_index === index)
        ?.why_it_matters,
    };
  });
  from("change", report.improvements, "improvement", (index) => {
    const fix = detail?.improvement_details.find(
      (d) => d.finding_index === index,
    );
    return { why: fix?.why_it_matters, tryThis: fix?.replacement_behavior };
  });
  from("missed", report.missed_opportunities, "missed", (index) => {
    const missed = detail?.missed_details.find(
      (d) => d.finding_index === index,
    );
    return {
      betterAnswer: missed?.follow_up,
      impact: missed?.potential_impact,
    };
  });
  from("objection", report.objection_analysis, "objection");
  from("closing", report.closing_analysis, "closing");

  for (const [index, note] of (detail?.rewatch ?? []).entries()) {
    const clip = note.evidence[0];
    if (!clip) continue;
    const owner = moments.find((moment) =>
      moment.evidence.some((item) => sameClip(item, clip)),
    );
    if (owner) owner.listen ??= note.purpose;
    else
      moments.push({
        id: `rewatch:${index}`,
        kind: "listen",
        title: note.text,
        evidence: note.evidence,
        listen: note.purpose,
      });
  }
  return moments.sort(
    (a, b) =>
      a.evidence[0].start_ms - b.evidence[0].start_ms ||
      a.id.localeCompare(b.id),
  );
}

export type ReportMomentsProps = {
  report: SalesReport;
  onSelectEvidence: (evidence: ReportEvidence, title: string) => void;
  onUnlock?: () => void;
  /** Plays a rewatch clip with the lines around it. */
  onSelectContextualPlayback?: (
    playback: ContextualSourcePlayback,
    title: string,
  ) => void;
  callId?: string | null;
  transcript?: Transcript;
};

const EMPTY_TRANSCRIPT: Transcript = {
  source_sha256: "",
  revision: "",
  timebase_id: "1ms",
  duration_ms: 0,
  segments: [],
};

/**
 * The call's key moments as one timeline: a map of the whole call to jump
 * from, filters by kind, and a card per moment with who said it, a play
 * control, and what to do about it.
 */
export function ReportMoments({
  report,
  onSelectEvidence,
  onUnlock,
  onSelectContextualPlayback,
  callId = null,
  transcript = EMPTY_TRANSCRIPT,
}: ReportMomentsProps) {
  const people = useReportPeople(callId, transcript);
  const moments = useMemo(() => timelineMoments(report), [report]);
  const [filter, setFilter] = useState<Kind | "must" | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const list = useRef<HTMLOListElement>(null);
  const duration = Math.max(
    transcript.duration_ms,
    ...moments.flatMap((moment) => moment.evidence.map((e) => e.end_ms)),
    1,
  );
  const kinds = (Object.keys(KINDS) as Kind[]).filter((kind) =>
    moments.some((moment) => moment.kind === kind),
  );
  const mustCount = moments.filter((m) => m.listen === "must_watch").length;
  const shown = moments.filter((moment) =>
    filter === null
      ? true
      : filter === "must"
        ? moment.listen === "must_watch"
        : moment.kind === filter,
  );
  const hidden = (
    [
      "strengths",
      "improvements",
      "missed_opportunities",
      "objection_analysis",
      "closing_analysis",
      "rewatch",
    ] as const
  ).reduce(
    (sum, section) =>
      sum + (report.preview?.sections[section].hidden_count ?? 0),
    0,
  );

  // Only a saved rewatch clip on the same transcript gets surrounding lines.
  const contextFor = (evidence: ReportEvidence) => {
    if (!onSelectContextualPlayback || !transcript.segments.length) return null;
    const playback = buildContextualSourcePlayback(
      report,
      transcript,
      evidence,
    );
    return playback && (playback.context_before || playback.context_after)
      ? { playback, onPlay: onSelectContextualPlayback }
      : null;
  };

  function jump(id: string) {
    setFilter(null);
    setFlash(id);
    window.setTimeout(
      () => setFlash((value) => (value === id ? null : value)),
      1600,
    );
    requestAnimationFrame(() =>
      list.current
        ?.querySelector<HTMLElement>(`[data-moment="${CSS.escape(id)}"]`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" }),
    );
  }

  if (!moments.length)
    return (
      <div className={styles.moments}>
        <Empty icon={Search}>
          This report did not point to any moment in the call.
        </Empty>
        <Locked count={hidden} noun="moments" onUnlock={onUnlock} />
      </div>
    );

  return (
    <div className={styles.moments} aria-label="Key moments">
      <div
        className={styles.map}
        aria-label="Where the moments are in the call"
      >
        <span className={styles.track} aria-hidden="true" />
        {moments.map((moment, index) => (
          <button
            key={moment.id}
            type="button"
            className={styles.pin}
            data-tone={KINDS[moment.kind].tone}
            data-must={moment.listen === "must_watch" ? "" : undefined}
            style={
              {
                "--x": `${(moment.evidence[0].start_ms / duration) * 100}%`,
                "--i": index,
              } as CSSProperties
            }
            onClick={() => jump(moment.id)}
            aria-label={`${KINDS[moment.kind].label} at ${formatClock(moment.evidence[0].start_ms)}: ${moment.title}`}
            title={`${formatClock(moment.evidence[0].start_ms)} · ${moment.title}`}
          />
        ))}
        <span className={styles.mapStart}>00:00</span>
        <span className={styles.mapEnd}>{formatClock(duration)}</span>
      </div>

      <div className={styles.filters} role="group" aria-label="Show moments">
        <button
          type="button"
          aria-pressed={filter === null}
          onClick={() => setFilter(null)}
        >
          All <em>{moments.length}</em>
        </button>
        {mustCount ? (
          <button
            type="button"
            data-tone="info"
            aria-pressed={filter === "must"}
            onClick={() => setFilter(filter === "must" ? null : "must")}
          >
            Must listen <em>{mustCount}</em>
          </button>
        ) : null}
        {kinds.map((kind) => (
          <button
            key={kind}
            type="button"
            data-tone={KINDS[kind].tone}
            aria-pressed={filter === kind}
            onClick={() => setFilter(filter === kind ? null : kind)}
          >
            {KINDS[kind].filter}{" "}
            <em>{moments.filter((m) => m.kind === kind).length}</em>
          </button>
        ))}
      </div>

      <ol ref={list} className={styles.timeline}>
        {shown.map((moment, index) => {
          const kind = KINDS[moment.kind];
          const [first, ...more] = moment.evidence;
          return (
            <li
              key={moment.id}
              data-moment={moment.id}
              data-tone={kind.tone}
              data-flash={flash === moment.id ? "" : undefined}
              className={styles.item}
            >
              <span className={styles.when}>{formatClock(first.start_ms)}</span>
              <span className={styles.node} aria-hidden="true" />
              <Card tone={kind.tone} index={index} className={styles.card}>
                <span className={styles.tags}>
                  <Tag
                    tone={kind.tone}
                    icon={moment.golden ? Sparkles : kind.icon}
                  >
                    {moment.golden ? "Best moment" : kind.label}
                  </Tag>
                  {moment.listen && moment.kind !== "listen" ? (
                    <Tag
                      tone="info"
                      icon={moment.listen === "must_watch" ? Flame : Headphones}
                    >
                      {LISTEN_LABEL[moment.listen]}
                    </Tag>
                  ) : null}
                </span>
                <h4>
                  <RichText text={moment.title} />
                </h4>
                {moment.explanation ? (
                  <p>
                    <RichText text={moment.explanation} />
                  </p>
                ) : null}
                <Clip
                  evidence={first}
                  title={moment.title}
                  onPlay={onSelectEvidence}
                  person={people.speakerOf(first)}
                  context={moment.listen ? contextFor(first) : null}
                />
                {moment.golden ? (
                  <Note label="Why it worked:">
                    <RichText text={moment.golden} />
                  </Note>
                ) : moment.why ? (
                  <Note label="Why it matters:">
                    <RichText text={moment.why} />
                  </Note>
                ) : null}
                {moment.betterAnswer ? (
                  <Script label="A better answer" text={moment.betterAnswer} />
                ) : null}
                {moment.impact ? (
                  <Note label="What it may have cost:">
                    <RichText text={moment.impact} />
                  </Note>
                ) : null}
                {moment.tryThis ? (
                  <Script label="Try this instead" text={moment.tryThis} />
                ) : null}
                {more.length ? (
                  <details className={styles.more}>
                    <summary>
                      {more.length} more {more.length === 1 ? "clip" : "clips"}{" "}
                      for this moment
                    </summary>
                    {more.map((item) => (
                      <Clip
                        key={`${item.segment_id}-${item.start_ms}`}
                        evidence={item}
                        title={moment.title}
                        onPlay={onSelectEvidence}
                        person={people.speakerOf(item)}
                      />
                    ))}
                  </details>
                ) : null}
              </Card>
            </li>
          );
        })}
      </ol>
      <Locked count={hidden} noun="moments" onUnlock={onUnlock} />
    </div>
  );
}
