"use client";

import { AudioLines, ChevronDown, GraduationCap } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { callHref } from "../../acquisition-client";
import { unnamedCallName } from "../../call-label";
import { callDate } from "../../call-status";
import { fetchCoaching, type Coaching } from "../../coaching/coaching-client";
import type { DisplayDates } from "../../display-dates";
import { formatClock } from "../../lightbox/time";
import {
  Avatar,
  Badge,
  Empty,
  Kpi,
  Meter,
  Panel,
  Spark,
  Tiles,
} from "../../ui/kit";
import type { OrgMember, OrgRole } from "../organisation-api";
import type { TeamPatterns } from "../team-patterns";
import {
  callStatus,
  PERSON_WEEKS,
  skillStatus,
  SKILL_STATUS,
  type PersonActivity,
  type PersonCall,
  type SkillRow,
  type Week,
} from "./person-data";
import styles from "./person.module.css";

const ROLE_LABEL: Record<OrgRole, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
};

const shortDate = (at: number | string, dates: DisplayDates) =>
  new Intl.DateTimeFormat(dates.locale, {
    day: "numeric",
    month: "short",
    timeZone: dates.timeZone,
  }).format(new Date(at));

export const memberName = (member: OrgMember) =>
  member.name?.trim() || member.email || "Invited person";

/* ---------- Header ---------- */

export type PersonAction = { kind: "role"; role: OrgRole } | { kind: "remove" };

