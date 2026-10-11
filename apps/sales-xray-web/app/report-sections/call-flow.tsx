"use client";

import { ChevronDown } from "lucide-react";
import { useMemo } from "react";

import { CALL_FLOW, METRIC_LABELS, changedAt } from "../report-copy";
import type { DocumentReportData } from "../report-document-data";
import { formatClock } from "../lightbox/time";
import type { StoryModel } from "../report-story-model";
import { speechFromTranscript } from "../report-visuals/timeline";
import {
  CallTimeline,
  ChangeSteps,
  InferredTag,
  MetricRow,
  PlayChip,
  Quote,
  SplitBar,
  StoryCard,
  type MetricItem,
} from "../report-visuals/visuals";
import { Gap, Text, speakerOf, type People, type Select } from "./shared";
import styles from "./sections.module.css";

/** "62 : 38" → [62, 38], for the measured split under the figure. */
function pair(value: string): [number, number] | null {
  const match = /^(\d+) : (\d+)$/.exec(value);
  return match ? [Number(match[1]), Number(match[2])] : null;
}

/** 2 How the Call Played Out: numbers, the timeline, and where it turned. */
export function CallFlow({
  model,
  data,
  people,
  onSelect,
}: {
  model: StoryModel;
  data: DocumentReportData;
  people: People;
  onSelect?: Select;
}) {
  const { flow } = model;
  const transcript = data.transcript;
  const seller = people.roles?.seller ?? null;
  const prospect = people.roles?.prospect ?? null;
  const speech = useMemo(
    () => speechFromTranscript(transcript, { top: seller, bottom: prospect }),
    [transcript, seller, prospect],
  );
  const names = speech
    ? {
        top: people.person(speech.topId)?.name ?? "Speaker 1",
        bottom: speech.bottomId
          ? (people.person(speech.bottomId)?.name ?? "Speaker 2")
          : "",
      }
    : null;
  const [first, second] = (
    names?.top && names.bottom ? [names.top, names.bottom] : ["", ""]
  ) as [string, string];

  // 2.1 Call metrics: evidence, not judgement.
  const metrics: MetricItem[] = flow.metrics.map((metric) => {
    const split = pair(metric.value);
    return {
      label: metric.label,
      value: metric.value,
      note: metric.note,
      visual:
        split && first && metric.label !== METRIC_LABELS.questions ? (
          <SplitBar
            parts={[
              { label: first, value: split[0] },
              { label: second, value: split[1] },
            ]}
            unit="%"
            showValues={false}
          />
        ) : undefined,
    };
  });

  const turn = flow.change?.turn.sources[0];
  // Older reports put the quote itself in the switch; show it once.
  const squash = (value: string) =>
    value
      .replace(/[\s\p{P}]+/gu, " ")
      .trim()
      .toLowerCase();
  const quoteRepeats =
    turn && flow.change && squash(turn.quote) === squash(flow.change.turn.text);
  return (
    <div className={styles.stack}>
      {metrics.length ? (
        <StoryCard label={CALL_FLOW.metrics.label}>
          <MetricRow bare items={metrics} label={CALL_FLOW.metrics.label} />
          <p className={styles.note}>{CALL_FLOW.metricsNote}</p>
        </StoryCard>
      ) : null}
      {/* 2.2 Conversation timeline: stages as labelled blocks over the call. */}
      {transcript?.duration_ms ? (
        <StoryCard label={CALL_FLOW.timeline.label}>
          <CallTimeline
            durationMs={transcript.duration_ms}
            speech={speech}
            phases={flow.phases}
            moments={model.topMoments.map((moment) => ({
              key: moment.key,
              kind: moment.kind,
              title: moment.title,
              at_ms: moment.source.start_ms,
              source: moment.source,
            }))}
            change={turn ? { at_ms: turn.start_ms } : null}
            names={names?.bottom ? names : null}
            onSelect={onSelect}
          />
        </StoryCard>
      ) : null}
      {/* 2.3 Key change, then 2.4 before / the switch / after. */}
      {flow.change && turn ? (
        <StoryCard
          label={changedAt(formatClock(turn.start_ms))}
          tone="accent"
          aside={
            <PlayChip
              source={turn}
              title={CALL_FLOW.change.label}
              onSelect={onSelect}
            />
          }
        >
          {quoteRepeats ? null : (
            <Quote
              text={<Text text={turn.quote} />}
              speaker={speakerOf(people, turn)}
            />
          )}
          <ChangeSteps
            before={
              <>
                {flow.change.beforeLabel ? (
                  <strong className={styles.stepName}>
                    {flow.change.beforeLabel}
                  </strong>
                ) : null}
                <Text text={flow.change.before.text} />
              </>
            }
            turn={<Text text={flow.change.turn.text} />}
            after={
              <>
                {flow.change.afterLabel ? (
                  <strong className={styles.stepName}>
                    {flow.change.afterLabel}
                  </strong>
                ) : null}
                <Text text={flow.change.after.text} />
              </>
            }
            turnLabel={CALL_FLOW.switch}
          />
          {flow.change.effect ? (
            <p className={styles.line}>
              <span className={styles.inlineLabel}>{CALL_FLOW.effect}</span>{" "}
              <InferredTag /> <Text text={flow.change.effect} />
            </p>
          ) : null}
        </StoryCard>
      ) : null}
      {/* Naming the speakers: the interactive map, folded away. */}
      <details className={styles.fold}>
        <summary>
          {CALL_FLOW.whoSpokeWhen}
          <ChevronDown
            className={styles.chevron}
            size={14}
            aria-hidden="true"
          />
        </summary>
        <div data-report-map-slot />
      </details>
      <Gap items={model.missing[1]} />
    </div>
  );
}
