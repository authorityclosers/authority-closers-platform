/**
 * Admin → Product telemetry → Friction (owner, 25 Oct 2026: "automatically find where
 * users stop, which screen they get stuck on, where they try to tap, and why ... a weekly
 * report feeding the redesign loop"). One India week: what to fix first with its evidence
 * and the question to answer, where flows stop, permission prompts, workspace switching
 * and screens by friction. The weekly job writes the same report as markdown.
 */
import { Badge, Card, Kpi, Panel, Table, Tiles, Why } from "../ui/kit";
import { CopyTask } from "./copy-task";
import {
  DIRECTION_WORDS,
  peopleWords,
  weekWords,
  type Friction,
  type FrictionFinding,
  type FlowSummary,
} from "./friction-data";
import { severityTone } from "./loop-data";
import { Bars } from "./loop-view";
import styles from "./loop.module.css";
import { msWords, shareWords } from "./telemetry-data";

const count = (value: number | "<3") => (value === "<3" ? "<3" : String(value));

function taskText(item: FrictionFinding, friction: Friction): string {
  return [
    item.title,
    `${item.people} people, ${item.events} times in the week of ${weekWords(friction.week)} on ${friction.environment} (${item.severityLabel.toLowerCase()}).`,
    `Evidence: ${item.evidence.map(([key, value]) => `${key} ${value}`).join("; ")}.`,
    `Ask: ${item.question}`,
    `Screen: ${item.screenLabel}. Suggested owner: ${item.owner}.`,
    `Finding ${item.key}: Admin → Product telemetry → Friction. The next week's report says whether it went.`,
  ].join("\n");
}

