/**
 * Who does each job (owner, 20 Oct 2026: "assign per stage with one dropdown each"): every
 * paid stage with the provider and model it runs on and what it costs per audio minute.
 * Call data (fast and deep) and AI replies change here, through their own audited settings,
 * with an estimate per model before saving. Transcription, facts and the report change in
 * Routes (advanced) until the production approval design is decided. Phones get one card
 * per job, so the change is never off-screen.
 */
import Link from "next/link";

import { SettingControl } from "../settings/setting-control";
import { currentValue, type RegistrySetting } from "../settings/registry-data";
import { Badge, Card, Panel, Table, Why } from "../ui/kit";
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

type Props = {
  metrics: Metrics | null;
  settings: readonly RegistrySetting[];
  answers: Readonly<Record<string, unknown>>;
  prices: readonly ModelPrice[];
};

/** One job as this environment runs it: route, cost, and its setting when it changes here. */
function jobView(job: Job, { metrics, settings, answers }: Props) {
  const here = metrics?.here ?? null;
  const route =
    metrics?.routes.find(
      (item) => item.stage === job.stage && item.environment === here,
    ) ?? metrics?.routes.find((item) => item.stage === job.stage);
  const cost =
    metrics?.overview.byStage.find((row) => row.stage === job.stage) ?? null;
  const setting = job.setting
    ? settings.find((item) => item.id === job.setting)
    : undefined;
  // Each setting reads its value from its own area's answer, keyed by route.
  const answer = setting ? answers[setting.read.path] : undefined;
  const chosen =
    setting && answer !== undefined ? currentValue(setting, answer) : undefined;
  return {
    job,
    provider: route?.provider ?? null,
    model: typeof chosen === "string" ? chosen : (route?.model ?? null),
    cost,
    control: setting && answer !== undefined ? { setting, answer } : null,
  };
}

type View = ReturnType<typeof jobView>;

function RunsOn({ view }: { view: View }) {
  return view.model ? (
    <span className={styles.runsOn}>
      {view.provider ?? ""}
      <code>{view.model}</code>
    </span>
  ) : (
    <span className={styles.muted}>Not run in this window</span>
  );
}

function Estimates({ view, props }: { view: View; props: Props }) {
  const audio = props.metrics?.overview.audioMinutes ?? 0;
  const usdToInr = props.metrics?.fx.usdToInr ?? 100;
  const cost = view.cost;
  if (!cost || audio <= 0) return null;
  return (
    <ul
      className={styles.estimates}
      aria-label={`${view.job.label}: estimate per model`}
    >
      {props.prices.map((price) => (
        <li
          key={price.model}
          data-current={price.model === view.model ? "" : undefined}
        >
          {price.label}{" "}
          <b>
            {rupeesPerMinute(estimatePerMinute(cost, audio, price, usdToInr))}
          </b>
        </li>
      ))}
    </ul>
  );
}

function Change({ view, props }: { view: View; props: Props }) {
  if (view.control)
    return (
      <div className={styles.change}>
        <SettingControl
          setting={view.control.setting}
          answer={view.control.answer}
        />
        <Estimates view={view} props={props} />
      </div>
    );
  if (view.job.stage === "PR")
    return <span className={styles.muted}>Set in code</span>;
  return (
    <Link href={ROUTES}>
      Routes (advanced) <Badge>needs approval in production</Badge>
    </Link>
  );
}

export function StageAssignments(props: Props) {
  const { metrics } = props;
  const views = JOBS.map((job) => jobView(job, props));
  return (
    <Panel
      title="Who does each job"
      sub={`${metrics?.here ?? "This environment"} · last ${metrics?.days ?? 30} days`}
      tools={
        <Why detail="What each paid stage ran on most recently in this environment and what it cost per audio minute. Call data and AI replies change here through their own settings, each change audited; the estimate for each model uses this window's tokens per audio minute. Transcription, facts and the report change in Routes (advanced): production needs the owner's approval." />
      }
    >
      <Table
        label="Who does each job"
        cards={views.map((view) => (
          <Card key={view.job.stage}>
            <strong>{view.job.label}</strong>
            <span className={styles.cardLine}>
              <RunsOn view={view} />
              <span>{rupeesPerMinute(view.cost?.perMinute ?? null)}</span>
            </span>
            <Change view={view} props={props} />
          </Card>
        ))}
      >
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
          {views.map((view) => (
            <tr key={view.job.stage}>
              <th scope="row">{view.job.label}</th>
              <td>
                <RunsOn view={view} />
              </td>
              <td data-num="">
                {rupeesPerMinute(view.cost?.perMinute ?? null)}
              </td>
              <td>
                <Change view={view} props={props} />
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Panel>
  );
}
