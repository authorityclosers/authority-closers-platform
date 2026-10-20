import Link from "next/link";

import { BackgroundSwitch, RaiseCap } from "@/app/ai-spend/spend-controls";
import {
  WINDOWS,
  normalizeAiSpend,
  rupees,
  windowLabel,
  type AiSpend,
} from "@/app/ai-spend/spend-data";
import styles from "@/app/ai-spend/spend.module.css";
import { adminRead } from "@/app/lib/server-api";
import {
  Badge,
  Kpi,
  Meter,
  Page,
  PageHeader,
  Panel,
  Table,
  Tiles,
  Unavailable,
  hue,
  kitStyles,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const colour = (feature: string) => `hsl(${hue(feature)} 62% 52%)`;
const tone = (level: 50 | 80 | 100 | null) =>
  level === 100
    ? "bad"
    : level === 80
      ? "warn"
      : level === 50
        ? "info"
        : "good";

function Caps({ data }: { data: AiSpend }) {
  return (
    <Panel
      title="Caps"
      sub="Background jobs check these before every model call and wait at a cap"
    >
      {data.environment === "development" ? (
        <div className={styles.capRow}>
          <div className={styles.capText}>
            <span>
              Background AI on development
              <span className={styles.note}>
                Call data, pointer review and partner facts. The deep pipeline
                never runs by itself here and backfills never run here.
              </span>
            </span>
            <Badge tone={data.backgroundEnabled ? "warn" : "good"}>
              {data.backgroundEnabled ? "On" : "Off"}
            </Badge>
          </div>
          <BackgroundSwitch
            revision={data.revision}
            config={data.config}
            enabled={data.backgroundEnabled}
          />
        </div>
      ) : null}
      {data.caps.map((cap) => (
        <div className={styles.capRow} key={cap.target}>
          <div>
            <div className={styles.capText}>
              <span>{cap.label}</span>
              <span className={styles.num}>
                {rupees(cap.spentInr)} of {rupees(cap.capInr)}{" "}
                {cap.level !== null ? (
                  <Badge tone={tone(cap.level)}>{cap.level}%</Badge>
                ) : null}
              </span>
            </div>
            <Meter
              value={cap.spentInr}
              max={Math.max(cap.capInr, cap.spentInr, 1)}
              label={`${cap.label}: ${rupees(cap.spentInr)} of ${rupees(cap.capInr)}`}
            />
          </div>
          <RaiseCap
            revision={data.revision}
            target={cap.target}
            raiseTo={cap.raiseToInr}
          />
        </div>
      ))}
    </Panel>
  );
}

function Elsewhere({ data }: { data: AiSpend }) {
  if (!data.elsewhere.length) return null;
  return (
    <Panel title="Caps on their own pages" sub="Raise these where they live">
      {data.elsewhere.map((item) => (
        <div className={styles.capRow} key={item.feature}>
          <div>
            <div className={styles.capText}>
              <span>
                {item.label}{" "}
                <Badge tone={item.enabled ? "info" : "neutral"}>
                  {item.enabled ? "On" : "Off"}
                </Badge>
              </span>
              <span className={styles.num}>
                {rupees(item.spentInr)} of {rupees(item.capInr)},{" "}
                {windowLabel(item.window)}
              </span>
            </div>
            <Meter
              value={item.spentInr}
              max={Math.max(item.capInr, item.spentInr, 1)}
            />
          </div>
          {item.page ? (
            <Link
              href={item.page}
              className={kitStyles.button}
              data-variant="ghost"
            >
              Open
            </Link>
          ) : null}
        </div>
      ))}
      <span className={styles.note}>
        Customer call analysis has its own analysis budget (Execution & budget):
        it waits instead of failing, and these caps never stop it.
      </span>
    </Panel>
  );
}

function ByDay({ data }: { data: AiSpend }) {
  const top = Math.max(...data.byDay.map((day) => day.inr), 1);
  return (
    <Panel title="By day" sub={`Last ${data.days} days, India time`}>
      <div className={styles.days} role="img" aria-label="AI spend per day">
        {data.byDay.map((day) => (
          <div
            className={styles.day}
            key={day.day}
            title={`${day.day}: ${rupees(day.inr)}`}
          >
            {day.parts.map((part) => (
              <span
                key={part.feature}
                className={styles.slice}
                style={{
                  height: `${(100 * part.inr) / top}%`,
                  background: colour(part.feature),
                }}
              />
            ))}
          </div>
        ))}
      </div>
      <div className={styles.dayLabels}>
        {data.byDay.map((day) => (
          <span key={day.day}>{day.day.slice(5)}</span>
        ))}
      </div>
      <div className={styles.legend}>
        {data.features.map((line) => (
          <span key={line.key}>
            <span
              className={styles.swatch}
              style={{ background: colour(line.key) }}
            />
            {line.label}
          </span>
        ))}
      </div>
    </Panel>
  );
}

function ByFeature({ data }: { data: AiSpend }) {
  return (
    <Panel title="By feature" sub={`Last ${data.days} days`}>
      <Table label="AI spend by feature">
        <thead>
          <tr>
            <th>Feature</th>
            <th>Who started it</th>
            <th className={styles.num}>Requests</th>
            <th className={styles.num}>Spend</th>
          </tr>
        </thead>
        <tbody>
          {data.features.map((line) => (
            <tr key={line.key}>
              <td>{line.label}</td>
              <td>
                {line.byTrigger
                  .map((part) => `${part.label} ${rupees(part.inr)}`)
                  .join(" · ")}
              </td>
              <td className={styles.num}>{line.requests}</td>
              <td className={styles.num}>{rupees(line.inr)}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Panel>
  );
}

function Models({ data }: { data: AiSpend }) {
  return (
    <Panel title="Models" sub="Tokens and audio, per feature">
      <Table label="AI spend by model">
        <thead>
          <tr>
            <th>Feature</th>
            <th>Model</th>
            <th className={styles.num}>Requests</th>
            <th className={styles.num}>Tokens in / out</th>
            <th className={styles.num}>Audio min</th>
            <th className={styles.num}>Spend</th>
          </tr>
        </thead>
        <tbody>
          {data.models.map((line) => (
            <tr key={`${line.feature}-${line.provider}-${line.model}`}>
              <td>{line.feature}</td>
              <td>{line.model || line.provider}</td>
              <td className={styles.num}>{line.requests}</td>
              <td className={styles.num}>
                {line.inputTokens.toLocaleString("en-IN")} /{" "}
                {line.outputTokens.toLocaleString("en-IN")}
              </td>
              <td className={styles.num}>{line.audioMinutes || "–"}</td>
              <td className={styles.num}>{rupees(line.inr)}</td>
            </tr>
          ))}
        </tbody>
      </Table>
      {data.unpriced ? (
        <span className={styles.note}>
          {data.unpriced} requests used a model with no list price and count as
          ₹0.
        </span>
      ) : null}
    </Panel>
  );
}

export default async function AiSpendPage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const query = await searchParams;
  const days = WINDOWS.find((value) => value === query.days) ?? "14";
  const result = await adminRead(
    `/v1/admin/ai-spend?days=${days}`,
    normalizeAiSpend,
  );
  return (
    <Page wide>
      <PageHeader
        title="AI spend"
        context={[
          "Every paid AI request in this environment: by day, by feature and by who started it. List-price estimates for Admin only, never a charge.",
        ]}
        actions={
          <span className={styles.control}>
            {WINDOWS.map((value) => (
              <Link
                key={value}
                href={`/ai-spend?days=${value}`}
                className={kitStyles.button}
                data-variant={value === days ? "primary" : "ghost"}
                aria-current={value === days ? "page" : undefined}
              >
                {value} days
              </Link>
            ))}
          </span>
        }
      />
      {result.ok ? (
        <>
          <Tiles label="AI spend now">
            <Kpi
              label="Last 24 hours"
              value={rupees(result.data.last24hInr)}
              tone={tone(
                result.data.caps.find((c) => c.target === "daily")?.level ??
                  null,
              )}
            />
            <Kpi
              label="This month"
              value={rupees(result.data.monthInr)}
              tone={tone(
                result.data.caps.find((c) => c.target === "monthly")?.level ??
                  null,
              )}
            />
            <Kpi
              label={`Last ${result.data.days} days`}
              value={rupees(result.data.totalInr)}
            />
            <Kpi
              label="A month at this week's pace"
              value={rupees(result.data.projectedMonthInr)}
            />
          </Tiles>
          {result.data.alerts.length ? (
            <Panel title="Alerts" sub="50, 80 and 100% of a cap">
              {result.data.alerts.map((alert) => (
                <div className={styles.capRow} key={alert.target}>
                  <span>
                    <Badge tone={tone(alert.level)}>{alert.level}%</Badge>{" "}
                    {alert.label}: {rupees(alert.spentInr)} of{" "}
                    {rupees(alert.capInr)}
                  </span>
                </div>
              ))}
            </Panel>
          ) : null}
          <div className={styles.grid}>
            <Caps data={result.data} />
            <Elsewhere data={result.data} />
            <ByDay data={result.data} />
            <ByFeature data={result.data} />
            <Models data={result.data} />
            <Panel title="Rules">
              <ul className={styles.rules}>
                {result.data.rules.map((rule) => (
                  <li key={rule}>{rule}</li>
                ))}
              </ul>
            </Panel>
          </div>
        </>
      ) : (
        <Unavailable title="AI spend" reason={result.error} />
      )}
    </Page>
  );
}
