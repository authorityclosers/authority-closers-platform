"use client";

import {
  ChevronDown,
  CircleCheck,
  CircleMinus,
  Clock3,
  Lightbulb,
  ShieldAlert,
} from "lucide-react";
import { useState } from "react";

import { PlayChip, type Select } from "../report-visuals/visuals";
import { brain4Band, type Brain4Dimension, type Brain4View } from "./brain4";
import { clock } from "./model";
import styles from "./xray.module.css";

const BAND = {
  excellent: { label: "Excellent", tone: styles.green },
  good: { label: "Good", tone: styles.green },
  average: { label: "Average", tone: styles.amber },
  needs_improvement: { label: "Needs Improvement", tone: styles.red },
} as const;

const CATEGORY: Record<string, string> = {
  how_you_talk: "How You Talk",
  understanding_the_buyer: "Understanding the Buyer",
  moving_the_sale_forward: "Moving the Sale Forward",
};

const CONFIDENCE = { high: "High", medium: "Medium", low: "Low" } as const;

const CALL_TYPES: Record<string, string> = {
  inbound: "Inbound call",
  cold: "Cold call",
  scheduled: "Scheduled call",
  follow_up: "Follow-up call",
  referral: "Referral call",
  existing_client: "Existing client",
  re_engagement: "Re-engagement call",
  operational: "Operational call",
};

// The rubric's scale, as every skill's locked scoring table words it.
const LEGEND =
  "5 clearly helped the call · 4 worked, small gaps only · 3 ordinary or mixed · " +
  "2 weak, caused friction · 1 damaging · – not enough to judge";

function span(source: { start_ms: number; end_ms: number }) {
  return source.end_ms > source.start_ms
    ? `${clock(source.start_ms)}–${clock(source.end_ms)}`
    : clock(source.start_ms);
}

function Chip({ dimension }: { dimension: Brain4Dimension }) {
  const band = brain4Band(dimension.rating);
  if (!band)
    return (
      <span
        className={`${styles.status} ${dimension.applicability === "not_applicable" ? styles.blue : styles.purple}`}
      >
        {dimension.applicability === "not_applicable" ? (
          <CircleMinus aria-hidden="true" />
        ) : (
          <Clock3 aria-hidden="true" />
        )}
        {dimension.applicability === "not_applicable"
          ? "Not needed on this call"
          : "Not enough evidence"}
      </span>
    );
  return (
    <span className={`${styles.status} ${BAND[band].tone}`}>
      <CircleCheck aria-hidden="true" />
      {BAND[band].label}
    </span>
  );
}

