/**
 * The call's pipeline as a graph (owner 19 Oct: "nicer nodes and a better
 * structure"): stages as nodes in lanes (checks, main and fast read, deep read,
 * report), links coloured by status with their time and cost. Drawn on the
 * server as SVG; wide graphs scroll inside their panel on phones.
 */
import {
  LANES,
  LAYOUT,
  placeStages,
  type DetailEdge,
  type DetailStage,
} from "./call-detail-data";
import { STAGE_STATUS_LABEL, duration, rupees } from "./call-map-data";
import styles from "./pipeline-graph.module.css";

const GUTTER = 92;
const COL = 196;
const LANE = 86;
const NODE_W = 164;
const NODE_H = 62;
const TOP = 10;

/** The links the engine draws, for older servers that send none. */
const DEFAULT_EDGES: readonly [string, string][] = [
  ["received", "audio_check"],
  ["received", "transcription"],
  ["transcription", "fast"],
  ["fast", "objects"],
  ["transcription", "better_transcript"],
  ["better_transcript", "deep"],
  ["deep", "objects_updated"],
  ["transcription", "report"],
  ["report", "pointer_review"],
  ["report", "prospect"],
];

const point = (key: string) => {
  const place = LAYOUT[key];
  return {
    x: GUTTER + place.col * COL,
    y: TOP + place.lane * LANE,
  };
};

function clip(text: string, max: number) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function PipelineGraph({
  stages,
  edges,
}: {
  stages: readonly DetailStage[];
  edges: readonly DetailEdge[];
}) {
  const { placed, extra } = placeStages(stages);
  const known = new Set(placed.map((stage) => stage.key));
  const byKey = new Map(placed.map((stage) => [stage.key, stage]));
  const links: DetailEdge[] = (
    edges.length
      ? edges
      : DEFAULT_EDGES.map(([from, to]) => ({
          from,
          to,
          branch: "main" as const,
          status: byKey.get(to)?.status ?? ("waiting" as const),
          costInr: byKey.get(to)?.costInr ?? null,
          durationMs: byKey.get(to)?.durationMs ?? null,
        }))
  ).filter((edge) => known.has(edge.from) && known.has(edge.to));
  const width = GUTTER + 5 * COL;
  const height = TOP * 2 + LANES.length * LANE - (LANE - NODE_H);

  return (
    <div className={styles.frame}>
      <svg
        className={styles.graph}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Pipeline: ${placed
          .map((stage) => `${stage.label} ${STAGE_STATUS_LABEL[stage.status]}`)
          .join(", ")}`}
      >
        {LANES.map((lane, index) => (
          <g key={lane}>
            <rect
              className={styles.lane}
              x={0}
              y={TOP + index * LANE - 6}
              width={width}
              height={NODE_H + 12}
              rx={8}
            />
            <text
              className={styles.laneLabel}
              x={10}
              y={TOP + index * LANE + NODE_H / 2 + 4}
            >
              {lane}
            </text>
          </g>
        ))}
        {links.map((edge) => {
          const from = point(edge.from);
          const to = point(edge.to);
          const x1 = from.x + NODE_W;
          const y1 = from.y + NODE_H / 2;
          const x2 = to.x;
          const y2 = to.y + NODE_H / 2;
          const bend = (x2 - x1) / 2;
          const label = [duration(edge.durationMs), rupees(edge.costInr)]
            .filter(Boolean)
            .join(" · ");
          // Each node already shows its time and cost; the link says it on hover.
          return (
            <path
              key={`${edge.from}-${edge.to}`}
              className={styles.edge}
              data-status={edge.status}
              d={`M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`}
            >
              <title>
                {[`${edge.from} → ${edge.to}`, label]
                  .filter(Boolean)
                  .join(": ")}
              </title>
            </path>
          );
        })}
        {placed.map((stage) => {
          const { x, y } = point(stage.key);
          const second = [
            STAGE_STATUS_LABEL[stage.status],
            duration(stage.durationMs),
            rupees(stage.costInr),
          ]
            .filter(Boolean)
            .join(" · ");
          const third = [stage.model ?? stage.provider, stage.version]
            .filter(Boolean)
            .join(" · ");
          return (
            <g
              key={stage.key}
              className={styles.node}
              data-status={stage.status}
            >
              <title>
                {[
                  stage.label,
                  second,
                  third,
                  stage.attempts && stage.attempts > 1
                    ? `${stage.attempts} attempts`
                    : null,
                  stage.tokensIn !== null || stage.tokensOut !== null
                    ? `${stage.tokensIn ?? 0} in / ${stage.tokensOut ?? 0} out tokens`
                    : null,
                  stage.detail,
                ]
                  .filter(Boolean)
                  .join("\n")}
              </title>
              <rect x={x} y={y} width={NODE_W} height={NODE_H} rx={8} />
              <circle className={styles.dot} cx={x + 12} cy={y + 15} r={4} />
              <text className={styles.nodeTitle} x={x + 22} y={y + 19}>
                {clip(stage.label, 22)}
              </text>
              <text className={styles.nodeMeta} x={x + 10} y={y + 37}>
                {clip(second, 27)}
              </text>
              {third ? (
                <text className={styles.nodeMeta} x={x + 10} y={y + 52}>
                  {clip(third, 27)}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      {extra.length ? (
        <p className={styles.extra}>
          Also:{" "}
          {extra
            .map(
              (stage) => `${stage.label} (${STAGE_STATUS_LABEL[stage.status]})`,
            )
            .join(", ")}
        </p>
      ) : null}
    </div>
  );
}
