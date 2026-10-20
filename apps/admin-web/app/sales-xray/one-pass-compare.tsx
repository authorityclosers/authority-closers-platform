/**
 * Today's pipeline (classic) and the Google-only one-pass pipeline, side by
 * side: per call (cost, tokens and time per stage; facts, pointer scores,
 * coaching points, the eight dimensions; the six contracts) and across calls.
 * Presentational and pure: the pages read the API and pass normalized data.
 */
import Link from "next/link";

import { Badge, Kpi, Panel, Table, Tiles } from "../ui/kit";
import {
  CONTRACTS,
  inr,
  share,
  took,
  type CompareLine,
  type Compared,
  type Side,
  type Summary,
} from "./one-pass-data";
import styles from "./one-pass.module.css";

const perMinute = (value: number | null) =>
  value === null ? "—" : `${inr(value)}/min`;

export function SummaryTiles({
  title,
  summary,
}: {
  title: string;
  summary: Summary;
}) {
  if (!summary.calls)
    return (
      <Panel title={title} sub="No compared calls yet">
        <p className={styles.note}>
          A call appears here once both pipelines have read it.
        </p>
      </Panel>
    );
  const { classic, onePass, agreement } = summary;
  return (
    <Panel
      title={title}
      sub={`${summary.calls} calls · ${summary.audioMinutes.toFixed(1)} audio minutes · list-price estimates`}
    >
      <Tiles label={`${title}: cost`}>
        <Kpi label="Today's pipeline" value={perMinute(classic.perMinuteInr)} />
        <Kpi
          label="One pass, as run"
          value={perMinute(onePass.perMinuteInr)}
          tone="good"
        />
        <Kpi
          label="One pass, standard"
          value={perMinute(onePass.standardPerMinuteInr)}
        />
        <Kpi
          label="One pass, Flex"
          value={perMinute(onePass.flexPerMinuteInr)}
        />
      </Tiles>
      <Tiles label={`${title}: quality and time`}>
        {classic.factRecall !== null || onePass.factRecall !== null ? (
          <Kpi
            label="Fact recall (judge), today → one pass"
            value={`${share(classic.factRecall)} → ${share(onePass.factRecall)}`}
          />
        ) : null}
        {classic.truthCoverage !== null || onePass.truthCoverage !== null ? (
          <Kpi
            label="Coaching truths covered, today → one pass"
            value={`${share(classic.truthCoverage)} → ${share(onePass.truthCoverage)}`}
          />
        ) : null}
        <Kpi label="Facts found by both" value={share(agreement.factOverlap)} />
        <Kpi
          label="Pointer verdicts that agree"
          value={share(agreement.pointerStatus)}
        />
        <Kpi
          label="Dimension states that agree"
          value={share(agreement.dimensionStatus)}
        />
        <Kpi
          label="Contracts passed"
          value={
            onePass.contractsChecked
              ? `${onePass.contractsPassed} of ${onePass.contractsChecked}`
              : "—"
          }
        />
        <Kpi
          label="Median time, today → one pass"
          value={`${took(classic.medianMs)} → ${took(onePass.medianMs)}`}
        />
      </Tiles>
    </Panel>
  );
}

const stateTone = (state: string | null) =>
  state === "succeeded" || state === "done"
    ? "good"
    : state === "failed"
      ? "bad"
      : "neutral";

