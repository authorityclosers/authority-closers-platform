/**
 * Every stage of one call in one dense table (owner 19 Oct: timings, cost per
 * stage, provider and model, Admin only): its code (C1 to C6), status, when it
 * started after the call arrived, how long it took on a bar against the whole
 * run, attempts, tokens, model and cost. Phones get the same rows as cards.
 */
import { Badge, Card, Table } from "../ui/kit";
import {
  LATER,
  after,
  stageTimeline,
  type DetailStage,
} from "./call-detail-data";
import {
  STAGE_STATUS_LABEL,
  STAGE_STATUS_TONE,
  duration,
  rupees,
} from "./call-map-data";
import styles from "./stage-table.module.css";

const count = (value: number | null) =>
  value === null ? null : value.toLocaleString("en-IN");

function tokens(stage: DetailStage) {
  if (stage.tokensIn === null && stage.tokensOut === null) return "";
  return `${count(stage.tokensIn) ?? "—"} / ${count(stage.tokensOut) ?? "—"}`;
}

const model = (stage: DetailStage) =>
  [stage.provider, stage.model].filter(Boolean).join(" · ");

export function StageTable({ stages }: { stages: readonly DetailStage[] }) {
  const { spanMs, times } = stageTimeline(stages);
  const total = stages.reduce((sum, stage) => sum + (stage.costInr ?? 0), 0);
  const share = (ms: number) =>
    spanMs > 0 ? Math.min(100, (ms / spanMs) * 100) : 0;

  return (
    <Table
      label="Stages"
      cards={stages.map((stage) => {
        const time = times.get(stage.key);
        return (
          <Card key={stage.key}>
            <strong>
              {stage.code ? (
                <span className={styles.code}>{stage.code}</span>
              ) : null}
              {stage.label}{" "}
              <Badge tone={STAGE_STATUS_TONE[stage.status]}>
                {STAGE_STATUS_LABEL[stage.status]}
              </Badge>
            </strong>
            <span>
              {[
                after(time?.startMs ?? null),
                duration(stage.durationMs),
                rupees(stage.costInr),
                model(stage),
              ]
                .filter(Boolean)
                .join(" · ") || "Nothing recorded yet"}
            </span>
            {stage.detail ? <small>{stage.detail}</small> : null}
          </Card>
        );
      })}
    >
      <thead>
        <tr>
          <th scope="col">Stage</th>
          <th scope="col">Status</th>
          <th scope="col" data-num="">
            Started
          </th>
          <th scope="col" data-num="">
            Took
          </th>
          <th scope="col" className={styles.barHead}>
            Timing
          </th>
          <th scope="col" data-num="">
            Tokens in / out
          </th>
          <th scope="col">Model</th>
          <th scope="col" data-num="">
            Cost
          </th>
        </tr>
      </thead>
      <tbody>
        {stages.map((stage) => {
          const time = times.get(stage.key);
          const start = time?.startMs ?? null;
          const end = time?.endMs ?? null;
          const later = LATER.has(stage.key);
          return (
            <tr key={stage.key} data-status={stage.status}>
              <th scope="row">
                {stage.code ? (
                  <span className={styles.code}>{stage.code}</span>
                ) : null}
                {stage.label}
                {stage.detail ? (
                  <small className={styles.detail}>{stage.detail}</small>
                ) : null}
              </th>
              <td>
                <Badge tone={STAGE_STATUS_TONE[stage.status]}>
                  {STAGE_STATUS_LABEL[stage.status]}
                </Badge>
                {stage.attempts && stage.attempts > 1 ? (
                  <small className={styles.detail}>
                    {stage.attempts} attempts
                  </small>
                ) : null}
              </td>
              <td data-num="">
                {after(later ? (start ?? end) : start) || "—"}
              </td>
              <td data-num="">{duration(stage.durationMs) || "—"}</td>
              <td className={styles.barCell}>
                {later ? (
                  <span className={styles.later}>
                    {start !== null || end !== null ? "after the run" : ""}
                  </span>
                ) : start !== null || end !== null ? (
                  <span
                    className={styles.track}
                    aria-hidden="true"
                    title={[after(start), duration(stage.durationMs)]
                      .filter(Boolean)
                      .join(" · ")}
                  >
                    <span
                      className={styles.bar}
                      data-status={stage.status}
                      style={{
                        left: `${share(start ?? end ?? 0)}%`,
                        width: `${Math.max(
                          share((end ?? start ?? 0) - (start ?? end ?? 0)),
                          1,
                        )}%`,
                      }}
                    />
                  </span>
                ) : null}
              </td>
              <td data-num="">{tokens(stage) || "—"}</td>
              <td className={styles.model}>
                {model(stage) || "—"}
                {stage.version ? (
                  <small className={styles.detail}>{stage.version}</small>
                ) : null}
              </td>
              <td data-num="">{rupees(stage.costInr) || "—"}</td>
            </tr>
          );
        })}
      </tbody>
      <tfoot>
        <tr>
          <th scope="row" colSpan={3}>
            Whole call
          </th>
          <td data-num="">{duration(spanMs) || "—"}</td>
          <td colSpan={3} />
          <td data-num="">{rupees(total) || "₹0.00"}</td>
        </tr>
      </tfoot>
    </Table>
  );
}
