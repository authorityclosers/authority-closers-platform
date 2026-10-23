/**
 * Admin → Product telemetry (owner, 24 Oct 2026: "Build full performance and usage
 * telemetry with the Admin dashboard"; "40% of devices are slow when clicking a lead").
 * One environment's speed per action by device tier and class, Web Vitals and app start,
 * the screen heatmap and flows, funnels, feature adoption, errors and slow APIs, rage and
 * dead taps, and releases. Counts and timings only: no person, workspace or call is named.
 */
import { Badge, Card, Kpi, Meter, Panel, Table, Tiles, Why } from "../ui/kit";
import {
  heatLevel,
  msWords,
  ratingTone,
  screenWords,
  shareWords,
  slowDeviceLine,
  slowTone,
  VITAL_WORDS,
  vitalWords,
  type ProductTelemetry,
  type SpeedRow,
  type Timing,
} from "./telemetry-data";
import styles from "./telemetry.module.css";

const TIER_WORDS: Record<string, string> = {
  low: "Low-end",
  mid: "Mid-range",
  high: "High-end",
  unknown: "Unknown",
};

const DAY = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  timeZone: "Asia/Kolkata",
});
const HOUR = new Intl.DateTimeFormat("en-IN", {
  hour: "2-digit",
  timeZone: "Asia/Kolkata",
});
const WHEN = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});

function bucketWords(bucket: string, hourly: boolean) {
  // Buckets are India time: "2026-10-24" or "2026-10-24T09:00".
  const moment = Date.parse(
    hourly ? `${bucket}:00+05:30` : `${bucket}T12:00:00+05:30`,
  );
  if (Number.isNaN(moment)) return bucket;
  return hourly ? HOUR.format(moment) : DAY.format(moment);
}

function when(iso: string) {
  const moment = Date.parse(iso);
  return Number.isNaN(moment) ? "–" : WHEN.format(moment);
}

function Slow({ share }: { share: number | null }) {
  return (
    <span className={styles.slow} data-tone={slowTone(share)}>
      {shareWords(share)}
    </span>
  );
}

function tierLine(row: SpeedRow) {
  return row.byTier
    .map((tier) => `${TIER_WORDS[tier.tier] ?? tier.tier} ${msWords(tier.p75)}`)
    .join(" · ");
}

