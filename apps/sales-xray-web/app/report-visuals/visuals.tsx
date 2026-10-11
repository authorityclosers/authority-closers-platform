"use client";

/*
 * The Report's visual building blocks (Strike A, workbench 11 Oct 2026):
 * calm, premium pieces the six pillars are composed from (Strike B owns the
 * composition). One teal accent, tones only as a small glyph or dot, text
 * 12-15 px with 20/24 px titles and figures, --sx-* / --lx-* tokens only.
 *
 * Figures here are measured facts (talk share, questions, times). There is no
 * quality score anywhere: skills keep the spec's five states as words with a
 * glyph (AGENTS: no autonomous AI scoring before AC-SVAL).
 *
 *   import { PillarHeading, CallTimeline, PlayChip } from "../report-visuals/visuals";
 */
import {
  ArrowDown,
  ArrowRight,
  CalendarCheck,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleDot,
  CircleMinus,
  ChevronDown,
  Handshake,
  IndianRupee,
  MessageCircleWarning,
  Milestone,
  RotateCcw,
  Scale,
  Star,
  TrendingUp,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import { formatClock } from "../lightbox/time";
import { COMMON } from "../report-copy";
import type { ReportEvidence } from "../report-contract";
import {
  ClipPlayIcon,
  ClipPlayState,
  waveformBins,
  type WaveformEnvelope,
} from "../source-waveform";
import { Avatar } from "../ui/kit";
import {
  WAVE_BARS,
  activityBins,
  allocateBars,
  cleanPhases,
  positionIn,
  shares,
  voiceBars,
  type Speech,
  type TimelinePhase,
} from "./timeline";
import styles from "./visuals.module.css";

export type VisualTone =
  | "neutral"
  | "accent"
  | "good"
  | "warn"
  | "bad"
  | "info";

/** Plays (or reports) a piece of evidence; the studio owns the one player. */
export type Select = (evidence: ReportEvidence, title: string) => void;

const cx = (...names: (string | false | null | undefined)[]) =>
  names.filter(Boolean).join(" ");

/* ---------- Pillars ---------- */

/** A pillar's heading: its number, name and one-line promise. */
export function PillarHeading({
  index,
  title,
  subtitle,
  id,
  level = 2,
  aside,
}: {
  index: number;
  title: ReactNode;
  subtitle?: ReactNode;
  id?: string;
  level?: 2 | 3;
  aside?: ReactNode;
}) {
  const Title = level === 2 ? "h2" : "h3";
  return (
    <header className={styles.pillarHead}>
      <span className={styles.pillarIndex} aria-hidden="true">
        {String(index).padStart(2, "0")}
      </span>
      <div className={styles.pillarText}>
        <Title className={styles.pillarTitle} id={id}>
          {title}
        </Title>
        {subtitle ? <p className={styles.pillarSub}>{subtitle}</p> : null}
      </div>
      {aside ? <div className={styles.pillarAside}>{aside}</div> : null}
    </header>
  );
}

/** A small tone dot that never carries meaning alone (the label says it). */
export function ToneDot({ tone = "neutral" }: { tone?: VisualTone }) {
  return <i className={styles.dot} data-tone={tone} aria-hidden="true" />;
}

/**
 * One calm card: a quiet label line (tone as a dot or icon), the content, and
 * an optional action on the label line. `emphasis` lifts the hero card.
 */
export function StoryCard({
  label,
  tone = "neutral",
  icon: Icon,
  aside,
  emphasis,
  children,
  className,
}: {
  label?: ReactNode;
  tone?: VisualTone;
  icon?: LucideIcon;
  aside?: ReactNode;
  emphasis?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cx(styles.card, className)}
      data-tone={tone}
      data-emphasis={emphasis ? "" : undefined}
    >
      {label ? (
        <p className={styles.cardLabel}>
          {Icon ? (
            <Icon
              className={styles.cardIcon}
              size={14}
              strokeWidth={2.2}
              aria-hidden="true"
            />
          ) : (
            <ToneDot tone={tone} />
          )}
          <span className={styles.cardLabelText}>{label}</span>
          {aside ? <span className={styles.cardAside}>{aside}</span> : null}
        </p>
      ) : null}
      {children}
    </div>
  );
}

