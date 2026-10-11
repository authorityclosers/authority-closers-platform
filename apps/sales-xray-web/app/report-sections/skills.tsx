"use client";

import { ArrowRight, ChevronDown } from "lucide-react";
import Link from "next/link";

import { SKILLS } from "../report-copy";
import type { StoryModel } from "../report-story-model";
import { PlayChip, SkillStateMark, StoryCard } from "../report-visuals/visuals";
import { Bullets, Field, Gap, LineText, Text, type Select } from "./shared";
import styles from "./sections.module.css";

/** Deep analysis (spec 5): four groups, each only with what this call has. */
function Deeper({ model, onSelect }: { model: StoryModel; onSelect?: Select }) {
  const { discovery, decision, communication, findings, presentation } =
    model.deeper;
  const groups = [
    discovery.clear.length ||
    discovery.unclear.length ||
    discovery.openingMissed ? (
      <section key="discovery" className={styles.group}>
        <h4>{SKILLS.deeperDiscovery}</h4>
        {discovery.clear.length ? (
          <Field label={SKILLS.becameClear}>
            <Bullets items={discovery.clear} />
          </Field>
        ) : null}
        {discovery.unclear.length ? (
          <Field label={SKILLS.stillUnclear}>
            <Bullets items={discovery.unclear} />
          </Field>
        ) : null}
        {discovery.openingMissed ? (
          <Field label={SKILLS.openingMissed}>
            <LineText
              line={discovery.openingMissed}
              title={SKILLS.openingMissed}
              onSelect={onSelect}
            />
          </Field>
        ) : null}
      </section>
    ) : null,
    presentation ? (
      <section key="presentation" className={styles.group}>
        <h4>{SKILLS.deeperPresentation}</h4>
        {presentation.relevant.length ? (
          <Field label={SKILLS.relevant}>
            <Bullets items={presentation.relevant} />
          </Field>
        ) : null}
        {presentation.lessRelevant ? (
          <Field label={SKILLS.lessRelevant}>
            <p className={styles.line}>
              <Text text={presentation.lessRelevant} />
            </p>
          </Field>
        ) : null}
        {presentation.valueConnection ? (
          <Field label={SKILLS.valueConnection}>
            <p className={styles.line}>{presentation.valueConnection}</p>
          </Field>
        ) : null}
      </section>
    ) : null,
    decision.price ||
    decision.likely.length ||
    decision.likelyStatus?.length ||
    findings.length ? (
      <section key="decision" className={styles.group}>
        <h4>{SKILLS.deeperDecision}</h4>
        {decision.price ? (
          <Field label={SKILLS.price}>
            <LineText
              line={decision.price}
              title={SKILLS.price}
              onSelect={onSelect}
            />
          </Field>
        ) : null}
        {decision.response ? (
          <Field label={SKILLS.prospectResponse}>
            <LineText
              line={decision.response}
              title={SKILLS.prospectResponse}
              onSelect={onSelect}
            />
          </Field>
        ) : null}
        {decision.likelyStatus?.length ? (
          <Field label={SKILLS.likelyStatus}>
            <Bullets items={decision.likelyStatus} />
          </Field>
        ) : null}
        {decision.likely.length ? (
          <Field label={SKILLS.possibleWorries} inferred>
            {decision.likely.map((item, index) => (
              <LineText
                key={index}
                line={item}
                title={SKILLS.possibleWorries}
                onSelect={onSelect}
              />
            ))}
          </Field>
        ) : null}
        {findings.length ? (
          <Field label={SKILLS.objectionsClosing}>
            {findings.map((finding, index) => (
              <p key={index} className={styles.line}>
                <strong>
                  <Text text={finding.title} />
                </strong>{" "}
                <Text text={finding.what.text} />{" "}
                <PlayChip
                  source={finding.what.sources[0]}
                  title={finding.title}
                  onSelect={onSelect}
                />
              </p>
            ))}
          </Field>
        ) : null}
      </section>
    ) : null,
    communication.longest ||
    communication.observation ||
    communication.listening ? (
      <section key="communication" className={styles.group}>
        <h4>{SKILLS.deeperCommunication}</h4>
        {communication.listening ? (
          <Field label={SKILLS.listening}>
            <p className={styles.line}>
              <Text text={communication.listening} />
            </p>
          </Field>
        ) : null}
        {communication.longest ? (
          <Field label={SKILLS.longestMonologue}>
            <p className={styles.line}>{communication.longest}</p>
          </Field>
        ) : null}
        {communication.observation ? (
          <Field label={SKILLS.importantObservation}>
            <LineText
              line={communication.observation}
              title={SKILLS.importantObservation}
              onSelect={onSelect}
            />
          </Field>
        ) : null}
      </section>
    ) : null,
  ].filter(Boolean);
  if (!groups.length) return null;
  return (
    <details className={styles.fold}>
      <summary>
        {SKILLS.deeper}
        <ChevronDown className={styles.chevron} size={14} aria-hidden="true" />
      </summary>
      <div className={styles.groups}>{groups}</div>
    </details>
  );
}

/** 5 Your Skills on This Call: eight rows; open one for its evidence. */
export function Skills({
  model,
  onSelect,
}: {
  model: StoryModel;
  onSelect?: Select;
}) {
  return (
    <div className={styles.stack}>
      <StoryCard>
        <ul className={styles.skills}>
          {model.skills.map((skill) => (
            <li key={skill.id}>
              <details className={styles.skill}>
                <summary>
                  <span className={styles.skillName} title={skill.label}>
                    {skill.short}
                  </span>
                  {skill.state ? (
                    <SkillStateMark state={skill.state} />
                  ) : (
                    <span className={styles.notCovered}>
                      {SKILLS.notCovered}
                    </span>
                  )}
                  <ChevronDown
                    className={styles.chevron}
                    size={14}
                    aria-hidden="true"
                  />
                </summary>
                <div className={styles.skillBody}>
                  <Field label={SKILLS.observation}>
                    <p className={styles.line}>
                      {skill.observation ? (
                        <Text text={skill.observation} />
                      ) : (
                        SKILLS.notCoveredText
                      )}
                    </p>
                  </Field>
                  {skill.sources.length ? (
                    <Field label={SKILLS.evidence}>
                      <p className={styles.plays}>
                        {skill.sources.slice(0, 4).map((source, index) => (
                          <PlayChip
                            key={`${source.segment_id}-${index}`}
                            source={source}
                            title={skill.label}
                            onSelect={onSelect}
                            label="Play"
                          />
                        ))}
                      </p>
                    </Field>
                  ) : null}
                  <Link
                    className={styles.link}
                    href={`/coaching?focus=${skill.id}`}
                  >
                    {SKILLS.toCoaching}
                    <ArrowRight size={13} aria-hidden="true" />
                  </Link>
                </div>
              </details>
            </li>
          ))}
        </ul>
        <Deeper model={model} onSelect={onSelect} />
      </StoryCard>
      <Gap items={model.missing[4]} />
    </div>
  );
}
