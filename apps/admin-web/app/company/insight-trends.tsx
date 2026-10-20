/**
 * The company view's trends from real data (Insights, orchestrator 20 Oct):
 * calls and the mean AI pointer score week by week, each skill's score over
 * time, how far leads got along the business's own stages, and each
 * salesperson's calls and scores. Every figure shows the count it comes from;
 * an empty panel says why it is empty. Internal reads, never an official score.
 */
import { Meter, Panel, Spark, Table, Why } from "../ui/kit";
import type { AnalysisInsights, PersonTrend } from "./analysis-data";
import styles from "./insight-trends.module.css";

/** Skill-by-week columns shown at most (the newest weeks). */
export const SKILL_WEEKS = 12;

const WEEK = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

/** "2026-10-12" → "12 Oct". */
export function weekLabel(week: string): string {
  const time = Date.parse(`${week}T00:00:00Z`);
  return Number.isNaN(time) ? week : WEEK.format(time);
}

const share = (value: number | null) =>
  value === null ? "—" : `${Math.round(value * 100)}%`;

/** Score bands for the skill cells: below 50 needs work, 70 and up is good. */
export function band(score: number | null): "low" | "mid" | "high" | "none" {
  if (score === null) return "none";
  return score < 50 ? "low" : score < 70 ? "mid" : "high";
}

export function WeeklyPanel({ data }: { data: AnalysisInsights }) {
  const weeks = data.weeks;
  const peak = Math.max(1, ...weeks.map((week) => week.calls));
  const scored = weeks.reduce((sum, week) => sum + week.scored, 0);
  const every = Math.max(1, Math.ceil(weeks.length / 8));
  const empty = !data.calls;
  return (
    <Panel
      title="Calls and scores by week"
      sub={`${data.calls} calls · ${data.callsAnalysed} read by the engine · ${data.callsScored} scored · weeks start Monday, India time`}
      tools={
        <Why detail="Bars: calls made each week, the darker part read by the call data engine. Dots: the mean AI pointer score of that week's scored calls (0 to 100), with how many calls it comes from." />
      }
    >
      {empty ? (
        <p className={styles.none}>
          No calls were uploaded in this window, so there is nothing to trend.
        </p>
      ) : (
        <div className={styles.weekly}>
          <div
            className={styles.bars}
            role="img"
            aria-label={`Calls per week: ${weeks
              .map((week) => `${weekLabel(week.week)} ${week.calls}`)
              .join(", ")}`}
          >
            {weeks.map((week) => (
              <span
                key={week.week}
                className={styles.week}
                title={`Week of ${weekLabel(week.week)}: ${week.calls} calls, ${week.analysed} read, ${week.scored} scored${
                  week.average === null
                    ? ""
                    : `, mean score ${week.average} from ${week.scored} calls`
                }`}
              >
                <i style={{ height: `${(week.calls / peak) * 100}%` }}>
                  <b
                    style={{
                      height: `${week.calls ? (week.analysed / week.calls) * 100 : 0}%`,
                    }}
                  />
                </i>
              </span>
            ))}
          </div>
          <div className={styles.scores} aria-label="Mean AI score by week">
            {weeks.map((week) => (
              <span
                key={week.week}
                data-band={band(week.average)}
                title={
                  week.average === null
                    ? `Week of ${weekLabel(week.week)}: no scored calls`
                    : `Week of ${weekLabel(week.week)}: ${week.average} from ${week.scored} calls`
                }
              >
                {week.average ?? "·"}
              </span>
            ))}
          </div>
          <div className={styles.axis} aria-hidden="true">
            {weeks.map((week, index) => (
              <span key={week.week}>
                {index % every === 0 ? weekLabel(week.week) : ""}
              </span>
            ))}
          </div>
          {!scored ? (
            <p className={styles.note}>
              No call in this window has an AI pointer review yet, so there are
              no scores: a call is scored after its report is ready.
            </p>
          ) : null}
        </div>
      )}
    </Panel>
  );
}