/* ---------- Evidence ---------- */

/**
 * "▶ 18:42": plays the clip in the report's one player and turns into Pause
 * while that clip plays. Without a player it is the time as plain text.
 */
export function PlayChip({
  source,
  title,
  onSelect,
  label,
  range,
}: {
  source: ReportEvidence | null | undefined;
  title: string;
  onSelect?: Select;
  /** Words before the time, e.g. "Play". */
  label?: string;
  /** Show "06:35–06:58" instead of the start time only. */
  range?: boolean;
}) {
  if (!source) return null;
  const at =
    range && source.end_ms > source.start_ms + 999
      ? `${formatClock(source.start_ms)}–${formatClock(source.end_ms)}`
      : formatClock(source.start_ms);
  if (!onSelect)
    return (
      <span className={styles.time}>
        {label ? `${label} · ` : ""}
        {at}
      </span>
    );
  return (
    <ClipPlayState startMs={source.start_ms} endMs={source.end_ms}>
      {(playing) => (
        <button
          type="button"
          className={styles.play}
          aria-pressed={playing}
          aria-label={`${playing ? "Pause" : "Play"} ${at}: ${title}`}
          onClick={() => onSelect(source, title)}
        >
          <ClipPlayIcon playing={playing} size={9} />
          {label ? `${label} · ` : ""}
          {at}
        </button>
      )}
    </ClipPlayState>
  );
}

/**
 * "Possible": Sales Xray's reading of the call, not something said (the copy
 * module's words, the same on screen, in the Document and in Word).
 */
export function PossibleTag() {
  return (
    <span className={styles.inferred} title={COMMON.possibleHint}>
      {COMMON.possible}
    </span>
  );
}

/** The earlier name, kept for the sections that import it. */
export const InferredTag = PossibleTag;

/**
 * Someone's own words: the quote first, then who said it and when. UI face,
 * no italics (Devanagari), a teal opening mark.
 */
export function Quote({
  text,
  speaker,
  source,
  title,
  onSelect,
  size = "md",
}: {
  text: ReactNode;
  speaker?: { name: string; role?: "you" | "prospect" | null } | null;
  source?: ReportEvidence | null;
  title?: string;
  onSelect?: Select;
  size?: "md" | "lg";
}) {
  return (
    <figure className={styles.quote} data-size={size}>
      <blockquote className={styles.quoteText}>
        <span className={styles.quoteMark} aria-hidden="true">
          “
        </span>
        {text}
        <span aria-hidden="true">”</span>
      </blockquote>
      {speaker || source ? (
        <figcaption className={styles.quoteBy}>
          {speaker ? (
            <>
              <Avatar name={speaker.name} size={18} />
              <span className={styles.quoteName}>{speaker.name}</span>
              {speaker.role ? (
                <span className={styles.quoteRole}>
                  {speaker.role === "you" ? "You" : "Prospect"}
                </span>
              ) : null}
            </>
          ) : null}
          <PlayChip
            source={source}
            title={title ?? (speaker ? `${speaker.name}'s words` : "Quote")}
            onSelect={onSelect}
          />
        </figcaption>
      ) : null}
    </figure>
  );
}

/* ---------- Outcome ---------- */

export const OUTCOME_TONE: Record<string, VisualTone> = {
  Won: "good",
  "Follow-up Set": "good",
  "Meeting Booked": "good",
  "Decision Pending": "warn",
  Deferred: "warn",
  "Still Open": "warn",
  "No Clear Next Step": "bad",
  Lost: "bad",
  Disqualified: "neutral",
};

/**
 * The call's one status, said in words with a quiet glyph; `origin` says who
 * established it (only a person records won or lost).
 */
