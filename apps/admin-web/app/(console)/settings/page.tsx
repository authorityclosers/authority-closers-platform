import { when } from "@/app/calls/call-data";
import { consoleEnvironment } from "@/app/lib/console-access";
import { read } from "@/app/lib/read";
import { adminRead } from "@/app/lib/server-api";
import { normalizeCallData } from "@/app/sales-xray/call-data-model";
import { normalizeReportSettings } from "@/app/sales-xray/report-settings-data";
import {
  analysisArea,
  callDataArea,
  executionArea,
  providerArea,
  reportArea,
  type SettingsArea,
} from "@/app/settings/settings-data";
import styles from "@/app/settings/settings.module.css";
import { Page, PageHeader, Panel, Table, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

/**
 * Admin → Settings (owner 19 Oct: "every setting exposed and changeable in one
 * click"): every area's settings and their values now, read in parallel from
 * the reads their own pages use, each with its last change and a Change link.
 */
export default async function SettingsPage() {
  const [providers, analysis, execution, callData, report] = await Promise.all([
    adminRead("/v1/admin/conversation/providers", read.object),
    adminRead("/v1/admin/conversation/analysis-settings", read.object),
    adminRead("/v1/admin/conversation/execution", read.object),
    adminRead("/v1/admin/call-data", normalizeCallData),
    adminRead(
      "/v1/admin/conversation/report-settings",
      normalizeReportSettings,
    ),
  ]);
  const areas: SettingsArea[] = [
    providerArea(providers),
    analysisArea(analysis),
    executionArea(execution),
    callDataArea(callData),
    reportArea(report),
  ];
  const settings = areas.reduce((sum, item) => sum + item.rows.length, 0);
  const missing = areas.filter((item) => item.unavailable).length;
  const environment = consoleEnvironment();

  return (
    <Page>
      <PageHeader
        title="Settings"
        context={[
          "Every setting Admin controls, its value now and where to change it",
          `${settings} settings in ${areas.length} areas`,
          missing ? `${missing} could not be read` : "All read just now",
          environment
            ? `${environment[0].toUpperCase()}${environment.slice(1)}`
            : null,
        ]}
      />
      <div className={styles.grid}>
        {areas.map((item) => (
          <Panel
            key={item.key}
            title={item.title}
            sub={item.what}
            action={{ href: item.href, label: "Change" }}
            foot={
              item.unavailable ? undefined : (
                <span className={styles.foot}>
                  {item.revision ? `Revision ${item.revision} · ` : ""}
                  {item.changedAt
                    ? `last changed ${when(item.changedAt)}`
                    : "never changed; defaults"}
                </span>
              )
            }
          >
            {item.unavailable ? (
              <Unavailable title={item.title} reason={item.unavailable} />
            ) : (
              <Table label={item.title}>
                <thead>
                  <tr>
                    <th scope="col">Setting</th>
                    <th scope="col">Now</th>
                  </tr>
                </thead>
                <tbody>
                  {item.rows.map((row) => (
                    <tr key={row.label}>
                      <th scope="row">{row.label}</th>
                      <td>
                        {row.value}
                        {row.note ? (
                          <small className={styles.note}>{row.note}</small>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Panel>
        ))}
      </div>
    </Page>
  );
}
