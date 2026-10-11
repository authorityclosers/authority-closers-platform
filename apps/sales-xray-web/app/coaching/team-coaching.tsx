"use client";

import { FileSearch } from "lucide-react";
import { Empty, Panel } from "../ui/kit";
import type { TeamCoaching } from "./team-contract";
import styles from "./coaching.module.css";

export function TeamCoachingStory({ coaching }: { coaching: TeamCoaching }) {
  const first = coaching.suggestions[0];
  return (
    <div className={styles.story}>
      <Panel title="Where the team can practise">
        <div className={styles.panelBody}>
          <p>
            {coaching.analysed_calls} retained analysed call
            {coaching.analysed_calls === 1 ? "" : "s"} in this view.
            Recommendations update when another analysed report is available.
          </p>
          {first ? (
            <>
              <h3>{first.label}</h3>
              <p>
                {first.suggestion_calls} call
                {first.suggestion_calls === 1 ? " has" : "s have"} a
                source-linked report suggestion in this area.
              </p>
            </>
          ) : (
            <Empty
              icon={FileSearch}
              title="No source-linked team suggestions yet"
              text="New analysed reports can add suggestions. Unknown evidence does not become a team weakness."
            />
          )}
          <p className={styles.muted}>
            Counts describe recommendations in reports. They do not measure
            recurring mistakes, successful execution or mastery.
          </p>
        </div>
      </Panel>
      {coaching.suggestions.length > 1 ? (
        <Panel title="Other reported coaching areas">
          <div className={styles.panelBody}>
            <ul>
              {coaching.suggestions.slice(1).map((row) => (
                <li key={row.skill_id}>
                  {row.label} · {row.suggestion_calls} call
                  {row.suggestion_calls === 1 ? "" : "s"}
                </li>
              ))}
            </ul>
          </div>
        </Panel>
      ) : null}
      <Panel title="Private by default">
        <div className={styles.panelBody}>
          <p>
            These are anonymous team totals. Each rep keeps their own focus,
            root cause, mission and call evidence private.
          </p>
          <p>
            Named coaching will require that rep’s explicit, revocable share.
            Sharing and assigned coach duties are not available yet.
          </p>
          {coaching.history_limited ? (
            <p>Only the most recent 40 retained team calls are included.</p>
          ) : null}
          {coaching.pending_calls ? (
            <p>
              {coaching.pending_calls} call
              {coaching.pending_calls === 1 ? " is" : "s are"} awaiting a usable
              report.
            </p>
          ) : null}
          {coaching.unavailable_calls ? (
            <p>
              {coaching.unavailable_calls} call
              {coaching.unavailable_calls === 1 ? " has" : "s have"} no usable
              retained coaching evidence.
            </p>
          ) : null}
        </div>
      </Panel>
    </div>
  );
}
