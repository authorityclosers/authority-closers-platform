import Link from "next/link";

import { KIND_BADGE, KIND_HINT, KIND_TONE } from "../lib/workspaces";
import { Badge, Card, Table, kitStyles, type Tone } from "../ui/kit";
import {
  STATUS_LABEL,
  STATUS_TONE,
  clock,
  languageLabel,
  when,
  type QueueItem,
} from "./call-data";
import { REVIEW_LABEL, REVIEW_TONE } from "./labels-data";
import styles from "./calls.module.css";

/** A read's newest run: done, failed, running, or a start with no outcome. */
const ENGINE_TONE: Record<string, Tone> = {
  succeeded: "good",
  failed: "bad",
  running: "accent",
  uncertain: "warn",
};

function EngineState({ item }: { item: QueueItem }) {
  const { fast, deep } = item.engine;
  if (!fast && !deep) return <span className={kitStyles.muted}>—</span>;
  const reads: [string, string | null][] = [
    ["Fast", fast],
    ["Deep", deep],
  ];
  return (
    <span className={styles.engine}>
      {reads.map(([label, state]) =>
        state ? (
          <span key={label} title={`${label} read: ${state}`}>
            <Badge tone={ENGINE_TONE[state] ?? "neutral"}>{label}</Badge>
          </span>
        ) : null,
      )}
    </span>
  );
}

const href = (item: QueueItem, back: string) => {
  const query = new URLSearchParams();
  if (item.reportRunId) query.set("run", item.reportRunId);
  if (back) query.set("back", back);
  const text = query.toString();
  return `/calls/${item.recordingId}${text ? `?${text}` : ""}`;
};

/** The queue as a dense table on wide screens and cards on phones. */
export function CallTable({
  items,
  back,
}: {
  items: QueueItem[];
  back: string;
}) {
  return (
    <Table
      label="Calls"
      cards={items.map((item) => (
        <Card key={item.recordingId}>
          <Link
            href={href(item, back)}
            className={styles.cardLink}
            data-call-link=""
          >
            <strong>{item.rep.label}</strong>
            <span>
              {item.organisation.name} · {when(item.uploadedAt)} ·{" "}
              {clock(item.durationMs)}
            </span>
            <span className={styles.cardMeta}>
              <Badge tone={REVIEW_TONE[item.review]}>
                {REVIEW_LABEL[item.review]}
              </Badge>
              <Badge tone={STATUS_TONE[item.status]}>
                {STATUS_LABEL[item.status]}
              </Badge>
              <span>{languageLabel(item.language)}</span>
              {item.engine.objects ? (
                <span>{item.engine.objects} objects</span>
              ) : null}
              {item.promptRevision ? <span>{item.promptRevision}</span> : null}
            </span>
          </Link>
        </Card>
      ))}
    >
      <thead>
        <tr>
          <th scope="col">Call</th>
          <th scope="col">Uploaded</th>
          <th scope="col">Language</th>
          <th scope="col">Model · prompt</th>
          <th scope="col">Engine</th>
          <th scope="col" data-num="">
            Objects
          </th>
          <th scope="col" data-num="">
            Runs
          </th>
          <th scope="col">Analysis</th>
          <th scope="col">Review</th>
          <th scope="col">
            <span className={styles.srOnly}>Analysis map</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.recordingId} className={styles.callRow}>
            <th scope="row" className={styles.callCell}>
              <Link
                href={href(item, back)}
                className={styles.rowLink}
                data-call-link=""
                title={item.rep.email ?? undefined}
              >
                {item.rep.label}
              </Link>
              {item.rep.kind === "guest" && !item.rep.personId ? (
                <span className={kitStyles.muted}> · guest</span>
              ) : null}
              <span
                className={styles.sub}
                title={KIND_HINT[item.organisation.kind]}
              >
                {item.organisation.name}{" "}
                <Badge tone={KIND_TONE[item.organisation.kind]}>
                  {KIND_BADGE[item.organisation.kind]}
                </Badge>
              </span>
            </th>
            <td>
              {when(item.uploadedAt)}
              <span className={styles.sub}>{clock(item.durationMs)}</span>
            </td>
            <td>
              {item.language ? (
                languageLabel(item.language)
              ) : (
                <span className={kitStyles.muted}>—</span>
              )}
            </td>
            <td className={styles.clip}>
              {[item.model ?? item.provider, item.promptRevision]
                .filter(Boolean)
                .join(" · ") || <span className={kitStyles.muted}>—</span>}
            </td>
            <td>
              <EngineState item={item} />
            </td>
            <td data-num="">
              {item.engine.objects || (
                <span className={kitStyles.muted}>—</span>
              )}
            </td>
            <td data-num="">{item.runs}</td>
            <td>
              <Badge tone={STATUS_TONE[item.status]}>
                {STATUS_LABEL[item.status]}
              </Badge>
            </td>
            <td>
              <Badge tone={REVIEW_TONE[item.review]}>
                {REVIEW_LABEL[item.review]}
              </Badge>
            </td>
            <td>
              <Link
                href={`/calls/${item.recordingId}/map`}
                className={styles.mapLink}
                title="Analysis map: pipeline, objects, runs and costs"
                prefetch={false}
              >
                Map
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
