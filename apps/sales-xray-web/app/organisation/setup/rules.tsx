"use client";
import {
  ChevronRight,
  Minus,
  Plus,
  Signpost,
  SlidersHorizontal,
  UsersRound,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { notify } from "../../notice-center";
import { RoutingRules } from "../../leads/routing-rules";
import {
  LeadsError,
  readTeam,
  saveSettings,
  saveWorkHours,
  type RepView,
  type Team,
} from "../../leads/leads-client";
import { TeamView } from "../../leads/team-view";
import { SellerSheet } from "../../leads/seller-sheet";
import { readCallAi, type CallAiSettings } from "../../call-ai/call-ai-client";
import { Skeleton } from "../../ui/kit";
import { Initials } from "../family";
import family from "../family.module.css";
import { PersonDisplayName } from "../people/person-display-name";
import { LeadSplitCard, perTen, useLeadSplit } from "./lead-split";
import { OnOff } from "./on-off";
import {
  clock,
  dayWords,
  hoursChanged,
  hoursDraft,
  hoursPayload,
  hoursProblem,
  WorkHoursCard,
  type HoursDraft,
} from "./work-hours-card";
import card from "./lead-split.module.css";
import styles from "./rules.module.css";

/**
 * Settings → Lead rules. One page, not two rows of tabs (round-2 board 3,
 * option C, 20 Nov 2026): the split, the move after work minutes, the hours
 * and the sellers' switch, then the rules for some leads and each seller's own
 * rules, one tap down. No title of its own: the settings frame says Lead rules
 * (owner, bug 190, 6 Nov 2026).
 *
 * v1.93 (22 Nov 2026, "Yes, build them"): every change is a draft and the
 * page has ONE solid deep-green Save, shown only when something changed. It
 * saves the split on the newest routing revision, then the team settings and
 * the work hours on the team's revision (each refused by the server when
 * stale). From a wide laptop the right side is a live preview of the rules.
 */
export function OrganisationRules() {
  const split = useLeadSplit();
  const rules = useTeamRules();
  const [saving, setSaving] = useState(false);
  const dirty = split.changed || rules.changed;
  const problem = !split.valid
    ? "The shares add up to 100 % to save."
    : rules.problem;

  const save = async () => {
    if (saving || problem) return;
    setSaving(true);
    try {
      const splitSaved = await split.save();
      const rulesSaved = await rules.save();
      if (splitSaved && rulesSaved)
        notify({ id: "org-rules", tone: "success", title: "Lead rules saved" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.frame}>
      <div className={styles.page}>
        <div className={styles.main}>
          <LeadSplitCard split={split} />
          <SellerRules rules={rules} />
        </div>
        <aside
          className={styles.rail}
          data-dirty={dirty ? "" : undefined}
          aria-label="Live preview"
        >
          <section className={styles.preview} aria-labelledby="preview-title">
            <h3 id="preview-title" className={card.title}>
              Live preview
            </h3>
            <p className={styles.previewLead}>
              {split.turns.length ? (
                <>
                  <strong>The next 5 leads go to:</strong>
                  <span>{split.turns.join(", ")}</span>
                </>
              ) : (
                <>
                  <strong>New leads go to:</strong>
                  <span>Whoever is free with the fewest open leads</span>
                </>
              )}
            </p>
            {split.turns.length ? (
              <p className={styles.previewTen}>
                Out of every 10: {perTen(split.parts)}
              </p>
            ) : null}
            {rules.team ? (
              <dl className={styles.facts}>
                <div>
                  <dt>Untouched leads</dt>
                  <dd>
                    {rules.auto
                      ? `Move after ${rules.minutes} ${rules.hours.set ? "work " : ""}min`
                      : "Stay with their seller"}
                  </dd>
                </div>
                <div>
                  <dt>Work hours</dt>
                  <dd>
                    {rules.hours.set && rules.hours.days.length
                      ? `${dayWords(rules.hours.days)} · ${clock(rules.hours.start)}–${clock(rules.hours.end)}`
                      : "Not set"}
                  </dd>
                </div>
                <div>
                  <dt>Sellers give leads</dt>
                  <dd>{rules.giving ? "Yes, with a reason" : "No"}</dd>
                </div>
              </dl>
            ) : null}
          </section>
          {dirty ? (
            <div className={styles.save} role="region" aria-label="Save rules">
              <p className={styles.saveWords}>
                <strong>Unsaved changes</strong>
                <span data-problem={problem ? "" : undefined}>
                  {problem ?? "New leads follow them once saved."}
                </span>
              </p>
              <div className={styles.saveActions}>
                <button
                  type="button"
                  className={styles.quiet}
                  disabled={saving}
                  onClick={() => {
                    split.discard();
                    rules.discard();
                  }}
                >
                  Undo
                </button>
                <button
                  type="button"
                  className={family.primary}
                  disabled={saving || !!problem}
                  data-sx-feature="lead_rules_saved"
                  onClick={() => void save()}
                >
                  {saving ? "Saving…" : "Save rules"}
                </button>
              </div>
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  );
}

type TeamRules = ReturnType<typeof useTeamRules>;

/** The team's lead settings and work hours as drafts over what is saved. */
function useTeamRules() {
  const [team, setTeam] = useState<Team | null>(null);
  const [callAi, setCallAi] = useState<CallAiSettings | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(false);
  const [minutes, setMinutes] = useState(10);
  const [giving, setGiving] = useState(false);
  const [hours, setHours] = useState<HoursDraft>(hoursDraft(null));
  const lock = useRef(false);

  const reset = (next: Team) => {
    setAuto(next.settings.auto_reassign);
    setMinutes(next.settings.reassign_minutes);
    setGiving(!!next.settings.sellers_reassign);
    setHours(hoursDraft(next.settings.work_hours));
  };

  useEffect(() => {
    const control = new AbortController();
    readTeam(control.signal).then(
      (next) => {
        if (control.signal.aborted) return;
        setTeam(next);
        reset(next);
        setFailed(false);
      },
      () => {
        if (!control.signal.aborted) setFailed(true);
      },
    );
    readCallAi(control.signal).then(setCallAi, () => {});
    return () => control.abort();
  }, [attempt]);

  const saved = team?.settings;
  const settingsChanged =
    !!saved &&
    (auto !== saved.auto_reassign ||
      minutes !== saved.reassign_minutes ||
      giving !== !!saved.sellers_reassign);
  const workChanged = !!saved && hoursChanged(hours, saved.work_hours);
  const minutesOk =
    Number.isInteger(minutes) && minutes >= 5 && minutes <= 1440;
  const problem = !minutesOk
    ? "Pick a wait between 5 and 1440 minutes."
    : hoursProblem(hours);

  /** Settings first, then the hours on the revision that save returned. */
  const save = async (): Promise<boolean> => {
    if (!team || !(settingsChanged || workChanged)) return true;
    if (lock.current || problem) return false;
    lock.current = true;
    setBusy(true);
    let current = team;
    try {
      if (settingsChanged) {
        current = await saveSettings(current.settings.revision, {
          auto_reassign: auto,
          reassign_minutes: minutes,
          ...(giving === !!current.settings.sellers_reassign
            ? {}
            : { sellers_reassign: giving }),
        });
        setTeam(current);
      }
      if (workChanged) {
        current = await saveWorkHours(
          current.settings.revision,
          hoursPayload(hours),
        );
        setTeam(current);
      }
      reset(current);
      return true;
    } catch (reason) {
      notify({
        id: "org-rules",
        tone: "error",
        title: "Rules were not saved",
        message:
          reason instanceof LeadsError || reason instanceof Error
            ? reason.message
            : "Try again.",
      });
      return false;
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };

  return {
    team,
    setTeam,
    callAi,
    setCallAi,
    failed,
    retry: () => setAttempt((value) => value + 1),
    busy,
    auto,
    setAuto,
    minutes,
    setMinutes,
    giving,
    setGiving,
    hours,
    setHours,
    changed: settingsChanged || workChanged,
    problem,
    save,
    discard: () => {
      if (team) reset(team);
    },
  };
}

function SellerRules({ rules }: { rules: TeamRules }) {
  const { team, busy } = rules;
  const [editing, setEditing] = useState<RepView | null>(null);
  const [round, setRound] = useState(0);
  const [advanced, setAdvanced] = useState(false);
  const [routingOpen, setRoutingOpen] = useState(false);

  if (!team)
    return rules.failed ? (
      <button type="button" className={card.retry} onClick={rules.retry}>
        Try loading rules again
      </button>
    ) : (
      <div aria-busy="true" aria-label="Loading seller rules">
        <Skeleton height={240} />
      </div>
    );

  const workHoursSet = !!team.settings.work_hours?.days?.length;
  const people = (
    <>
      {team.reps.length ? (
        <ul className={family.plainList}>
          {team.reps.map((rep) => (
            <li key={rep.person_id}>
              <button
                type="button"
                className={family.row}
                onClick={() => {
                  setEditing(rep);
                  setRound((value) => value + 1);
                }}
              >
                <Initials name={rep.name} id={rep.person_id} size={36} />
                <span className={family.rowText}>
                  <span className={family.rowTitle}>
                    <PersonDisplayName name={rep.name} />
                  </span>
                  <span className={family.rowSub}>
                    {rep.available ? "Taking leads" : "Not taking leads"} ·{" "}
                    {rep.max_open == null
                      ? "No cap"
                      : `${rep.max_open} open-lead cap`}
                  </span>
                </span>
                <ChevronRight className={family.chevron} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className={card.sub}>
          Invite a seller from Team to set their lead rules.
        </p>
      )}
      <SellerSheet
        key={round}
        rep={editing}
        callAi={rules.callAi}
        onClose={() => setEditing(null)}
        onSaved={rules.setTeam}
        onCallAiSaved={rules.setCallAi}
      />
    </>
  );

  return (
    <>
      <section className={card.card} aria-labelledby="move-title">
        <div className={card.head}>
          <h3 id="move-title" className={card.title}>
            Move untouched leads
          </h3>
          <OnOff
            label="Move untouched leads"
            on={rules.auto}
            disabled={busy}
            feature="lead_rules_move_switch"
            onChange={rules.setAuto}
          />
        </div>
        <p className={card.sub}>
          A lead with no call goes to the next seller
          {workHoursSet ? ", counting work hours only" : ""}.
        </p>
        <div className={styles.wait} data-off={rules.auto ? undefined : ""}>
          <span>After</span>
          <span className={styles.stepper}>
            <button
              type="button"
              aria-label="Wait five minutes less"
              disabled={busy || rules.minutes <= 5}
              onClick={() => rules.setMinutes(Math.max(5, rules.minutes - 5))}
            >
              <Minus size={18} aria-hidden="true" />
            </button>
            <input
              aria-label="Wait in minutes"
              type="number"
              inputMode="numeric"
              min={5}
              max={1440}
              step={5}
              value={rules.minutes}
              disabled={busy}
              onChange={(event) => rules.setMinutes(Number(event.target.value))}
            />
            <button
              type="button"
              aria-label="Wait five minutes more"
              disabled={busy || rules.minutes >= 1440}
              onClick={() =>
                rules.setMinutes(Math.min(1440, rules.minutes + 5))
              }
            >
              <Plus size={18} aria-hidden="true" />
            </button>
          </span>
          <span>{workHoursSet ? "work minutes" : "minutes"}</span>
        </div>
      </section>
      <WorkHoursCard
        draft={rules.hours}
        current={team.settings.work_hours}
        disabled={busy}
        onChange={rules.setHours}
      />
      {/* Sellers give their own leads to a colleague, with a reason (owner,
          Wise Life, 19 Nov 2026); owners and admins always can. */}
      <section className={card.card} aria-labelledby="give-title">
        <div className={card.head}>
          <h3 id="give-title" className={card.title}>
            Sellers can reassign leads
          </h3>
          <OnOff
            label="Sellers can reassign leads"
            on={rules.giving}
            disabled={busy}
            feature="lead_rules_give_switch"
            onChange={rules.setGiving}
          />
        </div>
        <p className={card.sub}>
          A seller gives their lead to a colleague and says why.
        </p>
      </section>
      <section className={styles.more} aria-label="More lead rules">
        <More
          icon={<Signpost aria-hidden="true" />}
          title="Rules for some leads"
          sub="A source, a city or a language goes to the right seller first"
          onToggle={setRoutingOpen}
        >
          {routingOpen ? (
            <div className={styles.routing}>
              <RoutingRules />
            </div>
          ) : null}
        </More>
        <More
          icon={<UsersRound aria-hidden="true" />}
          title="Each seller's areas and limits"
          sub={`${team.reps.length} ${team.reps.length === 1 ? "seller" : "sellers"} · areas, languages, products, open-lead cap`}
        >
          <div className={styles.sellerScope}>{people}</div>
        </More>
        <More
          icon={<SlidersHorizontal aria-hidden="true" />}
          title="More lead rules"
          sub="Who takes new leads, lists and languages"
          onToggle={setAdvanced}
        >
          {advanced ? (
            <TeamView
              rulesOnly
              onChanged={() => undefined}
              onOpen={() => undefined}
            />
          ) : null}
        </More>
      </section>
    </>
  );
}

/** A white chevron row that opens in place. */
function More({
  icon,
  title,
  sub,
  onToggle,
  children,
}: {
  icon: ReactNode;
  title: string;
  sub: string;
  onToggle?: (open: boolean) => void;
  children: ReactNode;
}) {
  return (
    <details
      className={styles.moreItem}
      onToggle={(event) => onToggle?.(event.currentTarget.open)}
    >
      <summary>
        <span className={family.tile}>{icon}</span>
        <span className={family.rowText}>
          <span className={styles.moreTitle}>{title}</span>
          <span className={family.rowSub} data-wrap="">
            {sub}
          </span>
        </span>
        <ChevronRight className={styles.chevron} aria-hidden="true" />
      </summary>
      <div className={styles.moreBody}>{children}</div>
    </details>
  );
}
