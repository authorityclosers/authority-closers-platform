"use client";
import { ChevronRight, Minus, Plus, UsersRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { notify } from "../../notice-center";
import { RoutingRules } from "../../leads/routing-rules";
import {
  readTeam,
  saveSettings,
  type RepView,
  type Team,
} from "../../leads/leads-client";
import { TeamView, WorkHoursPanel } from "../../leads/team-view";
import { SellerSheet } from "../../leads/seller-sheet";
import { readCallAi, type CallAiSettings } from "../../call-ai/call-ai-client";
import { Segmented, Skeleton } from "../../ui/kit";
import { PersonDisplayName } from "../people/person-display-name";
import styles from "./setup.module.css";

export function OrganisationRules() {
  const [part, setPart] = useState<"routing" | "people" | "limits">("routing");
  return (
    <div className={styles.stack}>
      <header className={styles.head}>
        <div>
          <h2>Lead rules</h2>
          <p>Choose who gets new leads and when they move.</p>
        </div>
      </header>
      <Segmented
        label="Lead rule setup"
        value={part}
        onChange={setPart}
        items={[
          { key: "routing", label: "Match leads" },
          { key: "people", label: "Seller rules" },
          { key: "limits", label: "Limits" },
        ]}
      />
      {part === "routing" ? (
        <div className={styles.routing}>
          <RoutingRules />
        </div>
      ) : (
        <SellerRules mode={part} />
      )}
    </div>
  );
}
function SellerRules({ mode }: { mode: "people" | "limits" }) {
  const [team, setTeam] = useState<Team | null>(null);
  const [callAi, setCallAi] = useState<CallAiSettings | null>(null);
  const [editing, setEditing] = useState<RepView | null>(null);
  const [round, setRound] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [failed, setFailed] = useState(false);
  const [minutes, setMinutes] = useState(10);
  const lock = useRef(false);
  useEffect(() => {
    const control = new AbortController();
    readTeam(control.signal).then(
      (next) => {
        if (!control.signal.aborted) {
          setTeam(next);
          setMinutes(next.settings.reassign_minutes);
          setFailed(false);
        }
      },
      () => {
        if (!control.signal.aborted) setFailed(true);
      },
    );
    readCallAi(control.signal).then(setCallAi, () => {});
    return () => control.abort();
  }, [attempt]);
  if (!team)
    return failed ? (
      <button
        className={styles.button}
        onClick={() => setAttempt((value) => value + 1)}
      >
        Try loading rules again
      </button>
    ) : (
      <div aria-busy="true" aria-label="Loading seller rules">
        <Skeleton height={240} />
      </div>
    );
  const save = async (auto: boolean) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const next = await saveSettings(team.settings.revision, {
        auto_reassign: auto,
        reassign_minutes: minutes,
      });
      setTeam(next);
      notify({ id: "org-rules", tone: "success", title: "Lead limit saved" });
    } catch (reason) {
      notify({
        id: "org-rules",
        tone: "error",
        title: "Rule was not saved",
        message: reason instanceof Error ? reason.message : "Try again.",
      });
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  return (
    <div className={styles.stack}>
      {mode === "people" ? (
        <>
          <p className={styles.help}>
            Choose a seller to set areas, languages, products and capacity.
          </p>
          <ul className={styles.list}>
            {team.reps.map((rep) => (
              <li key={rep.person_id}>
                <button
                  className={styles.choice}
                  onClick={() => {
                    setEditing(rep);
                    setRound((value) => value + 1);
                  }}
                >
                  <UsersRound size={20} aria-hidden="true" />
                  <span className={styles.copy}>
                    <PersonDisplayName name={rep.name} />
                    <small>
                      {rep.available ? "Taking leads" : "Not taking leads"} ·{" "}
                      {rep.max_open == null
                        ? "No cap"
                        : `${rep.max_open} open-lead cap`}
                    </small>
                  </span>
                  <ChevronRight size={18} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
          {team.reps.length === 0 ? (
            <p className={styles.help}>
              Invite a seller from Team to set their lead rules.
            </p>
          ) : null}
          <SellerSheet
            key={round}
            rep={editing}
            callAi={callAi}
            onClose={() => setEditing(null)}
            onSaved={setTeam}
            onCallAiSaved={setCallAi}
          />
        </>
      ) : (
        <>
          <section className={styles.card}>
            <div className={styles.head}>
              <div>
                <h3>Move untouched leads</h3>
                <p>Give another seller a turn when no call is logged.</p>
              </div>
              <button
                className={styles.button}
                role="switch"
                aria-label="Move untouched leads"
                aria-checked={team.settings.auto_reassign}
                disabled={busy}
                onClick={() => void save(!team.settings.auto_reassign)}
              >
                {team.settings.auto_reassign ? "On" : "Off"}
              </button>
            </div>
            <label className={styles.copy}>
              Wait before moving
              <div className={styles.tools}>
                <button
                  className={styles.button}
                  aria-label="Wait five minutes less"
                  disabled={busy || minutes <= 5}
                  onClick={() => setMinutes((value) => Math.max(5, value - 5))}
                >
                  <Minus size={18} />
                </button>
                <input
                  className={styles.search}
                  style={{ width: 100 }}
                  aria-label="Wait in minutes"
                  type="number"
                  min={5}
                  max={1440}
                  step={5}
                  value={minutes}
                  onChange={(event) => setMinutes(Number(event.target.value))}
                />
                <span>minutes</span>
                <button
                  className={styles.button}
                  aria-label="Wait five minutes more"
                  disabled={busy || minutes >= 1440}
                  onClick={() =>
                    setMinutes((value) => Math.min(1440, value + 5))
                  }
                >
                  <Plus size={18} />
                </button>
              </div>
            </label>
            <button
              className={styles.primary}
              disabled={
                busy ||
                !Number.isInteger(minutes) ||
                minutes < 5 ||
                minutes > 1440 ||
                minutes === team.settings.reassign_minutes
              }
              onClick={() => void save(team.settings.auto_reassign)}
            >
              Save wait time
            </button>
          </section>
          <WorkHoursPanel team={team} onSaved={setTeam} />
          <details
            className={styles.details}
            onToggle={(event) => setAdvanced(event.currentTarget.open)}
          >
            <summary>More lead rules</summary>
            {advanced ? (
              <div>
                <TeamView
                  rulesOnly
                  onChanged={() => undefined}
                  onOpen={() => undefined}
                />
              </div>
            ) : null}
          </details>
        </>
      )}
    </div>
  );
}