export function SkillWeeksPanel({ data }: { data: AnalysisInsights }) {
  const shown = data.weeks.slice(-SKILL_WEEKS).map((week) => week.week);
  const rows = data.skillWeeks.map((skill) => ({
    label: skill.label,
    cells: shown.map(
      (week) =>
        skill.weeks.find((entry) => entry.week === week) ?? {
          week,
          average: null,
          calls: 0,
        },
    ),
  }));
  return (
    <Panel
      title="Skill scores over time"
      sub={`Mean AI pointer score per skill and week, weakest skill first · ${data.callsScored} calls scored${
        data.weeks.length > SKILL_WEEKS ? ` · newest ${SKILL_WEEKS} weeks` : ""
      }`}
      tools={
        <Why detail="Each call's newest AI pointer review, by the week the call was made. The small number under a score is how many calls it comes from; one or two calls is a thin sample." />
      }
    >
      {rows.length ? (
        <Table label="Skill scores over time">
          <thead>
            <tr>
              <th scope="col">Skill</th>
              {shown.map((week) => (
                <th key={week} scope="col" data-num="">
                  {weekLabel(week)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <th scope="row">{row.label}</th>
                {row.cells.map((cell) => (
                  <td
                    key={cell.week}
                    data-num=""
                    className={styles.cell}
                    data-band={band(cell.average)}
                    title={
                      cell.average === null
                        ? "No scored calls"
                        : `${cell.average} from ${cell.calls} ${cell.calls === 1 ? "call" : "calls"}`
                    }
                  >
                    {cell.average ?? "—"}
                    {cell.calls ? <small>{cell.calls}</small> : null}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
      ) : (
        <p className={styles.none}>
          No AI pointer reviews in this window yet: a call is scored after its
          report is ready, so skill trends start with the first scored call.
        </p>
      )}
    </Panel>
  );
}

export function FunnelPanel({ data }: { data: AnalysisInsights }) {
  const { stages } = data;
  return (
    <Panel
      title="Lead stages"
      sub={`${stages.leads} leads created in this window · ${
        stages.version
          ? `the organisation's own stages (version ${stages.version})`
          : "Lead Desk's default stages (no stages of its own saved)"
      }`}
      tools={
        <Why detail="How far each lead got: its stage now, or the furthest stage its Lead Desk history reached. Each row: leads that got at least that far, their share of all leads, and of the row above. Test leads are left out." />
      }
    >
      {stages.leads && stages.funnel.length ? (
        <div className={styles.funnel}>
          <ol>
            {stages.funnel.map((stage) => (
              <li key={stage.key}>
                <span className={styles.stage}>{stage.label}</span>
                <Meter
                  value={stage.reached}
                  max={stages.leads}
                  label={`${stage.label}: ${stage.reached} of ${stages.leads} leads`}
                />
                <span className={styles.count}>
                  {stage.reached}
                  <small>
                    {share(stage.share)} of leads
                    {stage.fromPrevious === null
                      ? ""
                      : ` · ${share(stage.fromPrevious)} of the stage before`}
                  </small>
                </span>
              </li>
            ))}
          </ol>
          <p className={styles.note}>
            Beside the funnel now: {stages.unreachable} couldn&rsquo;t be
            reached · {stages.lost} lost
          </p>
        </div>
      ) : (
        <p className={styles.none}>
          No leads were created in Lead Desk in this window, so there is no
          stage conversion to show.
        </p>
      )}
    </Panel>
  );
}

function weakest(person: PersonTrend) {
  if (!person.weakest) return "—";
  const { label, average, calls } = person.weakest;
  return `${label} · ${average} (${calls} ${calls === 1 ? "call" : "calls"})`;
}

export function PeoplePanel({ data }: { data: AnalysisInsights }) {
  return (
    <Panel
      title="Salespeople, from the analysis"
      sub={`${data.people.length} with calls in the last ${data.days} days · most calls first · scores from the AI pointer review`}
      tools={
        <Why detail="Each salesperson's calls in the window, how many the engine read and the AI pointer review scored, their mean score, how often a skill needed work, and their weakest skill with the calls behind it." />
      }
    >
      {data.people.length ? (
        <Table label="Salespeople, from the analysis">
          <thead>
            <tr>
              <th scope="col">Salesperson</th>
              <th scope="col" data-num="">
                Calls
              </th>
              <th scope="col">By week</th>
              <th scope="col" data-num="">
                Read / scored
              </th>
              <th scope="col" data-num="">
                Mean score
              </th>
              <th scope="col" data-num="">
                Needs work
              </th>
              <th scope="col">Weakest skill</th>
            </tr>
          </thead>
          <tbody>
            {data.people.map((person) => (
              <tr key={person.personId}>
                <th scope="row">{person.name}</th>
                <td data-num="">{person.calls}</td>
                <td className={styles.spark}>
                  <Spark
                    values={person.weeks}
                    label={`${person.name}: calls per week`}
                  />
                </td>
                <td data-num="">
                  {person.analysed} / {person.scored}
                </td>
                <td
                  data-num=""
                  className={styles.cell}
                  data-band={band(person.average)}
                >
                  {person.average ?? "—"}
                </td>
                <td data-num="">{share(person.needsWorkShare)}</td>
                <td>{weakest(person)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : (
        <p className={styles.none}>
          No salesperson uploaded a call in this window.
        </p>
      )}
    </Panel>
  );
}
