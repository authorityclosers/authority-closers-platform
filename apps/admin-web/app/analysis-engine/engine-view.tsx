/**
 * Admin → Analysis engine (adaptive analysis, phase 1; owner, 22 Oct 2026): what each
 * analysis read was expected to cost (the registry's measured fit at each call's length)
 * against what it cost, which modules drift off their fit, and every plan's rupees per
 * audio minute on these calls and on production's measured 14-day mix. Read only: nothing
 * here routes a call.
 */
import {
  ageWords,
  isStale,
  meterTone,
  perMinuteWords,
} from "../usage/meter-data";
import { Badge, Card, Kpi, Panel, Table, Tiles, Why } from "../ui/kit";
import {
  STATUS_WORDS,
  ratioTone,
  ratioWords,
  rupeeWords,
  tokenWords,
  type AnalysisEngine,
  type EngineModuleRow,
  type EnginePlan,
  type RegistryModule,
  type TokenPair,
} from "./engine-data";
import styles from "./engine.module.css";

// The owner's two lines, as on the cost meter.
const TARGETS = [0.4, 0.1];

const ENVIRONMENT_WORDS: Record<string, string> = {
  production: "production",
  staging: "staging",
  development: "dev",
};

function Status({ value }: { value: RegistryModule["status"] }) {
  const words = STATUS_WORDS[value];
  return <Badge tone={words.tone}>{words.label}</Badge>;
}

function Ratio({ value, drift }: { value: number | null; drift: number }) {
  return (
    <span className={styles.ratio} data-tone={ratioTone(value, drift)}>
      {ratioWords(value)}
    </span>
  );
}

function Tokens({ pair }: { pair: TokenPair }) {
  // Reads billed by audio (transcripts, call data) have no token fit.
  if (pair.expected === null && !pair.actual) return <>–</>;
  return (
    <span className={styles.tokens}>
      {tokenWords(pair.actual)}
      <small> / {tokenWords(pair.expected)}</small>
    </span>
  );
}

function moduleName(row: EngineModuleRow) {
  return row.modelled
    ? (row.label ?? row.id)
    : `${row.stage} · ${row.model ?? "no model"}`;
}

function ModuleCell({ row }: { row: EngineModuleRow }) {
  return (
    <span className={styles.name}>
      <strong>{moduleName(row)}</strong>
      <small>
        <code>{row.modelled ? row.id : "no fit in the registry"}</code>
        {row.unpricedSteps
          ? ` · ${row.unpricedSteps} unpriced ${row.unpricedSteps === 1 ? "step" : "steps"}`
          : ""}
      </small>
    </span>
  );
}

