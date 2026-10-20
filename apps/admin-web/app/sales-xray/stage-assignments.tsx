/**
 * Who does each job (owner, 20 Oct 2026: "assign per stage with one dropdown each"): every
 * paid stage with the provider and model it runs on and what it costs per audio minute.
 * Call data (fast and deep) and AI replies change here, through their own audited settings,
 * with an estimate per model before saving. Transcription, facts and the report change in
 * Routes (advanced) until the production approval design is decided.
 */
import Link from "next/link";

import { SettingControl } from "../settings/setting-control";
import { currentValue, type RegistrySetting } from "../settings/registry-data";
import { Badge, Panel, Table, Why } from "../ui/kit";
import type { Metrics } from "../usage/cost-data";
import {
  estimatePerMinute,
  rupeesPerMinute,
  type ModelPrice,
} from "./provider-hub-data";
import styles from "./provider-hub.module.css";

type Job = { stage: string; label: string; setting?: string };

export const JOBS: readonly Job[] = [
  { stage: "C2", label: "Transcription" },
  { stage: "C4", label: "Facts" },
  { stage: "C5", label: "Report and coaching" },
  { stage: "PR", label: "Pointer review" },
  { stage: "CDF", label: "Call data · fast", setting: "call_data.fast.model" },
  { stage: "CDD", label: "Call data · deep", setting: "call_data.deep.model" },
  { stage: "AR", label: "AI replies", setting: "lead_desk_ai.model" },
];

const ROUTES = "/sales-xray/providers?tab=providers";

export function StageAssignments({
  metrics,
  settings,
  answers,
  prices,
}: {
  metrics: Metrics | null;
  settings: readonly RegistrySetting[];
  answers: Readonly<Record<string, unknown>>;
  prices: readonly ModelPrice[];
}) {
  const here = metrics?.here ?? null;
  const usdToInr = metrics?.fx.usdToInr ?? 100;
  const audio = metrics?.overview.audioMinutes ?? 0;
  return (
    <Panel
      title="Who does each job"
      sub={`Changes here apply to ${here ?? "this environment"} · costs from the last ${metrics?.days ?? 30} days`}
      tools={
        <Why detail="What each paid stage ran on most recently and what it cost per audio minute. Call data and AI replies change here through their own settings, each change audited; the estimate for each model uses this window's tokens per audio minute. Transcription, facts and the report change in Routes (advanced): production needs the owner's approval." />
      }
    >
      <Table label="Who does each job">
        <thead>
          <tr>
            <th scope="col">Job</th>
            <th scope="col">Runs on</th>
            <th scope="col" data-num="">
              Per audio minute
            </th>
            <th scope="col">Change</th>
          </tr>
        </thead>
        <tbody>
          {JOBS.map((job) => {
            const route =
              metrics?.routes.find(
                (item) => item.stage === job.stage && item.environment === here,
              ) ?? metrics?.routes.find((item) => item.stage === job.stage);
            const cost = metrics?.overview.byStage.find(
              (row) => row.stage === job.stage,
            );
            const setting = job.setting
              ? settings.find((item) => item.id === job.setting)
              : undefined;
            // Each setting reads its value from its own area's answer, keyed by route.
            const answer = setting ? answers[setting.read.path] : undefined;
            const chosen =
              setting && answer ? currentValue(setting, answer) : undefined;
            const model =
              typeof chosen === "string" ? chosen : (route?.model ?? null);
            return (
              <tr key={job.stage}>
                <th scope="row">{job.label}</th>
                <td>
                  {model ? (
                    <span className={styles.runsOn}>
                      {route?.provider ?? ""}
                      <code>{model}</code>
                    </span>
                  ) : (
                    <span className={styles.muted}>Not run in this window</span>
                  )}
                </td>
                <td data-num="">{rupeesPerMinute(cost?.perMinute ?? null)}</td>
                <td>
                  {setting && answer !== undefined ? (
                    <div className={styles.change}>
                      <SettingControl setting={setting} answer={answer} />
                      {cost && audio > 0 ? (
                        <ul
                          className={styles.estimates}
                          aria-label={`${job.label}: estimate per model`}
                        >
                          {prices.map((price) => {
                            const estimate = estimatePerMinute(
                              cost,
                              audio,
                              price,
                              usdToInr,
                            );
                            return (
                              <li
                                key={price.model}
                                data-current={
                                  price.model === model ? "" : undefined
                                }
                              >
                                {price.label} <b>{rupeesPerMinute(estimate)}</b>
                              </li>
                            );
                          })}
                        </ul>
                      ) : null}
                    </div>
                  ) : job.stage === "PR" ? (
                    <span className={styles.muted}>Set in code</span>
                  ) : (
                    <Link href={ROUTES}>
                      Routes (advanced){" "}
                      <Badge>needs approval in production</Badge>
                    </Link>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </Table>
    </Panel>
  );
}
