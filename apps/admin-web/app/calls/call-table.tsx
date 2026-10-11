import Link from "next/link";

import { Badge, Card, Table, kitStyles } from "../ui/kit";
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
              {item.promptRevision ? <span>{item.promptRevision}</span> : null}
            </span>
          </Link>
        </Card>
      ))}
    >
      <thead>
        <tr>
          <th scope="col">Rep</th>
          <th scope="col">Organisation</th>
          <th scope="col">Uploaded</th>
          <th scope="col" data-num="">
            Length
          </th>
          <th scope="col">Language</th>
          <th scope="col">Model · prompt</th>
          <th scope="col" data-num="">
            Runs
          </th>
          <th scope="col">Analysis</th>
          <th scope="col">Review</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.recordingId} className={styles.callRow}>
            <th scope="row">
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
            </th>
            <td className={styles.clip} title={item.organisation.name}>
              {item.organisation.name}
            </td>
            <td>{when(item.uploadedAt)}</td>
            <td data-num="">{clock(item.durationMs)}</td>
            <td>{languageLabel(item.language)}</td>
            <td className={styles.clip}>
              {[item.model ?? item.provider, item.promptRevision]
                .filter(Boolean)
                .join(" · ") || (
                <span className={kitStyles.muted}>Not recorded</span>
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
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
