import { History } from "lucide-react";
import Link from "next/link";
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
  speedWords,
} from "@/app/bugs/bugs-data";
import styles from "@/app/bugs/bugs.module.css";
import { sellerPath } from "@/app/sellers/seller-data";
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
      "What happened",
      bug.person.id ? (
        <Link key="seller" href={sellerPath(bug.person.id)}>
          Their days, before and after this report
        </Link>
      ) : null,
    ],
    [
      "Organisation",
      bug.organisation
        ? `${bug.organisation.name}${bug.workspaceRole ? ` (${bug.workspaceRole})` : ""}`
        : null,
    ],
    [
      "Screen",
      <span key="route">
        {typeof bug.app.page === "string" && bug.app.page !== "other"
          ? `${bug.app.page} · `
          : null}
        <code>{bug.route}</code>
      </span>,
    ],
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
  const advanced = bug.advanced;
  const fileUrl = (position: number) =>
    `/v1/admin/bugs/${bug.id}/files/${position}`;
  const original = bug.files.find((file) => file.role === "original");
  const partPicture = (n: number) =>
    bug.files.find((file) => file.role === "element" && file.part === n);
  const attachments = bug.files.filter((file) => file.role === "attachment");
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
          <Panel
            title="What they said"
            sub={
              bug.fromFeedback
                ? `From feedback: "Not good" after ${bug.fromFeedback.about}`
                : undefined
            }
          >
            <p className={styles.said}>{bug.words}</p>
            {bug.voice ? (
              <div className={styles.voice}>
                <small className={kitStyles.muted}>
                  Voice note, {bug.voice.seconds} s
                </small>
                {/* A private, same-origin recording from the tester. */}
                <audio
                  controls
                  preload="none"
                  src={`/v1/admin/bugs/${bug.id}/voice`}
                >
                  <track kind="captions" />
                </audio>
              </div>
            ) : null}
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
            {original ? (
              <div className={styles.before}>
                <small className={kitStyles.muted}>Before their marks</small>
                <a
                  href={fileUrl(original.position)}
                  target="_blank"
                  rel="noreferrer"
                  className={styles.shot}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- a private, same-origin picture */}
                  <img
                    src={fileUrl(original.position)}
                    alt={`The screen before the marks, bug ${bug.number}`}
                  />
                </a>
              </div>
            ) : null}
          </Panel>
          {advanced?.comments.length ? (
            <Panel
              title="On the screen"
              sub="Parts they pointed at, numbered as on the picture: where each is, never its text"
            >
              <ol className={styles.parts}>
                {advanced.comments.map((comment) => {
                  const crop = partPicture(comment.n);
                  return (
                    <li key={comment.n} className={styles.part}>
                      <span className={styles.partNumber}>{comment.n}</span>
                      {crop ? (
                        <a
                          href={fileUrl(crop.position)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element -- a private, same-origin picture */}
                          <img
                            className={styles.partPicture}
                            src={fileUrl(crop.position)}
                            alt=""
                          />
                        </a>
                      ) : (
                        <span className={styles.partPicture} />
                      )}
                      <span className={styles.partWords}>
                        <strong>{comment.note || "No words"}</strong>
                        <small className={kitStyles.muted}>
                          {[
                            comment.components.join(" › "),
                            comment.testid ? `testid ${comment.testid}` : null,
                            comment.role ?? comment.tag,
                            comment.onPicture
                              ? "on the picture"
                              : "not on the picture (the page had scrolled)",
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </small>
                        <code className={styles.mono}>{comment.selector}</code>
                      </span>
                    </li>
                  );
                })}
              </ol>
            </Panel>
          ) : null}
          {advanced?.steps.length ? (
            <Panel
              title="Steps to reproduce"
              sub="From their trail in the app, as they edited them"
            >
              <ol className={styles.steps}>
                {advanced.steps.map((step, index) => (
                  <li key={index}>{step}</li>
                ))}
              </ol>
            </Panel>
          ) : null}
          {attachments.length ? (
            <Panel
              title="Files they added"
              sub={`${attachments.length} kept; pictures re-encoded, logs scrubbed`}
            >
              <ul className={styles.attachments}>
                {attachments.map((file) => (
                  <li key={file.position}>
                    {file.contentType.startsWith("image/") ? (
                      <a
                        href={fileUrl(file.position)}
                        target="_blank"
                        rel="noreferrer"
                        className={styles.shot}
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element -- a private, same-origin picture */}
                        <img src={fileUrl(file.position)} alt={file.name} />
                      </a>
                    ) : file.contentType.startsWith("video/") ? (
                      <video
                        className={styles.recording}
                        src={fileUrl(file.position)}
                        controls
                        preload="metadata"
                      />
                    ) : null}
                    <a
                      href={fileUrl(file.position)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {file.name}
                    </a>{" "}
                    <small className={kitStyles.muted}>
                      {Math.max(1, Math.round(file.bytes / 1024))} KB
                    </small>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
          {advanced &&
          (advanced.calls.length || Object.keys(advanced.speed).length) ? (
            <Panel
              title="Calls and speed"
              sub="Slow or failed calls to the server, and how fast the page was"
            >
              {advanced.calls.length ? (
                <Table label="Slow or failed calls">
                  <thead>
                    <tr>
                      <th scope="col">Call</th>
                      <th scope="col">Answer</th>
                      <th scope="col">Reference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {advanced.calls.map((call, index) => (
                      <tr key={index}>
                        <td className={styles.mono}>
                          {[call.method, call.path].filter(Boolean).join(" ")}
                        </td>
                        <td>
                          {[
                            call.failed ? "Failed" : null,
                            call.status ? String(call.status) : null,
                            call.ms !== null ? `${call.ms} ms` : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </td>
                        <td className={styles.mono}>
                          <Fact value={call.reference} missing="None" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              ) : null}
              {Object.keys(advanced.speed).length ? (
                <dl className={styles.facts}>
                  {Object.entries(advanced.speed).map(([key, value]) => (
                    <div key={key}>
                      <dt>{speedWords(key)}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              ) : null}
            </Panel>
          ) : null}
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
          <Panel
            title="Last steps in the app"
            sub={`${bug.trail.length} kept, oldest first: what they did, never what they typed`}
          >
            {bug.trail.length ? (
              <Table label="Last steps">
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Step</th>
                    <th scope="col">Page</th>
                    <th scope="col">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {bug.trail.map((step, index) => (
                    <tr key={index}>
                      <td>{when(step.at)}</td>
                      <td className={styles.mono}>{step.event}</td>
                      <td className={styles.mono}>
                        <Fact value={step.route} missing="None" />
                      </td>
                      <td className={styles.mono}>
                        {Object.entries(step.detail)
                          .map(([key, value]) => `${key} ${value}`)
                          .join(" · ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <p className={kitStyles.muted}>No steps came with this report.</p>
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
