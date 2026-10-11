"use client";

import { WORKED_DIDNT } from "../report-copy";
import type { Item, StoryModel } from "../report-story-model";
import { PlayChip, StoryCard, ToneDot } from "../report-visuals/visuals";
import {
  Bullets,
  Field,
  Gap,
  Locked,
  Text,
  type Preview,
  type Select,
} from "./shared";
import styles from "./sections.module.css";

/** One card: what happened → evidence → why it helped / what it affected. */
function ItemRow({
  item,
  whyLabel,
  onSelect,
}: {
  item: Item;
  whyLabel: string;
  onSelect?: Select;
}) {
  return (
    <li className={styles.item}>
      <p className={styles.itemTitle}>
        <Text text={item.title} />
      </p>
      <p className={styles.line}>
        <Text text={item.what.text} />
      </p>
      {item.areas?.length ? (
        <Field label={WORKED_DIDNT.areasLead}>
          <Bullets items={item.areas} />
        </Field>
      ) : null}
      <PlayChip
        source={item.what.sources[0]}
        title={item.title}
        onSelect={onSelect}
        label="Play"
      />
      {item.why ? (
        <Field label={whyLabel}>
          <p className={styles.line}>
            <Text text={item.why.text} />
          </p>
        </Field>
      ) : null}
    </li>
  );
}

/** 3 What Worked — & What Didn't: at most five and three, by impact. */
export function WorkedDidnt({
  model,
  onSelect,
  preview,
}: {
  model: StoryModel;
  onSelect?: Select;
  preview?: Preview;
}) {
  return (
    <div className={styles.stack}>
      <div className={styles.pair}>
        <section aria-label={WORKED_DIDNT.worked.label}>
          <h3 className={styles.columnHead}>
            <ToneDot tone="good" />
            {WORKED_DIDNT.worked.label}
          </h3>
          <StoryCard>
            {model.worked.length ? (
              <ul className={styles.items}>
                {model.worked.map((item, index) => (
                  <ItemRow
                    key={index}
                    item={item}
                    whyLabel={WORKED_DIDNT.whyHelped}
                    onSelect={onSelect}
                  />
                ))}
              </ul>
            ) : (
              <p className={styles.note}>{WORKED_DIDNT.noneWorked}</p>
            )}
            <Locked
              preview={preview}
              sections={["strengths"]}
              noun={["strength", "strengths"]}
            />
          </StoryCard>
        </section>
        <section aria-label={WORKED_DIDNT.didnt.label}>
          <h3 className={styles.columnHead}>
            <ToneDot tone="warn" />
            {WORKED_DIDNT.didnt.label}
          </h3>
          <StoryCard>
            {model.didnt.length ? (
              <ul className={styles.items}>
                {model.didnt.map((item, index) => (
                  <ItemRow
                    key={index}
                    item={item}
                    whyLabel={WORKED_DIDNT.whatAffected}
                    onSelect={onSelect}
                  />
                ))}
              </ul>
            ) : (
              <p className={styles.note}>{WORKED_DIDNT.noneDidnt}</p>
            )}
            <Locked
              preview={preview}
              sections={["improvements"]}
              noun={["issue", "issues"]}
            />
          </StoryCard>
        </section>
      </div>
      <Gap items={model.missing[2]} />
    </div>
  );
}
