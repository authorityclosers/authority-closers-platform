"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";

import { MOMENTS, viewAllMoments } from "../report-copy";
import type { Moment, StoryModel } from "../report-story-model";
import {
  MomentTag,
  PlayChip,
  Quote,
  StoryCard,
} from "../report-visuals/visuals";
import {
  Field,
  Gap,
  Locked,
  Text,
  speakerOf,
  type People,
  type Preview,
  type Select,
} from "./shared";
import styles from "./sections.module.css";

/** One moment: kind · time, title, their words, why it mattered, Play. */
function MomentRow({
  moment,
  people,
  onSelect,
}: {
  moment: Moment;
  people: People;
  onSelect?: Select;
}) {
  const price = moment.priceStated;
  return (
    <li className={styles.item}>
      <p className={styles.momentHead}>
        <MomentTag kind={moment.kind} atMs={moment.source.start_ms} />
      </p>
      <p className={styles.itemTitle}>
        <Text text={moment.title} />
      </p>
      {price ? (
        <>
          <Field label={MOMENTS.priceStated}>
            <Quote
              text={<Text text={price.text} />}
              speaker={speakerOf(people, price.sources[0])}
            />
          </Field>
          {moment.prospectResponse ? (
            <Field label={MOMENTS.prospectResponse}>
              <Quote
                text={<Text text={moment.prospectResponse.text} />}
                speaker={speakerOf(people, moment.prospectResponse.sources[0])}
              />
            </Field>
          ) : null}
        </>
      ) : (
        <Quote
          text={<Text text={moment.source.quote} />}
          speaker={speakerOf(people, moment.source)}
        />
      )}
      {moment.movedToward ? (
        <Field label={MOMENTS.movedToward}>
          <p className={styles.line}>
            <Text text={moment.movedToward.text} />
          </p>
        </Field>
      ) : null}
      {moment.couldExplore ? (
        <Field label={MOMENTS.whatMissed}>
          <p className={styles.line}>
            {MOMENTS.couldFirst} <Text text={moment.couldExplore} />
          </p>
        </Field>
      ) : null}
      {moment.why ? (
        <Field label={MOMENTS.whyMattered}>
          <p className={styles.line}>
            <Text text={moment.why.text} />
          </p>
        </Field>
      ) : null}
      <PlayChip
        source={
          moment.prospectResponse
            ? {
                ...moment.source,
                end_ms:
                  moment.prospectResponse.sources[0]?.end_ms ??
                  moment.source.end_ms,
              }
            : moment.source
        }
        title={moment.title}
        onSelect={onSelect}
        label="Play"
        range
      />
    </li>
  );
}

/** 4 Moments That Mattered: the top five by importance, then all of them. */
export function Moments({
  model,
  people,
  onSelect,
  preview,
}: {
  model: StoryModel;
  people: People;
  onSelect?: Select;
  preview?: Preview;
}) {
  const [all, setAll] = useState(false);
  const shown = all
    ? [...model.moments].sort((a, b) => a.source.start_ms - b.source.start_ms)
    : model.topMoments;
  return (
    <div className={styles.stack}>
      {shown.length ? (
        <StoryCard>
          <ol className={styles.items}>
            {shown.map((moment) => (
              <MomentRow
                key={moment.key}
                moment={moment}
                people={people}
                onSelect={onSelect}
              />
            ))}
          </ol>
        </StoryCard>
      ) : (
        <p className={styles.note}>{MOMENTS.none}</p>
      )}
      {model.moments.length > model.topMoments.length ? (
        <button
          type="button"
          className={styles.more}
          aria-expanded={all}
          onClick={() => setAll((value) => !value)}
        >
          {all ? MOMENTS.showTop : viewAllMoments(model.moments.length)}
          <ChevronDown
            className={styles.chevron}
            size={14}
            aria-hidden="true"
          />
        </button>
      ) : null}
      <Locked
        preview={preview}
        sections={["golden_moments", "missed_opportunities", "rewatch"]}
        noun={["moment", "moments"]}
      />
      <Gap items={model.missing[3]} />
    </div>
  );
}
