import { Layers } from "lucide-react";

import { adminRead } from "@/app/lib/server-api";
import { stamp } from "@/app/usage/cost-data";
import {
  ChooseVersion,
  IndustryDefault,
  RollBack,
  VersionEditor,
} from "@/app/sales-xray/report-settings";
import {
  SOURCE_LABEL,
  describeChange,
  describeEvent,
  normalizeReportSettings,
} from "@/app/sales-xray/report-settings-data";
import styles from "@/app/sales-xray/report-settings.module.css";
import {
  Badge,
  Empty,
  Page,
  PageHeader,
  Panel,
  Table,
  Unavailable,
  Why,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

export default async function ReportSettingsPage() {
  const result = await adminRead(
    "/v1/admin/conversation/report-settings",
    normalizeReportSettings,
  );
  const data = result.ok ? result.data : null;
  // Only the newest choice of each scope can be rolled back.
  const newestChoice = new Set<string>();
  const seen = new Set<string>();
  for (const row of data?.history ?? []) {
    if (row.kind !== "assigned") continue;
    const scope = `${row.scope}:${row.tenantId ?? ""}:${row.industryCode ?? ""}`;
    if (!seen.has(scope)) newestChoice.add(row.id);
    seen.add(scope);
  }
  return (
    <Page>
      <PageHeader
        title="Report settings"
        context={[
          "How Report, Prospect and Coaching look for each organisation",
          "version 1 is today's report, frozen",
        ]}
      />
      {!result.ok ? (
        <Unavailable title="Report settings" reason={result.error} />
      ) : null}
      {data ? (
        <>
          <Panel
            title="Who uses which version"
            sub={`${data.organisations.length} organisations`}
            tools={
              <Why detail="An organisation uses the version chosen for it, else its industry's default (the industry comes from its profile), else the general default, else version 1. Choosing an earlier version is a rollback; every choice stays in the history." />
            }
          >
            {data.organisations.length ? (
              <Table label="Organisations and their versions">
                <thead>
                  <tr>
                    <th scope="col">Organisation</th>
                    <th scope="col">Industry</th>
                    <th scope="col">Uses</th>
                    <th scope="col">Choose</th>
                  </tr>
                </thead>
                <tbody>
                  {data.organisations.map((row) => (
                    <tr key={row.tenantId}>
                      <th scope="row">{row.name}</th>
                      <td>{row.industryCode ?? "not set"}</td>
                      <td>
                        Version {row.versionNumber}
                        <span className={styles.sub}>
                          {SOURCE_LABEL[row.source] ?? row.source}
                        </span>
                      </td>
                      <td>
                        <ChooseVersion
                          scope="organisation"
                          tenantId={row.tenantId}
                          current={row.ownVersionNumber}
                          inherited={
                            data.industries.find(
                              (item) => item.industryCode === row.industryCode,
                            )?.versionNumber ??
                            data.generalVersionNumber ??
                            1
                          }
                          versions={data.versions}
                          label={`Version for ${row.name}`}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <Empty icon={Layers} title="No Sales X-Ray organisations yet" />
            )}
          </Panel>
          <Panel
            title="Defaults"
            tools={
              <Why detail="The general default applies to every organisation without its own choice or an industry default. Industry defaults use the industry code on the organisation's profile (AUT-2115)." />
            }
          >
            <div className={styles.defaults}>
              <div>
                <strong>Everyone</strong>
                <ChooseVersion
                  scope="general"
                  current={data.generalVersionNumber}
                  versions={data.versions.filter((item) => item.number !== 1)}
                  label="General default version"
                />
              </div>
              {data.industries.map((row) => (
                <div key={row.industryCode}>
                  <strong>Industry {row.industryCode}</strong>
                  <ChooseVersion
                    scope="industry"
                    industryCode={row.industryCode}
                    current={row.versionNumber}
                    inherited={data.generalVersionNumber ?? 1}
                    versions={data.versions}
                    label={`Version for industry ${row.industryCode}`}
                  />
                </div>
              ))}
              <div>
                <strong>Add an industry default</strong>
                <IndustryDefault versions={data.versions} />
              </div>
            </div>
          </Panel>
          <Panel
            title="Versions"
            sub={`${data.versions.length} saved, none ever edited`}
            tools={
              <VersionEditor
                parameters={data.parameters}
                versions={data.versions}
              />
            }
          >
            <ol className={styles.versions}>
              {[...data.versions].reverse().map((version) => (
                <li key={version.number}>
                  <span className={styles.versionHead}>
                    <strong>
                      {version.number} · {version.label}
                    </strong>
                    {version.number === 1 ? (
                      <Badge tone="accent">frozen</Badge>
                    ) : null}
                    {version.industryCode ? (
                      <Badge>built for {version.industryCode}</Badge>
                    ) : null}
                    <span className={styles.sub}>
                      {version.baseNumber
                        ? `from version ${version.baseNumber} · `
                        : ""}
                      {stamp(version.createdAt)} · used by{" "}
                      {version.organisations}
                    </span>
                  </span>
                  {version.note ? (
                    <p className={styles.note}>{version.note}</p>
                  ) : null}
                  {version.changes.length ? (
                    <ul className={styles.changes}>
                      {version.changes.map((change) => (
                        <li key={change.key}>
                          {describeChange(change, data.parameters)}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ol>
          </Panel>
          <Panel title="History" sub="newest first, nothing is ever removed">
            {data.history.length ? (
              <Table label="Report settings history">
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">What</th>
                    <th scope="col">Why</th>
                    <th scope="col" />
                  </tr>
                </thead>
                <tbody>
                  {data.history.map((row) => (
                    <tr key={row.id}>
                      <td>{stamp(row.createdAt)}</td>
                      <th scope="row">{describeEvent(row)}</th>
                      <td>{row.reason ?? ""}</td>
                      <td>
                        {newestChoice.has(row.id) ? (
                          <RollBack row={row} />
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <Empty
                icon={Layers}
                title="Nothing changed yet"
                text="Everyone sees version 1, today's report."
              />
            )}
          </Panel>
        </>
      ) : null}
    </Page>
  );
}