function ModuleTable({ engine }: { engine: AnalysisEngine }) {
  const { modules, drift } = engine;
  return (
    <Table
      label="Expected against actual cost by module"
      cards={modules.map((row) => (
        <Card key={row.id}>
          <ModuleCell row={row} />
          <span>
            {rupeeWords(row.actualRupees)} actual ·{" "}
            {rupeeWords(row.expectedRupees)} expected ·{" "}
            <Ratio value={row.ratio} drift={drift} />
          </span>
          <span>
            {row.calls} {row.calls === 1 ? "call" : "calls"} · {row.steps}{" "}
            {row.steps === 1 ? "step" : "steps"}
            {row.tokensIn.actual || row.tokensIn.expected !== null ? (
              <>
                {" "}
                · tokens in <Tokens pair={row.tokensIn} />, out{" "}
                <Tokens pair={row.tokensOut} />
              </>
            ) : null}
          </span>
        </Card>
      ))}
    >
      <thead>
        <tr>
          <th scope="col">Module</th>
          <th scope="col" data-num="">
            Calls
          </th>
          <th scope="col" data-num="">
            Steps
          </th>
          <th scope="col" data-num="">
            Actual
          </th>
          <th scope="col" data-num="">
            Expected
          </th>
          <th scope="col" data-num="">
            Actual ÷ expected
          </th>
          <th scope="col" data-num="">
            Tokens in
          </th>
          <th scope="col" data-num="">
            Tokens out
          </th>
        </tr>
      </thead>
      <tbody>
        {modules.map((row) => (
          <tr key={row.id}>
            <th scope="row">
              <ModuleCell row={row} />
            </th>
            <td data-num="">{row.calls}</td>
            <td data-num="">{row.steps}</td>
            <td data-num="">{rupeeWords(row.actualRupees)}</td>
            <td data-num="">{rupeeWords(row.expectedRupees)}</td>
            <td data-num="">
              <Ratio value={row.ratio} drift={drift} />
            </td>
            <td data-num="">
              <Tokens pair={row.tokensIn} />
            </td>
            <td data-num="">
              <Tokens pair={row.tokensOut} />
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function PlanRate({ value }: { value: number | null }) {
  return (
    <span className={styles.ratio} data-tone={meterTone(value, TARGETS)}>
      {perMinuteWords(value)}
    </span>
  );
}

function uptakeWords(plan: EnginePlan, uptake: number) {
  if (!plan.onDemand.length || !plan.referenceWithUptake) return null;
  return `${perMinuteWords(plan.referenceWithUptake.perMinute)} if ${Math.round(uptake * 100)}% ask for the full report`;
}

function PlanTable({ engine }: { engine: AnalysisEngine }) {
  const { plans, registry } = engine;
  return (
    <Table
      label="Plans on these calls and on production's measured mix"
      cards={plans.map((plan) => (
        <Card key={plan.id}>
          <strong>{plan.label}</strong>
          <span>
            <Status value={plan.status} /> · these calls{" "}
            <PlanRate value={plan.window?.perMinute ?? null} /> · measured mix{" "}
            <PlanRate value={plan.reference?.perMinute ?? null} />
          </span>
          {uptakeWords(plan, registry.uptake) ? (
            <span>{uptakeWords(plan, registry.uptake)}</span>
          ) : null}
        </Card>
      ))}
    >
      <thead>
        <tr>
          <th scope="col">Plan</th>
          <th scope="col">Status</th>
          <th scope="col" data-num="">
            These calls
          </th>
          <th scope="col" data-num="">
            Measured mix
          </th>
          <th scope="col">Full report on demand</th>
        </tr>
      </thead>
      <tbody>
        {plans.map((plan) => (
          <tr key={plan.id} data-current={plan.id === "today" ? "" : undefined}>
            <th scope="row">
              <span className={styles.name}>
                <strong>{plan.label}</strong>
                <small>
                  <code>{plan.id}</code>
                </small>
              </span>
            </th>
            <td>
              <Status value={plan.status} />
            </td>
            <td data-num="">
              <PlanRate value={plan.window?.perMinute ?? null} />
            </td>
            <td data-num="">
              <PlanRate value={plan.reference?.perMinute ?? null} />
            </td>
            <td>
              <small className={styles.muted}>
                {uptakeWords(plan, registry.uptake) ?? "–"}
              </small>
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function RegistryList({ modules }: { modules: RegistryModule[] }) {
  return (
    <ul className={styles.registry}>
      {modules.map((module) => (
        <li key={module.id}>
          <span className={styles.registryHead}>
            <strong>{module.label}</strong>
            <Status value={module.status} />
          </span>
          <small>
            <code>{module.id}</code> · {module.stage}
            {module.models.length ? ` · ${module.models.join(", ")}` : ""}
          </small>
          <span className={styles.examples}>
            {module.examples.map((example) => (
              <span key={example.minutes}>
                {example.minutes} min <b>{rupeeWords(example.rupees)}</b>
              </span>
            ))}
          </span>
          <small className={styles.muted}>
            {module.evidence.replace(/\.$/, "")}
            {module.note ? `. ${module.note}` : "."}
          </small>
        </li>
      ))}
    </ul>
  );
}

export function EngineView({ engine }: { engine: AnalysisEngine }) {
  const where = ENVIRONMENT_WORDS[engine.environment] ?? engine.environment;
  const { window, registry, drift } = engine;
  const overall =
    window.expectedRupees > 0
      ? Math.round((window.actualRupees / window.expectedRupees) * 1000) / 1000
      : null;
  const drifting = engine.modules.filter((row) => row.drifting).length;
  const unmodelled = engine.modules.filter((row) => !row.modelled).length;
  const band = Math.round(drift * 100);
  return (
    <>
      {!engine.available ? (
        <p className={styles.note}>
          The {where} export isn&rsquo;t in the metrics store yet, so only the
          registry and its plans are shown.
        </p>
      ) : (
        <>
          {isStale(engine.ageSeconds) ? (
            <p className={styles.note} data-tone="warn">
              These numbers are from{" "}
              {ageWords(engine.ageSeconds).replace("updated ", "")}: the
              collector may have stopped.
            </p>
          ) : null}
          <Tiles label="Expected against actual">
            <Kpi
              label="Actual"
              value={perMinuteWords(window.actualPerMinute)}
              tone={meterTone(window.actualPerMinute, TARGETS)}
              note={`${window.calls} ${window.calls === 1 ? "call" : "calls"} · ${window.audioMinutes} min · ${rupeeWords(window.actualRupees)}`}
            />
            <Kpi
              label="Expected"
              value={perMinuteWords(window.expectedPerMinute)}
              note={`The registry's fits at these calls' lengths · ${rupeeWords(window.expectedRupees)}`}
            />
            <Kpi
              label="Actual ÷ expected"
              value={ratioWords(overall)}
              tone={ratioTone(overall, drift)}
              note={`Within ±${band}% means the fits hold`}
            />
            <Kpi
              label="Modules off their fit"
              value={drifting}
              tone={drifting ? "warn" : "good"}
              note={
                unmodelled
                  ? `${unmodelled} with no fit yet`
                  : "Every recorded step has a fit"
              }
            />
          </Tiles>
          <Panel
            title={`Expected against actual · ${where}`}
            sub={`Calls first transcribed in the last ${engine.days === 1 ? "24 hours" : `${engine.days} days`} · ${ageWords(engine.ageSeconds)}`}
            tools={
              <Why
                detail={`Each recorded step is matched to its registry module by stage, model and the call's fact prompt; the module's fit at the call's audio minutes is what was expected, once a call. Actual is the metrics store's list-price estimate for every priced attempt, re-runs included; tokens count every attempt (actual / expected). Steps no module covers are listed with no fit, never guessed. A module more than ${band}% off its fit is flagged for a refit. Canary, QA and synthetic calls never count. Rupees at the planning rate (₹${registry.planningFx} to the US dollar); not a bill.`}
              />
            }
          >
            {engine.modules.length ? (
              <ModuleTable engine={engine} />
            ) : (
              <p className={styles.note}>No analysed calls in this window.</p>
            )}
          </Panel>
        </>
      )}
      <Panel
        title="Plans"
        sub={`₹ per audio minute, all-in · under ${registry.shortCallMinutes} min a call gets the transcript and lead details only`}
        tools={
          <Why
            detail={`Each plan is a set of modules for short calls, analysed calls and, where marked, the full report on demand. These calls: the plan priced on this window's own calls. Measured mix: production's 14 days (62 calls, 284.4 min, 27 under a minute); today's plan there recomputes the ₹0.709/min the design used, plus fast lead facts on short calls. Projections from measured fits; only Live plans run.`}
          />
        }
      >
        <PlanTable engine={engine} />
      </Panel>
      <Panel
        title={`Registry · ${registry.version.replace("analysis-engine-registry/", "v")}`}
        sub={`Digest ${registry.digest} · what each read costs, measured; example costs at 2, 5 and 15 minutes`}
      >
        <RegistryList modules={registry.modules} />
      </Panel>
    </>
  );
}
