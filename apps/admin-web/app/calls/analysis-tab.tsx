"use client";

/**
 * The call page's Analysis tab (owner 19 Oct: "the call objects and the real
 * data captured, much, much denser than what the Report and Coaching show"):
 * what the engine found, fact by fact under its category, with confidence,
 * whose word it is, and the moments it heard it (each jumps the player). The
 * whole map, objects and runs are one click away. Moments (the engine's
 * reading of each stretch of talk) follow, judged in psychology terms.
 */
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge, type Tone } from "../ui/kit";
import type { CallDetail, Evidence } from "./call-detail-data";
import { clock } from "./call-data";
import { rupees } from "./call-map-data";
import {
  myAnswers,
  othersOn,
  withSaved,
  type ReviewCall,
} from "./review-verdicts-data";
import { VerdictChips } from "./verdict-chips";
import styles from "./analysis-tab.module.css";

const PERSON = new Set(["person", "confirmed", "edited"]);

const RUN_TONE: Record<string, Tone> = {
  succeeded: "good",
  failed: "bad",
  running: "accent",
  uncertain: "warn",
};

const SENTIMENT_TONE: Record<string, Tone> = {
  positive: "good",
  neutral: "neutral",
  negative: "bad",
};

/** Moments shown before "Show all". */
const FIRST_MOMENTS = 12;

const words = (value: string) => {
  const spaced = value.replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
};

const tokens = (value: number) =>
  value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);

