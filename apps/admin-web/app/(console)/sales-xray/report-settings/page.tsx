import { Layers } from "lucide-react";

import { adminRead } from "@/app/lib/server-api";
import { stamp } from "@/app/usage/cost-data";
import {
  ChooseVersion,
  IndustryDefault,
  RollBack,
  VersionEditor,
} from "@/app/sales-xray/report-settings";
import { ReportPreview } from "@/app/sales-xray/report-preview";
import {
  SOURCE_LABEL,
  describeChange,
  describeEvent,
  industryName,
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
              <Why detail="An organisation uses the version chosen for it, else its industry's default (its industry is the profile its lead stages were built from), else the general default, else version 1. Choosing an earlier version is a rollback; every choice stays in the history." />
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
                      <td>
                        {industryName(
                          row.industryCode,
                          data.industryProfiles,
                        ) ?? "not set"}
                      </td>
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
              <Why detail="The general default applies to every organisation without its own choice or an industry default. Industries are the lead-stage profiles (Real estate, Insurance and so on): an organisation's industry is the one its lead stages were built from." />
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
                  <strong>
                    {industryName(row.industryCode, data.industryProfiles)}
                  </strong>
                  <ChooseVersion
                    scope="industry"
                    industryCode={row.industryCode}
                    current={row.versionNumber}
                    inherited={data.generalVersionNumber ?? 1}
                    versions={data.versions}
                    label={`Version for ${industryName(row.industryCode, data.industryProfiles)}`}
                  />
                </div>
              ))}
              <div>
                <strong>Add an industry default</strong>
                <IndustryDefault
                  versions={data.versions}
                  profiles={data.industryProfiles}
                />
              </div>
            </div>
          </Panel>
          <Panel
            title="Versions"
            sub={`${data.versions.length} saved, none ever edited · publish makes one everyone's default`}
          >
            <VersionEditor
              parameters={data.parameters}
              versions={data.versions}
              profiles={data.industryProfiles}
              generalVersionNumber={data.generalVersionNumber}
            />
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
                      <Badge>
                        built for{" "}
                        {industryName(
                          version.industryCode,
                          data.industryProfiles,
                        )}
                      </Badge>
                    ) : null}
                    {version.number === (data.generalVersionNumber ?? 1) ? (
                      <Badge tone="good">everyone&rsquo;s default</Badge>
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
                  <details className={styles.previewToggle}>
                    <summary>Preview on a fictional call</summary>
                    <ReportPreview
                      settings={version.settings}
                      baseline={data.versions[0]?.settings ?? {}}
                      parameters={data.parameters}
                    />
                  </details>
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