export function CompareTable({ items }: { items: CompareLine[] }) {
  return (
    <Table label="Compared calls">
      <thead>
        <tr>
          <th scope="col">Call</th>
          <th scope="col">Length</th>
          <th scope="col">Today</th>
          <th scope="col">One pass</th>
          <th scope="col">Contracts</th>
          <th scope="col">Facts in both</th>
          <th scope="col">Pointers agree</th>
          <th scope="col">Time, today → one pass</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={`${item.kind}-${item.subject}`}>
            <th scope="row">
              <Link href={`/sales-xray/one-pass/${item.subject}`}>
                {item.kind === "bench"
                  ? `Fictional ${item.subject}`
                  : item.subject.slice(0, 8)}
              </Link>
            </th>
            <td>{took(item.audioMs)}</td>
            <td>{inr(item.classic.costInr) || "—"}</td>
            <td>
              {item.onePass.state === "succeeded" ? (
                inr(item.onePass.costInr)
              ) : (
                <Badge tone={stateTone(item.onePass.state)}>
                  {item.onePass.reason
                    ? `${item.onePass.state}: ${item.onePass.reason}`
                    : (item.onePass.state ?? "not yet")}
                </Badge>
              )}
            </td>
            <td>
              {item.onePass.state === "succeeded"
                ? `${item.onePass.contractsOk}/6`
                : "—"}
            </td>
            <td>{share(item.factOverlap)}</td>
            <td>{share(item.pointerAgreement)}</td>
            <td>
              {took(item.classic.durationMs)} → {took(item.onePass.durationMs)}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function Stages({ side }: { side: Side }) {
  return (
    <Table label={`${side.pipeline} stages`}>
      <thead>
        <tr>
          <th scope="col">Stage</th>
          <th scope="col">Model</th>
          <th scope="col">Tokens in / out</th>
          <th scope="col">Time</th>
          <th scope="col">Cost</th>
        </tr>
      </thead>
      <tbody>
        {side.stages.map((stage) => (
          <tr key={stage.key}>
            <th scope="row">
              {stage.label}
              {stage.note ? (
                <small className={styles.note}>{stage.note}</small>
              ) : null}
            </th>
            <td>
              {stage.model ?? "—"}
              {stage.tier && stage.tier !== "standard" ? (
                <Badge tone="info">{stage.tier}</Badge>
              ) : null}
            </td>
            <td>
              {stage.tokensIn === null && stage.tokensOut === null
                ? "—"
                : `${(stage.tokensIn ?? 0).toLocaleString("en-IN")} / ${(stage.tokensOut ?? 0).toLocaleString("en-IN")}`}
            </td>
            <td>{took(stage.ms)}</td>
            <td>{inr(stage.inr) || "—"}</td>
          </tr>
        ))}
        <tr>
          <th scope="row">All</th>
          <td />
          <td>
            {side.tokensIn.toLocaleString("en-IN")} /{" "}
            {side.tokensOut.toLocaleString("en-IN")}
          </td>
          <td>{took(side.durationMs)}</td>
          <td>
            {inr(side.costInr) || "—"}
            {side.perMinuteInr !== null ? (
              <small className={styles.note}>
                {perMinute(side.perMinuteInr)}
              </small>
            ) : null}
          </td>
        </tr>
      </tbody>
    </Table>
  );
}

function SideCard({ title, side }: { title: string; side: Side | null }) {
  if (!side)
    return (
      <Panel title={title} sub="Not read yet">
        <p className={styles.note}>No result for this side yet.</p>
      </Panel>
    );
  return (
    <Panel
      title={title}
      sub={[
        side.transcript
          ? `${side.transcript.source}: ${side.transcript.segments} turns, ${side.transcript.speakers} speakers, ${side.transcript.words} words`
          : "No transcript",
        side.c4Observations !== null ? `${side.c4Observations} C4 facts` : null,
        side.pointers?.overall !== null && side.pointers?.overall !== undefined
          ? `pointer score ${side.pointers.overall}`
          : null,
      ]
        .filter(Boolean)
        .join(" · ")}
    >
      {side.state && side.state !== "succeeded" && side.state !== "done" ? (
        <Badge tone={stateTone(side.state)}>
          {side.reason ? `${side.state}: ${side.reason}` : side.state}
        </Badge>
      ) : null}
      <Stages side={side} />
      {side.checks ? (
        <ul className={styles.checks} aria-label="Contracts">
          {CONTRACTS.map((contract) => {
            const value = side.checks?.[contract.key];
            return (
              <li key={contract.key}>
                <Badge
                  tone={value === "ok" ? "good" : value ? "bad" : "neutral"}
                >
                  {value === "ok" ? "passes" : (value ?? "not checked")}
                </Badge>{" "}
                {contract.label}
              </li>
            );
          })}
        </ul>
      ) : null}
      {side.coaching ? (
        <div className={styles.coaching}>
          {side.coaching.summary ? <p>{side.coaching.summary}</p> : null}
          <Points title="Strengths" items={side.coaching.strengths} />
          <Points title="Improvements" items={side.coaching.improvements} />
          <Points title="Missed opportunities" items={side.coaching.missed} />
        </div>
      ) : null}
    </Panel>
  );
}

function Points({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <>
      <h4 className={styles.pointsTitle}>
        {title} ({items.length})
      </h4>
      <ul className={styles.points}>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </>
  );
}

export function CompareDetail({ data }: { data: Compared }) {
  return (
    <>
      <Tiles label="This call">
        <Kpi
          label="Cost, today → one pass"
          value={`${inr(data.classic?.costInr) || "—"} → ${inr(data.onePass?.costInr) || "—"}`}
          tone={
            data.costSavingInr !== null && data.costSavingInr > 0
              ? "good"
              : undefined
          }
        />
        <Kpi label="Facts found by both" value={share(data.facts?.overlap)} />
        <Kpi
          label="Pointer verdicts that agree"
          value={share(data.pointers?.agreement)}
        />
        <Kpi
          label="Mean pointer score gap"
          value={
            data.pointers?.meanScoreGap === null ||
            data.pointers?.meanScoreGap === undefined
              ? "—"
              : `${data.pointers.meanScoreGap} points`
          }
        />
        <Kpi
          label="Dimension states that agree"
          value={share(data.dimensionAgreement)}
        />
        <Kpi
          label="Transcript words, one pass vs today"
          value={share(data.transcript?.wordRatio)}
        />
      </Tiles>
      <div className={styles.sides}>
        <SideCard title="Today's pipeline" side={data.classic} />
        <SideCard title="One pass (Google)" side={data.onePass} />
      </div>
      {data.facts ? (
        <Panel
          title="Facts"
          sub={`${data.facts.both.length} in both · ${data.facts.onlyClassic.length} only today · ${data.facts.onlyOnePass.length} only one pass`}
        >
          <Table label="Facts side by side">
            <thead>
              <tr>
                <th scope="col">Fact</th>
                <th scope="col">Today</th>
                <th scope="col">One pass</th>
              </tr>
            </thead>
            <tbody>
              {data.facts.both.map((fact, index) => (
                <tr key={`both-${fact.type}-${index}`}>
                  <th scope="row">{fact.label}</th>
                  <td>{fact.classic}</td>
                  <td>{fact.onePass}</td>
                </tr>
              ))}
              {data.facts.onlyClassic.map((fact, index) => (
                <tr key={`classic-${fact.type}-${index}`}>
                  <th scope="row">{fact.label}</th>
                  <td>{fact.display}</td>
                  <td className={styles.missing}>—</td>
                </tr>
              ))}
              {data.facts.onlyOnePass.map((fact, index) => (
                <tr key={`one-${fact.type}-${index}`}>
                  <th scope="row">{fact.label}</th>
                  <td className={styles.missing}>—</td>
                  <td>{fact.display}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Panel>
      ) : null}
      {data.pointers ? (
        <Panel
          title="The 27 pointers"
          sub={`${share(data.pointers.agreement)} agree · AI drafts, not official scores`}
        >
          <Table label="Pointer scores side by side">
            <thead>
              <tr>
                <th scope="col">Pointer</th>
                <th scope="col">Today</th>
                <th scope="col">One pass</th>
              </tr>
            </thead>
            <tbody>
              {data.pointers.rows.map((row) => (
                <tr
                  key={row.id}
                  className={row.same ? undefined : styles.differs}
                >
                  <th scope="row">{row.label}</th>
                  <td>
                    {row.classic.status}
                    {row.classic.score !== null
                      ? ` · ${row.classic.score}`
                      : ""}
                  </td>
                  <td>
                    {row.onePass.status}
                    {row.onePass.score !== null
                      ? ` · ${row.onePass.score}`
                      : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Panel>
      ) : null}
      {data.dimensions.length ? (
        <Panel
          title="The eight dimensions"
          sub={`${share(data.dimensionAgreement)} agree`}
        >
          <Table label="Dimensions side by side">
            <thead>
              <tr>
                <th scope="col">Dimension</th>
                <th scope="col">Today</th>
                <th scope="col">One pass</th>
              </tr>
            </thead>
            <tbody>
              {data.dimensions.map((row) => (
                <tr
                  key={row.id}
                  className={
                    row.classic === row.onePass ? undefined : styles.differs
                  }
                >
                  <th scope="row">{row.id.replaceAll("_", " ")}</th>
                  <td>{row.classic}</td>
                  <td>{row.onePass ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Panel>
      ) : null}
    </>
  );
}
