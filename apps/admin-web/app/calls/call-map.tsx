import { when } from "./call-data";
import {
  duration,
  rupees,
  STAGE_STATUS_LABEL,
  STAGE_STATUS_TONE,
  stageCounts,
  stageMeta,
  type CallMapData,
} from "./call-map-data";
import styles from "./call-map.module.css";
import { Badge, Panel } from "../ui/kit";

/**
 * One call's journey through the pipelines (call data engine, owner 19 Oct):
 * one line per stage with its status, timing, cost, provider, model and
 * version. Read-only and content-free.
 */
export function CallMap({ map }: { map: CallMapData }) {
  const running = map.stages.some((stage) => stage.status === "running");
  return (
    <Panel
      title="Pipeline map"
      sub={`${map.stages.filter((s) => s.status === "done").length} of ${map.stages.length} stages done · ${rupees(map.costInr) || "₹0.00"} estimated`}
      tools={running ? <Badge tone="accent">Live</Badge> : null}
    >
      <ol className={styles.map} aria-label="Stages">
        {map.stages.map((stage) => {
          const meta = stageMeta(stage);
          const counts = stageCounts(stage);
          return (
            <li
              key={stage.key}
              className={styles.stage}
              data-status={stage.status}
            >
              <span className={styles.dot} aria-hidden="true" />
              <div className={styles.body}>
                <div className={styles.line}>
                  <strong>{stage.label}</strong>
                  <Badge tone={STAGE_STATUS_TONE[stage.status]}>
                    {STAGE_STATUS_LABEL[stage.status]}
                  </Badge>
                </div>
                {meta ? <span className={styles.meta}>{meta}</span> : null}
                {stage.detail ? (
                  <span className={styles.meta}>{stage.detail}</span>
                ) : null}
                {counts.length ? (
                  <span className={styles.meta}>{counts.join(" · ")}</span>
                ) : null}
              </div>
              <dl className={styles.figures}>
                <div>
                  <dt>Time</dt>
                  <dd>{duration(stage.durationMs) || "—"}</dd>
                </div>
                <div>
                  <dt>Cost</dt>
                  <dd>{rupees(stage.costInr) || "—"}</dd>
                </div>
                <div>
                  <dt>Finished</dt>
                  <dd>{stage.finishedAt ? when(stage.finishedAt) : "—"}</dd>
                </div>
              </dl>
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}