function Findings({ friction }: { friction: Friction }) {
  const { findings, gone } = friction;
  return (
    <>
      <Panel
        title="What to fix first"
        sub={`${findings.length}${friction.more ? ` of ${findings.length + friction.more}` : ""}`}
        tools={
          <Why
            detail="Ranked by people affected times severity (1 minor to 4 critical: people stopping in setup or not logging a call). A finding needs three people or more, so nobody is singled out."
            more="Each finding keeps its key week to week; the next report shows whether it went. Copy task gives the card text for the board or AC Pulse."
          />
        }
      >
        {findings.length ? (
          <ol className={styles.fixes}>
            {findings.map((item) => (
              <li key={item.key} className={styles.fix}>
                <span className={styles.rank} aria-hidden="true">
                  {item.rank}
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
                    {peopleWords(item.people)} · {item.events} times ·{" "}
                    {item.screenLabel} · suggested owner{" "}
                    <strong>{item.owner}</strong>
                    {item.peopleBefore !== null
                      ? ` · ${item.peopleBefore} the week before`
                      : ""}
                  </p>
                  <p className={styles.muted}>
                    {item.evidence
                      .map(([key, value]) => `${key} ${value}`)
                      .join(" · ")}
                  </p>
                  {item.question ? (
                    <p className={styles.muted}>Ask: {item.question}</p>
                  ) : null}
                </div>
                <CopyTask text={taskText(item, friction)} />
              </li>
            ))}
          </ol>
        ) : (
          <p className={styles.body}>
            Nothing reached the bar this week: no flow step, tap, prompt or
            switch troubled three people or more.
          </p>
        )}
      </Panel>
      {gone.length ? (
        <Panel title="Gone since the week before" sub={`${gone.length}`}>
          <ul className={styles.improved}>
            {gone.map((item) => (
              <li key={item.key}>
                <strong>{item.title}</strong> <Badge tone="good">Gone</Badge>
                <span className={styles.muted}>
                  {" "}
                  {item.peopleBefore} people the week before
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </>
  );
}

function FlowPanel({ flow }: { flow: FlowSummary }) {
  const top = Math.max(1, flow.started);
  return (
    <Panel
      title={`${flow.label}: ${shareWords(flow.doneShare)} finish`}
      sub={`${flow.started} started · ${count(flow.people)} people`}
    >
      <div className={styles.body}>
        <p className={styles.line}>
          Finished {flow.done}, skipped {flow.skipped}, cancelled{" "}
          {flow.cancelled}, left half way {flow.abandoned}, no end seen{" "}
          {flow.noEnd}, failed {flow.failed}. Time to finish: median{" "}
          {msWords(flow.doneP50)}, 90% within {msWords(flow.doneP90)}.
        </p>
        <Bars
          label={`${flow.label}: people reaching each step`}
          max={top}
          rows={flow.steps.map((step) => ({
            key: step.step,
            label: step.label,
            value: step.reached,
            text: `${step.reached} reached${step.quit ? ` · ${step.quit} stopped` : ""}${step.blocked ? ` · ${step.blocked} Save refused` : ""}`,
            tone: step.step === flow.worstStep ? "warn" : undefined,
          }))}
        />
      </div>
    </Panel>
  );
}

function Prompts({ friction }: { friction: Friction }) {
  const rows = friction.permissions;
  return (
    <Panel
      title="Permission prompts in phone setup"
      sub={rows.length ? `${rows.length}` : undefined}
      tools={
        <Why detail="Each ask and what Android answered: granted, denied, blocked (Android no longer asks; only the app's settings can allow it) or a settings screen that didn't open. Answer time runs from the tap to the answer." />
      }
    >
      {rows.length ? (
        <Table
          label="Permission prompts"
          cards={rows.map((row) => (
            <Card key={row.permission}>
              <strong>
                {row.label} · {shareWords(row.grantedShare)} granted
              </strong>
              <span>
                Asked {row.asked} · denied {row.denied} · blocked {row.blocked}{" "}
                · didn&rsquo;t open {row.notOpened}
              </span>
              <span className={styles.muted}>
                Answer median {msWords(row.answerP50)}
              </span>
            </Card>
          ))}
        >
          <thead>
            <tr>
              <th scope="col">Permission</th>
              <th scope="col" data-num="">
                Asked
              </th>
              <th scope="col" data-num="">
                Granted
              </th>
              <th scope="col" data-num="">
                Denied
              </th>
              <th scope="col" data-num="">
                Blocked
              </th>
              <th scope="col" data-num="">
                Didn&rsquo;t open
              </th>
              <th scope="col" data-num="">
                Answer (median)
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.permission}>
                <th scope="row">
                  {row.label}{" "}
                  {row.core ? <Badge tone="info">Calls need it</Badge> : null}
                </th>
                <td data-num="">{row.asked}</td>
                <td data-num="">
                  {row.granted} ({shareWords(row.grantedShare)})
                </td>
                <td data-num="">{row.denied}</td>
                <td data-num="">{row.blocked}</td>
                <td data-num="">{row.notOpened}</td>
                <td data-num="">{msWords(row.answerP50)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : (
        <p className={styles.body}>No permission was asked for this week.</p>
      )}
    </Panel>
  );
}

function Switching({ friction }: { friction: Friction }) {
  const switching = friction.workspaces;
  return (
    <Panel
      title="Workspace switching"
      tools={
        <Why detail="Read from the workspace each event was recorded in. A bounce is a switch straight back within two minutes; ping-pong is three switches or more in ten minutes; an early switch comes within a minute of opening the app." />
      }
    >
      <Tiles label="Workspace switching">
        <Kpi
          label="Switches"
          value={switching.switches}
          note={`${count(switching.switchPeople)} people · ${count(switching.peopleInSeveral)} use more than one`}
        />
        <Kpi
          label="Straight back"
          value={switching.bounces}
          note={`${count(switching.bouncePeople)} people · ping-pong ${count(switching.pingPongPeople)}`}
          tone={switching.bounces ? "warn" : undefined}
        />
        <Kpi
          label="Within a minute of opening"
          value={switching.earlySwitches}
          note={`${count(switching.earlyPeople)} people: opened in the wrong one`}
        />
        <Kpi
          label="Menu opened"
          value={switching.menuOpens}
          note={`${switching.menuLeft} times without a switch`}
        />
      </Tiles>
      {switching.directions.length ? (
        <p className={`${styles.body} ${styles.muted}`}>
          {switching.directions
            .map(
              ([key, value]) =>
                `${DIRECTION_WORDS[key] ?? key.replace(/_/g, " ")} ${value}`,
            )
            .join(" · ")}
        </p>
      ) : null}
    </Panel>
  );
}

function Screens({ friction }: { friction: Friction }) {
  const rows = friction.screens;
  if (!rows.length)
    return (
      <Panel title="Screens by friction">
        <p className={styles.body}>No screen was viewed this week.</p>
      </Panel>
    );
  return (
    <Panel
      title="Screens by friction"
      sub={`${rows.length}`}
      tools={
        <Why
          detail="Seen is the time a screen was on view (a call in the dialler doesn't count). Quick back: left with Back within 5 s. Exits: the last screen before the app closed or went idle. Rage and dead taps per 100 views; No change: key taps that changed nothing for a second; Loops: back and forth with another screen."
          more="Sorted by weighted friction per 100 views (a rage tap counts 3, a dead or unanswered tap 2, the rest 1)."
        />
      }
    >
      <Table
        label="Screens by friction"
        cards={rows.map((row) => (
          <Card key={row.screen}>
            <strong>
              {row.label} · {row.views} views · {count(row.people)} people
            </strong>
            <span>
              Seen {msWords(row.seenP50)} (90% within {msWords(row.seenP90)}) ·
              quick back {shareWords(row.quickBackShare)} · exits{" "}
              {shareWords(row.exitShare)}
            </span>
            <span className={styles.muted}>
              Rage {row.ragePer100 ?? "–"} · dead {row.deadPer100 ?? "–"} per
              100 views · no change {row.unresponsive} · loops {row.loops}
            </span>
          </Card>
        ))}
      >
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
              Seen (median · 90%)
            </th>
            <th scope="col" data-num="">
              Quick back
            </th>
            <th scope="col" data-num="">
              Exits
            </th>
            <th scope="col" data-num="">
              Rage /100
            </th>
            <th scope="col" data-num="">
              Dead /100
            </th>
            <th scope="col" data-num="">
              No change
            </th>
            <th scope="col" data-num="">
              Loops
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.screen}>
              <th scope="row">{row.label}</th>
              <td data-num="">{row.views}</td>
              <td data-num="">{count(row.people)}</td>
              <td data-num="">
                {msWords(row.seenP50)} · {msWords(row.seenP90)}
              </td>
              <td data-num="">{shareWords(row.quickBackShare)}</td>
              <td data-num="">{shareWords(row.exitShare)}</td>
              <td data-num="">{row.ragePer100 ?? "–"}</td>
              <td data-num="">{row.deadPer100 ?? "–"}</td>
              <td data-num="">{row.unresponsive}</td>
              <td data-num="">{row.loops}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Panel>
  );
}

export function FrictionView({
  friction,
  markdownHref,
}: {
  friction: Friction;
  /** The same report as a markdown file (the weekly job's). */
  markdownHref?: string;
}) {
  if (!friction.available)
    return (
      <Panel title="Friction">
        <p className={styles.body}>
          This environment&rsquo;s API doesn&rsquo;t have the friction report
          yet.
        </p>
      </Panel>
    );
  const { coverage } = friction;
  return (
    <>
      <Tiles label={`Week of ${weekWords(friction.week)}`}>
        <Kpi
          label="People"
          value={count(coverage.people)}
          note={`${coverage.visits} visits over ${coverage.days} days${friction.complete ? "" : " (week still running)"}`}
        />
        <Kpi
          label="Findings"
          value={friction.findings.length + friction.more}
          note={`${friction.gone.length} gone since the week before`}
          tone={
            friction.findings.some((item) => item.severity >= 4)
              ? "warn"
              : undefined
          }
        />
        <Kpi
          label="Flow events"
          value={coverage.flowEvents}
          note={`${coverage.promptEvents} permission prompts`}
        />
        <Kpi
          label="Events"
          value={coverage.events}
          note={
            coverage.apps
              .map(([app, value]) => `${app} ${value}`)
              .join(" · ") || "none"
          }
        />
      </Tiles>
      {friction.truncated ? (
        <p className={`${styles.body} ${styles.muted}`}>
          The read hit its row limit: counts are a lower bound.
        </p>
      ) : null}
      {markdownHref ? (
        <p className={styles.body}>
          <a href={markdownHref} download>
            Download this week as markdown
          </a>{" "}
          <span className={styles.muted}>
            (the file the weekly job writes for the owner and the builders)
          </span>
        </p>
      ) : null}
      <Findings friction={friction} />
      {friction.flows.length ? (
        friction.flows.map((flow) => <FlowPanel key={flow.flow} flow={flow} />)
      ) : (
        <Panel title="Flows">
          <p className={styles.body}>
            No flow events yet: they start with the release that records
            first-run setup, phone setup, Add lead and &ldquo;How did it
            go?&rdquo;.
          </p>
        </Panel>
      )}
      <Prompts friction={friction} />
      <Switching friction={friction} />
      <Screens friction={friction} />
    </>
  );
}
