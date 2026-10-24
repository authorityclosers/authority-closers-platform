/**
 * The improvement loop's pages (owner, 24 Oct 2026: "where is the telemetry data of each
 * device ... nicely visualised and presented ... each new update we improve the app using
 * that data"): Devices, Releases and Fix next. Charts follow the house rules: one question
 * each with its answer as the title, sorted bars with their values written beside them, at
 * most seven bars on a phone, colour never alone, light and dark from the tokens.
 */
import Link from "next/link";
import type { ReactNode } from "react";

import {
  Badge,
  Card,
  Kpi,
  Panel,
  Table,
  Tiles,
  Why,
  type Tone,
} from "../ui/kit";
import { CopyTask } from "./copy-task";
import {
  ACTION_WORDS,
  KEY_ACTIONS,
  NET_WORDS,
  RAM_WORDS,
  VERDICT_WORDS,
  actionBars,
  changeWords,
  gateWords,
  indexWords,
  metricWords,
  mixOf,
  severityTone,
  slowLimit,
  trendWords,
  speedTone,
  verdictTone,
  type ActionTiming,
  type Comparison,
  type Counted,
  type DeviceGroup,
  type Devices,
  type FixNext,
  type KeyAction,
  type Metric,
} from "./loop-data";
import styles from "./loop.module.css";
import { msWords, shareWords } from "./telemetry-data";

/* ---------- Shared pieces ---------- */

const LOOP_PAGES = [
  { key: "overview", label: "Overview" },
  { key: "devices", label: "Devices" },
  { key: "releases", label: "Releases" },
  { key: "fix", label: "Fix next" },
] as const;
export type LoopPage = (typeof LOOP_PAGES)[number]["key"];

/** Overview, Devices, Releases and Fix next: the telemetry pages, one tab each. */
export function LoopTabs({
  current,
  hrefs,
}: {
  current: LoopPage;
  hrefs: Record<LoopPage, string>;
}) {
  return (
    <nav className={styles.loopTabs} aria-label="Product telemetry">
      {LOOP_PAGES.map((page) => (
        <Link
          key={page.key}
          href={hrefs[page.key]}
          className={styles.loopTab}
          aria-current={page.key === current ? "page" : undefined}
        >
          {page.label}
        </Link>
      ))}
    </nav>
  );
}

export const LOOP_HREFS: Record<LoopPage, string> = {
  overview: "/telemetry",
  devices: "/telemetry/devices",
  releases: "/telemetry/releases",
  fix: "/telemetry/fix-next",
};

type Bar = {
  key: string;
  label: ReactNode;
  value: number;
  text: string;
  tone?: Tone;
  muted?: boolean;
  /** A little room after this bar (the end of a before-and-after pair). */
  gapAfter?: boolean;
};

/**
 * Sorted horizontal bars with each value written at the end (colour never alone). `limit`
 * draws the line a value should stay under; on phones only the first seven bars show.
 */
function Bars({
  label,
  rows,
  limit,
  limitText,
  max,
}: {
  label: string;
  rows: Bar[];
  limit?: number;
  limitText?: string;
  max?: number;
}) {
  const top = Math.max(
    1,
    max ?? 0,
    limit ?? 0,
    ...rows.map((row) => row.value),
  );
  return (
    <figure className={styles.chart}>
      <ol className={styles.bars} aria-label={label}>
        {rows.map((row) => (
          <li
            key={row.key}
            className={styles.barRow}
            data-gap={row.gapAfter ? "" : undefined}
          >
            <span className={styles.barLabel}>{row.label}</span>
            <span className={styles.barTrack}>
              <i
                data-tone={row.tone ?? "accent"}
                data-muted={row.muted ? "" : undefined}
                style={{ width: `${Math.max(1, (row.value / top) * 100)}%` }}
              />
              {limit ? (
                <b
                  className={styles.limit}
                  style={{ left: `${(limit / top) * 100}%` }}
                  aria-hidden="true"
                />
              ) : null}
            </span>
            <span className={styles.barValue}>{row.text}</span>
          </li>
        ))}
      </ol>
      {limit && limitText ? (
        <figcaption className={styles.caption}>
          <span className={styles.limitKey} aria-hidden="true" /> {limitText}
          {rows.length > 7 ? (
            <span className={styles.phoneOnly}>
              {" "}
              · the seven highest here; every one is in the table
            </span>
          ) : null}
        </figcaption>
      ) : rows.length > 7 ? (
        <figcaption className={`${styles.caption} ${styles.phoneOnly}`}>
          The seven highest here; every one is in the table.
        </figcaption>
      ) : null}
    </figure>
  );
}

