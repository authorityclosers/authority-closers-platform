import { when } from "@/app/calls/call-data";
import { consoleEnvironment } from "@/app/lib/console-access";
import { read } from "@/app/lib/read";
import { adminRead } from "@/app/lib/server-api";
import { normalizeCallData } from "@/app/sales-xray/call-data-model";
import { normalizeReportSettings } from "@/app/sales-xray/report-settings-data";
import {
  normalizePipelineSettings,
  reviewArea,
} from "@/app/settings/review-pipelines-data";
import {
  analysisArea,
  callDataArea,
  executionArea,
  providerArea,
  reportArea,
  type SettingsArea,
} from "@/app/settings/settings-data";
import { normalizeRegistry } from "@/app/settings/registry-data";
import { SettingControl } from "@/app/settings/setting-control";
import styles from "@/app/settings/settings.module.css";
import { Page, PageHeader, Panel, Table, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

/**
 * Admin → Settings (owner 19 Oct: "every setting exposed and changeable in one
 * click"): every area's settings and their values now, read in parallel from
 * the reads their own pages use, each with its last change and a Change link.
 */
export default async function SettingsPage() {
  const [
    providers,
    analysis,
    execution,
    budget,
    callDataRaw,
    report,
    review,
    registry,
  ] = await Promise.all([
    adminRead("/v1/admin/conversation/providers", read.object),
    adminRead("/v1/admin/conversation/analysis-settings", read.object),
    adminRead("/v1/admin/conversation/execution", read.object),
    adminRead("/v1/admin/conversation/budget", read.object),
    adminRead("/v1/admin/call-data", read.object),
    adminRead(
      "/v1/admin/conversation/report-settings",
      normalizeReportSettings,
    ),
    adminRead(
      "/v1/admin/conversation/review/pipelines",
      normalizePipelineSettings,
    ),
    adminRead("/v1/admin/settings", normalizeRegistry),
  ]);
  const callData = callDataRaw.ok
    ? { ok: true as const, data: normalizeCallData(callDataRaw.data) }
    : callDataRaw;
  // Each area's answer as read, by its route: the registry's controls change from these.
  const answers: Record<string, unknown> = Object.fromEntries(
    (
      [
        ["/v1/admin/conversation/providers", providers],
        ["/v1/admin/conversation/analysis-settings", analysis],
        ["/v1/admin/conversation/execution", execution],
        ["/v1/admin/conversation/budget", budget],
        ["/v1/admin/call-data", callDataRaw],
      ] as const
    )
      .filter(([, result]) => result.ok)
      .map(([path, result]) => [path, result.ok ? result.data : null]),
  );
  const control = (id: string | undefined) => {
    const setting =
      id && registry.ok
        ? registry.data.settings.find((item) => item.id === id)
        : undefined;
    if (!setting?.write || !(setting.read.path in answers)) return null;
    return (
      <SettingControl setting={setting} answer={answers[setting.read.path]} />
    );
  };
  const areas: SettingsArea[] = [
    providerArea(providers),
    analysisArea(analysis),
    executionArea(execution, budget),
    callDataArea(callData),
    reportArea(report),
    reviewArea(review),
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
          registry.ok
            ? "Change in place: each change goes through its area's own checks"
            : null,
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
                        <div className={styles.now}>
                          <span>
                            {row.value}
                            {row.note ? (
                              <small className={styles.note}>{row.note}</small>
                            ) : null}
                          </span>
                          {control(row.id)}
                        </div>
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
