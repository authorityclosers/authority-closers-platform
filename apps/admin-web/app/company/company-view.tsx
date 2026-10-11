/**
 * The Admin company view (AUT-1798), on the server: the same aggregates an
 * organisation's owners see in Sales Xray Insights. Every chart is labelled
 * and every value is also written out; amber marks only "needs attention".
 */
import Link from "next/link";
import type { CSSProperties } from "react";

import {
  Badge,
  Delta,
  Kpi,
  Page,
  PageHeader,
  Panel,
  Table,
  Tiles,
  Unavailable,
  Why,
} from "@/app/ui/kit";

import { CompanyControls, PrepareCalls } from "./company-controls";
import {
  RANGES,
  SKILLS,
  bucketLabel,
  count,
  dateLabel,
  duration,
  minutes,
  observedShare,
  outcomeLabel,
  percent,
  rupees,
  type CallPage,
  type CallRow,
  type Filters,
  type Group,
  type Insights,
  type Organisation,
} from "./company-data";
import styles from "./company.module.css";

function points(now: number | null, before: number | null) {
  if (now === null || before === null) return null;
  const value = Math.round((now - before) * 100);
  return (
    <span className={styles.points}>
      {value === 0 ? "±0" : value > 0 ? `+${value}` : `${value}`} pts
    </span>
  );
}

function change(value: number | null) {
  if (value === null) return { text: "—", tone: undefined };
  const size = Math.round(Math.abs(value) * 100);
  if (size === 0) return { text: "steady", tone: undefined };
  const unit = size === 1 ? "1 pt" : `${size} pts`;
  return value < 0
    ? { text: `${unit} better`, tone: "better" }
    : { text: `${unit} worse`, tone: "worse" };
}

function SkillDots({ skills }: { skills: string | null }) {
  if (!skills) return <span className={styles.muted}>—</span>;
  return (
    <span className={styles.dots} title={skills}>
      {Array.from(skills).map((code, index) => (
        <i key={index} data-code={code} />
      ))}
    </span>
  );
}

