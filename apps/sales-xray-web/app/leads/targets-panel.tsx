"use client";

/**
 * Targets and nudges for owners and managers (owner program, 25 Oct 2026,
 * section 2, on Lead OS's team engine): each seller's progress today against
 * the targets set for them, a sheet to set a seller's daily and weekly
 * targets, and nudges: a seller who drifts gets an urgent alert back to work,
 * inside work hours only.
 */

import { BellRing, Target } from "lucide-react";
import { useEffect, useState } from "react";

import { METRIC_WORDS, type Metric } from "../dashboard/my-day-client";
import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { Sheet } from "../ui/sheet";
import { Avatar } from "../ui/kit";
import { commandId, readTeam, type RepView, type Team } from "./leads-client";
import {
  readTeamTargets,
  saveNudges,
  saveTargets,
  type NudgeSettings,
  type SellerTargets,
  type TargetLine,
} from "./team-engine-client";
import styles from "./targets-panel.module.css";

const METRICS: Metric[] = ["calls", "connects", "follow_ups", "meetings"];
const PERIODS = ["day", "week"] as const;

type Loaded = { team: Team; targets: Map<string, SellerTargets> };

function useTeamTargets(round: number) {
  const [state, setState] = useState<Loaded | "error" | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      readTeam(controller.signal),
      readTeamTargets(controller.signal),
    ])
      .then(([team, targets]) =>
        setState({
          team,
          targets: new Map(
            targets.sellers.map((seller) => [seller.person_id, seller]),
          ),
        }),
      )
      .catch(() => {
        if (!controller.signal.aborted) setState("error");
      });
    return () => controller.abort();
  }, [round]);
  return state;
}

/** "Calls 18/40 · 8 behind", the day's lines first. */
function ProgressLine({ seller }: { seller: SellerTargets | undefined }) {
  const lines = (seller?.progress ?? []).filter(
    (line) => line.period === "day",
  );
  if (!lines.length)
    return <small className={styles.none}>No targets yet</small>;
  return (
    <span className={styles.lines}>
      {lines.map((line) => (
        <span
          key={line.metric}
          className={styles.line}
          data-tone={
            line.done >= line.target ? "good" : line.behind ? "warn" : "on"
          }
        >
          {`${METRIC_WORDS[line.metric]} ${line.done}/${line.target}`}
          {line.behind && line.done < line.target
            ? ` · ${line.short} behind`
            : ""}
        </span>
      ))}
    </span>
  );
}

