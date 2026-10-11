"use client";

import { CalendarClock, Flag, Sparkles, TriangleAlert } from "lucide-react";

import { CallOutcomeEditor } from "../report-call-outcome";
import { BIG_PICTURE, followUpOn } from "../report-copy";
import { useCallOutcome } from "../report-outcome-context";
import type { StoryModel } from "../report-story-model";
import { OutcomeBadge, PlayChip, StoryCard } from "../report-visuals/visuals";
import { Gap, LineText, Text, type Select } from "./shared";
import styles from "./sections.module.css";

/** One tap records won, lost, follow-up or no decision for this call. */
function OutcomeControl() {
  const { state, save, reload } = useCallOutcome();
  // A teammate's call: its owner records the outcome; nothing to show here.
  if (state.status === "off" || state.status === "not_owner") return null;
  if (state.status === "loading")
    return <span className={styles.outcomeSkeleton} aria-hidden="true" />;
  if (state.status === "unavailable")
    return (
      <p className={styles.gap} role="status">
        The call outcome couldn&apos;t be read.{" "}
        <button
          type="button"
          className={styles.more}
          onClick={() => void reload().catch(() => {})}
        >
          Try again
        </button>
      </p>
    );
  return (
    <CallOutcomeEditor
      scopeKey={state.key}
      value={state.record.value}
      canEdit={state.record.can_edit}
      onSave={save}
      onReload={reload}
    />
  );
}

/** 1 The Big Picture: one outcome, one summary, one of each, then lower. */
export function BigPicture({
  model,
  onSelect,
}: {
  model: StoryModel;
  onSelect?: Select;
}) {
  const { picture } = model;
  const when = model.deal.nextEvent?.text ?? null;
  const nextRepeatsOutcome =
    picture.nextStep?.text === picture.outcome.detail?.text;
  return (
    <div className={styles.stack}>
      <StoryCard emphasis>
        {/* 1.1 Call outcome: the status, then why in one sentence. */}
        <OutcomeBadge
          status={picture.outcome.status}
          origin={picture.outcome.origin}
          size="lg"
        />
        {picture.outcome.detail && !nextRepeatsOutcome ? (
          <LineText
            line={picture.outcome.detail}
            title={BIG_PICTURE.outcome.label}
            onSelect={onSelect}
          />
        ) : null}
        {/* 1.2 Executive summary: three to five short sentences. */}
        {picture.summary || picture.assessment ? (
          <div className={styles.summary}>
            {picture.summary ? (
              <p>
                <Text text={picture.summary.text} />
              </p>
            ) : null}
            {picture.assessment ? (
              <p>
                <Text text={picture.assessment} />
              </p>
            ) : null}
          </div>
        ) : null}
        {/* Only a person records the outcome (Won / Lost come from here). */}
        <OutcomeControl />
      </StoryCard>
      {picture.influence ? (
        <StoryCard
          label={BIG_PICTURE.influence.label}
          tone="accent"
          icon={Sparkles}
        >
          <LineText
            line={picture.influence}
            title={BIG_PICTURE.influence.label}
            onSelect={onSelect}
          />
        </StoryCard>
      ) : null}
      {picture.strongest || picture.concern ? (
        <div className={styles.pair}>
          {picture.strongest ? (
            <StoryCard
              label={BIG_PICTURE.strongest.label}
              tone="good"
              icon={Flag}
            >
              <LineText
                line={picture.strongest}
                title={BIG_PICTURE.strongest.label}
                onSelect={onSelect}
              />
            </StoryCard>
          ) : null}
          {picture.concern ? (
            <StoryCard
              label={BIG_PICTURE.concern.label}
              tone="warn"
              icon={TriangleAlert}
            >
              <LineText
                line={picture.concern}
                title={BIG_PICTURE.concern.label}
                onSelect={onSelect}
              />
            </StoryCard>
          ) : null}
        </div>
      ) : null}
      {picture.nextStep ? (
        <StoryCard
          label={BIG_PICTURE.nextStep.label}
          tone="accent"
          icon={CalendarClock}
          aside={
            <PlayChip
              source={picture.nextStep.sources.at(-1)}
              title={BIG_PICTURE.nextStep.label}
              onSelect={onSelect}
            />
          }
        >
          <p className={styles.line}>
            <Text text={picture.nextStep.text} />
          </p>
          {when && !picture.nextStep.text.includes(when) ? (
            <p className={styles.strong}>{followUpOn(when)}</p>
          ) : null}
        </StoryCard>
      ) : null}
      <Gap items={model.missing[0]} />
    </div>
  );
}
