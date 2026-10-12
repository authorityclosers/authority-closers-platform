"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  recurringIssue,
  type RecurringIssue,
} from "../coaching/recurring-issue";
import { useWorkspaceAccess } from "../workspace-access";

import { COMMON, DEAL, WORKED_DIDNT } from "../report-copy";
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
      {item.sentence ? null : (
        <p className={styles.line}>
          <Text text={item.what.text} />
        </p>
      )}
      {item.areas?.length ? (
        <Field label={WORKED_DIDNT.areasLead}>
          <Bullets items={item.areas} />
        </Field>
      ) : null}
      <PlayChip
        source={item.what.sources[0]}
        title={item.title}
        onSelect={onSelect}
        label={COMMON.play}
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

/**
 * The one pointer to long-term Coaching the spec allows in a Report: shown
 * only when Coaching says this call's main issue recurs; nothing otherwise.
 */
function Recurring({ callId }: { callId: string | null }) {
  const access = useWorkspaceAccess();
  const context =
    access?.status === "ready" && access.authenticated ? access.context : null;
  const personId = context?.personId;
  const tenantId = context?.tenantId;
  const sessionId = context?.sessionId;
  const [found, setFound] = useState<{
    key: string;
    issue: RecurringIssue | null;
  } | null>(null);
  const key =
    callId && personId && tenantId ? `${callId}:${personId}:${tenantId}` : null;
  useEffect(() => {
    if (!key || !callId || !personId || !tenantId) return;
    const controller = new AbortController();
    void recurringIssue(
      callId,
      { personId, tenantId, sessionId },
      controller.signal,
    ).then((issue) => {
      if (!controller.signal.aborted) setFound({ key, issue });
    });
    return () => controller.abort();
  }, [key, callId, personId, tenantId, sessionId]);
  const issue = found?.key === key ? found.issue : null;
  if (!issue?.recurring) return null;
  return (
    <p className={styles.recurring}>
      {DEAL.recurring}{" "}
      <Link className={styles.link} href={issue.href}>
        {DEAL.viewCoachingShort}
        <ArrowRight size={13} aria-hidden="true" />
      </Link>
    </p>
  );
}

/** 3 What Worked — & What Didn't: at most five and three, by impact. */
export function WorkedDidnt({
  model,
  onSelect,
  preview,
  callId = null,
}: {
  model: StoryModel;
  onSelect?: Select;
  preview?: Preview;
  /** The saved call, so Coaching can say whether its issue recurs. */
  callId?: string | null;
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
          {model.didnt.length && !preview ? (
            <Recurring callId={callId} />
          ) : null}
        </section>
      </div>
      <Gap items={model.missing[2]} />
    </div>
  );
}