function Speed({
  action,
  timing,
}: {
  action: KeyAction;
  timing: ActionTiming | undefined;
}) {
  if (!timing || timing.p75 === null)
    return <span className={styles.muted}>–</span>;
  return (
    <span className={styles.speed} data-tone={speedTone(action, timing.p75)}>
      {msWords(timing.p75)}
    </span>
  );
}

const tierWords = (value: string) =>
  value === "unknown"
    ? "Unknown tier"
    : `${value.charAt(0).toUpperCase()}${value.slice(1)}-${value === "mid" ? "range" : "end"}`;

const countedWords = (items: Counted[], words?: (value: string) => string) =>
  items.length
    ? items
        .slice(0, 3)
        .map((item) => (words ? words(item.value) : item.value))
        .join(", ")
    : "–";

const plural = (count: number, one: string, many: string) =>
  count ? `${count} ${count === 1 ? one : many}` : "";

function issuesLine(item: {
  crashes: number;
  scriptErrors: number;
  rageTaps: number;
  deadTaps: number;
  killed: number;
}) {
  const parts = [
    plural(item.crashes, "crash", "crashes"),
    item.killed ? `${item.killed} closed by Android` : "",
    plural(item.scriptErrors, "script error", "script errors"),
    plural(item.rageTaps, "rage tap", "rage taps"),
    plural(item.deadTaps, "dead tap", "dead taps"),
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "No issues";
}

/* ---------- Devices ---------- */

export function DevicesView({
  devices,
  action,
  actionTabs,
}: {
  devices: Devices;
  action: KeyAction;
  /** The page's tabs for choosing the action the chart shows. */
  actionTabs?: ReactNode;
}) {
  if (!devices.available)
    return (
      <Panel title="Devices">
        <p className={styles.body}>
          This environment&rsquo;s API doesn&rsquo;t answer the Devices view
          yet.
        </p>
      </Panel>
    );
  const { totals, groups } = devices;
  const bars = actionBars(groups, action);
  const limit = slowLimit(action);
  const slowest = bars[0];
  const crashes = groups.reduce((sum, group) => sum + group.crashes, 0);
  const errors = groups.reduce((sum, group) => sum + group.scriptErrors, 0);
  return (
    <>
      <Tiles label="Devices in this window">
        <Kpi
          label="Devices"
          value={totals.devices}
          note={`${totals.models} phone models · ${totals.classes} other device kinds`}
        />
        <Kpi
          label="Slow devices"
          value={shareWords(totals.slowShare)}
          tone={
            totals.slowShare === null
              ? undefined
              : totals.slowShare > 0.25
                ? "bad"
                : totals.slowShare > 0.1
                  ? "warn"
                  : "good"
          }
          note={`${totals.slowDevices} of ${totals.ranked} ranked: a typical key tap over the slow limit`}
        />
        <Kpi
          label="Slowest 10% start at"
          value={indexWords(devices.cutoffIndex)}
          note={`the slow limit; the median device is at ${indexWords(devices.medianIndex)}`}
        />
        <Kpi
          label="Crashes"
          value={crashes}
          note={`${errors} script errors`}
          tone={crashes ? "warn" : undefined}
        />
      </Tiles>
      <Panel
        title={`${ACTION_WORDS[action]} by device`}
        sub="75% of taps settle within"
        tools={
          <Why
            detail="From the tap to the screen settling, per device: a phone model where the Android app says which (1.0.26 and later), or else the kind of device, app and speed tier."
            more="Bars are sorted slowest first; the line is the action's slow limit."
          />
        }
      >
        <div className={styles.body}>
          {actionTabs}
          {slowest ? (
            <p className={styles.headline}>
              {slowest.p75 > limit
                ? `Slowest on ${slowest.label}: ${msWords(slowest.p75)}, over the ${msWords(limit)} limit.`
                : `Every device is within ${msWords(limit)}; the slowest is ${slowest.label} at ${msWords(slowest.p75)}.`}
            </p>
          ) : (
            <p className={styles.muted}>
              No taps on {ACTION_WORDS[action].toLowerCase()} in this window.
            </p>
          )}
          {bars.length ? (
            <Bars
              label={`${ACTION_WORDS[action]}, 75th percentile by device`}
              limit={limit}
              limitText={`Slow over ${msWords(limit)}`}
              rows={bars.map((bar) => ({
                key: bar.key,
                label: bar.label,
                value: bar.p75,
                text: `${msWords(bar.p75)} · ${bar.taps} taps`,
                tone: speedTone(action, bar.p75),
              }))}
            />
          ) : null}
        </div>
      </Panel>
      <Slowest devices={devices} />
      <MakeUp groups={groups} />
      <EveryDevice groups={groups} />
    </>
  );
}

function Slowest({ devices }: { devices: Devices }) {
  const rows = devices.slowest;
  return (
    <Panel
      title="Slowest 10% of devices"
      sub={rows.length ? `${rows.length} devices` : undefined}
      tools={
        <Why
          detail="Each device (one person's phone model or device kind) is ranked by its typical key-action tap against that action's slow limit: 2.0× means its median tap takes twice the limit. Devices with fewer than 3 key taps are not ranked."
          more="No person is named; a device is shown by its model, versions and tiers only."
        />
      }
    >
      {rows.length ? (
        <Table
          label="Slowest 10% of devices"
          cards={rows.map((row, index) => (
            <Card key={`${row.key}-${index}`}>
              <strong>
                {row.label} · {indexWords(row.speedIndex)}
              </strong>
              <span>
                {[
                  row.appVersion ? `App ${row.appVersion}` : "",
                  row.android !== null ? `Android ${row.android}` : "",
                  row.ram ? RAM_WORDS(row.ram) : "",
                  row.network ? (NET_WORDS[row.network] ?? row.network) : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              <span>
                {KEY_ACTIONS.filter((action) => row.actions[action])
                  .map(
                    (action) =>
                      `${ACTION_WORDS[action]} ${msWords(row.actions[action]?.p75 ?? null)}`,
                  )
                  .join(" · ")}
              </span>
              <span className={styles.muted}>{issuesLine(row)}</span>
            </Card>
          ))}
        >
          <thead>
            <tr>
              <th scope="col">Device</th>
              <th scope="col" data-num="">
                Speed
              </th>
              <th scope="col">App</th>
              <th scope="col">Android</th>
              <th scope="col">Memory</th>
              <th scope="col">Network</th>
              {KEY_ACTIONS.map((action) => (
                <th key={action} scope="col" data-num="">
                  {ACTION_WORDS[action]}
                </th>
              ))}
              <th scope="col">Issues</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${row.key}-${index}`}>
                <th scope="row">{row.label}</th>
                <td data-num="">
                  <span
                    className={styles.speed}
                    data-tone={row.speedIndex > 2 ? "bad" : "warn"}
                  >
                    {indexWords(row.speedIndex)}
                  </span>
                </td>
                <td>{row.appVersion || "–"}</td>
                <td>{row.android ?? "–"}</td>
                <td>{row.ram ? RAM_WORDS(row.ram) : "–"}</td>
                <td>
                  {row.network ? (NET_WORDS[row.network] ?? row.network) : "–"}
                </td>
                {KEY_ACTIONS.map((action) => (
                  <td key={action} data-num="">
                    <Speed action={action} timing={row.actions[action]} />
                  </td>
                ))}
                <td className={styles.muted}>{issuesLine(row)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : (
        <p className={styles.body}>
          No device has 3 or more key-action taps in this window yet.
        </p>
      )}
    </Panel>
  );
}

function MixChart({
  title,
  items,
  words,
}: {
  title: string;
  items: Counted[];
  words?: (value: string) => string;
}) {
  if (!items.length) return null;
  const top = items[0];
  const total = items.reduce((sum, item) => sum + item.people, 0);
  return (
    <div className={styles.mix}>
      <h3 className={styles.heading}>{title}</h3>
      <p className={styles.muted}>
        Most: {words ? words(top.value) : top.value} (
        {shareWords(total ? top.people / total : null)})
      </p>
      <Bars
        label={title}
        rows={items.map((item) => ({
          key: item.value,
          label: words ? words(item.value) : item.value,
          value: item.people,
          text: `${item.people} ${item.people === 1 ? "person" : "people"}`,
        }))}
      />
    </div>
  );
}

function MakeUp({ groups }: { groups: readonly DeviceGroup[] }) {
  const android = mixOf(groups, (group) => group.android);
  const ram = mixOf(groups, (group) => group.ram);
  const versions = mixOf(groups, (group) => group.appVersions);
  const networks = mixOf(groups, (group) => group.networks);
  const tiers = mixOf(groups, (group) => group.tiers);
  if (!groups.length) return null;
  return (
    <Panel
      title="What the devices are"
      tools={
        <Why detail="People per value; Android, WebView and memory come from the Android app's daily profile (1.0.26 and later), speed tiers from the browser." />
      }
    >
      <div className={`${styles.body} ${styles.mixes}`}>
        <MixChart title="Android version" items={android} />
        <MixChart title="Phone memory" items={ram} words={RAM_WORDS} />
        <MixChart title="App version" items={versions} />
        <MixChart
          title="Network"
          items={networks}
          words={(value) => NET_WORDS[value] ?? value}
        />
        <MixChart
          title="Speed tier"
          items={tiers}
          words={(value) =>
            value === "unknown"
              ? "Unknown"
              : `${value.charAt(0).toUpperCase()}${value.slice(1)}`
          }
        />
      </div>
    </Panel>
  );
}

function EveryDevice({ groups }: { groups: readonly DeviceGroup[] }) {
  if (!groups.length)
    return (
      <Panel title="Every device">
        <p className={styles.body}>
          No device has sent telemetry in this window.
        </p>
      </Panel>
    );
  return (
    <Panel title="Every device" sub={`${groups.length} models and kinds`}>
      <Table
        label="Every device"
        cards={groups.map((group) => (
          <Card key={group.key}>
            <strong>
              {group.label} · {group.people}{" "}
              {group.people === 1 ? "person" : "people"}
            </strong>
            <span>
              App {countedWords(group.appVersions)}
              {group.android.length
                ? ` · Android ${countedWords(group.android)}`
                : ""}
              {group.ram.length
                ? ` · ${countedWords(group.ram, RAM_WORDS)}`
                : ""}
            </span>
            <span>
              {KEY_ACTIONS.filter((action) => group.actions[action])
                .map(
                  (action) =>
                    `${ACTION_WORDS[action]} ${msWords(group.actions[action]?.p75 ?? null)}`,
                )
                .join(" · ") || "No key taps"}
            </span>
            <span className={styles.muted}>{issuesLine(group)}</span>
          </Card>
        ))}
      >
        <thead>
          <tr>
            <th scope="col">Device</th>
            <th scope="col" data-num="">
              People
            </th>
            <th scope="col">App</th>
            <th scope="col">Android · WebView</th>
            <th scope="col">Memory or tier</th>
            <th scope="col">Network</th>
            {KEY_ACTIONS.map((action) => (
              <th key={action} scope="col" data-num="">
                {ACTION_WORDS[action]}
              </th>
            ))}
            <th scope="col" data-num="">
              In slowest 10%
            </th>
            <th scope="col">Issues</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <tr key={group.key}>
              <th scope="row">{group.label}</th>
              <td data-num="">{group.people}</td>
              <td>{countedWords(group.appVersions)}</td>
              <td>
                {group.android.length
                  ? `${countedWords(group.android)} · ${countedWords(group.webview)}`
                  : "–"}
              </td>
              <td>
                {group.ram.length
                  ? countedWords(group.ram, RAM_WORDS)
                  : countedWords(group.tiers, tierWords)}
              </td>
              <td>
                {countedWords(
                  group.networks,
                  (value) => NET_WORDS[value] ?? value,
                )}
              </td>
              {KEY_ACTIONS.map((action) => (
                <td key={action} data-num="">
                  <Speed action={action} timing={group.actions[action]} />
                </td>
              ))}
              <td data-num="">
                {group.taps ? shareWords(group.slowTailShare) : "–"}
              </td>
              <td className={styles.muted}>{issuesLine(group)}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Panel>
  );
}

/* ---------- Releases ---------- */

const KIND_WORDS: Record<Metric["kind"], string> = {
  speed: "Speed of key actions (75th percentile)",
  rate: "Problems per 100 sessions",
  vital: "Page speed (75th percentile)",
  funnel: "Funnels (reached the last step)",
};

export function ReleasesView({
  comparison,
  releaseTabs,
}: {
  comparison: Comparison;
  releaseTabs?: ReactNode;
}) {
  if (!comparison.available)
    return (
      <Panel title="Releases">
        <p className={styles.body}>
          This environment&rsquo;s API doesn&rsquo;t compare releases yet.
        </p>
      </Panel>
    );
  const { head, base, metrics } = comparison;
  const gate = gateWords(comparison);
  const worse = metrics.filter((item) => item.verdict === "worse");
  const speed = metrics.filter((item) => item.kind === "speed");
  return (
    <>
      {releaseTabs}
      <section className={styles.corner} aria-label="Release check">
        <article className={styles.cornerCard} data-tone={gate.verdict}>
          <strong>
            {gate.verdict === "block"
              ? "Release gate: hold"
              : gate.verdict === "pass"
                ? "Release gate: passes"
                : "Release gate: not enough data"}
          </strong>
          <span>{gate.line}</span>
          <span className={styles.muted}>
            {head ? `${head}` : "No release yet"}
            {base ? ` against ${base}` : " (nothing before it to compare)"}
          </span>
        </article>
        {worse.map((item) => (
          <article
            key={item.key}
            className={styles.cornerCard}
            data-tone={item.regression ? "block" : "worse"}
          >
            <strong>
              {item.label}:{" "}
              {item.regression ? "slower past the limit" : "worse"}
            </strong>
            <span>
              {metricWords(item.unit, item.base)} →{" "}
              {metricWords(item.unit, item.head)} ({changeWords(item)})
            </span>
            <span className={styles.muted}>
              {item.baseSamples} → {item.headSamples}{" "}
              {item.kind === "speed"
                ? "taps"
                : item.kind === "funnel"
                  ? "people"
                  : "samples"}
            </span>
          </article>
        ))}
      </section>
      <Panel
        title="Before and after on key actions"
        sub={base && head ? `${base} → ${head}` : undefined}
        tools={<Why detail={comparison.blockRule} more={comparison.warnRule} />}
      >
        <div className={styles.body}>
          {speed.some((item) => item.base !== null || item.head !== null) ? (
            <Bars
              label="Key actions, 75th percentile, before and after"
              rows={speed.flatMap((item) => [
                {
                  key: `${item.key}-base`,
                  label: `${item.label}, before`,
                  value: item.base ?? 0,
                  text: msWords(item.base),
                  muted: true,
                },
                {
                  key: `${item.key}-head`,
                  gapAfter: true,
                  label: `${item.label}, after`,
                  value: item.head ?? 0,
                  text: `${msWords(item.head)} · ${VERDICT_WORDS[item.verdict].toLowerCase()}`,
                  tone:
                    item.verdict === "worse"
                      ? "warn"
                      : item.verdict === "better"
                        ? "good"
                        : "accent",
                },
              ])}
            />
          ) : (
            <p className={styles.muted}>
              No key-action taps in these releases yet.
            </p>
          )}
        </div>
      </Panel>
      <Panel title="Every measure">
        <Table
          label="Every measure, before and after"
          cards={metrics.map((item) => (
            <Card key={item.key}>
              <strong>{item.label}</strong>
              <span>
                {metricWords(item.unit, item.base)} →{" "}
                {metricWords(item.unit, item.head)} · {changeWords(item)}
              </span>
              <span>
                <Badge tone={verdictTone(item.verdict)}>
                  {VERDICT_WORDS[item.verdict]}
                </Badge>
              </span>
            </Card>
          ))}
        >
          <thead>
            <tr>
              <th scope="col">Measure</th>
              <th scope="col" data-num="">
                Before
              </th>
              <th scope="col" data-num="">
                After
              </th>
              <th scope="col" data-num="">
                Change
              </th>
              <th scope="col">Verdict</th>
            </tr>
          </thead>
          {(Object.keys(KIND_WORDS) as Metric["kind"][]).map((kind) => {
            const rows = metrics.filter((item) => item.kind === kind);
            return rows.length ? (
              <tbody key={kind}>
                <tr>
                  <th scope="rowgroup" colSpan={5} className={styles.group}>
                    {KIND_WORDS[kind]}
                  </th>
                </tr>
                {rows.map((item) => (
                  <tr key={item.key}>
                    <th scope="row">{item.label}</th>
                    <td data-num="">{metricWords(item.unit, item.base)}</td>
                    <td data-num="">{metricWords(item.unit, item.head)}</td>
                    <td data-num="">{changeWords(item)}</td>
                    <td>
                      <Badge tone={verdictTone(item.verdict)}>
                        {VERDICT_WORDS[item.verdict]}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            ) : null;
          })}
        </Table>
      </Panel>
      <Panel title="Releases seen" sub="last 30 days">
        <Table label="Releases seen">
          <thead>
            <tr>
              <th scope="col">Release</th>
              <th scope="col">First seen</th>
              <th scope="col" data-num="">
                Sessions
              </th>
              <th scope="col" data-num="">
                Key taps
              </th>
            </tr>
          </thead>
          <tbody>
            {comparison.releases.map((row) => (
              <tr key={row.release}>
                <th scope="row">
                  <code>{row.release}</code>
                  {row.release === head
                    ? " (after)"
                    : row.release === base
                      ? " (before)"
                      : ""}
                </th>
                <td>{dayWords(row.firstAt)}</td>
                <td data-num="">{row.sessions}</td>
                <td data-num="">{row.taps}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Panel>
    </>
  );
}

const DAY = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});
const dayWords = (value: string) => {
  const moment = new Date(value);
  return Number.isNaN(moment.getTime()) ? "–" : DAY.format(moment);
};

/* ---------- Fix next ---------- */

export function FixNextView({ fixNext }: { fixNext: FixNext }) {
  if (!fixNext.available)
    return (
      <Panel title="Fix next">
        <p className={styles.body}>
          This environment&rsquo;s API doesn&rsquo;t rank fixes yet.
        </p>
      </Panel>
    );
  const { items, improved } = fixNext;
  return (
    <>
      <Panel
        title="What to fix next"
        sub={`${items.length}${fixNext.more ? ` of ${items.length + fixNext.more}` : ""}`}
        tools={
          <Why
            detail="Ranked by people affected times severity (1 minor to 4 critical: crashes). Each finding keeps its key, so after a fix ships its measure shows release by release, and the next week says whether it improved."
            more="Copy task gives the card text for the bug board or AC Pulse: title, evidence, screen and a suggested owner."
          />
        }
      >
        {items.length ? (
          <ol className={styles.fixes}>
            {items.map((item, index) => (
              <li key={item.key} className={styles.fix}>
                <span className={styles.rank} aria-hidden="true">
                  {index + 1}
                </span>
                <div className={styles.fixMain}>
                  <p className={styles.fixTitle}>
                    {item.title}{" "}
                    <Badge tone={severityTone(item.severity)}>
                      {item.severityLabel}
                    </Badge>{" "}
                    {item.isNew ? <Badge tone="info">New</Badge> : null}
                  </p>
                  <p className={styles.line}>
                    {item.people} {item.people === 1 ? "person" : "people"} ·{" "}
                    {item.events} times · {item.screenLabel} · suggested owner{" "}
                    <strong>{item.owner}</strong>
                  </p>
                  <p className={styles.muted}>
                    {item.evidence
                      .map(([key, value]) => `${key} ${value}`)
                      .join(" · ")}
                  </p>
                  <p className={styles.muted}>
                    Now {metricWords(item.unit, item.now)}
                    {item.before !== null
                      ? ` · the window before ${metricWords(item.unit, item.before)}`
                      : ""}
                  </p>
                  {item.byRelease.length > 1 ? (
                    <p className={styles.muted}>
                      Release by release:{" "}
                      {trendWords(item.unit, item.byRelease)}
                    </p>
                  ) : null}
                </div>
                <CopyTask text={item.task} />
              </li>
            ))}
          </ol>
        ) : (
          <p className={styles.body}>
            Nothing crosses a line in this window: no slow key action, failing
            call, crash or repeated tap affects anyone yet.
          </p>
        )}
      </Panel>
      <Panel
        title="Improved since the window before"
        sub={improved.length ? `${improved.length}` : undefined}
      >
        {improved.length ? (
          <ul className={styles.improved}>
            {improved.map((item) => (
              <li key={item.key}>
                <strong>{item.title}</strong>{" "}
                <Badge tone="good">{item.gone ? "Gone" : "Better"}</Badge>
                <span className={styles.muted}>
                  {" "}
                  {metricWords(item.unit, item.before)} →{" "}
                  {metricWords(item.unit, item.now)} · {item.peopleBefore}{" "}
                  {item.peopleBefore === 1 ? "person" : "people"} before
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.body}>
            Nothing from the window before has improved enough to show yet.
          </p>
        )}
      </Panel>
    </>
  );
}