export function OutcomeBadge({
  status,
  origin,
  size = "md",
}: {
  status: string | null;
  origin?: "person" | "call" | null;
  size?: "md" | "lg";
}) {
  const tone = status ? (OUTCOME_TONE[status] ?? "neutral") : "neutral";
  const Icon =
    tone === "good" ? CircleCheck : tone === "bad" ? CircleAlert : CircleDot;
  return (
    <span className={styles.outcome} data-size={size}>
      <span className={styles.outcomeStatus} data-tone={tone}>
        <Icon size={size === "lg" ? 16 : 14} aria-hidden="true" />
        {status ?? "Outcome not recorded"}
      </span>
      {origin !== undefined ? (
        <span className={styles.outcomeOrigin}>
          {origin === "person"
            ? "Recorded by your team"
            : origin === "call"
              ? "As heard on the call"
              : "Only a person records won or lost"}
        </span>
      ) : null}
    </span>
  );
}

/* ---------- Measured figures ---------- */

export type MetricItem = {
  label: string;
  value: ReactNode;
  /** What the figure counts, e.g. "You : Amit". */
  note?: ReactNode;
  /** A small measured visual under the figure (SplitBar, ShareDial). */
  visual?: ReactNode;
};

/** A compact horizontal row of measured figures; labels wrap, never cut. */
export function MetricRow({
  items,
  label = "Call figures",
}: {
  items: MetricItem[];
  label?: string;
}) {
  if (!items.length) return null;
  return (
    <dl className={styles.metrics} aria-label={label}>
      {items.map((item) => (
        <div key={item.label} className={styles.metric}>
          <dt className={styles.metricLabel}>{item.label}</dt>
          <dd className={styles.metricValue}>{item.value}</dd>
          {item.note ? (
            <dd className={styles.metricNote}>{item.note}</dd>
          ) : null}
          {item.visual ? (
            <dd className={styles.metricVisual}>{item.visual}</dd>
          ) : null}
        </div>
      ))}
    </dl>
  );
}

/**
 * Two measured amounts side by side (talk share, questions): the first
 * person in teal, the second quiet. Shares add up to 100.
 */
export function SplitBar({
  parts,
  unit = "",
  showValues = true,
}: {
  parts: [{ label: string; value: number }, { label: string; value: number }];
  /** "%" shows the shares; "" shows the raw counts. */
  unit?: "%" | "";
  showValues?: boolean;
}) {
  const [first, second] = shares(parts[0].value, parts[1].value);
  const shown = (index: 0 | 1) =>
    unit === "%"
      ? `${index === 0 ? first : second}%`
      : String(parts[index].value);
  const description = `${parts[0].label} ${shown(0)}, ${parts[1].label} ${shown(1)}`;
  return (
    <span className={styles.split} role="img" aria-label={description}>
      {showValues ? (
        <span className={styles.splitLabels} aria-hidden="true">
          <span>
            <ToneDot tone="accent" />
            {parts[0].label} <b>{shown(0)}</b>
          </span>
          <span>
            <b>{shown(1)}</b> {parts[1].label}
            <i className={styles.dot} data-side="other" />
          </span>
        </span>
      ) : null}
      <span className={styles.splitTrack} aria-hidden="true">
        <i style={{ flexGrow: first || 0.0001 }} />
        <i data-side="other" style={{ flexGrow: second || 0.0001 }} />
      </span>
    </span>
  );
}

