"use client";

import { useEffect, useState } from "react";

import { displayName } from "../display-name";
import { Segmented } from "../ui/kit";
import { readJourney, type StageView } from "./journey/journey-client";
import { stageName } from "./journey/stage-look";
import type { RepView } from "./leads-client";
import {
  countsFor,
  startStages,
  type Recipients,
  type UploadChoices,
} from "./bulk-upload";
import styles from "./upload-choices.module.css";

const RECIPIENTS: { key: Recipients; label: string }[] = [
  { key: "people", label: "Salespeople I pick" },
  { key: "rules", label: "The lead rules" },
  { key: "me", label: "Me" },
  { key: "none", label: "Nobody yet" },
];

/**
 * Bulk upload's choices (stages-views-sources.md section 5): where the new leads go, who
 * receives them and how many each (owners and admins), and the stage they start in.
 */
export function UploadChoicesFields({
  canManage,
  team,
  fresh,
  pipeline,
  value,
  onChange,
}: {
  canManage: boolean;
  /** The team, for owners and admins; null while it is read. */
  team: RepView[] | null;
  /** About how many rows become new leads. */
  fresh: number;
  pipeline: string;
  value: UploadChoices;
  onChange: (next: UploadChoices) => void;
}) {
  const [stages, setStages] = useState<StageView[] | null>(null);
  useEffect(() => {
    let live = true;
    readJourney(pipeline || undefined).then(
      (next) => {
        if (live) setStages(next.stages);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [pipeline]);

  const starts = stages ? startStages(stages) : [];
  const counts = team ? countsFor(value, team, fresh) : {};
  const given = Object.values(counts).reduce((sum, count) => sum + count, 0);
  const left = fresh - given;

  return (
    <div className={styles.choices}>
      <div className={styles.choice}>
        <span className={styles.label} aria-hidden="true">
          Where should these leads go?
        </span>
        <Segmented
          label="Where should these leads go?"
          value={value.side}
          onChange={(side) => onChange({ ...value, side })}
          items={[
            { key: "cold", label: "Cold Leads" },
            { key: "live", label: "Inbound Leads" },
          ]}
        />
        <small className={styles.help}>
          {value.side === "cold"
            ? "For bulk cold databases."
            : "Only for records that came from real enquiries."}
        </small>
      </div>

      {canManage ? (
        <div className={styles.choice}>
          <span className={styles.label} aria-hidden="true">
            Who should receive them?
          </span>
          <div
            className={styles.chips}
            role="group"
            aria-label="Who should receive them?"
          >
            {RECIPIENTS.map((item) => (
              <button
                key={item.key}
                type="button"
                className={styles.chip}
                aria-pressed={value.assign === item.key}
                onClick={() => onChange({ ...value, assign: item.key })}
              >
                {item.label}
              </button>
            ))}
          </div>
          {value.assign === "people" ? (
            team === null ? (
              <small className={styles.help}>Reading your team…</small>
            ) : team.length === 0 ? (
              <small className={styles.help}>
                Nobody on your team takes leads yet.
              </small>
            ) : (
              <>
                <ul className={styles.people} aria-label="Salespeople">
                  {team.map((rep) => {
                    const on = !value.off.includes(rep.person_id);
                    const name = displayName(rep.name);
                    return (
                      <li key={rep.person_id} className={styles.person}>
                        <label className={styles.personName}>
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={(event) =>
                              onChange({
                                ...value,
                                // Turning someone on or off splits evenly again.
                                counts: null,
                                off: event.target.checked
                                  ? value.off.filter(
                                      (id) => id !== rep.person_id,
                                    )
                                  : [...value.off, rep.person_id],
                              })
                            }
                          />
                          <span>{name}</span>
                        </label>
                        <input
                          className={styles.count}
                          type="number"
                          inputMode="numeric"
                          min={0}
                          max={fresh}
                          aria-label={`New leads for ${name}`}
                          disabled={!on}
                          value={on ? (counts[rep.person_id] ?? 0) : ""}
                          onChange={(event) =>
                            onChange({
                              ...value,
                              counts: {
                                ...counts,
                                [rep.person_id]: Math.max(
                                  0,
                                  Math.floor(Number(event.target.value) || 0),
                                ),
                              },
                            })
                          }
                        />
                      </li>
                    );
                  })}
                </ul>
                <small
                  className={left < 0 ? styles.problem : styles.help}
                  role={left < 0 ? "alert" : undefined}
                >
                  {left < 0
                    ? `That's ${-left} more than the ${fresh} new leads.`
                    : left > 0
                      ? `${left} stay unassigned.`
                      : "Every new lead has a salesperson."}
                </small>
              </>
            )
          ) : null}
        </div>
      ) : (
        <small className={styles.help}>They go on your desk.</small>
      )}

      {starts.length > 1 ? (
        <div className={styles.choice}>
          <span className={styles.label} aria-hidden="true">
            Starting stage
          </span>
          <div
            className={styles.chips}
            role="group"
            aria-label="Starting stage"
          >
            {starts.map((stage, index) => {
              const key = index === 0 ? "" : stage.key;
              return (
                <button
                  key={stage.key}
                  type="button"
                  className={styles.chip}
                  aria-pressed={value.step === key}
                  onClick={() => onChange({ ...value, step: key })}
                >
                  {stageName(stage, value.side === "cold" ? "cold" : "inbound")}
                </button>
              );
            })}
          </div>
          <small className={styles.help}>
            Open Leads or Interested only when the file has real past talks.
          </small>
        </div>
      ) : null}
    </div>
  );
}

/** Who gets the new leads, in a line, before anything is written. */
export function sharesLine(
  value: UploadChoices,
  team: RepView[] | null,
  fresh: number,
): string {
  if (value.assign === "rules") return "Given out by the lead rules.";
  if (value.assign === "me") return `All ${fresh} on your desk.`;
  if (value.assign === "none") return `All ${fresh} stay unassigned.`;
  if (!team) return "";
  const counts = countsFor(value, team, fresh);
  const named = team
    .filter((rep) => (counts[rep.person_id] ?? 0) > 0)
    .map((rep) => `${displayName(rep.name)} ${counts[rep.person_id]}`);
  const given = Object.values(counts).reduce((sum, count) => sum + count, 0);
  const left = Math.max(0, fresh - given);
  return `${[...named, ...(left ? [`${left} unassigned`] : [])].join(" · ")}.`;
}
