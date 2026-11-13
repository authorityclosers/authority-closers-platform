import { Download, UsersRound } from "lucide-react";

import { when } from "@/app/calls/call-data";
import { adminRead } from "@/app/lib/server-api";
import { TesterActions } from "@/app/testers/tester-actions";
import {
  EXPORT_PATH,
  HOURS_LABEL,
  HOURS_TONE,
  STAGE_LABEL,
  STAGE_TONE,
  aboutLine,
  inView,
  normalizeTesters,
  testerView,
  type Tester,
} from "@/app/testers/testers-data";
import styles from "@/app/testers/testers.module.css";
import {
  Badge,
  Card,
  Empty,
  Kpi,
  Page,
  PageHeader,
  Panel,
  QueryTabs,
  Table,
  Tiles,
  Unavailable,
  Why,
  kitStyles,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

function Who({ tester }: { tester: Tester }) {
  return (
    <span className={styles.who}>
      <strong>{tester.name ?? tester.email}</strong>
      {tester.name ? <small>{tester.email}</small> : null}
      {aboutLine(tester) ? <small>{aboutLine(tester)}</small> : null}
    </span>
  );
}

function Stage({ tester }: { tester: Tester }) {
  return (
    <span className={styles.marks}>
      <Badge tone={STAGE_TONE[tester.stage]}>{STAGE_LABEL[tester.stage]}</Badge>
      {tester.emailStatus === "failed" ? (
        <Badge tone="bad">Email failed</Badge>
      ) : null}
      {tester.emailStatus === "queued" ? <Badge>Email sending</Badge> : null}
      {tester.hours ? (
        <Badge tone={HOURS_TONE[tester.hours]}>
          {HOURS_LABEL[tester.hours]}
        </Badge>
      ) : null}
      {tester.bugs ? (
        <Badge tone="accent">
          {tester.bugs === 1 ? "1 bug report" : `${tester.bugs} bug reports`}
        </Badge>
      ) : null}
    </span>
  );
}

/** Where they are in the app: version and last time seen, or why not yet. */
function InApp({ tester }: { tester: Tester }) {
  if (tester.lastAppAt)
    return (
      <span className={styles.who}>
        <span>{tester.appVersion ? `App ${tester.appVersion}` : "App"}</span>
        <small>Last opened {when(tester.lastAppAt)}</small>
      </span>
    );
  if (tester.webLastAt)
    return (
      <span className={styles.who}>
        <span>Not in the app yet</span>
        <small>Website {when(tester.webLastAt)}</small>
      </span>
    );
  return (
    <span className={kitStyles.muted}>
      {tester.hasAccount ? "Signed up, not in the app" : "No sign-in yet"}
    </span>
  );
}

/** The step that got them here, for the team's reading of the row. */
function Since({ tester }: { tester: Tester }) {
  const moment =
    tester.stage === "applied" || tester.stage === "declined"
      ? tester.appliedAt
      : tester.stage === "emailed"
        ? tester.emailedAt
        : tester.stage === "in_group" || tester.stage === "approved"
          ? tester.inGroupAt
          : tester.firstAppAt;
  const how =
    tester.stage === "emailed" && tester.emailedVia === "gmail"
      ? " (by hand)"
      : "";
  return (
    <span className={kitStyles.muted}>
      {moment
        ? `${when(moment)}${how}`
        : tester.source === "listed"
          ? "In the group already"
          : "—"}
    </span>
  );
}

/** Admin -> Testers (owner, 13 Nov 2026): who applied, who was sent, who installed. */
export default async function TestersPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const view = testerView(params.stage);
  const result = await adminRead("/v1/admin/testers", normalizeTesters);
  const data = result.ok ? result.data : null;
  const waiting = data
    ? data.items.filter((item) => item.stage === "applied")
    : [];
  const shown = data ? inView(data.items, view) : [];
  const total = data?.items.length ?? 0;
  const enough = data ? data.active >= data.playNeeds : false;
  return (
    <Page wide>
      <PageHeader
        title="Testers"
        context={[
          "Sales X-Ray Play testers",
          data
            ? `${data.active} active of the ${data.playNeeds} Play needs`
            : null,
        ]}
        actions={
          <span className={styles.headerActions}>
            {data && total ? (
              <a className={kitStyles.button} href={EXPORT_PATH} download>
                <Download size={14} aria-hidden="true" />
                Export CSV
              </a>
            ) : null}
            <Why detail="People join at app.salesxray.in/testers with the Google account their Play Store uses. Approve them here, add that account to the salesxray-testers Google Group, then send the welcome email: Play's opt-in link works only for group members. Installed is their first Sales X-Ray app session; active is an app session in the last 7 days. Play needs 12 testers opted in for 14 days in a row. Every step adds to the tester's history; nothing is overwritten." />
          </span>
        }
      />
      {!data ? (
        <Unavailable title="Testers" reason={result.ok ? "" : result.error} />
      ) : (
        <>
          <Tiles label="Testers by stage">
            <Kpi
              label="Waiting for review"
              value={data.counts.applied}
              tone={data.counts.applied ? "warn" : undefined}
              href="/testers?stage=applied"
            />
            <Kpi
              label="In the group, not installed"
              value={
                data.counts.approved +
                data.counts.in_group +
                data.counts.emailed
              }
              href="/testers?stage=emailed"
            />
            <Kpi
              label="Installed"
              value={data.counts.installed + data.counts.active}
              href="/testers?stage=installed"
            />
            <Kpi
              label={`Active, last ${data.activeDays} days`}
              value={data.active}
              note={`Play needs ${data.playNeeds}`}
              tone={enough ? "good" : "warn"}
              href="/testers?stage=active"
            />
            <Kpi
              label="Gave feedback"
              value={data.feedback}
              href="/testers?stage=feedback"
            />
          </Tiles>
          {waiting.length && view === "all" ? (
            <Panel
              title="Review"
              sub={`${waiting.length} waiting: approve to add them to the Play group and email them`}
            >
              <ul className={styles.queue}>
                {waiting.map((tester) => (
                  <li key={tester.id} className={styles.queueRow}>
                    <Who tester={tester} />
                    <Since tester={tester} />
                    <TesterActions tester={tester} groupUrl={data.groupUrl} />
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
          <QueryTabs
            base="/testers"
            param="stage"
            current={view}
            items={[
              { key: "all", label: "All", count: total },
              { key: "applied", label: "Waiting", count: data.counts.applied },
              {
                key: "approved",
                label: "Approved",
                count: data.counts.approved,
              },
              {
                key: "in_group",
                label: "In the group",
                count: data.counts.in_group,
              },
              { key: "emailed", label: "Emailed", count: data.counts.emailed },
              {
                key: "installed",
                label: "Installed",
                count: data.counts.installed,
              },
              { key: "active", label: "Active", count: data.counts.active },
              { key: "feedback", label: "Feedback", count: data.feedback },
              {
                key: "declined",
                label: "Declined",
                count: data.counts.declined,
              },
            ]}
          />
          {shown.length ? (
            <Panel
              title="Everyone"
              sub={`The Play group is ${data.groupEmail}; installs and activity come from their app sessions`}
            >
              <Table
                label="Testers"
                cards={shown.map((tester) => (
                  <Card key={tester.id}>
                    <Who tester={tester} />
                    <Stage tester={tester} />
                    <InApp tester={tester} />
                    <TesterActions tester={tester} groupUrl={data.groupUrl} />
                  </Card>
                ))}
              >
                <thead>
                  <tr>
                    <th scope="col">Tester</th>
                    <th scope="col">Stage</th>
                    <th scope="col">Since</th>
                    <th scope="col">In the app</th>
                    <th scope="col">Next</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((tester) => (
                    <tr key={tester.id}>
                      <th scope="row">
                        <Who tester={tester} />
                      </th>
                      <td>
                        <Stage tester={tester} />
                      </td>
                      <td>
                        <Since tester={tester} />
                      </td>
                      <td>
                        <InApp tester={tester} />
                      </td>
                      <td>
                        <TesterActions
                          tester={tester}
                          groupUrl={data.groupUrl}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Panel>
          ) : (
            <Panel title="Everyone">
              <Empty
                icon={UsersRound}
                title={
                  view === "all" ? "No testers yet" : "No testers at this stage"
                }
                text={
                  view === "all"
                    ? "People who join at app.salesxray.in/testers wait here for review."
                    : "Try another stage."
                }
                action={
                  view === "all"
                    ? undefined
                    : { href: "/testers", label: "Show everyone" }
                }
              />
            </Panel>
          )}
        </>
      )}
    </Page>
  );
}
