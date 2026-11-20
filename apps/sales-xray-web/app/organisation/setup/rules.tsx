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
import { Skeleton } from "../../ui/kit";
import { PersonDisplayName } from "../people/person-display-name";
import { LeadSplit } from "./lead-split";
import split from "./lead-split.module.css";
import styles from "./setup.module.css";

export function OrganisationRules() {
  // One page, not two rows of tabs (round-2 board 3, option C, 20 Nov 2026):
  // the split, the move after work minutes, the hours and the sellers' switch,
  // then the rules for some leads and each seller's own rules, one tap down.
  // No title of its own: Leads setup's switch already says Lead rules (owner,
  // bug 190, 6 Nov 2026).
  return (
    <div className={styles.stack}>
      <LeadSplit />
      <SellerRules />
    </div>
  );
}
function SellerRules() {
  const [team, setTeam] = useState<Team | null>(null);
  const [callAi, setCallAi] = useState<CallAiSettings | null>(null);
  const [editing, setEditing] = useState<RepView | null>(null);
  const [round, setRound] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [routingOpen, setRoutingOpen] = useState(false);
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
  const save = async (auto: boolean, giving?: boolean) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const next = await saveSettings(team.settings.revision, {
        auto_reassign: auto,
        reassign_minutes: minutes,
        ...(giving === undefined ? {} : { sellers_reassign: giving }),
      });
      setTeam(next);
      notify({ id: "org-rules", tone: "success", title: "Lead rules saved" });
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
  const people = (
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
  );
  const hours = team.settings.work_hours?.days?.length ? "work " : "";
  return (
    <>
      <section className={styles.card}>
        <div className={styles.head}>
          <div>
            <h3>Move untouched leads</h3>
            <p>
              A lead with no call goes to the next seller
              {team.settings.work_hours?.days?.length
                ? ", counting work hours only"
                : ""}
              .
            </p>
          </div>
          <label className={split.toggle}>
            <input
              type="checkbox"
              role="switch"
              className={split.switch}
              aria-label="Move untouched leads"
              checked={team.settings.auto_reassign}
              disabled={busy}
              data-sx-feature="lead_rules_move_switch"
              onChange={() => void save(!team.settings.auto_reassign)}
            />
            {team.settings.auto_reassign ? "On" : "Off"}
          </label>
        </div>
        <p className={split.wait}>
          After
          <span className={split.stepper}>
            <button
              type="button"
              aria-label="Wait five minutes less"
              disabled={busy || minutes <= 5}
              onClick={() => setMinutes((value) => Math.max(5, value - 5))}
            >
              <Minus size={18} aria-hidden="true" />
            </button>
            <input
              aria-label="Wait in minutes"
              type="number"
              min={5}
              max={1440}
              step={5}
              value={minutes}
              onChange={(event) => setMinutes(Number(event.target.value))}
            />
            <button
              type="button"
              aria-label="Wait five minutes more"
              disabled={busy || minutes >= 1440}
              onClick={() => setMinutes((value) => Math.min(1440, value + 5))}
            >
              <Plus size={18} aria-hidden="true" />
            </button>
          </span>
          {hours}minutes with no call
        </p>
        {minutes !== team.settings.reassign_minutes ? (
          <div className={split.actions}>
            <button
              className={styles.primary}
              disabled={
                busy ||
                !Number.isInteger(minutes) ||
                minutes < 5 ||
                minutes > 1440
              }
              data-sx-feature="lead_rules_wait_saved"
              onClick={() => void save(team.settings.auto_reassign)}
            >
              Save wait time
            </button>
          </div>
        ) : null}
      </section>
      <WorkHoursPanel team={team} onSaved={setTeam} />
      {/* Sellers give their own leads to a colleague, with a reason (owner,
          Wise Life, 19 Nov 2026); owners and admins always can. */}
      <section className={styles.card}>
        <div className={styles.head}>
          <div>
            <h3>Sellers can reassign leads</h3>
            <p>A seller gives their lead to a colleague and says why.</p>
          </div>
          <label className={split.toggle}>
            <input
              type="checkbox"
              role="switch"
              className={split.switch}
              aria-label="Sellers can reassign leads"
              checked={!!team.settings.sellers_reassign}
              disabled={busy}
              data-sx-feature="lead_rules_give_switch"
              onChange={() =>
                void save(
                  team.settings.auto_reassign,
                  !team.settings.sellers_reassign,
                )
              }
            />
            {team.settings.sellers_reassign ? "On" : "Off"}
          </label>
        </div>
      </section>
      <details
        className={styles.details}
        onToggle={(event) => setRoutingOpen(event.currentTarget.open)}
      >
        <summary>Rules for some leads (a source, a city, a language)</summary>
        {routingOpen ? (
          <div className={`${styles.routing} ${split.more}`}>
            <RoutingRules />
          </div>
        ) : null}
      </details>
      <details className={styles.details}>
        <summary>Each seller&apos;s areas and limits</summary>
        <div className={`${styles.sellerScope} ${split.more}`}>{people}</div>
      </details>
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
  );
}
