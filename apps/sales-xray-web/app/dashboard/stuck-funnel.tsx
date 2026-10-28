"use client";

/**
 * Where leads get stuck (owner Home v3, 28 Oct 2026: "A's 'where leads get
 * stuck' insight"; the owner's #53 called the plain stage bars "low quality").
 * The open leads by stage right now, as a funnel, with one plain line saying
 * where most of them wait and what to do about it. Each stage opens its leads.
 * Widths use a log scale so a stage of 3 still shows beside one of 162; the
 * counts are the real ones and a true zero stays on the page.
 */

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import type { Performance } from "../leads/leads-client";
import {
  MAIN_PIPELINE,
  readJourney,
  type Kind,
} from "../leads/journey/journey-client";
import { KIND_WORDS } from "../leads/stage-tabs";
import { several, usePipelines } from "../leads/use-pipelines";
import { Segmented } from "../ui/kit";
import { FunnelSkeleton } from "./sales-home-skeleton";
import homeStyles from "./sales-home.module.css";
import styles from "./stuck-funnel.module.css";

export const OPEN_KINDS = [
  "new",
  "not_connected",
  "follow_up",
  "interested",
] as const;
type OpenKind = (typeof OPEN_KINDS)[number];

/** Where most open leads wait, and the one thing to do about it. */
const ADVICE: Record<OpenKind, { where: string; next: string }> = {
  new: { where: "are still untouched", next: "Call the newest first." },
  not_connected: {
    where: "haven't picked up yet",
    next: "Try them again at another time of day.",
  },
  follow_up: {
    where: "are waiting on a follow-up",
    next: "Clear the late ones first.",
  },
  interested: { where: "are interested", next: "Book their next step." },
};

export function stuckInsight(pipeline: Record<string, number>): {
  kind: OpenKind;
  count: number;
  share: string;
  next: string;
} | null {
  const total = OPEN_KINDS.reduce(
    (sum, kind) => sum + (pipeline[kind] ?? 0),
    0,
  );
  if (!total) return null;
  // The fullest stage; a tie goes to the earlier one, the work comes first.
  const kind = OPEN_KINDS.reduce((best, each) =>
    (pipeline[each] ?? 0) > (pipeline[best] ?? 0) ? each : best,
  );
  const count = pipeline[kind] ?? 0;
  return {
    kind,
    count,
    share: `${Math.round((count / total) * 100)}% of open leads ${ADVICE[kind].where}.`,
    next: ADVICE[kind].next,
  };
}

/**
 * A pipeline's own name for each kind of stage, where it has one stage of that
 * kind (Redmi, 22 Oct 2026: Home read "New / Not contacted" while Leads read
 * "New enquiry / Not connected").
 */
function useStageNames(pipeline: string): Partial<Record<Kind, string>> {
  const [names, setNames] = useState<{
    key: string;
    value: Partial<Record<Kind, string>>;
  } | null>(null);
  useEffect(() => {
    let live = true;
    readJourney(pipeline).then(
      (view) => {
        if (!live) return;
        const found: Partial<Record<Kind, string>> = {};
        for (const kind of OPEN_KINDS) {
          const own = view.stages.filter(
            (stage) => !stage.archived && stage.kind === kind,
          );
          if (own.length === 1) found[kind] = own[0].label;
        }
        setNames({ key: pipeline, value: found });
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [pipeline]);
  return names?.key === pipeline ? names.value : {};
}

/** The stage's share of the widest, on a log scale: 162, 3 and 1 all read. */
const logWidth = (count: number, most: number) =>
  count ? Math.max(8, (Math.log1p(count) / Math.log1p(most)) * 100) : 0;

function Stages({
  pipeline,
  inPipeline,
}: {
  pipeline: Record<string, number>;
  inPipeline: string | null;
}) {
  const names = useStageNames(inPipeline ?? MAIN_PIPELINE);
  const where = inPipeline ? `&pipeline=${encodeURIComponent(inPipeline)}` : "";
  const most = Math.max(1, ...OPEN_KINDS.map((kind) => pipeline[kind] ?? 0));
  const total = OPEN_KINDS.reduce(
    (sum, kind) => sum + (pipeline[kind] ?? 0),
    0,
  );
  const insight = stuckInsight(pipeline);
  const word = (kind: OpenKind) => names[kind] ?? KIND_WORDS[kind];
  return (
    <div className={styles.card}>
      <p
        className={styles.kicker}
      >{`${total} open ${total === 1 ? "lead" : "leads"} · right now`}</p>
      {insight ? (
        <p className={styles.insight}>
          <strong>{insight.share}</strong>
          <span>{insight.next}</span>
        </p>
      ) : (
        <p className={styles.insight}>
          <span>No open leads right now.</span>
        </p>
      )}
      <ul className={styles.stages}>
        {OPEN_KINDS.map((kind) => {
          const count = pipeline[kind] ?? 0;
          return (
            <li key={kind} data-kind={kind}>
              <Link href={`/leads?tab=all&stage=${kind}${where}`}>
                <span className={styles.stageHead}>
                  <span>{word(kind)}</span>
                  <strong>{count}</strong>
                </span>
                <span className={styles.track} aria-hidden="true">
                  <span
                    className={styles.bar}
                    data-zero={count === 0 || undefined}
                    data-top={insight?.kind === kind || undefined}
                    style={
                      count ? { width: `${logWidth(count, most)}%` } : undefined
                    }
                  />
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
      {insight ? (
        <Link
          className={styles.action}
          href={`/leads?tab=all&stage=${insight.kind}${where}`}
        >
          {`Open ${insight.count} ${word(insight.kind).toLowerCase()} ${insight.count === 1 ? "lead" : "leads"}`}
          <ChevronRight size={16} aria-hidden="true" />
        </Link>
      ) : null}
      <p className={styles.footnote}>
        Tap a stage to open its leads. Widths use a log scale.
      </p>
    </div>
  );
}

/** The open leads by stage, from the period's report (the same "right now" for any period). */
export function StuckFunnel({
  performance,
}: {
  performance: Performance | null;
}) {
  // Several pipelines: one at a time, in its own stages.
  const pipes = usePipelines();
  const [picked, setPicked] = useState<string | null>(null);
  const inPipeline = several(pipes)
    ? (
        pipes.pipelines.find((item) => item.key === picked) ??
        pipes.pipelines[0]
      ).key
    : null;
  const open = performance
    ? inPipeline
      ? (performance.pipelines?.[inPipeline] ?? {})
      : performance.pipeline
    : null;
  return (
    <section className={homeStyles.block} aria-labelledby="pipeline-title">
      <div className={homeStyles.head}>
        <h2 id="pipeline-title">Where leads get stuck</h2>
      </div>
      {several(pipes) && inPipeline ? (
        <Segmented
          label="Pipeline"
          value={inPipeline}
          onChange={setPicked}
          items={pipes.pipelines.map((item) => ({
            key: item.key,
            label: item.name,
          }))}
        />
      ) : null}
      {open ? (
        <Stages pipeline={open} inPipeline={inPipeline} />
      ) : (
        <FunnelSkeleton />
      )}
    </section>
  );
}
