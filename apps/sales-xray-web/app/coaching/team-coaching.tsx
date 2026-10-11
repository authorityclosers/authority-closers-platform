"use client";

import { FileSearch, FlaskConical, Lock, Users } from "lucide-react";
import { useState } from "react";
import {
  Avatar,
  Badge,
  Empty,
  Kpi,
  kitStyles,
  List,
  Meter,
  Panel,
  Row,
  Tiles,
} from "../ui/kit";
import { callDate } from "./coaching-format";
import type { TeamCoaching, TeamRep } from "./team-contract";
import styles from "./coaching.module.css";

// The owner's plain words for each approved skill area.
const AREA: Record<string, string> = {
  human_connection_trust: "Rapport",
  discovery_deep_understanding: "Discovery",
  qualification: "Qualification",
  problem_impact_desire: "Pain and impact",
  solution_relevance_presentation: "Pitch",
  certainty_objection_intelligence: "Objections",
  closing_decision_management: "Closing",
  communication_tonality: "Delivery",
  report_next_step: "Other",
};

const share = (part: number, whole: number) =>
  whole > 0 ? Math.round((part / whole) * 100) : 0;

/** Buyer objections from report call maps: how often, and how they were met. */
function ObjectionsPanel({ coaching }: { coaching: TeamCoaching }) {
  const calls = coaching.objection_calls;
  return (
    <Panel
      title="Objections your team hears"
      sub={`In ${calls} mapped call${calls === 1 ? "" : "s"}`}
    >
      {coaching.objections.length ? (
        <List label="Objections">
          {coaching.objections.map((row) => (
            <Row
              key={row.kind}
              title={row.label}
              meta={[
                `${row.calls} of ${calls} call${calls === 1 ? "" : "s"}`,
                row.handled < row.heard
                  ? `${row.heard - row.handled} of ${row.heard} left open`
                  : `all ${row.heard} answered`,
              ]}
              end={
                <span className={styles.share}>
                  <Meter value={row.calls} max={calls} />
                  <span>{share(row.calls, calls)}%</span>
                </span>
              }
            />
          ))}
        </List>
      ) : (
        <Empty
          icon={FileSearch}
          title="No objections in these calls"
          text="Each analysed call’s map lists the buyer’s objections."
        />
      )}
      <p className={styles.body}>
        <span className={styles.note}>
          Left open means the reply deflected or skipped it. Counts come from
          each report’s call map; they never show the words or who said them.
        </span>
      </p>
    </Panel>
  );
}

/** Fictional AC Sandbox reps, each with their newest call's one focus. */
function RepList({
  reps,
  rows,
  shared,
}: {
  reps: TeamRep[];
  rows: TeamCoaching["suggestions"];
  /** Real reps who shared their coaching, rather than fictional ones. */
  shared: boolean;
}) {
  const [area, setArea] = useState("all");
  const [all, setAll] = useState(false);
  const shown = reps.filter((rep) => area === "all" || rep.skill_id === area);
  const visible = all ? shown : shown.slice(0, 8);
  const areas = rows.filter((row) =>
    reps.some((rep) => rep.skill_id === row.skill_id),
  );
  return (
    <Panel
      title="Who needs help with what"
      sub={
        shared
          ? `${reps.length} shared with you`
          : `${reps.length} fictional ${reps.length === 1 ? "rep" : "reps"}`
      }
    >
      {areas.length > 1 ? (
        <div className={styles.repFilter}>
          <span className={kitStyles.field}>
            <select
              aria-label="Coaching area"
              value={area}
              onChange={(event) => {
                setArea(event.target.value);
                setAll(false);
              }}
            >
              <option value="all">All areas</option>
              {areas.map((row) => (
                <option key={row.skill_id} value={row.skill_id}>
                  {AREA[row.skill_id] ?? row.label}
                </option>
              ))}
            </select>
          </span>
          <span className={styles.note}>
            {shown.length} {shown.length === 1 ? "rep" : "reps"}
          </span>
        </div>
      ) : null}
      <List label="Reps and their current focus">
        {visible.map((rep) => (
          <Row
            key={rep.person_id}
            icon={<Avatar name={rep.name} size={24} />}
            title={rep.name}
            href={`/coaching?person=${rep.person_id}`}
            meta={[
              rep.focus_label,
              `${rep.calls} call${rep.calls === 1 ? "" : "s"}`,
              shared && rep.shared_at
                ? `Shared ${callDate(rep.shared_at)}`
                : rep.latest_call_at
                  ? callDate(rep.latest_call_at)
                  : null,
            ]}
            end={
              rep.skill_id ? (
                <Badge>{AREA[rep.skill_id] ?? "Other"}</Badge>
              ) : null
            }
          />
        ))}
      </List>
      {shown.length > visible.length ? (
        <button
          type="button"
          className={`${kitStyles.button} ${styles.moreCalls}`}
          data-many=""
          onClick={() => setAll(true)}
        >
          Show all {shown.length} people
        </button>
      ) : null}
    </Panel>
  );
}

