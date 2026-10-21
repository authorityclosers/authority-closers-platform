import { adminRead } from "@/app/lib/server-api";
import {
  Badge,
  Kpi,
  Page,
  PageHeader,
  Panel,
  Table,
  Tiles,
  Unavailable,
  Why,
} from "@/app/ui/kit";

import {
  CATEGORY_LABELS,
  READINESS,
  decimal,
  lean,
  normalizeBrain4,
  percent,
  ratio,
  withInterval,
  type Checkpoint,
} from "./brain4-data";

export const dynamic = "force-dynamic";

const HOW =
  "Each line is one of the coaching lead's phone-review answers on a pointer of a real call. " +
  "A dimension is compared through the pointers that ask its question. Exact: the same band " +
  "(needs improvement, average, good, excellent; Brain 4.0's 5 is excellent, 4 good, 3 average, " +
  "1-2 needs improvement). Intervals resample whole calls. Kappa is quadratic weighted kappa.";

const DIMENSIONS: Record<string, string> = {
  D01: "Starting the Call",
  D02: "Setting the Plan",
  D03: "Tone, Pace & Pauses",
  D04: "Listening Well",
  D05: "Asking the Right Questions",
  D06: "Building Connection",
  D07: "Being Professional",
  D08: "Finding the Decision-Makers",
  D09: "Understanding Problems & Goals",
  D10: "Understanding What They're Doing Now",
  D11: "Understanding the Real Impact",
  D12: "Understanding How They Will Decide",
  D13: "Matching the Right Solution",
  D14: "Explaining the Solution Clearly",
  D15: "Talking About Price & Budget",
  D16: "Handling Objections",
  D17: "Asking for the Decision",
  D18: "Setting Clear Next Steps",
};

