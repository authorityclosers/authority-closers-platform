"use client";

/**
 * Team controls (owner Home v3, 28 Oct 2026: "Team controls behind a gear";
 * the owner's #52: settings were buried in the Home scroll). One sheet from a
 * labelled gear in Home's header, for owners, admins and managers:
 * - each seller's target on a stepper, for any of the eight kinds (calls,
 *   connects, follow-ups or meetings; a day or a week), saved together;
 * - nudges on or off (on unless turned off, with the off confirmation), and
 *   who gets them as rows with faces and checks;
 * - the way to the lead rules.
 * The pickers are the app's own segmented controls, never a native select
 * (the owner's #62). Each seller's progress stays on their My day.
 */

import { Minus, Plus, Settings2, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";

import type { Metric } from "./my-day-client";
import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { commandId, readTeam, type Team } from "../leads/leads-client";
import {
  readTeamTargets,
  saveTargets,
  type SellerTargets,
  type TargetLine,
} from "../leads/team-engine-client";
import { METRICS, Nudges, PERIODS } from "../leads/targets-panel";
import { ActionList, ActionRow, Avatar, Segmented } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import styles from "./team-controls.module.css";

type Period = (typeof PERIODS)[number];
type Loaded = { team: Team; targets: Map<string, SellerTargets> };

const PERIOD_WORDS: Record<Period, string> = { day: "A day", week: "A week" };
/** Short, so four fit one segmented control at 360 px. */
const METRIC_SHORT: Record<Metric, string> = {
  calls: "Calls",
  connects: "Connects",
  follow_ups: "Follow-ups",
  meetings: "Meetings",
};
const MOST = 99_999;

const key = (metric: Metric, period: Period) => `${metric}:${period}`;

/** The team and its targets, read when the sheet opens (and after a save). */
function useControls(open: boolean, round: number) {
  const [state, setState] = useState<Loaded | "error" | null>(null);
  useEffect(() => {
    if (!open) return;
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
  }, [open, round]);
  return state;
}

const saved = (
  seller: SellerTargets | undefined,
  metric: Metric,
  period: Period,
) =>
  seller?.targets.find(
    (line) => line.metric === metric && line.period === period,
  )?.value ?? 0;

/** "18 calls today" or "62 this week": what the stepper's target is measured on. */
function progressWords(
  seller: SellerTargets | undefined,
  metric: Metric,
  period: Period,
): string {
  const line = seller?.progress.find(
    (item) => item.metric === metric && item.period === period,
  );
  const done = line?.done ?? 0;
  return `${done} ${period === "day" ? "today" : "this week"}`;
}

function Stepper({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (next: number) => void;
}) {
  const [text, setText] = useState(String(value));
  const [last, setLast] = useState(value);
  if (value !== last) {
    setLast(value);
    setText(String(value));
  }
  const set = (next: number) =>
    onChange(Math.min(MOST, Math.max(0, Math.round(next))));
  return (
    <span className={styles.stepper} role="group" aria-label={label}>
      <button
        type="button"
        aria-label={`One less: ${label}`}
        disabled={value <= 0}
        onClick={() => set(value - 1)}
      >
        <Minus size={16} aria-hidden="true" />
      </button>
      <input
        inputMode="numeric"
        aria-label={label}
        value={text}
        onChange={(event) => {
          const typed = event.target.value.replace(/\D/g, "").slice(0, 5);
          setText(typed);
          if (typed !== "") set(Number(typed));
        }}
        onBlur={() => setText(String(value))}
      />
      <button
        type="button"
        aria-label={`One more: ${label}`}
        disabled={value >= MOST}
        onClick={() => set(value + 1)}
      >
        <Plus size={16} aria-hidden="true" />
      </button>
    </span>
  );
}

export function TeamControls() {
  const [open, setOpen] = useState(false);
  const [round, setRound] = useState(0);
  const state = useControls(open, round);
  const [team, setTeam] = useState<Team | null>(null);
  const [metric, setMetric] = useState<Metric>("calls");
  const [period, setPeriod] = useState<Period>("day");
  // Unsaved targets: person -> "metric:period" -> value.
  const [drafts, setDrafts] = useState<Record<string, Record<string, number>>>(
    {},
  );
  const [ids, setIds] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const loaded = state && state !== "error" ? state : null;
  const shownTeam = team ?? loaded?.team ?? null;
  const valueOf = (person: string, which: Metric, when: Period) =>
    drafts[person]?.[key(which, when)] ??
    saved(loaded?.targets.get(person), which, when);
  const changed = Object.keys(drafts).filter((person) =>
    Object.entries(drafts[person]).some(([name, value]) => {
      const [which, when] = name.split(":") as [Metric, Period];
      return value !== saved(loaded?.targets.get(person), which, when);
    }),
  );
  const close = () => {
    setOpen(false);
    setDrafts({});
    setTeam(null);
  };
  const save = async () => {
    if (!loaded || busy || !changed.length) return;
    setBusy(true);
    try {
      for (const person of changed) {
        // The whole set of eight, so the kinds not on screen keep their value.
        const lines: TargetLine[] = METRICS.flatMap((which) =>
          PERIODS.map((when) => ({
            metric: which,
            period: when,
            value: valueOf(person, which, when),
          })),
        );
        await saveTargets(person, lines, ids[person] ?? commandId());
      }
      notify({
        id: "targets",
        tone: "success",
        title:
          changed.length === 1
            ? "Targets saved"
            : `Targets saved for ${changed.length} sellers`,
        message: "They count from today, on each seller's My day.",
        timeout: 5_000,
      });
      setDrafts({});
      setIds({});
      setRound((value) => value + 1);
    } catch {
      notify({
        id: "targets",
        tone: "error",
        title: "The targets weren't saved",
        message: "Check your connection and try again.",
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button
        type="button"
        className={styles.gear}
        aria-haspopup="dialog"
        onClick={() => {
          setOpen(true);
          setRound((value) => value + 1);
        }}
      >
        <Settings2 size={18} aria-hidden="true" />
        Controls
      </button>
      <Sheet
        open={open}
        onClose={close}
        title="Team controls"
        description="Targets and nudges for the team, in one place."
        footer={
          <div className={styles.footer}>
            <button
              type="button"
              className={styles.save}
              disabled={!changed.length || busy}
              onClick={() => void save()}
            >
              {busy ? "Saving…" : "Save targets"}
            </button>
            <small>From today on. 0 means no target.</small>
          </div>
        }
      >
        {state === "error" ? (
          <p className={styles.quiet} role="status">
            The team didn&apos;t load. Close this and try again in a moment.
          </p>
        ) : !loaded || !shownTeam ? (
          <div className={styles.loading} aria-busy="true" />
        ) : (
          <div className={styles.body}>
            <section aria-labelledby="controls-targets">
              <h3 id="controls-targets" className={styles.title}>
                Targets per seller
              </h3>
              <div className={styles.pickers}>
                {/* Four kinds as compact chips that wrap (a four-way
                    segmented control broke "Follow-ups" in two at 390 px). */}
                <div
                  className={styles.kinds}
                  role="radiogroup"
                  aria-label="Target"
                >
                  {METRICS.map((which) => (
                    <button
                      key={which}
                      type="button"
                      role="radio"
                      aria-checked={metric === which}
                      className={styles.kind}
                      onClick={() => setMetric(which)}
                    >
                      {METRIC_SHORT[which]}
                    </button>
                  ))}
                </div>
                <Segmented
                  label="Each"
                  value={period}
                  onChange={setPeriod}
                  items={PERIODS.map((when) => ({
                    key: when,
                    label: PERIOD_WORDS[when],
                  }))}
                />
              </div>
              {shownTeam.reps.length ? (
                <ul className={styles.sellers}>
                  {shownTeam.reps.map((rep) => {
                    const seller = loaded.targets.get(rep.person_id);
                    const name = displayName(rep.name);
                    return (
                      <li key={rep.person_id}>
                        <Avatar name={rep.name} size={34} />
                        <span className={styles.who}>
                          <strong>{name}</strong>
                          <small>{progressWords(seller, metric, period)}</small>
                        </span>
                        <Stepper
                          label={`${name}: ${METRIC_SHORT[metric]}, ${PERIOD_WORDS[period].toLowerCase()}`}
                          value={valueOf(rep.person_id, metric, period)}
                          onChange={(next) => {
                            setIds((now) =>
                              now[rep.person_id]
                                ? now
                                : { ...now, [rep.person_id]: commandId() },
                            );
                            setDrafts((now) => ({
                              ...now,
                              [rep.person_id]: {
                                ...now[rep.person_id],
                                [key(metric, period)]: next,
                              },
                            }));
                          }}
                        />
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className={styles.quiet}>
                  Add sellers to give them targets.
                </p>
              )}
            </section>
            <Nudges team={shownTeam} onSaved={setTeam} who="rows" />
            <ActionList label="Rules">
              <ActionRow
                icon={<SlidersHorizontal size={20} />}
                tone="neutral"
                title="Lead rules"
                note="Who gets which leads, and how fast"
                href="/settings/lead-rules"
              />
            </ActionList>
          </div>
        )}
      </Sheet>
    </>
  );
}
