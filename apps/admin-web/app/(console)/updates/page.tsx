import { Megaphone } from "lucide-react";

import { adminRead } from "@/app/lib/server-api";
import {
  Badge,
  Empty,
  Page,
  PageHeader,
  Panel,
  Unavailable,
  kitStyles,
} from "@/app/ui/kit";
import { AUDIENCE_LABEL, normalizeNotes } from "@/app/updates/updates-data";
import styles from "@/app/updates/updates.module.css";

export const dynamic = "force-dynamic";

/** What Sales Xray users see as "What's new", newest first; read-only. */
export default async function UpdatesPage() {
  const result = await adminRead(
    "/v1/admin/conversation/product-updates",
    normalizeNotes,
  );
  return (
    <Page>
      <PageHeader
        title="Product updates"
        context={[
          "The “What's new” notes Sales Xray shows, with who sees them and whether they're live",
        ]}
      />
      {!result.ok ? (
        <Unavailable title="Product updates" reason={result.error} />
      ) : null}
      {result.ok && !result.data.length ? (
        <Panel title="Notes">
          <Empty
            icon={Megaphone}
            title="No product notes yet"
            text="Notes are added with each release from the pull request's user note."
          />
        </Panel>
      ) : null}
      {result.ok && result.data.length ? (
        <Panel title="Notes" sub={`${result.data.length}`}>
          <ul className={styles.notes}>
            {result.data.map((note) => (
              <li key={note.key}>
                <span className={styles.head}>
                  <strong>{note.title}</strong>
                  <Badge
                    tone={
                      note.status === "published"
                        ? "good"
                        : note.status === "approved"
                          ? "accent"
                          : "neutral"
                    }
                  >
                    {note.status}
                  </Badge>
                  {note.major ? <Badge tone="warn">Major</Badge> : null}
                </span>
                <span className={kitStyles.muted}>
                  {[
                    note.date,
                    AUDIENCE_LABEL[note.audience] ?? note.audience,
                    note.releaseId,
                    note.sourcePr ? `PR #${note.sourcePr}` : null,
                    note.version > 1 ? `version ${note.version}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
                <ul className={styles.items}>
                  {note.items.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </Page>
  );
}
