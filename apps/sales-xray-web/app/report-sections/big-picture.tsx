"use client";

import { CalendarClock, Flag, Sparkles, TriangleAlert } from "lucide-react";

import { BIG_PICTURE, followUpOn } from "../report-copy";
import type { StoryModel } from "../report-story-model";
import { OutcomeBadge, PlayChip, StoryCard } from "../report-visuals/visuals";
import { Gap, LineText, Text, type Select } from "./shared";
import styles from "./sections.module.css";

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
