"use client";

import {
  AudioLines,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Filter,
  Handshake,
  MessagesSquare,
  Presentation,
  ShieldCheck,
  Target,
  Users,
} from "lucide-react";
import {
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from "react";

import type {
  ReportDimension,
  ReportEvidence,
  Transcript,
} from "./report-contract";
import { formatClock } from "./lightbox/time";
import { RichText } from "./report-entities";
import { getReportUiCopy } from "./report-ui-copy";
import { Clip, IconBadge, useReportPeople, type Tone } from "./report-kit";
import { useReportDocument } from "./report-reading-context";
import styles from "./sales-skills.module.css";

// Colour identifies a topic, never its performance. Labels and observations
// remain the server's dimensions; any number of skills fits the list.
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
const topicOf = (id: string) =>
  topics[id] ?? { icon: BookOpen, tone: "info" as Tone };

const factorStatus = getReportUiCopy().factorStatus;
const STATUS_ORDER = Object.keys(factorStatus);
const statusOf = (status: string) =>
  factorStatus[status] ? status : "unknown";

type SkillDimension = ReportDimension & { evidence?: ReportEvidence[] };

const EMPTY_TRANSCRIPT: Transcript = {
  source_sha256: "",
  revision: "",
  timebase_id: "1ms",
  duration_ms: 0,
  segments: [],
};

/**
 * Sales skills, one at a time, like a settings window: the list of skills
 * on the left (any number of them), the chosen skill in full on the right,
 * with its note and every clip the call gave for it. A count of what the
 * call showed sits on top; nothing here is a score.
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
  const documentView = useReportDocument();
  const id = useId();
  const list = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState(0);
  const counts = STATUS_ORDER.map((status) => ({
    status,
    count: dimensions.filter((d) => statusOf(d.status) === status).length,
  })).filter((item) => item.count);

  if (!dimensions.length)
    return (
      <p className={styles.empty}>
        No skill observations were supplied for this call.
      </p>
    );

  const current = Math.min(selected, dimensions.length - 1);
  const skill = dimensions[current];
  const topic = topicOf(skill.dimension_id);
  const clips = skill.evidence ?? [];

  function choose(index: number, focus = false) {
    const next = (index + dimensions.length) % dimensions.length;
    setSelected(next);
    if (focus)
      list.current
        ?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
        [next]?.focus();
  }
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const keys: Record<string, number> = {
      ArrowDown: current + 1,
      ArrowRight: current + 1,
      ArrowUp: current - 1,
      ArrowLeft: current - 1,
      Home: 0,
      End: dimensions.length - 1,
    };
    if (!(event.key in keys)) return;
    event.preventDefault();
    choose(keys[event.key], true);
  }

  return (
    <div
      className={styles.skills}
      aria-label="Sales skills"
      data-document={documentView || undefined}
    >
      <header className={styles.summary}>
        <p>
          <small>Draft observations, not scores. Work on one at a time.</small>
        </p>
        <ul className={styles.legend}>
          {counts.map(({ status, count }) => (
            <li key={status} data-status={status}>
              <i aria-hidden="true" />
              {factorStatus[status]} <b>{count}</b>
            </li>
          ))}
        </ul>
      </header>

      <div
        className={styles.window}
        aria-hidden={documentView}
        inert={documentView}
      >
        <div
          ref={list}
          className={styles.list}
          role="tablist"
          aria-orientation="vertical"
          aria-label="Skills"
          onKeyDown={onKeyDown}
        >
          {dimensions.map((dimension, index) => {
            const itemTopic = topicOf(dimension.dimension_id);
            const active = index === current;
            return (
              <button
                key={dimension.dimension_id}
                type="button"
                role="tab"
                id={`${id}-tab-${index}`}
                aria-selected={active}
                aria-controls={`${id}-panel`}
                tabIndex={active ? 0 : -1}
                className={styles.item}
                onClick={() => choose(index)}
              >
                <IconBadge
                  icon={itemTopic.icon}
                  tone={itemTopic.tone}
                  size={26}
                />
                <span className={styles.itemLabel}>{dimension.label}</span>
                <span
                  className={styles.dot}
                  data-status={statusOf(dimension.status)}
                  title={factorStatus[statusOf(dimension.status)]}
                  aria-label={factorStatus[statusOf(dimension.status)]}
                />
              </button>
            );
          })}
        </div>

        <section
          key={skill.dimension_id}
          id={`${id}-panel`}
          role="tabpanel"
          aria-labelledby={`${id}-tab-${current}`}
          className={styles.detail}
        >
          <header className={styles.detailHead}>
            <IconBadge icon={topic.icon} tone={topic.tone} size={46} />
            <div className={styles.detailTitle}>
              <h3>{skill.label}</h3>
              <p
                className={styles.detailStatus}
                data-status={statusOf(skill.status)}
              >
                {factorStatus[statusOf(skill.status)]}
                {clips.length
                  ? ` · ${clips.length} ${clips.length === 1 ? "clip" : "clips"} from the call`
                  : ""}
              </p>
            </div>
            {clips.length && transcript.duration_ms > 0 ? (
              <div className={styles.where}>
                <span>Where in the call</span>
                <div className={styles.whereBar}>
                  {clips.map((evidence) => (
                    <button
                      key={`${evidence.segment_id}-${evidence.start_ms}`}
                      type="button"
                      style={
                        {
                          "--x": `${(evidence.start_ms / transcript.duration_ms) * 100}%`,
                        } as CSSProperties
                      }
                      title={formatClock(evidence.start_ms)}
                      aria-label={`Play clip at ${formatClock(evidence.start_ms)}`}
                      onClick={() => onSelectEvidence?.(evidence)}
                      disabled={!onSelectEvidence}
                    />
                  ))}
                </div>
                <small>
                  <span>00:00</span>
                  <span>{formatClock(transcript.duration_ms)}</span>
                </small>
              </div>
            ) : null}
          </header>
          <p className={styles.observation}>
            <RichText text={skill.observation} />
          </p>
          {clips.length ? (
            <div className={styles.clips}>
              <span className={styles.clipsLabel}>From the call</span>
              {clips.map((evidence) =>
                onSelectEvidence ? (
                  <Clip
                    key={`${evidence.segment_id}-${evidence.start_ms}`}
                    evidence={evidence}
                    title={skill.label}
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
                ),
              )}
            </div>
          ) : (
            <p className={styles.noSource}>
              The call gave no clip for this skill.
            </p>
          )}
          <footer className={styles.pager}>
            <button
              type="button"
              onClick={() => choose(current - 1)}
              aria-label="Previous skill"
            >
              <ChevronLeft size={15} aria-hidden="true" />
              Previous
            </button>
            <span>
              {current + 1} of {dimensions.length}
            </span>
            <button
              type="button"
              onClick={() => choose(current + 1)}
              aria-label="Next skill"
            >
              Next
              <ChevronRight size={15} aria-hidden="true" />
            </button>
          </footer>
        </section>
      </div>

      {/* Document and print show every supplied skill in full. */}
      <div
        className={styles.print}
        aria-hidden={!documentView}
        data-document-skills={documentView || undefined}
      >
        {dimensions.map((dimension) => (
          <section key={dimension.dimension_id}>
            <h4>
              {dimension.label} · {factorStatus[statusOf(dimension.status)]}
            </h4>
            <p>{dimension.observation}</p>
            {(dimension.evidence ?? []).map((evidence) => (
              <blockquote key={`${evidence.segment_id}-${evidence.start_ms}`}>
                {evidence.quote}
              </blockquote>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}