function Speed({ telemetry }: { telemetry: ProductTelemetry }) {
  const rows = telemetry.speed;
  const lead = rows.find((row) => row.action === "lead_open");
  const headline = slowDeviceLine(lead ?? rows[0]);
  return (
    <Panel
      title="Speed: tap to response"
      sub="From the tap to the screen settling, on people's own devices"
      tools={
        <Why detail="From the tap to the screen settling (no change for 150 ms, at most 10 s), measured on the person's own device. A device is one person on one device class and tier; it is slow when its median is over the action's limit. Input to paint is the browser's own time to the next frame after the tap (Chrome and Android only)." />
      }
    >
      <div className={styles.body}>
        <p
          className={styles.headline}
          data-tone={slowTone((lead ?? rows[0])?.slowDeviceShare ?? null)}
        >
          {headline ?? "No timed taps in this window yet."}
        </p>
      </div>
      {rows.length ? (
        <Table
          label="Tap to response per action"
          cards={rows.map((row) => (
            <Card key={row.action}>
              <strong>{row.label}</strong>
              <span>
                Median {msWords(row.p50)} · 75% under {msWords(row.p75)} · slow
                over {msWords(row.slowMs)}
              </span>
              <span>
                Slow taps <Slow share={row.slowShare} /> · slow devices{" "}
                <Slow share={row.slowDeviceShare} /> of {row.devices}
              </span>
              <span className={styles.muted}>{tierLine(row)}</span>
            </Card>
          ))}
        >
          <thead>
            <tr>
              <th scope="col">Action</th>
              <th scope="col" data-num="">
                Taps
              </th>
              <th scope="col" data-num="">
                Median
              </th>
              <th scope="col" data-num="">
                75%
              </th>
              <th scope="col" data-num="">
                Slow taps
              </th>
              <th scope="col" data-num="">
                Slow devices
              </th>
              <th scope="col">By device tier (75%)</th>
              <th scope="col" data-num="">
                Input to paint
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.action}>
                <th scope="row">
                  {row.label}
                  <small className={styles.muted}>
                    {" "}
                    over {msWords(row.slowMs)}
                  </small>
                </th>
                <td data-num="">{row.taps}</td>
                <td data-num="">{msWords(row.p50)}</td>
                <td data-num="">{msWords(row.p75)}</td>
                <td data-num="">
                  <Slow share={row.slowShare} />
                </td>
                <td data-num="">
                  <Slow share={row.slowDeviceShare} />
                  <small className={styles.muted}> of {row.devices}</small>
                </td>
                <td className={styles.muted}>{tierLine(row) || "–"}</td>
                <td data-num="">{msWords(row.paintP75)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
      {lead?.byDevice.length ? (
        <p className={`${styles.line} ${styles.body}`}>
          Opening a lead by device:{" "}
          {lead.byDevice
            .map(
              (part: Timing & { device: string }) =>
                `${part.device} ${msWords(part.p75)} (${shareWords(part.slowShare)} slow)`,
            )
            .join(" · ")}
        </p>
      ) : null}
    </Panel>
  );
}

function Vitals({ telemetry }: { telemetry: ProductTelemetry }) {
  return (
    <Panel
      title="Web Vitals and start"
      sub="The 75th percentile, rated by web.dev's limits"
      tools={
        <Why detail="Largest paint, response to input, layout shift, first paint and first byte, as each browser reports them, and the app's start: from opening the page or app to the first screen working. Cold is the first start in a browser session." />
      }
    >
      <div className={styles.body}>
        {telemetry.vitals.length ? (
          <div className={styles.vitals}>
            {telemetry.vitals.map((vital) => (
              <section
                key={vital.metric}
                className={styles.vital}
                aria-label={`${VITAL_WORDS[vital.metric]?.label ?? vital.metric}: ${vitalWords(vital.metric, vital.p75)}`}
              >
                <span className={styles.label}>
                  {VITAL_WORDS[vital.metric]?.label ?? vital.metric}
                </span>
                <strong data-tone={ratingTone(vital.rating)}>
                  {vitalWords(vital.metric, vital.p75)}
                </strong>
                <span className={styles.muted}>
                  {shareWords(vital.shares.good)} good ·{" "}
                  {shareWords(vital.shares.poor)} poor · {vital.samples} samples
                </span>
                {vital.byDevice.length ? (
                  <span className={styles.muted}>
                    {vital.byDevice
                      .map(
                        (part) =>
                          `${part.device} ${vitalWords(vital.metric, part.p75)}`,
                      )
                      .join(" · ")}
                  </span>
                ) : null}
              </section>
            ))}
          </div>
        ) : (
          <p className={styles.line}>No vitals in this window yet.</p>
        )}
        {telemetry.starts.length ? (
          <p className={styles.line}>
            Start:{" "}
            {telemetry.starts
              .map(
                (start) =>
                  `${start.start} ${start.app} median ${msWords(start.p50)}, 75% ${msWords(start.p75)} (${start.samples})`,
              )
              .join(" · ")}
          </p>
        ) : null}
      </div>
    </Panel>
  );
}

function Screens({ telemetry }: { telemetry: ProductTelemetry }) {
  const { buckets, hourly, rows, flows } = telemetry.screens;
  // One scale for the whole table: the busiest screens show darkest.
  const max = Math.max(0, ...rows.flatMap((row) => row.heat));
  return (
    <Panel
      title="Screens"
      sub={`Views by ${hourly ? "hour" : "day"}, India time`}
      tools={
        <Why detail="Each screen's views and people, how long people stayed (median), and the share of sessions that ended there. The heatmap shades the busiest screen and bucket darkest, on one scale for the whole table." />
      }
    >
      <div className={styles.body}>
        {rows.length ? (
          <div className={styles.heatWrap}>
            <table className={styles.heat} aria-label="Screen views heatmap">
              <thead>
                <tr>
                  <th scope="col">Screen</th>
                  <th scope="col" data-num="">
                    Views
                  </th>
                  <th scope="col" data-num="">
                    People
                  </th>
                  <th scope="col" data-num="">
                    Stay
                  </th>
                  <th scope="col" data-num="">
                    Exits
                  </th>
                  {buckets.map((bucket, index) => (
                    <th key={bucket} scope="col" className={styles.bucket}>
                      {index % (hourly ? 3 : 1) === 0
                        ? bucketWords(bucket, hourly)
                        : ""}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  return (
                    <tr key={row.screen}>
                      <th scope="row">{screenWords(row.screen)}</th>
                      <td data-num="">{row.views}</td>
                      <td data-num="">{row.people}</td>
                      <td data-num="">{msWords(row.stayP50)}</td>
                      <td data-num="">{shareWords(row.exitShare)}</td>
                      {row.heat.map((value, index) => (
                        <td
                          key={buckets[index] ?? index}
                          className={styles.cell}
                          data-level={heatLevel(value, max)}
                          title={`${bucketWords(buckets[index] ?? "", hourly)}: ${value}`}
                        >
                          <span className={styles.visuallyHidden}>{value}</span>
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className={styles.line}>No screens viewed in this window yet.</p>
        )}
        {flows.length ? (
          <ol
            className={styles.flows}
            aria-label="Busiest moves between screens"
          >
            {flows.map((flow) => (
              <li key={`${flow.from}-${flow.to}`}>
                {screenWords(flow.from)} → {screenWords(flow.to)}{" "}
                <span className={styles.muted}>{flow.count}</span>
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </Panel>
  );
}

function Funnels({ telemetry }: { telemetry: ProductTelemetry }) {
  return (
    <Panel title="Funnels" sub="People who reached each step, in this window">
      <div className={styles.body}>
        <div className={styles.funnels}>
          {telemetry.funnels.map((funnel) => {
            const first = funnel.steps[0]?.people ?? 0;
            return (
              <section
                key={funnel.key}
                aria-label={funnel.label}
                className={styles.funnel}
              >
                <strong>{funnel.label}</strong>
                <ol>
                  {funnel.steps.map((step) => (
                    <li key={step.key}>
                      <span>{step.label}</span>
                      <Meter value={step.people} max={first} />
                      <span className={styles.num}>
                        {step.people} <small>{shareWords(step.share)}</small>
                      </span>
                    </li>
                  ))}
                </ol>
              </section>
            );
          })}
        </div>
      </div>
    </Panel>
  );
}

function Features({ telemetry }: { telemetry: ProductTelemetry }) {
  const { activePeople, rows } = telemetry.features;
  return (
    <Panel title="Feature adoption" sub={`Of ${activePeople} active people`}>
      <div className={styles.body}>
        {rows.length ? (
          <ul className={styles.bars} aria-label="Feature adoption">
            {rows.map((row) => (
              <li key={row.feature}>
                <span>{row.label}</span>
                <Meter value={row.people} max={activePeople} />
                <span className={styles.num}>
                  {row.people} <small>{shareWords(row.share)}</small>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.line}>No use recorded in this window yet.</p>
        )}
      </div>
    </Panel>
  );
}

function Problems({ telemetry }: { telemetry: ProductTelemetry }) {
  const { scripts, apis, taps, shown } = telemetry.errors;
  return (
    <Panel
      title="Errors, slow calls and frustrated taps"
      tools={
        <Why detail="Script errors carry their class and a fingerprint of where they were thrown, never their message. Slow API calls took 1.5 s or more, or failed with a 5xx; every id is taken out of the path. A rage tap is three taps in a second on one spot; a dead tap is a tap on something that looks tappable and changes nothing." />
      }
    >
      <div className={styles.body}>
        <h3 className={styles.heading}>Script errors</h3>
        {scripts.length ? (
          <Table
            label="Script errors"
            cards={scripts.map((row) => (
              <Card key={`${row.error}-${row.where}`}>
                <strong>
                  {row.error} <code>{row.where}</code>
                </strong>
                <span>
                  {row.count} times · {row.people} people · {row.source}
                </span>
                <span className={styles.muted}>
                  {row.screens.map(screenWords).join(", ")} ·{" "}
                  {row.releases.join(", ")}
                </span>
              </Card>
            ))}
          >
            <thead>
              <tr>
                <th scope="col">Error</th>
                <th scope="col" data-num="">
                  Times
                </th>
                <th scope="col" data-num="">
                  People
                </th>
                <th scope="col">Where</th>
                <th scope="col">Releases</th>
                <th scope="col">Last</th>
              </tr>
            </thead>
            <tbody>
              {scripts.map((row) => (
                <tr key={`${row.error}-${row.where}`}>
                  <th scope="row">
                    {row.error} <code>{row.where}</code>{" "}
                    <Badge tone={row.source === "app" ? "bad" : "neutral"}>
                      {row.source}
                    </Badge>
                  </th>
                  <td data-num="">{row.count}</td>
                  <td data-num="">{row.people}</td>
                  <td>{row.screens.map(screenWords).join(", ")}</td>
                  <td>{row.releases.join(", ")}</td>
                  <td>{when(row.lastAt)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <p className={styles.line}>No script errors in this window.</p>
        )}
        <h3 className={styles.heading}>Slow or failed API calls</h3>
        {apis.length ? (
          <ul className={styles.plain}>
            {apis.map((row) => (
              <li key={row.endpoint}>
                <code>{row.endpoint}</code> {row.count} slow, 75%{" "}
                {msWords(row.p75)}
                {row.failed ? (
                  <>
                    {" "}
                    · <Badge tone="bad">{row.failed} failed</Badge>
                  </>
                ) : null}{" "}
                <span className={styles.muted}>
                  {row.screens.map(screenWords).join(", ")}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.line}>No slow API calls in this window.</p>
        )}
        <h3 className={styles.heading}>Rage and dead taps</h3>
        {taps.length ? (
          <ul className={styles.plain}>
            {taps.map((row) => (
              <li key={`${row.kind}-${row.screen}-${row.target}`}>
                <Badge tone={row.kind === "rage" ? "warn" : "neutral"}>
                  {row.kind}
                </Badge>{" "}
                {screenWords(row.screen)}, a {row.target}: {row.count} times by{" "}
                {row.people} {row.people === 1 ? "person" : "people"}
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.line}>No rage or dead taps in this window.</p>
        )}
        {shown.length ? (
          <>
            <h3 className={styles.heading}>Error cards shown</h3>
            <ul className={styles.plain}>
              {shown.map((row) => (
                <li key={`${row.surface}-${row.code}`}>
                  <code>{row.surface}</code> {row.code}: {row.count}
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </Panel>
  );
}

function Releases({ telemetry }: { telemetry: ProductTelemetry }) {
  const rows = telemetry.releaseRows;
  if (!rows.length) return null;
  return (
    <Panel
      title="By release"
      sub="Opening a lead and script errors per release"
    >
      <Table
        label="Telemetry by release"
        cards={rows.map((row) => (
          <Card key={row.release}>
            <strong>
              <code>{row.release || "unknown"}</code>
            </strong>
            <span>
              {row.people} people · open a lead 75% {msWords(row.leadOpen.p75)},{" "}
              <Slow share={row.leadOpen.slowShare} /> slow
            </span>
            <span>{row.scriptErrors} script errors</span>
          </Card>
        ))}
      >
        <thead>
          <tr>
            <th scope="col">Release</th>
            <th scope="col" data-num="">
              People
            </th>
            <th scope="col" data-num="">
              Events
            </th>
            <th scope="col" data-num="">
              Open a lead, 75%
            </th>
            <th scope="col" data-num="">
              Slow
            </th>
            <th scope="col" data-num="">
              Script errors
            </th>
            <th scope="col">First seen</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.release}>
              <th scope="row">
                <code>{row.release || "unknown"}</code>
              </th>
              <td data-num="">{row.people}</td>
              <td data-num="">{row.events.toLocaleString("en-IN")}</td>
              <td data-num="">{msWords(row.leadOpen.p75)}</td>
              <td data-num="">
                <Slow share={row.leadOpen.slowShare} />
              </td>
              <td data-num="">{row.scriptErrors}</td>
              <td>{when(row.firstAt)}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Panel>
  );
}

function Mix({ telemetry }: { telemetry: ProductTelemetry }) {
  const groups: Array<[string, keyof ProductTelemetry["mix"]]> = [
    ["Device", "device"],
    ["Device tier", "tier"],
    ["App", "app"],
    ["Network", "net"],
  ];
  return (
    <Panel title="Devices and networks" sub="People on each, in this window">
      <div className={styles.body}>
        <dl className={styles.mix}>
          {groups.map(([label, key]) => (
            <div key={key}>
              <dt>{label}</dt>
              <dd>
                {telemetry.mix[key].length
                  ? telemetry.mix[key]
                      .map(
                        (item) =>
                          `${key === "tier" ? (TIER_WORDS[item.value] ?? item.value) : item.value} ${item.people}`,
                      )
                      .join(" · ")
                  : "–"}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </Panel>
  );
}

export function TelemetryView({ telemetry }: { telemetry: ProductTelemetry }) {
  if (!telemetry.available)
    return (
      <Panel title="Product telemetry">
        <p className={styles.line}>
          This environment&rsquo;s API doesn&rsquo;t answer telemetry yet.
        </p>
      </Panel>
    );
  const { totals, consent } = telemetry;
  return (
    <>
      <Tiles label="Telemetry in this window">
        <Kpi
          label="People"
          value={totals.people}
          note={`${totals.workspaces} workspaces`}
        />
        <Kpi label="Sessions" value={totals.sessions} />
        <Kpi
          label="Events"
          value={totals.events.toLocaleString("en-IN")}
          note={telemetry.truncated ? "The newest 200,000 only" : undefined}
        />
        <Kpi
          label="Turned off"
          value={consent.peopleOff}
          note={`people · ${consent.workspacesOff} workspaces`}
        />
      </Tiles>
      <Speed telemetry={telemetry} />
      <Vitals telemetry={telemetry} />
      <Screens telemetry={telemetry} />
      <Funnels telemetry={telemetry} />
      <Features telemetry={telemetry} />
      <Problems telemetry={telemetry} />
      <Releases telemetry={telemetry} />
      <Mix telemetry={telemetry} />
    </>
  );
}
