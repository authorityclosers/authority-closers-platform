import { BarChart3 } from "lucide-react";

import styles from "@/app/health/health.module.css";
import { adminRead } from "@/app/lib/server-api";
import {
  Empty,
  Kpi,
  Page,
  PageHeader,
  Panel,
  QueryTabs,
  Spark,
  Table,
  Tiles,
  Unavailable,
  Why,
} from "@/app/ui/kit";
import { eventLabel, journey, normalizeUsage } from "@/app/usage/usage-data";
import usageStyles from "@/app/usage/usage.module.css";

export const dynamic = "force-dynamic";

const WINDOWS = [
  { key: "7", label: "7 days" },
  { key: "1", label: "Today" },
  { key: "30", label: "30 days" },
  { key: "90", label: "90 days" },
];

export default async function UsagePage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const { days } = await searchParams;
  const window = WINDOWS.find((item) => item.key === days)?.key ?? "7";
  const result = await adminRead(
    `/v1/admin/conversation/usage?days=${window}`,
    normalizeUsage,
  );
  const usage = result.ok ? result.data : null;
  const peak = Math.max(1, ...(usage?.daily.map((day) => day.events) ?? [1]));
  return (
    <Page>
      <PageHeader
        title="Usage"
        context={[
          "What people do in Sales Xray, from product events (counts only)",
        ]}
      />
      <QueryTabs base="/usage" param="days" items={WINDOWS} current={window} />
      {!result.ok ? <Unavailable title="Usage" reason={result.error} /> : null}
      {usage && usage.events === 0 ? (
        <Panel title="No product events yet">
          <Empty
            icon={BarChart3}
            title="Nothing has been recorded in this window"
            text="Sales Xray's screens send typed product events (telemetry/1: sign-in, uploads, report and pillar views, Coaching, clips, missions, outcomes and errors shown), but the server stores them only once product analytics has a consent and retention policy. This page fills in from then on; it counts events and never reads call content."
          />
        </Panel>
      ) : null}
      {usage && usage.events > 0 ? (
        <>
          <Tiles label="Usage">
            <Kpi
              label="Events"
              value={usage.events.toLocaleString("en-IN")}
              spark={
                <Spark
                  values={usage.daily.map((day) => day.events)}
                  label="Events per day"
                />
              }
            />
            <Kpi
              label="Active people"
              value={usage.people}
              note="Sent at least one event"
            />
            <Kpi label="Organisations" value={usage.organisations} />
          </Tiles>
          <Panel title="Per day">
            <div className={styles.bars} role="img" aria-label="Events per day">
              {usage.daily.map((day) => (
                <span
                  key={day.day}
                  className={styles.day}
                  title={`${day.day}: ${day.events} events, ${day.people} people`}
                >
                  <i style={{ height: `${(day.events / peak) * 100}%` }} />
                </span>
              ))}
            </div>
            <div className={styles.axis} aria-hidden="true">
              <span>{usage.daily[0]?.day}</span>
              <span>{usage.daily.at(-1)?.day}</span>
            </div>
          </Panel>
          {journey(usage).recorded ? (
            <Panel
              title="Journey"
              sub="people at each step in this window"
              tools={
                <Why detail="People who sent each step's event in this window. Not a strict funnel: people can skip steps or have done earlier steps before the window." />
              }
            >
              <ol className={usageStyles.journey} aria-label="Journey">
                {journey(usage).steps.map((step) => (
                  <li key={step.name}>
                    <span>{step.label}</span>
                    <span className={usageStyles.track} aria-hidden="true">
                      <i style={{ width: `${step.share * 100}%` }} />
                    </span>
                    <strong>{step.people}</strong>
                  </li>
                ))}
              </ol>
            </Panel>
          ) : null}
          <Panel
            title="Events"
            sub={`${usage.byEvent.length} kinds`}
            tools={
              <Why detail="Counts of product-analytics events for the served Sales Xray organisations. Analytics never become progress or payment state." />
            }
          >
            <Table label="Events by name">
              <thead>
                <tr>
                  <th scope="col">Event</th>
                  <th scope="col">Version</th>
                  <th scope="col" data-num="">
                    Count
                  </th>
                  <th scope="col" data-num="">
                    People
                  </th>
                </tr>
              </thead>
              <tbody>
                {usage.byEvent.map((row) => (
                  <tr key={`${row.name}-${row.version}`}>
                    <th scope="row" title={row.name}>
                      {eventLabel(row.name)}
                    </th>
                    <td>{row.version}</td>
                    <td data-num="">{row.count.toLocaleString("en-IN")}</td>
                    <td data-num="">{row.people}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Panel>
        </>
      ) : null}
    </Page>
  );
}