/** A fixed evaluation on an earlier gold set: how each pipeline agrees with the coach. */
function CheckpointPanel({ point }: { point: Checkpoint }) {
  const labels = point.labels;
  const dimensions = Object.keys(DIMENSIONS).filter((id) =>
    point.scorers.some((scorer) => scorer.dimensions[id]?.labels),
  );
  const empty = { agree: 0, rated: 0 };
  return (
    <Panel
      title={`Checkpoint · ${point.title || point.checkpoint}`}
      sub={`${point.date} · ${point.calls} calls · ${labels.total ?? 0} labels from ${point.notes_mapped} notes (${labels.positive ?? 0} praise, ${labels.negative ?? 0} criticism, ${labels.mixed ?? 0} mixed)`}
      tools={<Why detail={point.source} more={point.limits.join(" ")} />}
    >
      <Table label="Agreement with the coach by pipeline">
        <thead>
          <tr>
            <th scope="col">Pipeline</th>
            <th scope="col">Agrees with the coach</th>
            <th scope="col" data-num="">
              Praise kept
            </th>
            <th scope="col" data-num="">
              Criticism caught
            </th>
            <th scope="col" data-num="">
              Mixed
            </th>
            <th scope="col" data-num="">
              Rated
            </th>
          </tr>
        </thead>
        <tbody>
          {point.scorers.map((scorer) => (
            <tr key={scorer.scorer}>
              <th scope="row">{scorer.scorer}</th>
              <td>
                {withInterval(scorer.overall.agreement, scorer.overall.wilson)}
              </td>
              <td data-num="">{ratio(scorer.by_label.positive ?? empty)}</td>
              <td data-num="">{ratio(scorer.by_label.negative ?? empty)}</td>
              <td data-num="">{ratio(scorer.by_label.mixed ?? empty)}</td>
              <td data-num="">
                {scorer.overall.rated}/{scorer.overall.labels}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      <Table label="Agreement with the coach by dimension">
        <thead>
          <tr>
            <th scope="col">Dimension</th>
            {point.scorers.map((scorer) => (
              <th scope="col" data-num="" key={scorer.scorer}>
                {scorer.scorer}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dimensions.map((id) => (
            <tr key={id}>
              <th scope="row">
                {id} {DIMENSIONS[id]}
              </th>
              {point.scorers.map((scorer) => (
                <td data-num="" key={scorer.scorer}>
                  {ratio(scorer.dimensions[id] ?? empty)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </Table>
    </Panel>
  );
}

/**
 * Brain 4.0 (the coaching lead's 18-dimension rubric) against his gold set, beside
 * today's pointer review on the same lines. Internal evidence for the AC-SVAL
 * gates: never an official score and never shown to reps.
 */
export default async function Brain4EvaluationPage() {
  const result = await adminRead(
    "/v1/admin/conversation/gold-evaluation",
    normalizeBrain4,
  );
  const data = result.ok ? result.data : null;
  const accepted = data?.classic_acceptance;
  return (
    <Page>
      <PageHeader
        title="Brain 4.0 evaluation"
        back={{ href: "/gold", label: "Gold set" }}
        context={[
          "Brain 4.0 and today's pointer review against the gold set",
          data?.rubric_revision ?? null,
        ]}
        actions={<Badge tone="warn">Beta · not an official score</Badge>}
      />
      {!result.ok ? (
        <Unavailable title="The Brain 4.0 evaluation" reason={result.error} />
      ) : null}
      {data && accepted ? (
        <>
          <Tiles label="Gold set">
            <Kpi
              label="Gold calls"
              value={data.gold.calls}
              note={`${data.gold.lines} current answers`}
            />
            <Kpi
              label="Calls with Brain 4.0"
              value={data.gold.calls_with_brain4}
              note="gold calls Brain 4.0 has read"
            />
            <Kpi
              label="Today's review accepted"
              value={percent(accepted.agree_rate)}
              note={withInterval(accepted.agree_rate, accepted.agree_ci)}
            />
            <Kpi
              label="Agreement alerts"
              value={data.alerts.length}
              tone={data.alerts.length ? "bad" : undefined}
              note={
                data.alerts.length
                  ? "agreement fell recently"
                  : "no recent fall"
              }
            />
          </Tiles>
          {data.alerts.length ? (
            <Panel title="Agreement fell">
              <ul>
                {data.alerts.map((alert) => (
                  <li key={`${alert.scorer}-${alert.dimension ?? "all"}`}>
                    {alert.scorer === "classic"
                      ? "Today's pointer review"
                      : `Brain 4.0 ${alert.dimension}`}
                    : {percent(alert.before)} before, {percent(alert.recent)} in
                    the newest answers
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
          <Panel
            title="By dimension"
            sub="Brain 4.0 against the gold band, and today's review on the same lines"
            tools={<Why detail={HOW} more={data.limits.join(" ")} />}
          >
            <Table label="Brain 4.0 agreement by dimension">
              <thead>
                <tr>
                  <th scope="col">Dimension</th>
                  <th scope="col" data-num="">
                    Calls · lines
                  </th>
                  <th scope="col">Brain 4.0 exact</th>
                  <th scope="col">Today exact</th>
                  <th scope="col" data-num="">
                    Within one
                  </th>
                  <th scope="col">Weighted kappa</th>
                  <th scope="col">Lean</th>
                  <th scope="col">State</th>
                </tr>
              </thead>
              <tbody>
                {data.dimensions.map((row) => {
                  const state =
                    READINESS[row.readiness.state] ?? READINESS.beta;
                  return (
                    <tr key={row.id}>
                      <th scope="row">
                        {row.id} {row.label}
                        <br />
                        <small>
                          {CATEGORY_LABELS[row.category] ?? row.category} ·{" "}
                          {row.pointers.join(", ").replaceAll("_", " ")}
                        </small>
                      </th>
                      <td data-num="">
                        {row.brain4.calls} · {row.brain4.lines}
                      </td>
                      <td>
                        {withInterval(row.brain4.exact, row.brain4.exact_ci)}
                      </td>
                      <td>
                        {withInterval(row.classic.exact, row.classic.exact_ci)}
                      </td>
                      <td data-num="">{percent(row.brain4.within_one)}</td>
                      <td>
                        {withInterval(
                          row.brain4.kappa,
                          row.brain4.kappa_ci,
                          (n) => decimal(n),
                        )}
                      </td>
                      <td>{lean(row.brain4.lean)}</td>
                      <td>
                        <Badge tone={state.tone}>{state.label}</Badge>
                        {row.readiness.needs.length ? (
                          <small> {row.readiness.needs.join("; ")}</small>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          </Panel>
          <Panel
            title="Today's pointer review, per pointer"
            sub="how often the reviewer accepts it, and why not"
          >
            <Table label="Acceptance of today's pointer review">
              <thead>
                <tr>
                  <th scope="col">Pointer</th>
                  <th scope="col" data-num="">
                    Agree
                  </th>
                  <th scope="col" data-num="">
                    Partly
                  </th>
                  <th scope="col" data-num="">
                    Disagree
                  </th>
                  <th scope="col">Accepted</th>
                  <th scope="col">Reasons</th>
                </tr>
              </thead>
              <tbody>
                {data.pointers.map((row) => (
                  <tr key={row.target}>
                    <th scope="row">{row.target.replaceAll("_", " ")}</th>
                    <td data-num="">{row.agree}</td>
                    <td data-num="">{row.partly}</td>
                    <td data-num="">{row.disagree}</td>
                    <td>{withInterval(row.agree_rate, row.agree_ci)}</td>
                    <td>
                      {Object.entries(row.reasons)
                        .map(
                          ([reason, count]) =>
                            `${reason.replaceAll("_", " ")} ${count}`,
                        )
                        .join(", ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Panel>
          {data.checkpoints.map((point) => (
            <CheckpointPanel key={point.checkpoint} point={point} />
          ))}
          {Object.keys(data.stability).length ? (
            <Panel
              title="Run to run"
              sub="repeated Brain 4.0 reads of one call giving the same rating"
            >
              <Table label="Brain 4.0 stability">
                <thead>
                  <tr>
                    <th scope="col">Dimension</th>
                    <th scope="col" data-num="">
                      Calls
                    </th>
                    <th scope="col" data-num="">
                      Same rating
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.stability).map(([id, row]) => (
                    <tr key={id}>
                      <th scope="row">{id}</th>
                      <td data-num="">{row.calls}</td>
                      <td data-num="">{percent(row.same)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Panel>
          ) : null}
        </>
      ) : null}
    </Page>
  );
}