function TargetsSheet({
  rep,
  current,
  onClose,
  onSaved,
}: {
  rep: RepView | null;
  current: SellerTargets | undefined;
  onClose: () => void;
  onSaved: () => void;
}) {
  const valueOf = (metric: Metric, period: "day" | "week") =>
    String(
      current?.targets.find(
        (line) => line.metric === metric && line.period === period,
      )?.value ?? "",
    );
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      METRICS.flatMap((metric) =>
        PERIODS.map((period) => [
          `${metric}:${period}`,
          valueOf(metric, period),
        ]),
      ),
    ),
  );
  const [id] = useState(commandId);
  const [busy, setBusy] = useState(false);
  const bad = Object.values(values).some(
    (value) => value !== "" && !/^\d{1,5}$/.test(value.trim()),
  );
  const save = async () => {
    if (!rep || bad || busy) return;
    const lines: TargetLine[] = METRICS.flatMap((metric) =>
      PERIODS.map((period) => ({
        metric,
        period,
        value: Number(values[`${metric}:${period}`] || 0),
      })),
    );
    setBusy(true);
    try {
      await saveTargets(rep.person_id, lines, id);
      notify({
        id: "targets",
        tone: "success",
        title: `${displayName(rep.name).split(" ")[0]}'s targets saved`,
        message: "They count from today, on their My day.",
        timeout: 5_000,
      });
      onSaved();
    } catch {
      notify({
        id: "targets",
        tone: "error",
        title: "The targets weren't saved",
        message: "Check your connection and try again.",
      });
      setBusy(false);
    }
  };
  return (
    <Sheet
      open={rep !== null}
      onClose={onClose}
      title={rep ? `${displayName(rep.name)}'s targets` : "Targets"}
      description="From today on. Leave a box empty, or 0, for no target."
      footer={
        <button
          type="button"
          className={styles.save}
          disabled={bad || busy}
          onClick={() => void save()}
        >
          Save targets
        </button>
      }
    >
      <table className={styles.form}>
        <thead>
          <tr>
            <th scope="col">
              <span className={styles.hidden}>What</span>
            </th>
            <th scope="col">A day</th>
            <th scope="col">A week</th>
          </tr>
        </thead>
        <tbody>
          {METRICS.map((metric) => (
            <tr key={metric}>
              <th scope="row">{METRIC_WORDS[metric]}</th>
              {PERIODS.map((period) => {
                const name = `${metric}:${period}`;
                return (
                  <td key={period}>
                    <input
                      inputMode="numeric"
                      aria-label={`${METRIC_WORDS[metric]} ${period === "day" ? "a day" : "a week"}`}
                      value={values[name]}
                      aria-invalid={
                        values[name] !== "" &&
                        !/^\d{1,5}$/.test(values[name].trim())
                          ? true
                          : undefined
                      }
                      onChange={(event) =>
                        setValues((now) => ({
                          ...now,
                          [name]: event.target.value,
                        }))
                      }
                    />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {bad ? (
        <p className={styles.error} role="alert">
          Use whole numbers, like 40.
        </p>
      ) : null}
    </Sheet>
  );
}

function Nudges({
  team,
  onSaved,
}: {
  team: Team;
  onSaved: (next: Team) => void;
}) {
  const settings = team.settings as NudgeSettings;
  const on = settings.nudges === true;
  const offFor = settings.nudges_off_for ?? [];
  const [busy, setBusy] = useState(false);
  const save = async (enabled: boolean, off: string[]) => {
    setBusy(true);
    try {
      onSaved(await saveNudges(settings.revision, enabled, off));
    } catch {
      notify({
        id: "nudges",
        tone: "error",
        title: "Nudges weren't changed",
        message: "Someone may have changed the team just now. Try again.",
      });
    }
    setBusy(false);
  };
  return (
    <div className={styles.nudges}>
      <div className={styles.nudgesHead}>
        <span className={styles.nudgeIcon} aria-hidden="true">
          <BellRing size={18} />
        </span>
        <span className={styles.nudgeWords}>
          <strong>Nudges</strong>
          <small>
            A seller who drifts from their targets gets an urgent alert back to
            work, in work hours only.
          </small>
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-label="Nudges"
          className={styles.switch}
          disabled={busy}
          onClick={() => void save(!on, offFor)}
        >
          <span />
        </button>
      </div>
      {on ? (
        <div className={styles.chips} aria-label="Nudges for">
          {team.reps.map((rep) => {
            const off = offFor.includes(rep.person_id);
            return (
              <button
                key={rep.person_id}
                type="button"
                className={styles.chip}
                aria-pressed={!off}
                disabled={busy}
                onClick={() =>
                  void save(
                    true,
                    off
                      ? offFor.filter((item) => item !== rep.person_id)
                      : [...offFor, rep.person_id],
                  )
                }
              >
                {displayName(rep.name).split(" ")[0]}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export function TargetsPanel() {
  const [round, setRound] = useState(0);
  const state = useTeamTargets(round);
  const [editing, setEditing] = useState<RepView | null>(null);
  const [team, setTeam] = useState<Team | null>(null);
  const shownTeam = team ?? (state && state !== "error" ? state.team : null);
  return (
    <section className={styles.panel} aria-labelledby="targets-title">
      <div className={styles.head}>
        <h2 id="targets-title">Targets</h2>
        <span className={styles.meta}>Today</span>
      </div>
      {state === "error" ? (
        <p className={styles.quiet} role="status">
          Targets didn&apos;t load. Come back in a moment.
        </p>
      ) : state === null || shownTeam === null ? (
        <div className={styles.loading} aria-busy="true" />
      ) : (
        <>
          {state.targets.size === 0 ? (
            <div className={styles.start}>
              <Target size={20} aria-hidden="true" />
              <span>
                Set daily targets for calls, connects, follow-ups and meetings.
                Each seller sees their progress on My day.
              </span>
            </div>
          ) : null}
          <ul className={styles.rows}>
            {shownTeam.reps.map((rep) => (
              <li key={rep.person_id}>
                <Avatar name={rep.name} size={34} />
                <span className={styles.rowMain}>
                  <strong>{displayName(rep.name)}</strong>
                  <ProgressLine seller={state.targets.get(rep.person_id)} />
                </span>
                <button
                  type="button"
                  className={styles.set}
                  onClick={() => setEditing(rep)}
                  aria-label={`Set ${displayName(rep.name)}'s targets`}
                >
                  Set
                </button>
              </li>
            ))}
          </ul>
          <Nudges team={shownTeam} onSaved={setTeam} />
        </>
      )}
      <TargetsSheet
        key={editing?.person_id ?? "none"}
        rep={editing}
        current={
          editing && state && state !== "error"
            ? state.targets.get(editing.person_id)
            : undefined
        }
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          setRound((value) => value + 1);
        }}
      />
    </section>
  );
}
