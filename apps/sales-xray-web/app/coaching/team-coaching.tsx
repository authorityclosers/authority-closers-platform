"use client";

import { FileSearch, FlaskConical, LineChart, Lock, Users } from "lucide-react";
import { useId, useImperativeHandle, useRef, useState, type Ref } from "react";
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

const NO_FOCUS = "no-focus";

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

type RepListHandle = { findArea: (skill: string) => void };

/** Already shared or fictional reps, with their current focus. */
function RepList({
  reps,
  rows,
  shared,
  ref,
}: {
  reps: TeamRep[];
  rows: TeamCoaching["suggestions"];
  /** Real reps who shared their coaching, rather than fictional ones. */
  shared: boolean;
  ref: Ref<RepListHandle>;
}) {
  const [area, setArea] = useState("all");
  const [query, setQuery] = useState("");
  const [all, setAll] = useState(false);
  const listId = useId();
  const search = useRef<HTMLInputElement>(null);
  useImperativeHandle(ref, () => ({
    findArea(skill) {
      setArea(skill);
      setQuery("");
      setAll(false);
      search.current?.focus({ preventScroll: true });
      search.current?.scrollIntoView({ block: "center", behavior: "instant" });
    },
  }));
  const term = query.trim().toLocaleLowerCase();
  const shown = reps.filter(
    (rep) =>
      (area === "all" ||
        (area === NO_FOCUS ? !rep.focus_label : rep.skill_id === area)) &&
      (rep.name.toLocaleLowerCase().includes(term) ||
        (rep.focus_label?.toLocaleLowerCase().includes(term) ?? false)),
  );
  const visible = all ? shown : shown.slice(0, 8);
  // Totals describe past call suggestions; named reps carry their current
  // focus. Keep the existing option order, then include any other current
  // skills without adding a suggestion to the totals.
  const areas = [
    ...new Set([
      ...rows.map((row) => row.skill_id),
      ...reps.map((rep) => rep.skill_id),
    ]),
  ].filter(
    (skill): skill is string =>
      skill !== null && reps.some((rep) => rep.skill_id === skill),
  );
  const hasMissingFocus = reps.some((rep) => !rep.focus_label);
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
            placeholder={TEAM.findRepHint}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setAll(false);
            }}
          />
        </label>
        {areas.length > 1 ||
        (areas.length === 1 && reps.some((rep) => !rep.skill_id)) ||
        hasMissingFocus ||
        area !== "all" ? (
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
              {areas.map((skill) => (
                <option key={skill} value={skill}>
                  {AREA[skill] ?? "Other"}
                </option>
              ))}
              {hasMissingFocus ? (
                <option value={NO_FOCUS}>{TEAM.noFocusShown}</option>
              ) : null}
            </select>
          </span>
        ) : null}
        <span className={styles.note} role="status">
          {TEAM.repCount(shown.length)}
        </span>
        {query || area !== "all" ? (
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
        ) : null}
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
                    {rep.name}{" "}
                    <span className={styles.repFocus}>
                      {rep.focus_label ?? TEAM.noFocusShown}
                    </span>
                  </>
                }
                href={`/coaching?person=${rep.person_id}`}
                meta={[
                  `${rep.calls} call${rep.calls === 1 ? "" : "s"}`,
                  rep.latest_call_at
                    ? TEAM.repLatest(callDate(rep.latest_call_at))
                    : null,
                  shared && rep.shared_at
                    ? `Shared ${callDate(rep.shared_at)}`
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
  const reps = useRef<RepListHandle>(null);
  const rows = coaching.suggestions;
  const hasRepFocus = rows.some((row) =>
    coaching.reps.some((rep) => rep.skill_id === row.skill_id),
  );
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
              ref={reps}
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
                      <span className={styles.areaActions}>
                        <span className={styles.share}>
                          <Meter value={row.suggestion_calls} max={analysed} />
                          <span>{share(row.suggestion_calls, analysed)}%</span>
                        </span>
                        {coaching.reps.some(
                          (rep) => rep.skill_id === row.skill_id,
                        ) ? (
                          <button
                            type="button"
                            className={kitStyles.button}
                            aria-label={TEAM.findRepsLabel(row.label)}
                            onClick={() => reps.current?.findArea(row.skill_id)}
                          >
                            {TEAM.findReps}
                          </button>
                        ) : null}
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
                {hasRepFocus ? ` ${TEAM.currentFocusNote}` : null}
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