function Bars({
  rows,
}: {
  rows: { key: string; label: string; value: number; note?: string }[];
}) {
  const max = Math.max(1, ...rows.map((row) => row.value));
  return (
    <ul className={styles.bars}>
      {rows.map((row) => (
        <li key={row.key}>
          <span className={styles.barLabel}>{row.label}</span>
          <span className={styles.track} aria-hidden="true">
            <i style={{ width: `${(row.value / max) * 100}%` }} />
          </span>
          <span className={styles.value}>
            {count(row.value)}
            {row.note ? <small>{row.note}</small> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Trend({ data }: { data: Insights }) {
  const max = Math.max(1, ...data.trend.map((point) => point.calls));
  const every = Math.max(1, Math.ceil(data.trend.length / 6));
  return (
    <div className={styles.trend}>
      <div
        className={styles.columns}
        role="img"
        aria-label={`Calls by ${data.window.unit}`}
      >
        {data.trend.map((point) => (
          <span
            key={point.at}
            className={styles.column}
            title={`${bucketLabel(point.at, data.window.unit)}: ${count(point.calls)} calls, ${count(point.won)} won`}
          >
            <span
              className={styles.stack}
              style={{ height: `${(point.calls / max) * 100}%` }}
            >
              <i
                data-key="calls"
                style={{ flexGrow: Math.max(0, point.calls - point.won) }}
              />
              <i data-key="won" style={{ flexGrow: point.won }} />
            </span>
          </span>
        ))}
      </div>
      <ol className={styles.dates} aria-hidden="true">
        {data.trend.map((point, index) => (
          <li key={point.at}>
            {index % every === 0 ? bucketLabel(point.at, data.window.unit) : ""}
          </li>
        ))}
      </ol>
      <p className={styles.legend}>
        <span>
          <i data-key="won" /> Won
        </span>
        <span>
          <i data-key="calls" /> Other calls
        </span>
        <span className={styles.muted}>
          Peak {count(max)} calls a {data.window.unit}
        </span>
      </p>
    </div>
  );
}

function HeatCells({ group }: { group: Group }) {
  return (
    <>
      {SKILLS.map((skill) => {
        const cell = group.skills.find((item) => item.id === skill.id);
        const share = cell ? observedShare(cell) : null;
        return (
          <td
            key={skill.id}
            className={styles.heat}
            data-full={share === 1 ? "" : undefined}
            data-empty={share === null ? "" : undefined}
            style={
              share === null || share === 1
                ? undefined
                : ({
                    "--gap": `${Math.min(72, Math.round(10 + (1 - share) * 120))}%`,
                  } as CSSProperties)
            }
            title={`${skill.short}: ${percent(share)} observed`}
          >
            {percent(share)}
          </td>
        );
      })}
    </>
  );
}

function CallList({ rows }: { rows: CallRow[] }) {
  if (!rows.length)
    return (
      <p className={styles.inset}>No calls with all eight skills read yet.</p>
    );
  return (
    <ul className={styles.callList}>
      {rows.map((row) => (
        <li key={row.key}>
          <span>
            <strong>{row.person}</strong>
            <small>
              {dateLabel(row.at)} · {outcomeLabel(row.outcome)} ·{" "}
              {duration(row.durationMs)}
            </small>
          </span>
          <SkillDots skills={row.skills} />
        </li>
      ))}
    </ul>
  );
}

export function CompanyView({
  organisations,
  organisation,
  overview: data,
  filters,
  calls,
  callsError,
  offset,
}: {
  organisations: Organisation[];
  organisation: Organisation;
  overview: Insights;
  filters: Filters;
  calls: CallPage | null;
  callsError: string | null;
  offset: number;
}) {
  const { totals, previous } = data;
  const value = rupees(totals.wonValue);
  const outcomes = data.outcomes
    .filter((row) => row.calls > 0)
    .sort((a, b) => b.calls - a.calls)
    .map((row) => ({
      key: row.outcome,
      label: outcomeLabel(row.outcome),
      value: row.calls,
      note: percent(totals.calls ? row.calls / totals.calls : null),
    }));
  const attention = [...data.skills]
    .filter((skill) => skill.needsAttention > 0)
    .sort((a, b) => b.needsAttention - a.needsAttention)
    .slice(0, 6)
    .map((skill) => ({
      key: skill.id,
      label: skill.label,
      value: skill.needsAttention,
    }));
  const range =
    RANGES.find((item) => item.key === filters.range)?.label ?? "90 days";
  const address = (next: Partial<Filters> = {}, nextOffset = 0) => {
    const merged = { ...filters, ...next };
    const query = new URLSearchParams();
    query.set("organisation", organisation.id);
    if (merged.range !== "90d") query.set("range", merged.range);
    for (const name of ["person", "team", "outcome", "language"] as const) {
      const value = merged[name];
      if (value) query.set(name, value);
    }
    if (nextOffset) query.set("offset", String(nextOffset));
    return `/company?${query}`;
  };
  const page = (nextOffset: number) => address({}, nextOffset);
  return (
    <Page wide>
      <PageHeader
        title="Company view"
        context={[
          organisation.name,
          range,
          `${count(totals.calls)} calls · ${count(totals.people)} people`,
          data.synthetic ? (
            <Badge key="synthetic" tone="warn">
              Synthetic sandbox data
            </Badge>
          ) : null,
        ]}
      />
      <CompanyControls
        organisations={organisations}
        organisation={organisation.id}
        filters={filters}
        facets={data.facets}
      />
      <PrepareCalls organisation={organisation.id} pending={data.pending} />
      <Tiles label="This period">
        <Kpi
          label="Calls analysed"
          value={count(totals.calls)}
          delta={
            previous ? (
              <Delta value={totals.calls} previous={previous.calls} />
            ) : null
          }
          note={`${minutes(totals.minutes)} · ${count(totals.people)} people`}
        />
        <Kpi
          label="Agreed a next step"
          value={percent(totals.nextStepShare)}
          delta={points(totals.nextStepShare, previous?.nextStepShare ?? null)}
          note={`${count(totals.nextStep)} calls`}
        />
        <Kpi
          label="Won"
          value={count(totals.won)}
          delta={
            previous ? (
              <Delta value={totals.won} previous={previous.won} />
            ) : null
          }
          note={
            value
              ? `${percent(totals.winShare)} · ${value} quoted`
              : percent(totals.winShare)
          }
        />
        <Kpi
          label="Skills needing attention"
          value={percent(totals.needsAttentionShare)}
          delta={points(
            totals.needsAttentionShare,
            previous?.needsAttentionShare ?? null,
          )}
          note="Lower is better"
        />
      </Tiles>
      <Panel
        title="Calls over time"
        sub={`By ${data.window.unit}`}
        tools={
          <Why detail="Outcomes and skill states are what each call's report says, added up: a guide for coaching, never an official score (AC-SVAL)." />
        }
      >
        <div className={styles.inset}>
          {data.trend.length ? (
            <Trend data={data} />
          ) : (
            <p className={styles.muted}>No calls in this period.</p>
          )}
        </div>
      </Panel>
      <div className={styles.grid}>
        <Panel title="How calls ended" sub="As each report read it">
          <div className={styles.inset}>
            <Bars
              rows={[
                {
                  key: "calls",
                  label: "Calls analysed",
                  value: totals.calls,
                  note: "100%",
                },
                {
                  key: "next",
                  label: "Agreed a next step",
                  value: totals.nextStep,
                  note: percent(totals.nextStepShare),
                },
                {
                  key: "won",
                  label: "Won",
                  value: totals.won,
                  note: percent(totals.winShare),
                },
              ]}
            />
            <Bars rows={outcomes} />
          </div>
        </Panel>
        <Panel
          title="Skills across the calls"
          sub="Observed share; calls needing attention"
        >
          <div className={styles.inset}>
            <ul className={styles.skills}>
              {data.skills.map((skill) => {
                const observed = skill.strong + skill.observed;
                const whole = observed + skill.needsAttention + skill.unknown;
                return (
                  <li key={skill.id}>
                    <span>{skill.label}</span>
                    <span className={styles.split} aria-hidden="true">
                      <i data-key="observed" style={{ flexGrow: observed }} />
                      <i
                        data-key="attention"
                        style={{ flexGrow: skill.needsAttention }}
                      />
                      <i
                        data-key="unknown"
                        style={{ flexGrow: skill.unknown }}
                      />
                    </span>
                    <span className={styles.value}>
                      {percent(whole ? observed / whole : null)}
                      <small>
                        {skill.needsAttention
                          ? `${count(skill.needsAttention)} need work`
                          : "—"}
                      </small>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        </Panel>
      </div>
      <Panel
        title={data.teams.length ? "People (and teams)" : "People"}
        sub={`${count(data.people.length)} with calls · skill cells: share observed, amber marks gaps`}
      >
        <Table label="People">
          <thead>
            <tr>
              <th scope="col">Person</th>
              {data.teams.length ? <th scope="col">Team</th> : null}
              <th scope="col" data-num="">
                Calls
              </th>
              <th scope="col" data-num="">
                Next step
              </th>
              <th scope="col" data-num="">
                Won
              </th>
              <th scope="col" data-num="">
                Talk
              </th>
              {SKILLS.map((skill) => (
                <th key={skill.id} scope="col" className={styles.heatHead}>
                  {skill.short}
                </th>
              ))}
              <th scope="col">Skills trend</th>
            </tr>
          </thead>
          <tbody>
            {data.people.slice(0, 40).map((person) => {
              const trend = change(person.needsAttentionChange);
              return (
                <tr key={person.key ?? person.name}>
                  <th scope="row">
                    {person.key ? (
                      <Link href={address({ person: person.key })}>
                        {person.name}
                      </Link>
                    ) : (
                      person.name
                    )}
                  </th>
                  {data.teams.length ? <td>{person.team ?? "—"}</td> : null}
                  <td data-num="">{count(person.calls)}</td>
                  <td data-num="">
                    {percent(
                      person.calls ? person.nextStep / person.calls : null,
                    )}
                  </td>
                  <td data-num="">{count(person.won)}</td>
                  <td data-num="">
                    {person.talkShare === null ? "—" : `${person.talkShare}%`}
                  </td>
                  <HeatCells group={person} />
                  <td className={styles.trendCell} data-trend={trend.tone}>
                    {trend.text}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      </Panel>
      <div className={styles.grid}>
        <Panel title="Objections" sub="What prospects pushed back on">
          <div className={styles.inset}>
            {data.objections.length ? (
              <Bars
                rows={data.objections.map((row) => ({
                  key: row.kind,
                  label: row.label,
                  value: row.calls,
                  note: `${percent(row.calls ? row.won / row.calls : null)} won`,
                }))}
              />
            ) : (
              <p className={styles.muted}>
                No objections recorded in these calls.
              </p>
            )}
          </div>
        </Panel>
        <Panel
          title={
            data.mistakes.length
              ? "Common mistakes"
              : "Skills most often needing work"
          }
          sub={
            data.mistakes.length
              ? "The main mistake in each call"
              : "Calls where the skill needed attention"
          }
        >
          <div className={styles.inset}>
            {data.mistakes.length ? (
              <Bars
                rows={data.mistakes.map((row) => ({
                  key: row.kind,
                  label: row.label,
                  value: row.calls,
                }))}
              />
            ) : attention.length ? (
              <Bars rows={attention} />
            ) : (
              <p className={styles.muted}>
                No skill needed attention in these calls.
              </p>
            )}
          </div>
        </Panel>
      </div>
      <div className={styles.grid}>
        <Panel title="Strongest calls" sub="Fewest skills needing attention">
          <CallList rows={data.strongest} />
        </Panel>
        <Panel title="Calls to review" sub="Most skills needing attention">
          <CallList rows={data.weakest} />
        </Panel>
      </div>
      <Panel
        title="Calls"
        sub={
          calls
            ? `${count(calls.total)} in this view · newest first`
            : undefined
        }
        foot={
          calls && (offset > 0 || calls.nextOffset !== null) ? (
            <span className={styles.pager}>
              {offset > 0 ? (
                <Link href={page(Math.max(0, offset - 50))}>Newer 50</Link>
              ) : null}
              <span className={styles.muted}>
                {count(offset + 1)}–{count(offset + calls.items.length)} of{" "}
                {count(calls.total)}
              </span>
              {calls.nextOffset !== null ? (
                <Link href={page(calls.nextOffset)}>Older 50</Link>
              ) : null}
            </span>
          ) : undefined
        }
      >
        {callsError ? <Unavailable title="Calls" reason={callsError} /> : null}
        {calls ? (
          <Table label="Calls">
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Person</th>
                <th scope="col">Outcome</th>
                <th scope="col" data-num="">
                  Length
                </th>
                <th scope="col" data-num="">
                  Talk
                </th>
                <th scope="col">Skills</th>
                <th scope="col">Objections</th>
              </tr>
            </thead>
            <tbody>
              {calls.items.map((row) => (
                <tr key={row.key}>
                  <td>{dateLabel(row.at, true)}</td>
                  <td>
                    {row.person}
                    {row.team ? (
                      <small className={styles.sub}>{row.team}</small>
                    ) : null}
                  </td>
                  <td>{outcomeLabel(row.outcome)}</td>
                  <td data-num="">{duration(row.durationMs)}</td>
                  <td data-num="">
                    {row.talkShare === null ? "—" : `${row.talkShare}%`}
                  </td>
                  <td>
                    <SkillDots skills={row.skills} />
                  </td>
                  <td className={styles.objections}>
                    {row.objections.length
                      ? row.objections
                          .map((item) => item.replace(/_/g, " "))
                          .join(", ")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : null}
      </Panel>
      <p className={styles.footnote}>
        Outcomes and skill states are what each call&apos;s report says, added
        up.
        {data.synthetic
          ? " This organisation is the synthetic sandbox: every call, person and company is fictional."
          : " Talk share counts only calls where the rep confirmed who the seller was."}{" "}
        Internal: never an official score.
      </p>
    </Page>
  );
}
