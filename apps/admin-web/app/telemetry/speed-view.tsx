/**
 * Admin → Product telemetry → Speed and journeys (owner, 27 Oct 2026: "on low-end devices
 * with the worst processors this app might be slow... show things in the most beautiful,
 * presentable way"). In the order the speed study found matters: frames on Android, slow
 * API calls, load and the CPU test, taps by device tier, and the journey from Leads. With
 * few people, every number says how many samples it rests on.
 */
import { Card, Kpi, Panel, Table, Tiles, Why } from "../ui/kit";
import { Bars } from "./loop-view";
import loop from "./loop.module.css";
import {
  TIER_WORDS,
  apiTone,
  cpuWords,
  endpointWords,
  frameTone,
  overTone,
  samplesWords,
  statWords,
  type SpeedJourneys,
  type Stat,
} from "./speed-data";
import styles from "./speed.module.css";
import { msWords, ratingTone, screenWords, shareWords } from "./telemetry-data";

const TIERS = ["low", "mid", "high", "unknown"] as const;
// web.dev's good limit for the largest paint.
const LCP_GOOD_MS = 2_500;

/** A value with its sample count beside it, greyed when too few to tell. */
function Value({
  stat,
  which = "p75",
  words = statWords,
}: {
  stat: Stat;
  which?: "p50" | "p75" | "p95";
  words?: (stat: Stat, which: "p50" | "p75" | "p95") => string;
}) {
  if (stat.n === 0) return <span className={loop.muted}>–</span>;
  return (
    <span className={styles.value} data-few={stat.few ? "" : undefined}>
      {words(stat, which)}
      <small className={styles.n} title={samplesWords(stat.n, stat.few)}>
        {" "}
        n {stat.n}
      </small>
    </span>
  );
}

const cpuStat = (stat: Stat, which: "p50" | "p75" | "p95") =>
  cpuWords(stat[which]);

