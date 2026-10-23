import { History } from "lucide-react";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { when } from "@/app/calls/call-data";
import { adminRead } from "@/app/lib/server-api";
import { BugActions } from "@/app/bugs/bug-actions";
import {
  AREA_LABEL,
  BOARD_URL,
  SEVERITY_LABEL,
  SEVERITY_TONE,
  STATUS_LABEL,
  STATUS_TONE,
  appLine,
  deviceLine,
  eventText,
  normalizeDetail,
} from "@/app/bugs/bugs-data";
import styles from "@/app/bugs/bugs.module.css";
import {
  Badge,
  Empty,
  Fact,
  Page,
  PageHeader,
  Panel,
  Table,
  Unavailable,
  kitStyles,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** One bug report: everything captured, its history, and the next step. */
export default async function BugPage({
  params,
}: {
  params: Promise<{ bugId: string }>;
}) {
  const { bugId } = await params;
  if (!UUID.test(bugId)) notFound();
  const id = bugId.toLowerCase();
  const result = await adminRead(`/v1/admin/bugs/${id}`, normalizeDetail);
  if (!result.ok) {
    return (
      <Page>
        <PageHeader title="Bug" back={{ href: "/bugs", label: "Bugs" }} />
        <Unavailable title="This bug report" reason={result.error} />
      </Page>
    );
  }
  const bug = result.data;
  const facts: [string, ReactNode][] = [
    ["Reported", when(bug.createdAt)],
    [
      "By",
      [bug.person.name, bug.person.email].filter(Boolean).join(" · ") || null,
    ],
    [
      "Organisation",
      bug.organisation
        ? `${bug.organisation.name}${bug.workspaceRole ? ` (${bug.workspaceRole})` : ""}`
        : null,
    ],
    ["Screen", <code key="route">{bug.route}</code>],
    ["App", appLine(bug.app)],
    ["Device", deviceLine(bug.device) || null],
    [
      "Server",
      [bug.server.environment, String(bug.server.release ?? "").slice(0, 12)]
        .filter(Boolean)
        .join(" · ") || null,
    ],
    [
      "Work board",
      bug.boardCard ? (
        <a
          key="card"
          href={`${BOARD_URL}${bug.boardCard}`}
          target="_blank"
          rel="noreferrer"
        >
          {bug.boardCard}
        </a>
      ) : (
        "A card is being raised"
      ),
    ],
  ];
  const deviceFacts = Object.entries(bug.device).filter(
    ([key]) => !["os", "browser", "model", "viewport"].includes(key),
  );
  return (
    <Page wide>
      <PageHeader
        title={`Bug ${bug.number}`}
        back={{ href: "/bugs", label: "Bugs" }}
        context={[
          <Badge key="status" tone={STATUS_TONE[bug.status]}>
            {STATUS_LABEL[bug.status]}
          </Badge>,
          bug.severity ? (
            <Badge key="severity" tone={SEVERITY_TONE[bug.severity]}>
              {SEVERITY_LABEL[bug.severity]}
            </Badge>
          ) : null,
          bug.blocksWork ? (
            <Badge key="blocks" tone="bad">
              Stops their work
            </Badge>
          ) : null,
          AREA_LABEL[bug.area],
        ]}
      />
      <div className={styles.detail}>
        <div className={styles.main}>
          <Panel title="What they said">
            <p className={styles.said}>{bug.words}</p>
          </Panel>
          <Panel
            title="Picture of the screen"
            sub={
              bug.screenshot
                ? bug.screenshot.source === "upload"
                  ? "Chosen by the tester"
                  : "Taken on their device when they opened the reporter"
                : undefined
            }
          >
            {bug.screenshot ? (
              <a
                href={`/v1/admin/bugs/${bug.id}/screenshot`}
                target="_blank"
                rel="noreferrer"
                className={styles.shot}
              >
                {/* eslint-disable-next-line @next/next/no-img-element -- a private, same-origin picture */}
                <img
                  src={`/v1/admin/bugs/${bug.id}/screenshot`}
                  alt={`The screen when bug ${bug.number} was reported`}
                />
              </a>
            ) : (
              <p className={kitStyles.muted}>
                No picture came with this report.
              </p>
            )}
          </Panel>
          <Panel
            title="Recent errors on the device"
            sub={`${bug.errors.length} kept, oldest first, scrubbed on the device and again on the server`}
          >
            {bug.errors.length ? (
              <Table label="Recent errors">
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Kind</th>
                    <th scope="col">What</th>
                    <th scope="col">Reference</th>
                  </tr>
                </thead>
                <tbody>
                  {bug.errors.map((error, index) => (
                    <tr key={index}>
                      <td>{when(error.at)}</td>
                      <td>
                        {error.kind}
                        {error.status ? ` ${error.status}` : ""}
                      </td>
                      <td className={styles.errorText}>
                        {[error.method, error.path, error.message, error.source]
                          .filter(Boolean)
                          .join(" · ")}
                      </td>
                      <td className={styles.mono}>
                        <Fact value={error.reference} missing="None" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <p className={kitStyles.muted}>
                No errors on the device before this report.
              </p>
            )}
          </Panel>
          <Panel title="History" sub="Oldest first; nothing is overwritten">
            {bug.history.length ? (
              <ol className={styles.history}>
                {bug.history.map((event) => (
                  <li key={event.id}>
                    <span className={styles.historyWhat}>
                      {eventText(event)}
                    </span>
                    <small className={kitStyles.muted}>
                      {event.actor === "board"
                        ? "Work board"
                        : event.actor === "reporter"
                          ? "Reporter"
                          : (event.actorName ?? "AC team")}{" "}
                      · {when(event.createdAt)}
                    </small>
                  </li>
                ))}
              </ol>
            ) : (
              <Empty icon={History} title="No history yet" />
            )}
          </Panel>
        </div>
        <aside className={styles.side}>
          <Panel title="Next step">
            <BugActions
              bugId={bug.id}
              status={bug.status}
              severity={bug.severity}
              area={bug.area}
            />
          </Panel>
          <Panel title="Captured with it">
            <dl className={styles.facts}>
              {facts.map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>
                    <Fact value={value} missing="Not known" />
                  </dd>
                </div>
              ))}
              {deviceFacts.map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replace(/_/g, " ")}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
              <div>
                <dt>Browser line</dt>
                <dd className={styles.mono}>
                  <Fact value={bug.userAgent} missing="Not known" />
                </dd>
              </div>
            </dl>
          </Panel>
        </aside>
      </div>
    </Page>
  );
}