/** Level 3: anonymous team totals. A rep's own coaching stays private. */
export function TeamCoachingStory({ coaching }: { coaching: TeamCoaching }) {
  const rows = coaching.suggestions;
  const first = rows[0];
  const analysed = coaching.analysed_calls;
  return (
    <div className={styles.story}>
      <Tiles label="Team coaching totals">
        <Kpi
          label="Analysed calls"
          value={analysed}
          note={
            [
              coaching.rep_count
                ? `${coaching.rep_count} ${coaching.rep_count === 1 ? "person" : "people"}`
                : null,
              coaching.latest_call_at
                ? `updated ${callDate(coaching.latest_call_at)}`
                : null,
              coaching.history_limited ? "last 40" : null,
            ]
              .filter(Boolean)
              .join(" · ")
              .replace(/^./, (c) => c.toUpperCase()) || "In this view"
          }
        />
        <Kpi
          label="Top coaching area"
          value={first ? `${share(first.suggestion_calls, analysed)}%` : "—"}
          note={
            first ? (AREA[first.skill_id] ?? first.label) : "No suggestions yet"
          }
          tone={first ? "accent" : undefined}
        />
        <Kpi
          label="Coaching areas"
          value={rows.length}
          note="With suggestions"
        />
        {coaching.sandbox ? (
          <Kpi
            label="Fictional reps"
            value={coaching.rep_count}
            note="AC Sandbox, only you"
          />
        ) : (
          <Kpi
            label="Awaiting a report"
            value={coaching.pending_calls}
            note={
              coaching.unavailable_calls
                ? `${coaching.unavailable_calls} unusable`
                : "Being analysed"
            }
          />
        )}
      </Tiles>
      <div className={styles.layout}>
        <div className={styles.main}>
          <Panel
            title="Where the team can practise"
            sub="Share of analysed calls"
          >
            {rows.length ? (
              <List label="Coaching areas">
                {rows.map((row) => (
                  <Row
                    key={row.skill_id}
                    title={row.label}
                    meta={[
                      AREA[row.skill_id] !== row.label
                        ? (AREA[row.skill_id] ?? "Other")
                        : null,
                      `${row.suggestion_calls} of ${analysed} call${analysed === 1 ? "" : "s"}`,
                    ]}
                    end={
                      <span className={styles.share}>
                        <Meter value={row.suggestion_calls} max={analysed} />
                        <span>{share(row.suggestion_calls, analysed)}%</span>
                      </span>
                    }
                  />
                ))}
              </List>
            ) : (
              <Empty
                icon={FileSearch}
                title="No team suggestions yet"
                text="Each analysed report can add one. Unknown evidence never becomes a team weakness."
              />
            )}
            <p className={styles.body}>
              <span className={styles.note}>
                {coaching.sandbox
                  ? "Each fictional call carries one authored focus. Counts are those focuses, not measured mistakes or mastery."
                  : "Counts describe report suggestions. They do not measure recurring mistakes, successful execution or mastery. They update after every analysed call."}
              </span>
            </p>
          </Panel>
          {coaching.objection_calls > 0 ? (
            <ObjectionsPanel coaching={coaching} />
          ) : null}
          {coaching.reps.length ? (
            <RepList
              reps={coaching.reps}
              rows={rows}
              shared={coaching.reps_basis === "shared"}
            />
          ) : (
            <Panel title="Who needs help with what" sub="Shared only">
              <Empty
                icon={Lock}
                title="Named coaching appears when a rep shares it"
                text="Each rep’s focus, reason and mission stay private until they share them with one tap. They can stop sharing at any time."
              />
            </Panel>
          )}
        </div>
        <aside className={styles.rail} aria-label="Privacy">
          {coaching.sandbox ? (
            <Panel title="Fictional AC Sandbox" tools={<Badge>Sandbox</Badge>}>
              <div className={styles.body}>
                <p className={styles.eyebrow}>
                  <FlaskConical size={14} aria-hidden="true" />
                  Only you see these reps
                </p>
                <p>
                  These reps, calls and coaching are fictional dataset records
                  you imported. Each call carries one authored focus.
                </p>
                <p className={styles.note}>
                  Real reps’ coaching stays private until they share it; their
                  totals never name anyone.
                </p>
              </div>
            </Panel>
          ) : (
            <Panel title="Private by default" tools={<Badge>Anonymous</Badge>}>
              <div className={styles.body}>
                <p className={styles.eyebrow}>
                  <Users size={14} aria-hidden="true" />
                  Owners and admins see these totals
                </p>
                <p>
                  Totals never name a rep or show their calls, quotes, focus or
                  mission. Leadership and admins follow the same rule as
                  everyone else.
                </p>
                <p className={styles.note}>
                  A rep can share their coaching with owners and admins in one
                  tap, and stop at any time. Assigned coaches come next; a coach
                  will see only their reps, and only what each rep shares.
                </p>
              </div>
            </Panel>
          )}
          {coaching.limitations.length ? (
            <details className={styles.more}>
              <summary>How these totals are counted</summary>
              <ul className={styles.takeaways}>
                {coaching.limitations.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