/** A measured share as a small ring (talk share, questions). Not a score. */
export function ShareDial({
  value,
  total,
  label,
  centre,
  size = 56,
}: {
  value: number;
  total: number;
  /** Read by screen readers, e.g. "You talked 62% of the time". */
  label: string;
  centre?: ReactNode;
  size?: number;
}) {
  const share = total > 0 ? Math.min(1, Math.max(0, value / total)) : 0;
  const radius = 15.5;
  const circumference = 2 * Math.PI * radius;
  return (
    <span
      className={styles.dial}
      role="img"
      aria-label={label}
      style={{ "--size": `${size}px` } as CSSProperties}
    >
      <svg viewBox="0 0 36 36" aria-hidden="true">
        <circle className={styles.dialTrack} cx="18" cy="18" r={radius} />
        <circle
          className={styles.dialArc}
          cx="18"
          cy="18"
          r={radius}
          strokeDasharray={`${share * circumference} ${circumference}`}
        />
      </svg>
      <span className={styles.dialCentre} aria-hidden="true">
        {centre ?? `${Math.round(share * 100)}%`}
      </span>
    </span>
  );
}

/* ---------- Moments ---------- */

export const MOMENT_STYLE: Record<
  string,
  { tone: VisualTone; icon: LucideIcon }
> = {
  "Strong Moment": { tone: "good", icon: Star },
  "Turning Point": { tone: "accent", icon: Milestone },
  "Buying Signal": { tone: "good", icon: TrendingUp },
  "Important Miss": { tone: "warn", icon: CircleDashed },
  Objection: { tone: "warn", icon: MessageCircleWarning },
  "Price Moment": { tone: "info", icon: IndianRupee },
  "Decision Moment": { tone: "accent", icon: Scale },
  "Trust Moment": { tone: "good", icon: Handshake },
  Commitment: { tone: "good", icon: CalendarCheck },
  Risk: { tone: "bad", icon: TriangleAlert },
  "Worth Replaying": { tone: "neutral", icon: RotateCcw },
};

export function momentStyle(kind: string) {
  return MOMENT_STYLE[kind] ?? MOMENT_STYLE["Worth Replaying"];
}

/** "★ Strong Moment · 06:35": what kind of moment, and when. */
export function MomentTag({ kind, atMs }: { kind: string; atMs?: number }) {
  const { tone, icon: Icon } = momentStyle(kind);
  return (
    <span className={styles.momentTag} data-tone={tone}>
      <Icon size={13} strokeWidth={2.2} aria-hidden="true" />
      <span>{kind}</span>
      {atMs !== undefined ? (
        <span className={styles.momentAt}>· {formatClock(atMs)}</span>
      ) : null}
    </span>
  );
}

/* ---------- Skills ---------- */

const SKILL_STATE: Record<string, { tone: VisualTone; icon: LucideIcon }> = {
  "Strongly Demonstrated": { tone: "good", icon: CircleCheck },
  Observed: { tone: "accent", icon: CircleDot },
  "Needs Attention": { tone: "warn", icon: CircleAlert },
  "Not Enough Evidence": { tone: "neutral", icon: CircleDashed },
  "Not Applicable": { tone: "neutral", icon: CircleMinus },
};

/** A skill's state on this call, in the spec's words, with a calm glyph. */
export function SkillStateMark({ state }: { state: string | null }) {
  const known = state ? SKILL_STATE[state] : undefined;
  const { tone, icon: Icon } = known ?? {
    tone: "neutral" as const,
    icon: CircleDashed,
  };
  return (
    <span className={styles.skillState} data-tone={tone}>
      <Icon size={14} strokeWidth={2.2} aria-hidden="true" />
      {state ?? "Not established"}
    </span>
  );
}

/* ---------- The call over time ---------- */

export type TimelineMoment = {
  key: string;
  kind: string;
  title: string;
  at_ms: number;
  source?: ReportEvidence;
};

/**
 * The whole call as one wave, in stages: who talked when (you above the line,
 * the prospect below), the stage blocks with their times, the moments worth
 * replaying as pins, and where the call changed. On a phone the stages stack
 * as rows, each with its own stretch of the wave.
 */
