"use client";

import {
  AudioLines,
  BookOpen,
  Filter,
  Handshake,
  MessagesSquare,
  Presentation,
  ShieldCheck,
  Target,
  Users,
} from "lucide-react";
import { useState, type CSSProperties } from "react";

import type {
  ReportDimension,
  ReportEvidence,
  Transcript,
} from "./report-contract";
import { RichText } from "./report-entities";
import { Clip, IconBadge, useReportPeople, type Tone } from "./report-kit";
import styles from "./sales-skills.module.css";

// Colour identifies a topic, never its performance. Labels and observations
// remain the server's eight dimensions.
const topics: Record<string, { icon: typeof Users; tone: Tone }> = {
  human_connection_trust: { icon: Users, tone: "info" },
  discovery_deep_understanding: { icon: MessagesSquare, tone: "teal" },
  qualification: { icon: Filter, tone: "missed" },
  problem_impact_desire: { icon: Target, tone: "change" },
  solution_relevance_presentation: { icon: Presentation, tone: "objection" },
  certainty_objection_intelligence: { icon: ShieldCheck, tone: "closing" },
  closing_decision_management: { icon: Handshake, tone: "change" },
  communication_tonality: { icon: AudioLines, tone: "missed" },
};

// Plain words for how much the call showed: evidence, never a grade.
const STATUS: Record<string, string> = {
  observed: "Seen in this call",
  conflicted: "Mixed signs",
  insufficient_evidence: "Not enough to tell",
  not_applicable: "Doesn’t apply here",
  unknown: "Not checked",
};
const STATUS_ORDER = Object.keys(STATUS);

type SkillDimension = ReportDimension & { evidence?: ReportEvidence[] };

const EMPTY_TRANSCRIPT: Transcript = {
  source_sha256: "",
  revision: "",
  timebase_id: "1ms",
  duration_ms: 0,
  segments: [],
};

/** Text that folds to three lines; tap to read it all. */
function Folded({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 220;
  return (
    <p
      className={styles.observation}
      data-folded={long && !open ? "" : undefined}
      role={long ? "button" : undefined}
      tabIndex={long ? 0 : undefined}
      aria-expanded={long ? open : undefined}
      onClick={long ? () => setOpen((value) => !value) : undefined}
      onKeyDown={
        long
          ? (event) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              setOpen((value) => !value);
            }
          : undefined
      }
    >
      <RichText text={text} />
    </p>
  );
}

/**
 * The eight sales skills as one calm grid: how many the call showed (a
 * count, not a score), then each skill's note and one clip from the call.
 */
export function SalesSkills({
  dimensions,
  onSelectEvidence,
  callId = null,
  transcript = EMPTY_TRANSCRIPT,
}: {
  dimensions: SkillDimension[];
  onSelectEvidence?: (evidence: ReportEvidence) => void;
  callId?: string | null;
  transcript?: Transcript;
}) {
  const people = useReportPeople(callId, transcript);
  const [openMore, setOpenMore] = useState<Set<string>>(new Set());
  const statusOf = (status: string) => (STATUS[status] ? status : "unknown");
  const counts = STATUS_ORDER.map((status) => ({
    status,
    count: dimensions.filter((d) => statusOf(d.status) === status).length,
  })).filter((item) => item.count);
  const seen = dimensions.filter((d) => d.status === "observed").length;

  if (!dimensions.length)
    return (
      <p className={styles.empty}>
        No skill observations were supplied for this call.
      </p>
    );

  return (
    <div className={styles.skills} aria-label="Sales skills">
      <header className={styles.summary}>
        <div className={styles.lead}>
          <p>
            <b>{seen}</b> of {dimensions.length} skills were seen in this call
          </p>
          <small>
            Draft observations, not scores. Work on one skill at a time.
          </small>
        </div>
        <div className={styles.meter}>
          <div
            className={styles.bar}
            role="img"
            aria-label={counts
              .map(
                ({ status, count }) =>
                  `${count} ${STATUS[status].toLowerCase()}`,
              )
              .join(", ")}
          >
            {counts.map(({ status, count }) => (
              <span
                key={status}
                data-status={status}
                style={
                  { "--share": count / dimensions.length } as CSSProperties
                }
              />
            ))}
          </div>
          <ul className={styles.legend}>
            {counts.map(({ status, count }) => (
              <li key={status} data-status={status}>
                <i aria-hidden="true" />
                {STATUS[status]} <b>{count}</b>
              </li>
            ))}
          </ul>
        </div>
      </header>

      <div className={styles.grid}>
        {dimensions.map((dimension, index) => {
          const topic = topics[dimension.dimension_id] ?? {
            icon: BookOpen,
            tone: "info" as Tone,
          };
          const [first, ...more] = dimension.evidence ?? [];
          const showMore = openMore.has(dimension.dimension_id);
          const clip = (evidence: ReportEvidence) =>
            onSelectEvidence ? (
              <Clip
                key={`${evidence.segment_id}-${evidence.start_ms}`}
                evidence={evidence}
                title={dimension.label}
                onPlay={(item) => onSelectEvidence(item)}
                person={people.speakerOf(evidence)}
              />
            ) : (
              <blockquote
                key={`${evidence.segment_id}-${evidence.start_ms}`}
                className={styles.quote}
              >
                <RichText text={evidence.quote} />
              </blockquote>
            );
          return (
            <article
              key={dimension.dimension_id}
              className={styles.card}
              style={{ "--i": index } as CSSProperties}
            >
              <header className={styles.cardHead}>
                <IconBadge icon={topic.icon} tone={topic.tone} size={28} />
                <h3>{dimension.label}</h3>
                <span
                  className={styles.status}
                  data-status={statusOf(dimension.status)}
                >
                  {STATUS[statusOf(dimension.status)]}
                </span>
              </header>
              <Folded text={dimension.observation} />
              {first ? clip(first) : null}
              {showMore ? more.map(clip) : null}
              {more.length ? (
                <button
                  type="button"
                  className={styles.moreButton}
                  aria-expanded={showMore}
                  onClick={() =>
                    setOpenMore((current) => {
                      const next = new Set(current);
                      if (next.has(dimension.dimension_id))
                        next.delete(dimension.dimension_id);
                      else next.add(dimension.dimension_id);
                      return next;
                    })
                  }
                >
                  {showMore
                    ? "Show fewer clips"
                    : `${more.length} more ${more.length === 1 ? "clip" : "clips"}`}
                </button>
              ) : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}
