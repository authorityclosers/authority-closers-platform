import Link from "next/link";
import { Bug } from "lucide-react";

import { when } from "@/app/calls/call-data";
import { adminRead } from "@/app/lib/server-api";
import { BugFilters } from "@/app/bugs/bug-filters";
import {
  AREA_LABEL,
  SEVERITY_LABEL,
  SEVERITY_TONE,
  STATUSES,
  STATUS_LABEL,
  STATUS_TONE,
  bugFilters,
  bugQuery,
  bugsApiPath,
  ISSUE_LABEL,
  ISSUE_TONE,
  normalizeIssues,
  normalizePage,
  type BugIssue,
  type BugSummary,
} from "@/app/bugs/bugs-data";
import styles from "@/app/bugs/bugs.module.css";
import {
  Badge,
  Card,
  Empty,
  Page,
  PageHeader,
  Panel,
  QueryTabs,
  Table,
  Unavailable,
  Why,
  kitStyles,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

function Words({ bug }: { bug: BugSummary }) {
  return (
    <Link href={`/bugs/${bug.id}`} className={styles.words}>
      <strong>Bug {bug.number}</strong>
      <span>{bug.words}</span>
    </Link>
  );
}

function Marks({ bug }: { bug: BugSummary }) {
  return (
    <span className={styles.marks}>
      <Badge tone={STATUS_TONE[bug.status]}>{STATUS_LABEL[bug.status]}</Badge>
      {bug.severity ? (
        <Badge tone={SEVERITY_TONE[bug.severity]}>
          {SEVERITY_LABEL[bug.severity]}
        </Badge>
      ) : null}
      {bug.blocksWork ? <Badge tone="bad">Stops their work</Badge> : null}
    </span>
  );
}

/** Issues first (v0.93): what is wrong, how often, on which devices, with its reports. */
function Issues({
  issues,
  marked,
}: {
  issues: BugIssue[];
  marked: number | null;
}) {
  if (!issues.length) return null;
  return (
    <Panel
      title="Issues"
      sub="Reports that look like one problem, newest activity first; agents set their status with ac-bugs"
    >
      <Table label="Bug issues">
        <thead>
          <tr>
            <th scope="col">Issue</th>
            <th scope="col">State</th>
            <th scope="col">Screen</th>
            <th scope="col">Reports</th>
            <th scope="col">Devices</th>
            <th scope="col">Last report</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue) => (
            <tr
              key={issue.id}
              id={`issue-${issue.number}`}
              aria-current={issue.number === marked ? "true" : undefined}
            >
              <th scope="row">Issue {issue.number}</th>
              <td>
                <span className={styles.marks}>
                  <Badge tone={ISSUE_TONE[issue.status]}>
                    {ISSUE_LABEL[issue.status]}
                  </Badge>
                  {issue.cameBack ? (
                    <Badge tone="bad">Came back after the fix</Badge>
                  ) : null}
                  {issue.release ? <Badge>{issue.release}</Badge> : null}
                </span>
              </td>
              <td>
                <code>{issue.screen}</code>
              </td>
              <td>
                {issue.count}:{" "}
                {issue.reports.map((report, index) => (
                  <span key={report.id}>
                    {index ? ", " : ""}
                    <Link href={`/bugs/${report.id}`}>Bug {report.number}</Link>
                  </span>
                ))}
              </td>
              <td>
                {Object.entries(issue.devices)
                  .map(([name, n]) => `${name} (${n})`)
                  .join(", ") || "Not known"}
              </td>
              <td>{issue.lastSeen ? when(issue.lastSeen) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Panel>
  );
}

/** Bugs and problems testers report from Sales X-Ray (owner, 23 Oct 2026). */
export default async function BugsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const filters = bugFilters(params);
  const [result, issues] = await Promise.all([
    adminRead(bugsApiPath(filters), normalizePage),
    adminRead("/v1/admin/bugs/issues?which=all", normalizeIssues),
  ]);
  const marked = Number(
    Array.isArray(params.issue) ? params.issue[0] : params.issue,
  );
  const data = result.ok ? result.data : null;
  const open = data
    ? data.counts.new + data.counts.triaged + data.counts.in_progress
    : null;
  const keep = bugQuery(filters, ["view", "offset"]);
  return (
    <Page wide>
      <PageHeader
        title="Bugs"
        context={[
          "Reports from people using Sales X-Ray",
          open !== null ? `${open} open` : null,
        ]}
        actions={
          <Why detail="Anyone signed in to Sales X-Ray can report a problem from the You menu or an error card. Each report keeps their words, the screen, app and device, recent errors (scrubbed) and an optional picture, and raises a card on the work board. Changing a status adds to its history; nothing is overwritten." />
        }
      />
      <QueryTabs
        base="/bugs"
        param="status"
        keep={keep || undefined}
        current={filters.view}
        items={[
          { key: "open", label: "Open", count: open ?? undefined },
          ...STATUSES.map((status) => ({
            key: status,
            label: STATUS_LABEL[status],
            count: data?.counts[status],
          })),
          { key: "all", label: "All" },
        ]}
      />
      {issues.ok ? (
        <Issues
          issues={issues.data}
          marked={Number.isInteger(marked) ? marked : null}
        />
      ) : null}
      <BugFilters filters={filters} organisations={data?.organisations ?? []} />
      {!result.ok ? (
        <Unavailable title="Bug reports" reason={result.error} />
      ) : data && data.items.length ? (
        <Panel title="Reports" sub="Newest first">
          <Table
            label="Bug reports"
            cards={data.items.map((bug) => (
              <Card key={bug.id}>
                <Words bug={bug} />
                <Marks bug={bug} />
                <small className={kitStyles.muted}>
                  {AREA_LABEL[bug.area]} ·{" "}
                  {bug.organisation?.name ?? "No workspace"} ·{" "}
                  {when(bug.createdAt)}
                </small>
              </Card>
            ))}
          >
            <thead>
              <tr>
                <th scope="col">Report</th>
                <th scope="col">State</th>
                <th scope="col">Area</th>
                <th scope="col">Organisation</th>
                <th scope="col">Reported</th>
                <th scope="col">Board</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((bug) => (
                <tr key={bug.id}>
                  <th scope="row">
                    <Words bug={bug} />
                  </th>
                  <td>
                    <Marks bug={bug} />
                  </td>
                  <td>{AREA_LABEL[bug.area]}</td>
                  <td>{bug.organisation?.name ?? "No workspace"}</td>
                  <td>{when(bug.createdAt)}</td>
                  <td>{bug.boardCard ?? "Waiting"}</td>
                </tr>
              ))}
            </tbody>
          </Table>
          {data.nextOffset !== null || filters.offset ? (
            <nav className={styles.pager} aria-label="Pages">
              {filters.offset ? (
                <Link
                  className={kitStyles.button}
                  href={`/bugs?${bugQuery({ ...filters, offset: Math.max(0, filters.offset - 50) || undefined })}`}
                >
                  Newer
                </Link>
              ) : null}
              {data.nextOffset !== null ? (
                <Link
                  className={kitStyles.button}
                  href={`/bugs?${bugQuery({ ...filters, offset: data.nextOffset })}`}
                >
                  Older
                </Link>
              ) : null}
            </nav>
          ) : null}
        </Panel>
      ) : (
        <Panel title="Reports">
          <Empty
            icon={Bug}
            title={
              filters.view === "open" && !keep
                ? "No open bugs"
                : "No reports match"
            }
            text={
              filters.view === "open" && !keep
                ? "New reports from Sales X-Ray testers arrive here and on the work board."
                : "Try another status or clear the filters."
            }
            action={
              keep || filters.view !== "open"
                ? { href: "/bugs?status=all", label: "Show all reports" }
                : undefined
            }
          />
        </Panel>
      )}
    </Page>
  );
}
