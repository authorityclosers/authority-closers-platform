/**
 * The company view's real analysis (Phase 4, owner 19 Oct: "every skill reads
 * 100% and there are 0 objections"): what buyers said, what was promised, how
 * decisions and interest stood (call data engine), and each skill's AI pointer
 * score, weakest first. Internal reads of AI output, never an official score.
 */
import { Meter, Panel, Table, Why } from "../ui/kit";
import type { AnalysisInsights, Said, SkillScore } from "./analysis-data";
import styles from "./analysis-panels.module.css";

const SAID_TITLE: Record<keyof AnalysisInsights["said"], string> = {
  objections: "Objections",
  questions: "Questions",
  pains: "Pains",
  goals: "Goals",
};

export const SKILL_WHY =
  "Each call's newest AI pointer review: the average score per skill and how often it was not marked good. The reports' own skill states mark every skill observed, which says nothing about quality.";

const COMMITMENT_LABEL: Record<string, string> = {
  next_step: "Next step agreed",
  follow_up: "Follow-up set",
  seller_promise: "Seller promised",
  prospect_promise: "Prospect promised",
};

const READING_LABEL: Record<string, string> = {
  decision: "Decision",
  interest: "Interest",
  urgency: "Urgency",
  outcome: "Outcome",
};

function SaidList({ title, items }: { title: string; items: Said[] }) {
  return (
    <section className={styles.said} aria-label={title}>
      <h3>{title}</h3>
      {items.length ? (
        <ol>
          {items.map((item) => (
            <li key={item.text}>
              <span>{item.text}</span>
              <small>
                {item.calls} {item.calls === 1 ? "call" : "calls"}
              </small>
            </li>
          ))}
        </ol>
      ) : (
        <p className={styles.none}>None found</p>
      )}
    </section>
  );
}

/** Each skill's AI pointer score, weakest first: the table, or a line when none. */
export function SkillScores({ skills }: { skills: readonly SkillScore[] }) {
  return skills.length ? (
    <Table label="Skill scores">
      <thead>
        <tr>
          <th scope="col">Skill</th>
          <th scope="col">Average</th>
          <th scope="col" data-num="">
            Needs work
          </th>
          <th scope="col" data-num="">
            Calls
          </th>
        </tr>
      </thead>
      <tbody>
        {skills.map((skill) => (
          <tr key={skill.label}>
            <th scope="row">{skill.label}</th>
            <td className={styles.score}>
              <Meter
                value={skill.average}
                max={100}
                label={`${skill.label}: ${skill.average} of 100`}
              />
              <span>{skill.average}</span>
            </td>
            <td data-num="">{Math.round(skill.needsWorkShare * 100)}%</td>
            <td data-num="">{skill.calls}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  ) : (
    <p className={styles.none}>No AI pointer reviews in this window yet.</p>
  );
}

export function AnalysisPanels({
  data,
  skillsShown = false,
}: {
  data: AnalysisInsights;
  /** The company view already shows the skill scores in its own Skills panel. */
  skillsShown?: boolean;
}) {
  const readings = Object.entries(data.readings).filter(
    ([, items]) => items.length,
  );
  return (
    <>
      <Panel
        title="What buyers said"
        sub={`${data.callsAnalysed} calls the engine read · last ${data.days} days · most common wording first`}
        tools={
          <Why detail="From the call data engine's current objects (not superseded, retracted or erased). A wording said in several calls counts once per call." />
        }
      >
        <div className={styles.saidGrid}>
          {(Object.keys(SAID_TITLE) as (keyof AnalysisInsights["said"])[]).map(
            (key) => (
              <SaidList
                key={key}
                title={SAID_TITLE[key]}
                items={data.said[key]}
              />
            ),
          )}
        </div>
      </Panel>
      <div className={styles.pair}>
        {skillsShown ? null : (
          <Panel
            title="Skill scores"
            sub={`AI pointer review · ${data.callsScored} calls scored · weakest first`}
            tools={<Why detail={SKILL_WHY} />}
          >
            <SkillScores skills={data.skills} />
          </Panel>
        )}
        <Panel
          title="Commitments and readings"
          sub="Calls with each, from the engine"
        >
          <dl className={styles.facts}>
            {Object.entries(COMMITMENT_LABEL).map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{data.commitments[key] ?? 0}</dd>
              </div>
            ))}
          </dl>
          {readings.map(([key, items]) => (
            <p key={key} className={styles.reading}>
              <strong>{READING_LABEL[key] ?? key}</strong>
              {items.map((item) => (
                <span key={item.text}>
                  {item.text} <small>{item.calls}</small>
                </span>
              ))}
            </p>
          ))}
        </Panel>
      </div>
    </>
  );
}