export function AnalysisTab({
  detail,
  recordingId,
  review = null,
  onSeek,
}: {
  detail: CallDetail | null;
  recordingId: string;
  /** Review 2.0 for this call; null when this person isn't a gold reviewer. */
  review?: ReviewCall | null;
  onSeek: (ms: number) => void;
}) {
  const groups = useMemo(() => {
    if (!detail) return [];
    const byCategory = new Map<string, CallDetail["engine"]["facts"]>();
    for (const fact of detail.engine.facts) {
      const list = byCategory.get(fact.category) ?? [];
      list.push(fact);
      byCategory.set(fact.category, list);
    }
    return [...byCategory.entries()].map(([category, facts]) => ({
      category,
      title: detail.engine.categories[category] ?? category,
      facts,
    }));
  }, [detail]);

  const [verdicts, setVerdicts] = useState(review?.verdicts ?? []);
  const [allMoments, setAllMoments] = useState(false);
  const pipeline =
    review?.pipelines.find((item) => item.targets.includes("fact")) ?? null;
  const psychology =
    review?.pipelines.find((item) => item.targets.includes("segment")) ?? null;

  if (!detail)
    return (
      <p className={styles.empty}>
        The call data engine hasn&rsquo;t read this call yet, or its read
        can&rsquo;t be opened right now.{" "}
        <Link href={`/calls/${recordingId}/map`}>Open the analysis map</Link>
      </p>
    );

  const newest = (pipeline: string) =>
    detail.runs.find((run) => run.pipeline === pipeline)?.state ?? null;
  const current = detail.objects.filter((item) => item.state === "current");

  return (
    <div className={styles.tab}>
      <p className={styles.summary}>
        <strong>{rupees(detail.totals.call.costInr) || "₹0.00"}</strong>
        <span>
          {tokens(detail.totals.call.tokensIn)} in ·{" "}
          {tokens(detail.totals.call.tokensOut)} out tokens
        </span>
        {(["fast", "deep"] as const).map((pipeline) => {
          const state = newest(pipeline);
          return state ? (
            <Badge key={pipeline} tone={RUN_TONE[state] ?? "neutral"}>
              {pipeline === "fast" ? "Fast" : "Deep"} {state}
            </Badge>
          ) : null;
        })}
        <span>
          {current.length} current objects · {detail.engine.facts.length} facts
        </span>
        <Link href={`/calls/${recordingId}/map`} className={styles.more}>
          Full map, objects and runs
        </Link>
      </p>
      {groups.length ? (
        groups.map((group) => (
          <section
            key={group.category}
            className={styles.group}
            aria-label={group.title}
          >
            <h3>
              {group.title} <span>{group.facts.length}</span>
            </h3>
            <ul>
              {group.facts.map((fact) => {
                const moments: Evidence[] =
                  detail.evidence[fact.objectId] ?? [];
                return (
                  <li key={fact.objectId}>
                    <span className={styles.label}>{fact.label}</span>
                    <span className={styles.value}>{fact.display || "—"}</span>
                    <span className={styles.meta}>
                      {Math.round(fact.confidence * 100)}%
                      <Badge
                        tone={PERSON.has(fact.basis) ? "accent" : "neutral"}
                      >
                        {PERSON.has(fact.basis)
                          ? `Person · ${fact.basis}`
                          : `AI · ${fact.basis || fact.pipeline}`}
                      </Badge>
                    </span>
                    {moments.length ? (
                      <span className={styles.moments}>
                        {moments.slice(0, 4).map((moment, index) => (
                          <button
                            key={`${moment.startMs}-${index}`}
                            type="button"
                            onClick={() => onSeek(moment.startMs)}
                            title={moment.quote ?? "Play from here"}
                          >
                            ▶ {clock(moment.startMs)}
                          </button>
                        ))}
                      </span>
                    ) : null}
                    {pipeline ? (
                      <VerdictChips
                        recordingId={recordingId}
                        pipeline={pipeline}
                        targetKind="fact"
                        targetRef={fact.objectId}
                        mine={myAnswers(verdicts, fact.objectId)}
                        others={othersOn(verdicts, fact.objectId)}
                        onSaved={(saved) =>
                          setVerdicts((current) => withSaved(current, saved))
                        }
                      />
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      ) : (
        <p className={styles.empty}>No facts yet for this call.</p>
      )}
      {detail.engine.segments.length ? (
        <section className={styles.group} aria-label="Moments">
          <h3>
            Moments <span>{detail.engine.segments.length}</span>
          </h3>
          <ul>
            {(allMoments
              ? detail.engine.segments
              : detail.engine.segments.slice(0, FIRST_MOMENTS)
            ).map((moment, index) => {
              const objectId = detail.momentIds[index] ?? "";
              return (
                <li key={objectId || `${moment.segmentId}-${index}`}>
                  <span className={styles.label}>
                    <span className={styles.moments}>
                      <button
                        type="button"
                        onClick={() => onSeek(moment.startMs)}
                        title="Play from here"
                      >
                        ▶ {clock(moment.startMs)}
                      </button>
                    </span>{" "}
                    {words(moment.speaker)}
                  </span>
                  <span className={styles.value}>
                    {words(moment.intent)} · {words(moment.act)}
                    {moment.topics.length
                      ? ` · ${moment.topics.join(", ")}`
                      : ""}
                  </span>
                  <span className={styles.meta}>
                    {moment.tone ? <Badge>{words(moment.tone)}</Badge> : null}
                    {moment.sentiment ? (
                      <Badge
                        tone={SENTIMENT_TONE[moment.sentiment] ?? "neutral"}
                      >
                        {words(moment.sentiment)}
                      </Badge>
                    ) : null}
                  </span>
                  {psychology && objectId ? (
                    <VerdictChips
                      recordingId={recordingId}
                      pipeline={psychology}
                      targetKind="segment"
                      targetRef={objectId}
                      mine={myAnswers(verdicts, objectId)}
                      others={othersOn(verdicts, objectId)}
                      onSaved={(saved) =>
                        setVerdicts((current) => withSaved(current, saved))
                      }
                    />
                  ) : null}
                </li>
              );
            })}
          </ul>
          {detail.engine.segments.length > FIRST_MOMENTS ? (
            <button
              type="button"
              className={styles.showAll}
              onClick={() => setAllMoments((value) => !value)}
            >
              {allMoments
                ? "Show fewer"
                : `Show all ${detail.engine.segments.length} moments`}
            </button>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