export function CallTimeline({
  durationMs,
  speech,
  envelope,
  phases,
  moments = [],
  change,
  playheadMs,
  names,
  onSelect,
  label = "How the call moved",
}: {
  durationMs: number;
  /** Measured talk of the two people (see speechFromTranscript). */
  speech?: Speech | null;
  /**
   * The server's sound envelope: shapes the speech bars when both exist, and
   * draws the call alone when there is no speech data.
   */
  envelope?: WaveformEnvelope | null;
  phases?: TimelinePhase[] | null;
  moments?: TimelineMoment[];
  change?: { at_ms: number; label?: string } | null;
  playheadMs?: number | null;
  /** Names for the legend: top (the seller) and bottom (the prospect). */
  names?: { top: string; bottom: string } | null;
  onSelect?: Select;
  label?: string;
}) {
  if (!(durationMs > 0)) return null;
  const stages = cleanPhases(phases, durationMs);
  const blocks = stages.length
    ? stages
    : [{ label: "", start_ms: 0, end_ms: durationMs }];
  const bars = allocateBars(
    blocks.map((block) => block.end_ms - block.start_ms),
    WAVE_BARS,
    3,
  );
  const mode = speech?.top.length
    ? "speech"
    : envelope
      ? "level"
      : ("none" as const);
  const summary = stages.length
    ? `${label}: ${stages.length} stages over ${formatClock(durationMs)}`
    : `${label}: ${formatClock(durationMs)}`;
  return (
    <figure
      className={styles.timeline}
      data-mode={mode}
      data-single={stages.length ? undefined : ""}
      aria-label={summary}
    >
      {mode === "speech" && names ? (
        <p className={styles.legend} aria-hidden="true">
          <span>
            <i data-side="top" />
            {names.top}
          </span>
          <span>
            <i data-side="bottom" />
            {names.bottom}
          </span>
          {moments.length ? (
            <span>
              <i data-side="pin" />
              Moments
            </span>
          ) : null}
        </p>
      ) : null}
      <ol className={styles.blocks}>
        {blocks.map((block, index) => {
          const last = index === blocks.length - 1;
          const inside = (atMs: number) =>
            atMs >= block.start_ms && (atMs < block.end_ms || last);
          const count = bars[index] ?? 3;
          const levels = envelope
            ? waveformBins(envelope, block.start_ms, block.end_ms, count)
            : null;
          const { top, bottom } =
            mode === "speech" && speech
              ? voiceBars(
                  activityBins(speech.top, block.start_ms, block.end_ms, count),
                  activityBins(
                    speech.bottom,
                    block.start_ms,
                    block.end_ms,
                    count,
                  ),
                  levels,
                )
              : {
                  top: (levels ?? []).map((level) => level ?? 0),
                  bottom: (levels ?? []).map((level) => level ?? 0),
                };
          const pins = moments.filter((moment) => inside(moment.at_ms));
          const at = (ms: number) =>
            `${positionIn(ms, block.start_ms, block.end_ms) * 100}%`;
          return (
            <li
              key={`${block.label}-${block.start_ms}`}
              className={styles.block}
              data-stage={index % 4}
              style={{ flexGrow: block.end_ms - block.start_ms }}
            >
              {mode !== "none" ? (
                <div className={styles.wave}>
                  <span className={styles.bars} aria-hidden="true">
                    {top.map((level, bar) => (
                      <i
                        key={bar}
                        style={
                          {
                            "--t": lift(level),
                            "--b": lift(bottom[bar] ?? 0),
                          } as CSSProperties
                        }
                      />
                    ))}
                  </span>
                  {change && inside(change.at_ms) ? (
                    <span
                      className={styles.change}
                      data-flip={
                        positionIn(change.at_ms, block.start_ms, block.end_ms) >
                        0.6
                          ? ""
                          : undefined
                      }
                      style={{ left: at(change.at_ms) }}
                    >
                      <span className={styles.changeLabel}>
                        {change.label ?? "Changed here"} ·{" "}
                        {formatClock(change.at_ms)}
                      </span>
                    </span>
                  ) : null}
                  {playheadMs != null && inside(playheadMs) ? (
                    <span
                      className={styles.playhead}
                      style={{ left: at(playheadMs) }}
                      aria-hidden="true"
                    />
                  ) : null}
                  {pins.map((moment) => {
                    const { tone } = momentStyle(moment.kind);
                    const text = `${moment.kind} · ${formatClock(moment.at_ms)}: ${moment.title}`;
                    return onSelect && moment.source ? (
                      <button
                        key={moment.key}
                        type="button"
                        className={styles.pin}
                        data-tone={tone}
                        style={{ left: at(moment.at_ms) }}
                        title={text}
                        aria-label={`Play ${text}`}
                        onClick={() => onSelect(moment.source!, moment.title)}
                      />
                    ) : (
                      <span
                        key={moment.key}
                        className={styles.pin}
                        data-tone={tone}
                        style={{ left: at(moment.at_ms) }}
                        title={text}
                        role="img"
                        aria-label={text}
                      />
                    );
                  })}
                </div>
              ) : null}
              <span className={styles.stageBar} aria-hidden="true" />
              {stages.length ? (
                <span
                  className={styles.stageText}
                  title={`${block.label} · ${formatClock(block.start_ms)}–${formatClock(block.end_ms)}`}
                >
                  <strong>{block.label}</strong>
                  <span>
                    {formatClock(block.start_ms)}
                    <span className={styles.stageEnd}>
                      –{formatClock(block.end_ms)}
                    </span>
                  </span>
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
      <figcaption className={styles.axis} aria-hidden="true">
        <span>00:00</span>
        <span>{formatClock(durationMs)}</span>
      </figcaption>
    </figure>
  );
}

/** Any talk at all reads as a visible bar; silence stays on the line. */
function lift(level: number) {
  return level > 0.01 ? 0.18 + 0.82 * Math.min(1, level) : 0;
}

/* ---------- The switch ---------- */

/** Before → the switch → after, as three short steps. */
export function ChangeSteps({
  before,
  turn,
  after,
  turnLabel = "The switch",
}: {
  before: ReactNode;
  turn: ReactNode;
  after: ReactNode;
  turnLabel?: ReactNode;
}) {
  return (
    <div className={styles.stepsWrap}>
      <ol className={styles.steps}>
        <li>
          <span className={styles.stepLabel}>Before</span>
          <div className={styles.stepText}>{before}</div>
        </li>
        <li className={styles.stepArrow} aria-hidden="true">
          <ArrowRight size={14} className={styles.arrowWide} />
          <ArrowDown size={14} className={styles.arrowNarrow} />
        </li>
        <li data-turn="">
          <span className={styles.stepLabel}>{turnLabel}</span>
          <div className={styles.stepText}>{turn}</div>
        </li>
        <li className={styles.stepArrow} aria-hidden="true">
          <ArrowRight size={14} className={styles.arrowWide} />
          <ArrowDown size={14} className={styles.arrowNarrow} />
        </li>
        <li>
          <span className={styles.stepLabel}>After</span>
          <div className={styles.stepText}>{after}</div>
        </li>
      </ol>
    </div>
  );
}

/* ---------- Where the deal stands ---------- */

const QUALITY: Record<
  "Clear" | "Soft" | "Unclear",
  { filled: number; tone: VisualTone; meaning: string }
> = {
  Clear: {
    filled: 3,
    tone: "good",
    meaning: "A specific action with a specific date or time.",
  },
  Soft: {
    filled: 2,
    tone: "warn",
    meaning: "An action was mentioned, but no firm timing.",
  },
  Unclear: { filled: 1, tone: "bad", meaning: "No reliable next step." },
};

/** How firm the next step is: Clear, Soft or Unclear, with what that means. */
export function CommitmentQuality({
  quality,
  meaning,
}: {
  quality: "Clear" | "Soft" | "Unclear";
  meaning?: ReactNode;
}) {
  const { filled, tone, meaning: fallback } = QUALITY[quality];
  return (
    <span className={styles.quality} data-tone={tone}>
      <span className={styles.qualitySteps} aria-hidden="true">
        {[0, 1, 2].map((step) => (
          <i key={step} data-on={step < filled ? "" : undefined} />
        ))}
      </span>
      <span className={styles.qualityWord}>{quality}</span>
      <span className={styles.qualityMeaning}>{meaning ?? fallback}</span>
    </span>
  );
}

/** The report's last line: the story in five short cells. */
export function SummaryStrip({
  cells,
  label = "Report summary",
}: {
  cells: { label: string; value: ReactNode; tone?: VisualTone }[];
  label?: string;
}) {
  if (cells.length < 2) return null;
  return (
    <dl className={styles.strip} aria-label={label}>
      {cells.map((cell) => (
        <div key={cell.label}>
          <dt>{cell.label}</dt>
          <dd>
            {cell.tone ? <ToneDot tone={cell.tone} /> : null}
            {cell.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/* ---------- Cards the pillars repeat ---------- */

/**
 * One thing that worked or didn't: what happened, the evidence, and why it
 * mattered (spec 3.1 / 3.2), in that order.
 */
export function FindingCard({
  title,
  children,
  play,
  whyLabel,
  why,
  tone = "neutral",
}: {
  title: ReactNode;
  children?: ReactNode;
  play?: ReactNode;
  whyLabel: string;
  why?: ReactNode;
  tone?: VisualTone;
}) {
  return (
    <article className={styles.finding} data-tone={tone}>
      <h4 className={styles.findingTitle}>
        <ToneDot tone={tone} />
        <span>{title}</span>
      </h4>
      {children ? <div className={styles.findingText}>{children}</div> : null}
      {play ? <div className={styles.findingPlay}>{play}</div> : null}
      {why ? (
        <div className={styles.why}>
          <span className={styles.whyLabel}>{whyLabel}</span>
          <div>{why}</div>
        </div>
      ) : null}
    </article>
  );
}

/** A moment worth replaying: its kind and time, a title, the words, why. */
export function MomentCard({
  kind,
  atMs,
  title,
  quote,
  details = [],
  play,
}: {
  kind: string;
  atMs: number;
  title: ReactNode;
  quote?: ReactNode;
  details?: { label: string; text: ReactNode }[];
  play?: ReactNode;
}) {
  return (
    <article className={styles.moment}>
      <div className={styles.momentHead}>
        <MomentTag kind={kind} atMs={atMs} />
        {play ? <span className={styles.momentPlay}>{play}</span> : null}
      </div>
      <h4 className={styles.momentTitle}>{title}</h4>
      {quote}
      {details.map((detail) => (
        <div key={detail.label} className={styles.why}>
          <span className={styles.whyLabel}>{detail.label}</span>
          <div>{detail.text}</div>
        </div>
      ))}
    </article>
  );
}

/**
 * One compact skill row (name and state); opening it shows the observation
 * and evidence (spec "Skill UI Design").
 */
export function SkillRow({
  name,
  title,
  state,
  children,
}: {
  name: ReactNode;
  /** The full name when `name` is shortened. */
  title?: string;
  state: string | null;
  children?: ReactNode;
}) {
  return (
    <details className={styles.skill}>
      <summary>
        <span className={styles.skillName} title={title}>
          {name}
        </span>
        <SkillStateMark state={state} />
        <ChevronDown className={styles.chevron} size={16} aria-hidden="true" />
      </summary>
      {children ? <div className={styles.skillBody}>{children}</div> : null}
    </details>
  );
}

/** Label and value rows (Where the Deal Stands). */
export function FactList({
  items,
}: {
  items: { label: string; extra?: ReactNode; value: ReactNode }[];
}) {
  if (!items.length) return null;
  return (
    <dl className={styles.facts}>
      {items.map((item, index) => (
        <div key={`${item.label}-${index}`}>
          <dt>
            {item.label}
            {item.extra}
          </dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
