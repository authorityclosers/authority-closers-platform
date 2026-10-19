"use client";

/**
 * The call page's Analysis tab (owner 19 Oct: "the call objects and the real
 * data captured, much, much denser than what the Report and Coaching show"):
 * what the engine found, fact by fact under its category, with confidence,
 * whose word it is, and the moments it heard it (each jumps the player). The
 * whole map, objects and runs are one click away.
 */
import Link from "next/link";
import { useMemo } from "react";

import { Badge, type Tone } from "../ui/kit";
import type { CallDetail, Evidence } from "./call-detail-data";
import { clock } from "./call-data";
import { rupees } from "./call-map-data";
import styles from "./analysis-tab.module.css";

const PERSON = new Set(["person", "confirmed", "edited"]);

const RUN_TONE: Record<string, Tone> = {
  succeeded: "good",
  failed: "bad",
  running: "accent",
  uncertain: "warn",
};

const tokens = (value: number) =>
  value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);

export function AnalysisTab({
  detail,
  recordingId,
  onSeek,
}: {
  detail: CallDetail | null;
  recordingId: string;
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
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      ) : (
        <p className={styles.empty}>No facts yet for this call.</p>
      )}
    </div>
  );
}