function Detail({
  dimension,
  onSelect,
}: {
  dimension: Brain4Dimension;
  onSelect?: Select;
}) {
  return (
    <div className={styles.detail}>
      <div className={`${styles.card} ${styles.block}`}>
        <span className={`${styles.disc} ${styles.blue}`}>
          <CircleCheck />
        </span>
        <div className={styles.blockText}>
          <h4 className={styles.blockTitle}>What Happened?</h4>
          <p className={styles.body}>
            {dimension.observed ?? "Not stated in this report."}
          </p>
          {dimension.evidence.length ? (
            <ul className={styles.bullets}>
              {dimension.evidence.map((source) => (
                <li key={source.segment_id}>
                  {span(source)} “{source.quote}”{" "}
                  <PlayChip
                    source={source}
                    title={dimension.label}
                    onSelect={onSelect}
                  />
                </li>
              ))}
            </ul>
          ) : null}
          {dimension.confidence ? (
            <p className={`${styles.body} ${styles.muted}`}>
              Confidence: {CONFIDENCE[dimension.confidence]}
            </p>
          ) : null}
        </div>
      </div>
      {dimension.ethicsGate && dimension.ethicsGate !== "PASS" ? (
        <div className={`${styles.card} ${styles.block}`}>
          <span
            className={`${styles.disc} ${dimension.ethicsGate === "FAIL" ? styles.red : styles.amber}`}
          >
            <ShieldAlert />
          </span>
          <div className={styles.blockText}>
            <h4 className={styles.blockTitle}>
              {dimension.ethicsGate === "FAIL"
                ? "Ethics: a serious problem was seen"
                : "Ethics: a claim needs checking"}
            </h4>
          </div>
        </div>
      ) : null}
      {dimension.coaching ? (
        <div
          className={`${styles.card} ${styles.block} ${styles.improve} ${styles.purple}`}
        >
          <span className={styles.disc}>
            <Lightbulb />
          </span>
          <div className={styles.blockText}>
            <h4 className={`${styles.blockTitle} ${styles.toneTitle}`}>
              On Your Next Call
            </h4>
            <p className={styles.body}>{dimension.coaching}</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The AI coaching score (owner, 22 Oct 2026: "get that out a beta and the new brain live";
 * "the report structure given by dipak to be live only"): the coaching lead's Brain 4.0
 * report for this call, his 18 skills in 3 categories, each with its 1-5 rating, what
 * happened, the timed evidence, confidence and the next-call coaching (the rubric's own
 * analyser output). It is the Report's scoring wherever the call has a Brain 4.0 read.
 * Rated by AI: never called certified or official; the AC-SVAL gold checks continue.
 */
export function Brain4Analysis({
  view,
  onSelect,
}: {
  view: Brain4View;
  onSelect?: Select;
}) {
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = (id: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <section
      className={styles.xr}
      data-xray-part="brain4"
      aria-label="AI coaching score"
    >
      <div className={styles.filters}>
        <strong>AI coaching score · 18 skills</strong>
        {view.callType ? (
          <span className={styles.filter}>
            {CALL_TYPES[view.callType] ?? view.callType}
          </span>
        ) : null}
        {view.categories.map((category) => (
          <span key={category.id} className={styles.filter}>
            {CATEGORY[category.id] ?? category.label}
            <span>
              {category.score !== null
                ? `${category.score.toFixed(1)} / 5`
                : "–"}{" "}
              · {category.rated} of {category.of} rated
            </span>
          </span>
        ))}
      </div>
      <p className={`${styles.coachNote} ${styles.muted}`}>
        {view.rated
          ? `Rated by AI on the coaching lead's Brain 4.0 rubric: ${view.rated} of 18 skills had enough in this call to judge. ${LEGEND}.`
          : "This call was too short, or had too little conversation, to judge the 18 skills. Every skill shows – until a longer call."}
      </p>
      <div className={`${styles.card} ${styles.table}`}>
        <div className={styles.tableHead} aria-hidden="true">
          <span>#</span>
          <span>Skill</span>
          <span>Area</span>
          <span>Status</span>
          <span>Rating</span>
          <span />
        </div>
        <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {view.dimensions.map((dimension) => {
            const isOpen = open.has(dimension.id);
            const band = brain4Band(dimension.rating);
            const tone = band ? BAND[band].tone : styles.neutral;
            return (
              <li
                key={dimension.id}
                className={styles.row}
                data-open={isOpen ? "" : undefined}
                data-brain4={dimension.id}
              >
                <button
                  type="button"
                  className={styles.rowButton}
                  aria-expanded={isOpen}
                  aria-controls={`xray-brain4-${dimension.id}`}
                  aria-label={`${dimension.number}. ${dimension.label}: ${
                    dimension.rating !== null
                      ? `${dimension.rating} out of 5`
                      : "not rated"
                  }. ${isOpen ? "Hide details" : "View more"}`}
                  onClick={() => toggle(dimension.id)}
                >
                  <span className={`${styles.number} ${tone}`}>
                    {dimension.number}
                  </span>
                  <span className={styles.name}>{dimension.label}</span>
                  <span className={styles.evaluates}>
                    {CATEGORY[dimension.category] ?? dimension.category}
                  </span>
                  <Chip dimension={dimension} />
                  {dimension.rating !== null ? (
                    <span className={`${styles.points} ${tone}`}>
                      <strong>{dimension.rating}</strong>
                      <span>/ 5</span>
                    </span>
                  ) : (
                    <span className={styles.noScore}>–</span>
                  )}
                  <ChevronDown className={styles.chevron} aria-hidden="true" />
                </button>
                {isOpen ? (
                  <div id={`xray-brain4-${dimension.id}`}>
                    <Detail dimension={dimension} onSelect={onSelect} />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

/** An analysed call without a Brain 4.0 read yet: new calls get one within minutes. */
export function Brain4Pending() {
  return (
    <section
      className={styles.xr}
      data-xray-part="brain4-pending"
      aria-label="AI coaching score"
    >
      <div className={styles.filters}>
        <strong>AI coaching score · 18 skills</strong>
      </div>
      <p className={`${styles.card} ${styles.empty}`}>
        <Clock3 aria-hidden="true" /> The AI coaching score isn&apos;t ready for
        this call yet. New calls get it within a few minutes of their report;
        until then the earlier analysis is shown below.
      </p>
    </section>
  );
}