function Frames({ speed }: { speed: SpeedJourneys }) {
  const { all, byVersion, byModel } = speed.frames;
  const newest = byVersion[0];
  return (
    <Panel
      title="Frames on Android"
      sub="Frames slower than a screen refresh, per app version"
      tools={
        <Why detail="The Android app counts every frame it draws in a session, how many took longer than a refresh (16 ms on most phones) and how many froze (over 700 ms), and its slowest 10% frame. Over 10% slow frames starts to feel rough; over 30% feels slow." />
      }
    >
      <div className={loop.body}>
        {newest ? (
          <p
            className={styles.headline}
            data-tone={frameTone(newest.slowShare)}
          >
            On {newest.version}, {shareWords(newest.slowShare)} of frames were
            slow and {shareWords(newest.frozenShare)} froze, across{" "}
            {newest.sessions} {newest.sessions === 1 ? "session" : "sessions"}
            {newest.sessions < speed.few ? " (too few to tell)" : ""}.
          </p>
        ) : (
          <p className={loop.muted}>
            No frame counts from the Android app in this window.
          </p>
        )}
        {byVersion.length ? (
          <Bars
            label="Slow frames per app version, newest first"
            rows={byVersion.map((row) => ({
              key: row.version,
              label: row.version,
              value: (row.slowShare ?? 0) * 100,
              text: `${shareWords(row.slowShare)} slow · ${row.sessions} sessions`,
              tone: frameTone(row.slowShare),
              muted: row.sessions < speed.few,
            }))}
            max={100}
          />
        ) : null}
      </div>
      {byModel.length ? (
        <Table
          label="Frames per phone model"
          cards={byModel.map((row) => (
            <Card key={row.model}>
              <strong>{row.model}</strong>
              <span>
                {shareWords(row.slowShare)} slow · {shareWords(row.frozenShare)}{" "}
                frozen
              </span>
              <span className={loop.muted}>
                {row.sessions} sessions · slowest frames{" "}
                {statWords(row.p90, "p50")}
              </span>
            </Card>
          ))}
        >
          <thead>
            <tr>
              <th scope="col">Phone model</th>
              <th scope="col" data-num="">
                Sessions
              </th>
              <th scope="col" data-num="">
                Slow frames
              </th>
              <th scope="col" data-num="">
                Frozen
              </th>
              <th scope="col" data-num="">
                Slowest 10% (median)
              </th>
            </tr>
          </thead>
          <tbody>
            {byModel.map((row) => (
              <tr key={row.model}>
                <th scope="row">{row.model}</th>
                <td data-num="">{row.sessions}</td>
                <td data-num="">
                  <span
                    className={styles.toned}
                    data-tone={frameTone(row.slowShare)}
                  >
                    {shareWords(row.slowShare)}
                  </span>
                </td>
                <td data-num="">{shareWords(row.frozenShare)}</td>
                <td data-num="">
                  <Value stat={row.p90} which="p50" />
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
      {all.sessions ? (
        <p className={`${loop.body} ${loop.line}`}>
          All phones: {shareWords(all.slowShare)} slow,{" "}
          {shareWords(all.frozenShare)} frozen, from {all.sessions} sessions on{" "}
          {all.people} phones.
        </p>
      ) : null}
    </Panel>
  );
}

function Apis({ speed }: { speed: SpeedJourneys }) {
  const { byRelease, endpoints } = speed.apis;
  return (
    <Panel
      title="Slow API calls"
      sub="Answers that took over 1.5 s to start, per 100 screen views"
      tools={
        <Why
          detail="The app reports a call to the server when its answer takes over 1.5 s to start (to the first byte; before 27 Oct, the whole call, downloads included) or fails, and never one made while the app was in the background. Per 100 screen views, so busy and quiet releases compare."
          more="When many endpoints are slow at once, the server stalled rather than one endpoint."
        />
      }
    >
      <div className={loop.body}>
        <p
          className={styles.headline}
          data-tone={apiTone(speed.apis.per100Views)}
        >
          {speed.apis.calls
            ? `${speed.apis.per100Views ?? "–"} slow calls per 100 screen views: ${speed.apis.calls} calls from ${speed.apis.people} people over ${speed.apis.screenViews} screen views.`
            : "No slow API calls in this window."}
        </p>
        {byRelease.length ? (
          <Bars
            label="Slow calls per 100 screen views, by release, newest first"
            rows={byRelease.map((row) => ({
              key: row.release,
              label: row.release,
              value: row.per100Views ?? 0,
              text: `${row.per100Views ?? "–"} · ${row.slowCalls} calls in ${row.screenViews} views`,
              tone: apiTone(row.per100Views),
              muted: row.screenViews < 20,
            }))}
          />
        ) : null}
      </div>
      {endpoints.length ? (
        <Table
          label="Slow calls per endpoint"
          cards={endpoints.map((row) => (
            <Card key={row.endpoint}>
              <strong>{endpointWords(row.endpoint)}</strong>
              <span>
                {row.calls} slow calls · {row.people} people
              </span>
              <span>
                First byte {statWords(row.wait)} · whole call{" "}
                {statWords(row.total)}
              </span>
            </Card>
          ))}
        >
          <thead>
            <tr>
              <th scope="col">Endpoint</th>
              <th scope="col" data-num="">
                Calls
              </th>
              <th scope="col" data-num="">
                People
              </th>
              <th scope="col" data-num="">
                First byte, 75%
              </th>
              <th scope="col" data-num="">
                Whole call, 75%
              </th>
              <th scope="col" data-num="">
                Failed
              </th>
              <th scope="col">On</th>
            </tr>
          </thead>
          <tbody>
            {endpoints.map((row) => (
              <tr key={row.endpoint}>
                <th scope="row" className={styles.endpoint}>
                  {endpointWords(row.endpoint)}
                </th>
                <td data-num="">{row.calls}</td>
                <td data-num="">{row.people}</td>
                <td data-num="">
                  <Value stat={row.wait} />
                </td>
                <td data-num="">
                  <Value stat={row.total} />
                </td>
                <td data-num="">
                  {row.failed || row.refused
                    ? `${row.failed} 5xx · ${row.refused} 4xx`
                    : "–"}
                </td>
                <td className={loop.muted}>
                  {row.screens.map(screenWords).join(", ") || "–"}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
    </Panel>
  );
}

function Load({ speed }: { speed: SpeedJourneys }) {
  const { lcpByTier, starts, cpu } = speed.load;
  return (
    <Panel
      title="Load"
      sub="Largest paint and start by device tier, and the CPU test"
      tools={
        <Why
          detail="Largest paint is the browser's own time to draw the screen's biggest element. Start is from opening the page or the app to its first screen working; launch is the Android app's own start. The tier is measured: once the app is idle after starting, it times reading and writing the same JSON five times (under 3 ms is high-end, 6 ms and over low-end; about 1 ms on a laptop)."
          more="Tiers come from the CPU test since v1.01; until a device has run it, its tier is a guess from cores and memory."
        />
      }
    >
      <div className={loop.body}>
        {lcpByTier.length ? (
          <Bars
            label="Largest paint, 75% of screens within, by device tier"
            rows={lcpByTier.map((row) => ({
              key: row.tier,
              label: TIER_WORDS[row.tier] ?? row.tier,
              value: row.p75 ?? 0,
              text: `${statWords(row)} · ${samplesWords(row.n, row.few)}`,
              tone: ratingTone(
                row.rating as "good" | "needs_improvement" | "poor" | null,
              ),
              muted: row.few,
            }))}
            limit={LCP_GOOD_MS}
            limitText={`web.dev's good limit, ${msWords(LCP_GOOD_MS)}`}
          />
        ) : (
          <p className={loop.muted}>No largest-paint samples in this window.</p>
        )}
      </div>
      {starts.length ? (
        <Table label="Start">
          <thead>
            <tr>
              <th scope="col">Start</th>
              <th scope="col" data-num="">
                Samples
              </th>
              <th scope="col" data-num="">
                Median
              </th>
              <th scope="col" data-num="">
                75%
              </th>
              <th scope="col" data-num="">
                95%
              </th>
            </tr>
          </thead>
          <tbody>
            {starts.map((row) => (
              <tr key={`${row.app}-${row.start}-${row.what}`}>
                <th scope="row">
                  {row.app === "android" ? "Android app" : "Web"}, {row.start}
                  {row.what === "launch" ? " launch" : " page"}
                </th>
                <td
                  data-num=""
                  className={styles.count}
                  data-few={row.few ? "" : undefined}
                >
                  {row.n}
                </td>
                <td data-num="">{statWords(row, "p50")}</td>
                <td data-num="">{statWords(row, "p75")}</td>
                <td data-num="">
                  {row.p95 === null ? (
                    <span className={loop.muted} title="From 20 samples">
                      –
                    </span>
                  ) : (
                    msWords(row.p95)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
      <div className={loop.body}>
        <h3 className={loop.heading}>The CPU test</h3>
        {cpu.tests ? (
          <p className={loop.line}>
            {cpu.tests} tests on {cpu.people} devices: median{" "}
            {cpuWords(cpu.all.p50)}. {cpu.bands.low} low-end, {cpu.bands.mid}{" "}
            mid-range, {cpu.bands.high} high-end.
          </p>
        ) : (
          <p className={loop.muted}>
            No CPU tests yet: devices run it from v1.01.
          </p>
        )}
      </div>
      {cpu.byModel.length ? (
        <Table label="The CPU test per phone model">
          <thead>
            <tr>
              <th scope="col">Phone model</th>
              <th scope="col" data-num="">
                Devices
              </th>
              <th scope="col" data-num="">
                CPU test (median)
              </th>
              <th scope="col">Tier</th>
              <th scope="col" data-num="">
                Start, 75%
              </th>
            </tr>
          </thead>
          <tbody>
            {cpu.byModel.map((row) => (
              <tr key={row.model}>
                <th scope="row">
                  {row.model === "unknown" ? "Not named" : row.model}
                </th>
                <td data-num="">{row.people}</td>
                <td data-num="">
                  <Value stat={row.cpu} which="p50" words={cpuStat} />
                </td>
                <td>{TIER_WORDS[row.tier] ?? row.tier}</td>
                <td data-num="">
                  <Value stat={row.start} />
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
    </Panel>
  );
}

function Taps({ speed }: { speed: SpeedJourneys }) {
  const rows = speed.taps;
  return (
    <Panel
      title="Taps by device tier"
      sub="75% of taps settle within, on each tier"
      tools={
        <Why detail="From the tap to the screen settling (no change for 150 ms), on people's own devices, by the measured tier. Amber is over the action's limit, red over twice it." />
      }
    >
      {rows.length ? (
        <Table
          label="Tap to response by device tier"
          cards={rows.map((row) => (
            <Card key={row.action}>
              <strong>{row.label}</strong>
              <span className={loop.muted}>
                limit {msWords(row.slowMs)} ·{" "}
                {samplesWords(row.all.n, row.all.few)}
              </span>
              <span>
                {row.byTier
                  .map(
                    (part) =>
                      `${TIER_WORDS[part.tier] ?? part.tier} ${statWords(part)} (n ${part.n})`,
                  )
                  .join(" · ")}
              </span>
            </Card>
          ))}
        >
          <thead>
            <tr>
              <th scope="col">Action</th>
              {TIERS.map((tier) => (
                <th key={tier} scope="col" data-num="">
                  {TIER_WORDS[tier]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.action}>
                <th scope="row">
                  {row.label}
                  <small className={loop.muted}>
                    {" "}
                    limit {msWords(row.slowMs)}
                  </small>
                </th>
                {TIERS.map((tier) => {
                  const part = row.byTier.find((item) => item.tier === tier);
                  return (
                    <td key={tier} data-num="">
                      {part ? (
                        <span
                          className={styles.toned}
                          data-tone={overTone(part.p75, row.slowMs)}
                        >
                          <Value stat={part} />
                        </span>
                      ) : (
                        <span className={loop.muted}>–</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </Table>
      ) : (
        <p className={`${loop.body} ${loop.muted}`}>
          No timed taps in this window.
        </p>
      )}
    </Panel>
  );
}

function Journey({ speed }: { speed: SpeedJourneys }) {
  const { steps, from } = speed.journey;
  const first = steps[0];
  return (
    <Panel
      title={
        from === "signed_in"
          ? "The journey from sign-in"
          : "The journey from Leads"
      }
      sub="People who reached each step, in this window"
      tools={
        <Why
          detail="A person counts at a step when they also reached every step before it in this window. Sign-ins are recorded from v1.01; until one is, the journey starts at Leads."
          more="With a handful of people, a single person moves a share by a lot: read the counts."
        />
      }
    >
      <div className={loop.body}>
        {first && first.people ? (
          <ol className={styles.journey} aria-label="Journey steps">
            {steps.map((step, index) => (
              <li key={step.key} className={styles.step}>
                <span className={styles.stepLabel}>{step.label}</span>
                <span className={styles.stepTrack}>
                  <i
                    style={{
                      width: `${Math.max(1, (step.people / first.people) * 100)}%`,
                    }}
                  />
                </span>
                <span className={styles.stepValue}>
                  <strong>{step.people}</strong>{" "}
                  {step.people === 1 ? "person" : "people"}
                  {index > 0 ? (
                    <small className={loop.muted}>
                      {" "}
                      · {shareWords(step.ofPrevious)} of the step before
                    </small>
                  ) : null}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className={loop.muted}>Nobody opened Leads in this window.</p>
        )}
      </div>
    </Panel>
  );
}

export function SpeedView({ speed }: { speed: SpeedJourneys }) {
  const frames = speed.frames.all;
  const cpu = speed.load.cpu;
  return (
    <>
      {speed.heartbeat?.active ? (
        <Panel title="Telemetry needs attention">
          <div role="alert" className={styles.note}>
            <p>{speed.heartbeat.problems.join(" · ")}</p>
            <p>
              Last 30 minutes: {speed.heartbeat.accepted} accepted ·{" "}
              {speed.heartbeat.stored} stored · {speed.heartbeat.spooled} saved
              to raw archive.
            </p>
          </div>
        </Panel>
      ) : null}
      <p className={styles.note}>
        Every number shows how many samples it comes from. Under {speed.few} is
        too few to tell; the 95% column needs {speed.minP95}.
        {speed.truncated
          ? " This window had more events than Admin reads at once: the oldest are left out."
          : ""}
      </p>
      <Tiles label="Speed in this window">
        <Kpi
          label="Slow frames on Android"
          value={shareWords(frames.slowShare)}
          tone={frames.sessions ? frameTone(frames.slowShare) : undefined}
          note={`${frames.sessions} sessions on ${frames.people} phones`}
        />
        <Kpi
          label="Slow API calls"
          value={speed.apis.per100Views ?? "–"}
          unit={speed.apis.per100Views === null ? undefined : "per 100 views"}
          tone={speed.apis.calls ? apiTone(speed.apis.per100Views) : undefined}
          note={`${speed.apis.calls} calls from ${speed.apis.people} people`}
        />
        <Kpi
          label="CPU test, median"
          value={cpuWords(cpu.all.p50)}
          note={
            cpu.tests
              ? `${cpu.bands.low} low-end · ${cpu.bands.mid} mid · ${cpu.bands.high} high, ${cpu.tests} tests`
              : "from v1.01"
          }
        />
        <Kpi
          label="People"
          value={speed.totals.people}
          note={`${speed.totals.sessions} sessions`}
        />
      </Tiles>
      <Frames speed={speed} />
      <Apis speed={speed} />
      <Load speed={speed} />
      <Taps speed={speed} />
      <Journey speed={speed} />
    </>
  );
}
