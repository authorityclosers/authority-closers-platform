"use client";

import { FileSearch, FlaskConical, LineChart, Lock, Users } from "lucide-react";
import { useId, useRef, useState } from "react";
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
import { TEAM } from "./coaching-copy";
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
    <Panel title={TEAM.objections} sub={TEAM.objectionsSub(calls)}>
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
          title={TEAM.noObjections}
          text={TEAM.noObjectionsText}
        />
      )}
      <p className={styles.body}>
        <span className={styles.note}>{TEAM.objectionsNote}</span>
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
  const [query, setQuery] = useState("");
  const [all, setAll] = useState(false);
  const listId = useId();
  const search = useRef<HTMLInputElement>(null);
  const name = query.trim().toLocaleLowerCase();
  const shown = reps.filter(
    (rep) =>
      (area === "all" || rep.skill_id === area) &&
      rep.name.toLocaleLowerCase().includes(name),
  );
  const visible = all ? shown : shown.slice(0, 8);
  const areas = rows.filter((row) =>
    reps.some((rep) => rep.skill_id === row.skill_id),
  );
  return (
    <Panel
      title={TEAM.who}
      sub={
        shared ? TEAM.sharedSub(reps.length) : TEAM.fictionalSub(reps.length)
      }
    >
      <div className={styles.repFilter}>
        <label className={`${kitStyles.field} ${styles.repSearch}`}>
          <span className={styles.srOnly}>{TEAM.findRep}</span>
          <input
            ref={search}
            type="search"
            placeholder={TEAM.findRep}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setAll(false);
            }}
          />
        </label>
        {areas.length > 1 ? (
          <span className={`${kitStyles.field} ${styles.repArea}`}>
            <select
              aria-label="Coaching area"
              value={area}
              onChange={(event) => {
                setArea(event.target.value);
                setAll(false);
              }}
            >
              <option value="all">{TEAM.allAreas}</option>
              {areas.map((row) => (
                <option key={row.skill_id} value={row.skill_id}>
                  {AREA[row.skill_id] ?? row.label}
                </option>
              ))}
            </select>
          </span>
        ) : null}
        <span className={styles.note} role="status">
          {TEAM.repCount(shown.length)}
        </span>
      </div>
      {shown.length ? (
        <div id={listId} className={styles.repList}>
          <List label="Reps and their current focus">
            {visible.map((rep) => (
              <Row
                key={rep.person_id}
                icon={<Avatar name={rep.name} size={24} />}
                title={
                  <>
                    {rep.name}
                    {rep.focus_label ? (
                      <>
                        {" "}
                        <span className={styles.repFocus}>
                          {rep.focus_label}
                        </span>
                      </>
                    ) : null}
                  </>
                }
                href={`/coaching?person=${rep.person_id}`}
                meta={[
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
        </div>
      ) : (
        <div className={styles.repEmpty}>
          <Empty
            icon={Users}
            title={TEAM.noMatches}
            text={TEAM.noMatchesText}
          />
          <button
            type="button"
            className={kitStyles.button}
            onClick={() => {
              setQuery("");
              setArea("all");
              setAll(false);
              search.current?.focus();
            }}
          >
            {TEAM.clearFilters}
          </button>
        </div>
      )}
      {shown.length > 8 ? (
        <button
          type="button"
          className={`${kitStyles.button} ${styles.moreCalls}`}
          data-many=""
          aria-expanded={all}
          aria-controls={listId}
          onClick={() => {
            setAll(!all);
            if (all) {
              search.current?.focus({ preventScroll: true });
              search.current?.scrollIntoView({
                block: "center",
                behavior: "instant",
              });
            }
          }}
        >
          {all ? TEAM.showFewer : TEAM.showAll(shown.length)}
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
          label={TEAM.calls}
          value={analysed}
          note={
            [
              // One line in the tile; the latest call's date sits in the
              // footnote below, which wraps on phones.
              coaching.rep_count ? TEAM.people(coaching.rep_count) : null,
              coaching.history_limited ? TEAM.last40 : null,
            ]
              .filter(Boolean)
              .join(" · ")
              .replace(/^./, (c) => c.toUpperCase()) || TEAM.inView
          }
        />
        <Kpi
          label={TEAM.top}
          value={first ? `${share(first.suggestion_calls, analysed)}%` : "—"}
          note={first ? (AREA[first.skill_id] ?? first.label) : TEAM.noneYet}
          tone={first ? "accent" : undefined}
        />
        <Kpi label={TEAM.areas} value={rows.length} note={TEAM.areasNote} />
        {coaching.sandbox ? (
          <Kpi
            label={TEAM.sandboxReps}
            value={coaching.rep_count}
            note={TEAM.sandboxRepsNote}
          />
        ) : (
          <Kpi
            label={TEAM.pending}
            value={coaching.pending_calls}
            note={
              coaching.unavailable_calls
                ? TEAM.unusable(coaching.unavailable_calls)
                : TEAM.pendingNote
            }
          />
        )}
      </Tiles>
      <div className={styles.layout}>
        <div className={styles.main}>
          {coaching.reps.length ? (
            <RepList
              reps={coaching.reps}
              rows={rows}
              shared={coaching.reps_basis === "shared"}
            />
          ) : null}
          <Panel title={TEAM.practise} sub={TEAM.practiseSub}>
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
                title={TEAM.emptyTitle}
                text={TEAM.emptyText}
              />
            )}
            <p className={styles.body}>
              <span className={styles.note}>
                {coaching.sandbox ? TEAM.sandboxNote : TEAM.practiseNote}
                {coaching.latest_call_at
                  ? ` ${TEAM.latest(callDate(coaching.latest_call_at))}`
                  : null}
              </span>
            </p>
          </Panel>
          {coaching.objection_calls > 0 ? (
            <ObjectionsPanel coaching={coaching} />
          ) : null}
          {coaching.reps.length ? null : (
            <Panel title={TEAM.who} sub={TEAM.sharedOnly}>
              <Empty
                icon={Lock}
                title={TEAM.namedTitle}
                text={TEAM.namedText}
              />
            </Panel>
          )}
        </div>
        <aside className={styles.rail} aria-label="Privacy">
          {coaching.sandbox ? (
            <Panel title={TEAM.sandboxTitle} tools={<Badge>Sandbox</Badge>}>
              <div className={styles.body}>
                <p className={styles.eyebrow}>
                  <FlaskConical size={14} aria-hidden="true" />
                  {TEAM.sandboxWho}
                </p>
                <p>{TEAM.sandboxText}</p>
                <p className={styles.note}>{TEAM.sandboxPrivate}</p>
              </div>
            </Panel>
          ) : (
            <Panel
              title={TEAM.privateTitle}
              tools={<Badge>{TEAM.privateBadge}</Badge>}
            >
              <div className={styles.body}>
                <p className={styles.eyebrow}>
                  <Users size={14} aria-hidden="true" />
                  {TEAM.privateWho}
                </p>
                <p>{TEAM.privateText}</p>
                <p className={styles.note}>{TEAM.privateShare}</p>
              </div>
            </Panel>
          )}
          {coaching.sandbox ? null : (
            <Panel title={TEAM.insightsTitle}>
              <List label="Company view">
                <Row
                  icon={<LineChart size={15} aria-hidden="true" />}
                  title={TEAM.insights}
                  href="/organisation/insights"
                  meta={[TEAM.insightsNote]}
                />
              </List>
            </Panel>
          )}
          {coaching.limitations.length ? (
            <details className={styles.more}>
              <summary>{TEAM.counted}</summary>
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