export function PersonHeader({
  member,
  isYou,
  test,
  canChangeRole,
  canRemove,
  busy,
  dates,
  onAction,
}: {
  member: OrgMember;
  isYou: boolean;
  test: boolean;
  canChangeRole: boolean;
  canRemove: boolean;
  busy: boolean;
  dates: DisplayDates;
  onAction: (action: PersonAction) => void;
}) {
  const name = memberName(member);
  const [confirming, setConfirming] = useState<PersonAction | null>(null);
  const invited = member.status === "invited";
  const facts = [
    member.email && member.email !== name ? member.email : null,
    invited
      ? "Invited, not joined yet"
      : member.joinedAt
        ? `Joined ${callDate(member.joinedAt, undefined, dates)}`
        : null,
    member.lastActiveAt
      ? `Last active ${callDate(member.lastActiveAt, undefined, dates)}`
      : null,
  ].filter(Boolean);
  return (
    <header className={styles.header}>
      <Avatar name={name} size={48} />
      <div className={styles.who}>
        <h1 className={styles.name}>
          <span>{name}</span>
          <Badge tone={member.role === "member" ? "neutral" : "accent"}>
            {ROLE_LABEL[member.role]}
          </Badge>
          {isYou ? <Badge>You</Badge> : null}
          {invited ? <Badge tone="warn">Invited</Badge> : null}
          {test ? <Badge>Test account</Badge> : null}
        </h1>
        {facts.length ? (
          <p className={styles.facts}>
            {facts.map((fact) => (
              <span key={fact}>{fact}</span>
            ))}
          </p>
        ) : null}
      </div>
      {canChangeRole || canRemove ? (
        <div className={styles.actions}>
          {confirming ? (
            <p className={styles.confirm} role="group" aria-label="Confirm">
              <span>
                {confirming.kind === "remove"
                  ? invited
                    ? `Revoke ${name}'s invitation?`
                    : `Remove ${name}? Their calls stay with the organisation.`
                  : `Make ${name} ${ROLE_LABEL[confirming.role].toLowerCase()}?`}
              </span>
              <button
                type="button"
                className={styles.quiet}
                onClick={() => setConfirming(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={styles.primary}
                data-tone={confirming.kind === "remove" ? "bad" : undefined}
                disabled={busy}
                onClick={() => {
                  onAction(confirming);
                  setConfirming(null);
                }}
              >
                {confirming.kind === "remove"
                  ? invited
                    ? "Revoke"
                    : "Remove"
                  : "Change role"}
              </button>
            </p>
          ) : (
            <>
              {canChangeRole ? (
                <select
                  className={styles.select}
                  value={member.role}
                  disabled={busy}
                  aria-label={`Role for ${name}`}
                  onChange={(event) =>
                    setConfirming({
                      kind: "role",
                      role: event.target.value as OrgRole,
                    })
                  }
                >
                  <option value="admin">Admin</option>
                  <option value="member">Member</option>
                </select>
              ) : null}
              {canRemove ? (
                <button
                  type="button"
                  className={styles.quiet}
                  disabled={busy}
                  onClick={() => setConfirming({ kind: "remove" })}
                >
                  {invited ? "Revoke invitation" : "Remove"}
                </button>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </header>
  );
}

/* ---------- Figures ---------- */

export function PersonTiles({
  data,
  weeks,
  dates,
}: {
  data: PersonActivity;
  weeks: Week[];
  dates: DisplayDates;
}) {
  const last = data.listed[0] ?? null;
  return (
    <Tiles label="Last 12 weeks">
      <Kpi
        label="Calls"
        value={data.calls}
        note="last 12 weeks"
        spark={
          <Spark
            values={weeks.map((week) => week.calls)}
            label={`Calls per week, oldest first: ${weeks.map((week) => week.calls).join(", ")}`}
          />
        }
      />
      <Kpi
        label="Minutes recorded"
        value={Math.round(data.minutes)}
        note="length of those calls"
        spark={
          <Spark
            values={weeks.map((week) => week.minutes)}
            label={`Minutes per week, oldest first: ${weeks.map((week) => week.minutes).join(", ")}`}
          />
        }
      />
      <Kpi
        label="Reports ready"
        value={data.reportsReady}
        note={`of ${data.calls} ${data.calls === 1 ? "call" : "calls"}`}
        spark={
          data.calls ? (
            <Meter
              value={data.reportsReady}
              max={data.calls}
              label={`${data.reportsReady} of ${data.calls} calls have a report`}
            />
          ) : undefined
        }
      />
      <Kpi
        label="Last call"
        value={
          data.lastCallAt ? callDate(data.lastCallAt, undefined, dates) : "None"
        }
        note={
          last
            ? (last.label ?? unnamedCallName(last.createdAt, dates))
            : "in the last 12 weeks"
        }
      />
    </Tiles>
  );
}

/** Zero-based weekly bars with the largest value marked on the scale. */
export function WeekChart({
  title,
  weeks,
  metric,
  unit,
  dates,
}: {
  title: string;
  weeks: Week[];
  metric: "calls" | "minutes";
  unit: string;
  dates: DisplayDates;
}) {
  const values = weeks.map((week) => week[metric]);
  const top = Math.max(...values);
  const total = values.reduce((sum, value) => sum + value, 0);
  const scale = Math.max(1, top);
  return (
    <Panel title={title} sub={`${total} ${unit} · last ${PERSON_WEEKS} weeks`}>
      <figure className={styles.chart}>
        <div
          className={styles.plot}
          role="img"
          aria-label={`${title}, oldest week first: ${values.join(", ")}`}
        >
          <span className={styles.axisTop} aria-hidden="true">
            {top}
          </span>
          <span className={styles.axisZero} aria-hidden="true">
            0
          </span>
          {weeks.map((week, index) => (
            <span
              key={week.start}
              className={styles.bar}
              data-now={index === weeks.length - 1 ? "" : undefined}
              title={`Week of ${shortDate(week.start + 86_400_000, dates)}: ${week[metric]} ${unit}`}
            >
              <i
                style={{
                  height: `${week[metric] ? Math.max(3, (week[metric] / scale) * 100) : 0}%`,
                }}
              />
            </span>
          ))}
        </div>
        <figcaption className={styles.ticks} aria-hidden="true">
          <span>{shortDate(weeks[0].start + 86_400_000, dates)}</span>
          <span>{shortDate(weeks[6].start + 86_400_000, dates)}</span>
          <span>This week</span>
        </figcaption>
      </figure>
    </Panel>
  );
}

/* ---------- From the reports ---------- */

export function OutcomesPanel({
  tally,
  reading,
}: {
  tally: TeamPatterns;
  reading: boolean;
}) {
  const top = Math.max(1, ...tally.outcomes.map((item) => item.calls));
  return (
    <Panel
      title="How calls ended"
      sub={
        reading
          ? "Reading reports…"
          : `From ${tally.reports} ${tally.reports === 1 ? "report" : "reports"}`
      }
    >
      {tally.outcomes.length ? (
        <ul className={styles.bars}>
          {tally.outcomes.map((item) => (
            <li key={item.kind}>
              <span>{item.label}</span>
              <span className={styles.track} aria-hidden="true">
                <i style={{ width: `${(item.calls / top) * 100}%` }} />
              </span>
              <b>{item.calls}</b>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.quietLine}>
          {reading
            ? "Reading this person's reports…"
            : "No report says how a call ended yet."}
        </p>
      )}
    </Panel>
  );
}

export function SkillsPanel({
  rows,
  calls,
  reading,
  dates,
}: {
  rows: SkillRow[];
  calls: PersonCall[];
  reading: boolean;
  dates: DisplayDates;
}) {
  const byId = new Map(calls.map((call) => [call.id, call]));
  const columns = rows[0]?.cells ?? [];
  return (
    <Panel
      title="Skills across recent calls"
      sub={reading ? "Reading reports…" : "Oldest first · not a score"}
    >
      {rows.length ? (
        <div className={styles.skills}>
          <table className={styles.matrix}>
            <thead>
              <tr>
                <th scope="col">Skill</th>
                {columns.map((cell) => {
                  const call = byId.get(cell.callId);
                  return (
                    <th scope="col" key={cell.callId}>
                      <Link
                        href={callHref(cell.callId)}
                        prefetch={false}
                        title={
                          call
                            ? (call.label ??
                              unnamedCallName(call.createdAt, dates))
                            : "Open the call"
                        }
                      >
                        {call ? shortDate(call.createdAt, dates) : "Call"}
                      </Link>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <th scope="row">{row.label}</th>
                  {row.cells.map((cell) => {
                    const status = skillStatus(cell.status);
                    return (
                      <td key={cell.callId}>
                        <span
                          className={styles.mark}
                          data-mark={status.mark}
                          role="img"
                          aria-label={status.label}
                          title={status.label}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className={styles.legend}>
            {["observed", "partial", "insufficient_evidence", "conflicted"].map(
              (key) => (
                <span key={key}>
                  <span
                    className={styles.mark}
                    data-mark={SKILL_STATUS[key].mark}
                    aria-hidden="true"
                  />
                  {SKILL_STATUS[key].label}
                </span>
              ),
            )}
          </p>
        </div>
      ) : (
        <p className={styles.quietLine}>
          {reading
            ? "Reading this person's reports…"
            : "Skills appear once a report is ready."}
        </p>
      )}
    </Panel>
  );
}

/* ---------- Calls ---------- */

const CALLS_SHOWN = 8;

export function PersonCalls({
  data,
  dates,
  callsHref,
}: {
  data: PersonActivity;
  dates: DisplayDates;
  /** Calls filtered to this person, for the full list and search. */
  callsHref?: string;
}) {
  const [all, setAll] = useState(false);
  const calls = all ? data.listed : data.listed.slice(0, CALLS_SHOWN);
  return (
    <Panel
      title="Calls"
      sub={`${data.listed.length} in the last ${PERSON_WEEKS} weeks`}
      action={
        callsHref ? { href: callsHref, label: "Open in Calls" } : undefined
      }
      foot={
        !data.complete ? (
          <span>
            Showing the newest {data.listed.length} of {data.calls} calls.
          </span>
        ) : undefined
      }
    >
      {calls.length ? (
        <>
          <ul className={styles.calls}>
            {calls.map((call) => {
              const status = callStatus(call);
              return (
                <li key={call.id}>
                  <Link
                    href={callHref(call.id)}
                    prefetch={false}
                    className={styles.callRow}
                  >
                    <AudioLines size={15} aria-hidden="true" />
                    <span className={styles.callName}>
                      {call.label ?? unnamedCallName(call.createdAt, dates)}
                    </span>
                    <span className={styles.callDate}>
                      {callDate(call.createdAt, undefined, dates)}
                    </span>
                    <span className={styles.callLength}>
                      {call.durationSeconds > 0
                        ? formatClock(call.durationSeconds * 1000)
                        : "—"}
                    </span>
                    <span className={styles.status} data-tone={status.tone}>
                      <i aria-hidden="true" />
                      {status.label}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
          {data.listed.length > CALLS_SHOWN ? (
            <button
              type="button"
              className={styles.more}
              aria-expanded={all}
              onClick={() => setAll(!all)}
            >
              {all ? "Show fewer" : `Show all ${data.listed.length} calls`}
              <ChevronDown size={14} aria-hidden="true" />
            </button>
          ) : null}
        </>
      ) : (
        <p className={styles.quietLine}>
          No calls in the last {PERSON_WEEKS} weeks.
        </p>
      )}
    </Panel>
  );
}

/* ---------- Coaching ---------- */

/**
 * Coaching is private to each person unless they share it (owner, 10 Oct),
 * so the profile shows a summary only on your own page.
 */
export function CoachingPanel({
  isYou,
  firstName,
}: {
  isYou: boolean;
  firstName: string;
}) {
  const [coaching, setCoaching] = useState<
    | { status: "loading" }
    | { status: "ready"; value: Coaching }
    | { status: "none" }
  >({ status: "loading" });
  useEffect(() => {
    if (!isYou) return;
    const controller = new AbortController();
    fetchCoaching(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setCoaching({ status: "ready", value });
      })
      .catch(() => {
        if (!controller.signal.aborted) setCoaching({ status: "none" });
      });
    return () => controller.abort();
  }, [isYou]);
  if (!isYou)
    return (
      <Panel title="Coaching">
        <p className={styles.quietLine}>
          {firstName}&apos;s coaching stays private to them unless they share
          it.
        </p>
      </Panel>
    );
  const value = coaching.status === "ready" ? coaching.value : null;
  return (
    <Panel
      title="Your coaching"
      action={{ href: "/coaching", label: "Open Coaching" }}
    >
      {coaching.status === "loading" ? (
        <p className={styles.quietLine}>Reading your coaching…</p>
      ) : value?.focus ? (
        <dl className={styles.coaching}>
          <div>
            <dt>Current focus</dt>
            <dd>{value.focus.label}</dd>
          </div>
          {value.mission ? (
            <div>
              <dt>Mission</dt>
              <dd>{value.mission.behavior}</dd>
            </div>
          ) : null}
        </dl>
      ) : (
        <Empty
          icon={GraduationCap}
          title="No focus yet"
          text="Your coaching picks a focus once a few reports are ready."
        />
      )}
    </Panel>
  );
}
