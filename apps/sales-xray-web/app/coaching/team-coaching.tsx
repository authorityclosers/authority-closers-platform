"use client";

import { FileSearch, Lock, Users } from "lucide-react";
import { Badge, Empty, Kpi, List, Meter, Panel, Row, Tiles } from "../ui/kit";
import { callDate } from "./coaching-format";
import type { TeamCoaching } from "./team-contract";
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
            coaching.latest_call_at
              ? `Updated ${callDate(coaching.latest_call_at)}${coaching.history_limited ? " · last 40" : ""}`
              : coaching.history_limited
                ? "Most recent 40"
                : "In this view"
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
          note="With report suggestions"
        />
        <Kpi
          label="Awaiting a report"
          value={coaching.pending_calls}
          note={
            coaching.unavailable_calls
              ? `${coaching.unavailable_calls} without usable evidence`
              : "Still being analysed"
          }
        />
      </Tiles>
      <div className={styles.layout}>
        <div className={styles.main}>
          <Panel
            title="Where the team can practise"
            sub="Share of analysed calls with a suggestion"
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
                Counts describe report suggestions. They do not measure
                recurring mistakes, successful execution or mastery. They update
                after every analysed call.
              </span>
            </p>
          </Panel>
          <Panel title="Who needs help with what" sub="Shared coaching only">
            <Empty
              icon={Lock}
              title="Named coaching appears when a rep shares it"
              text="Each rep’s focus, reason and mission stay private until they share them with one tap. They can stop sharing at any time."
            />
          </Panel>
        </div>
        <aside className={styles.rail} aria-label="Privacy">
          <Panel title="Private by default" tools={<Badge>Anonymous</Badge>}>
            <div className={styles.body}>
              <p className={styles.eyebrow}>
                <Users size={14} aria-hidden="true" />
                Owners and admins see these totals
              </p>
              <p>
                No rep’s name, calls, quotes, focus or mission appears here.
                Leadership and admins follow the same rule as everyone else.
              </p>
              <p className={styles.note}>
                Sharing and assigned coaches are coming next. A coach will see
                only the reps assigned to them, and only what each rep shares.
              </p>
            </div>
          </Panel>
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
