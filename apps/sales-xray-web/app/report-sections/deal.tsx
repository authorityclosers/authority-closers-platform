"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { formatClock } from "../lightbox/time";
import {
  COMMITMENT_MEANING,
  DEAL,
  END_SUMMARY,
  prospectAgreed,
} from "../report-copy";
import type { StoryModel } from "../report-story-model";
import {
  CommitmentQuality,
  OutcomeBadge,
  StoryCard,
  SummaryStrip,
} from "../report-visuals/visuals";
import {
  Bullets,
  Field,
  Gap,
  LineText,
  Text,
  type People,
  type Select,
} from "./shared";
import styles from "./sections.module.css";

/** Optional end strip (spec): the whole story in five short cells. */
function EndSummary({ model }: { model: StoryModel }) {
  const { end } = model;
  const cells = [
    { label: END_SUMMARY.outcome, value: model.picture.outcome.status },
    { label: END_SUMMARY.strongest, value: end.strongest },
    { label: END_SUMMARY.issue, value: end.issue },
    {
      label: END_SUMMARY.moment,
      value: end.moment
        ? `${end.moment.title} · ${formatClock(end.moment.source.start_ms)}`
        : null,
    },
    {
      label: END_SUMMARY.nextEvent,
      value:
        end.nextEvent ??
        (model.picture.nextStep ? END_SUMMARY.agreedNoDate : null),
    },
  ].filter((cell): cell is { label: string; value: string } =>
    Boolean(cell.value),
  );
  return <SummaryStrip cells={cells} label={END_SUMMARY.title} />;
}

/** 6 Where the Deal Stands: 6.1 to 6.9 in order, then the two ways on. */
export function DealStands({
  model,
  people,
  onSelect,
  prospectControls,
  onOpenCoaching,
}: {
  model: StoryModel;
  people: People;
  onSelect?: Select;
  prospectControls?: ReactNode;
  onOpenCoaching?: () => void;
}) {
  const { deal } = model;
  const prospectName = people.prospect?.name.split(" ")[0] ?? null;
  return (
    <div className={styles.stack}>
      <StoryCard>
        <div className={styles.facts}>
          <Field label={DEAL.status.label}>
            <OutcomeBadge
              status={deal.outcome.status}
              origin={deal.outcome.origin}
            />
          </Field>
          {deal.position ? (
            <Field label={DEAL.position.label}>
              <LineText
                line={deal.position}
                title={DEAL.position.label}
                onSelect={onSelect}
              />
            </Field>
          ) : null}
          {deal.blocker ? (
            <Field label={DEAL.blocker.label} inferred={deal.blocker.inferred}>
              <LineText
                line={deal.blocker}
                title={DEAL.blocker.label}
                onSelect={onSelect}
              />
            </Field>
          ) : null}
          {deal.prospectCommitments.length ? (
            <Field label={prospectAgreed(prospectName)}>
              {deal.prospectCommitments.map((item, index) => (
                <LineText
                  key={index}
                  line={item}
                  title={DEAL.prospectCommitment.label}
                  onSelect={onSelect}
                />
              ))}
            </Field>
          ) : null}
          {deal.sellerCommitments.length ? (
            <Field label={DEAL.sellerCommitment.label}>
              {deal.sellerCommitments.map((item, index) => (
                <LineText
                  key={index}
                  line={item}
                  title={DEAL.sellerCommitment.label}
                  onSelect={onSelect}
                />
              ))}
            </Field>
          ) : null}
          {deal.nextEvent ? (
            <Field label={DEAL.nextEvent.label}>
              <LineText
                line={deal.nextEvent}
                title={DEAL.nextEvent.label}
                onSelect={onSelect}
                last
              />
            </Field>
          ) : null}
          {deal.quality ? (
            <Field label={DEAL.quality.label}>
              <CommitmentQuality
                quality={deal.quality}
                meaning={COMMITMENT_MEANING[deal.quality]}
              />
            </Field>
          ) : null}
          {deal.unclear.length ? (
            <Field label={DEAL.unclear.label}>
              <Bullets items={deal.unclear} />
            </Field>
          ) : null}
          {deal.action ? (
            <Field label={DEAL.action.label}>
              <p className={styles.line}>
                <Text text={deal.action} />
              </p>
            </Field>
          ) : null}
        </div>
      </StoryCard>
      {deal.coachingMission ? (
        <p className={styles.mission}>
          <span className={styles.inlineLabel}>{DEAL.coachingMission}</span>{" "}
          <Text text={deal.coachingMission} />
        </p>
      ) : null}
      <Gap items={model.missing[5]} />
      <EndSummary model={model} />
      {prospectControls ? (
        <section
          className={styles.prospectLink}
          aria-label={DEAL.prospectSection}
        >
          <h3 className={styles.columnHead}>{DEAL.prospectSection}</h3>
          {prospectControls}
        </section>
      ) : null}
      <div className={styles.ctas}>
        <Link className={styles.cta} href="/prospects">
          {DEAL.viewProspect}
          <ArrowRight size={14} aria-hidden="true" />
        </Link>
        {onOpenCoaching ? (
          <button type="button" className={styles.cta} onClick={onOpenCoaching}>
            {DEAL.viewCoaching}
            <ArrowRight size={14} aria-hidden="true" />
          </button>
        ) : (
          <Link className={styles.cta} href="/coaching">
            {DEAL.viewCoaching}
            <ArrowRight size={14} aria-hidden="true" />
          </Link>
        )}
      </div>
    </div>
  );
}
