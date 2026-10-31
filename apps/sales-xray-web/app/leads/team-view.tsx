"use client";

/**
 * Team: who takes new leads and why. Rules per seller (available, open-lead
 * cap, languages, areas, products) feed the allocation; managers see each
 * seller's load and today's calls, and switch on auto-reassign.
 */

import { RefreshCw, SlidersHorizontal, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  Avatar,
  Badge,
  Button,
  Card,
  Empty,
  Field,
  Kpi,
  Panel,
  Skeleton,
  Tiles,
} from "../ui/kit";
import {
  LeadsError,
  readTeam,
  runSweep,
  saveSettings,
  saveWorkHours,
  waitWords,
  type RepView,
  type Team,
} from "./leads-client";
import {
  LEVEL_NAMES,
  levelFor,
  readCallAi,
  type CallAiSettings,
} from "../call-ai/call-ai-client";
import { notify } from "../notice-center";
import { CaptureRates } from "../capture-guard/capture-rates";
import { CallsReport } from "./calls-report";
import { AdSpendPanel } from "./ad-spend";
import { SlaPanel } from "./sla-panel";
import {
  LIMIT_RULE,
  LimitField,
  limitDraft,
  openWords,
  readLimit,
} from "./limit-field";
import { phoneDot } from "./phone-setup-words";
import { SellerSheet } from "./seller-sheet";
import { RoutingRules } from "./routing-rules";
import { can } from "../organisation/roles";
import { useWorkspaceAccess } from "../workspace-access";
import styles from "./leads.module.css";

/**
 * Whether this person may change the team's rules (leads.manage). A Viewer
 * reads the team and changes nothing (Roles B, 27 Oct 2026), so the page is
 * read-only for them; the server refuses their saves anyway. Unknown (no
 * workspace list yet, or a page drawn without one) stays editable.
 */
export function useCanEditTeam(): boolean {
  const access = useWorkspaceAccess();
  const role = access?.workspaces?.find(
    (item) => item.tenant_id === access.context?.tenantId,
  )?.role;
  return role === undefined || can(role, "leads.manage");
}

const STAGE_ORDER = [
  "new",
  "not_connected",
  "follow_up",
  "interested",
  "won",
  "lost",
];
const STAGE_NAMES: Record<string, string> = {
  new: "New",
  not_connected: "Not connected",
  follow_up: "Follow-up",
  interested: "Interested",
  won: "Won",
  lost: "Lost",
};
const SOURCE_NAMES: Record<string, string> = {
  manual: "Added by hand",
  referral: "Referral",
  csv: "File upload",
  sheet: "Google Sheet",
  webhook: "Website form",
  meta: "Meta lead form",
  synthetic: "Test data",
};

/** The seller's phone (UX study item 7): a dot, a few words, and what is left in its title. */
export function PhoneCell({ rep }: { rep: RepView }) {
  const dot = phoneDot(rep.phone);
  const missing = dot.missing.length ? `To do: ${dot.missing.join(", ")}` : "";
  return (
    <span
      className={styles.phoneDot}
      data-tone={dot.tone}
      title={missing || undefined}
    >
      {dot.label}
      {missing ? <span className={styles.srOnly}>. {missing}</span> : null}
    </span>
  );
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** The team's work hours (Salestrail's business hours), India time. */
export function WorkHoursPanel({
  team,
  onSaved,
  readOnly = false,
}: {
  team: Team;
  onSaved: (team: Team) => void;
  /** A Viewer sees the hours and changes nothing. */
  readOnly?: boolean;
}) {
  const current = team.settings.work_hours ?? null;
  const [days, setDays] = useState<number[]>(
    current?.days ?? [0, 1, 2, 3, 4, 5],
  );
  const [start, setStart] = useState(current?.start ?? "09:30");
  const [end, setEnd] = useState(current?.end ?? "19:00");
  const [pause, setPause] = useState(current?.pause_leads ?? true);
  // One set break (lunch): a gap between calls there isn't red on Home.
  const [lunch, setLunch] = useState(current?.breaks?.[0] ?? null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async (clear = false) => {
    if (!clear && start >= end) {
      setNote("Work ends after it starts. Pick the hours again.");
      return;
    }
    if (
      !clear &&
      lunch &&
      !(start <= lunch.start && lunch.start < lunch.end && lunch.end <= end)
    ) {
      setNote("The break sits inside work hours. Pick its time again.");
      return;
    }
    setBusy(true);
    setNote(null);
    try {
      onSaved(
        await saveWorkHours(team.settings.revision, {
          days: clear ? [] : days,
          start,
          end,
          pause_leads: pause,
          breaks: lunch ? [lunch] : [],
        }),
      );
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="Work hours"
      sub={
        current
          ? current.inside
            ? "working now"
            : "after hours now"
          : "not set"
      }
    >
      <fieldset className={styles.form} disabled={readOnly}>
        <p className={styles.hint}>
          India time. Calls outside these hours stay on the seller&apos;s phone
          and are never logged.
        </p>
        <div className={styles.chips} role="group" aria-label="Work days">
          {DAYS.map((label, day) => (
            <button
              key={label}
              type="button"
              className={styles.chip}
              aria-pressed={days.includes(day)}
              onClick={() =>
                setDays((now) =>
                  now.includes(day)
                    ? now.filter((item) => item !== day)
                    : [...now, day].sort(),
                )
              }
            >
              {label}
            </button>
          ))}
        </div>
        <div className={styles.row}>
          <Field label="Starts">
            <input
              type="time"
              value={start}
              onChange={(event) => setStart(event.target.value)}
            />
          </Field>
          <Field label="Ends">
            <input
              type="time"
              value={end}
              onChange={(event) => setEnd(event.target.value)}
            />
          </Field>
        </div>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={pause}
            onChange={(event) => setPause(event.target.checked)}
          />
          New leads wait outside work hours, then go out when work starts
        </label>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={lunch !== null}
            onChange={(event) =>
              setLunch(
                event.target.checked ? { start: "13:00", end: "14:00" } : null,
              )
            }
          />
          A set break every work day (lunch): not counted against sellers
        </label>
        {lunch ? (
          <div className={styles.row}>
            <Field label="Break starts">
              <input
                type="time"
                value={lunch.start}
                onChange={(event) =>
                  setLunch({ ...lunch, start: event.target.value })
                }
              />
            </Field>
            <Field label="Break ends">
              <input
                type="time"
                value={lunch.end}
                onChange={(event) =>
                  setLunch({ ...lunch, end: event.target.value })
                }
              />
            </Field>
          </div>
        ) : null}
        {readOnly ? null : (
          <div className={styles.row}>
            <Button
              variant="primary"
              disabled={busy || days.length === 0}
              onClick={() => void save()}
            >
              Save work hours
            </Button>
            {current ? (
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => void save(true)}
              >
                Clear
              </Button>
            ) : null}
          </div>
        )}
        {note ? (
          <p className={styles.hint} role="status">
            {note}
          </p>
        ) : null}
      </fieldset>
    </Panel>
  );
}

/** The seller's AI on calls level; "default" when it is the organisation's. */
function AiCell({ callAi, rep }: { callAi: CallAiSettings; rep: RepView }) {
  const { level, own } = levelFor(callAi, rep.person_id);
  return (
    <td>
      <Badge
        tone={level === "full" ? "good" : level === "off" ? "warn" : "neutral"}
      >
        {LEVEL_NAMES[level]}
      </Badge>
      {own ? null : <small className={styles.hint}> default</small>}
    </td>
  );
}

export function TeamView({
  onChanged,
  onOpen,
  rulesOnly = false,
}: {
  onChanged: () => void;
  onOpen: (leadId: string) => void;
  /**
   * Settings → Lead rules (owner #38, 27 Oct 2026: "Lead rules shows this
   * dashboard again, and why?"): only the rules. Who takes new leads and
   * their limits, auto-reassign, limits and work hours; the team's numbers,
   * calls, response times and ad spend stay on Leads → Team.
   */
  rulesOnly?: boolean;
}) {
  const [team, setTeam] = useState<Team | null>(null);
  const [callAi, setCallAi] = useState<CallAiSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<RepView | null>(null);
  const [editRound, setEditRound] = useState(0);
  const [minutes, setMinutes] = useState("10");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canEdit = useCanEditTeam();

  const load = (signal?: AbortSignal) =>
    readTeam(signal)
      .then((next) => {
        setTeam(next);
        setMinutes(String(next.settings.reassign_minutes));
      })
      .catch((reason: unknown) => {
        if (signal?.aborted) return;
        setError(
          reason instanceof LeadsError
            ? reason.message
            : "The team didn't load.",
        );
      });

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    // AI on calls is its own read: if it fails, the team still shows without it.
    readCallAi(controller.signal)
      .then(setCallAi)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  if (error)
    return (
      <Empty
        icon={Users}
        title="The team didn't load"
        text={error}
        action={{
          label: "Try again",
          onClick: () => {
            setError(null);
            void load();
          },
        }}
      />
    );
  if (!team)
    return (
      <div
        className={styles.listSkeleton}
        aria-busy="true"
        aria-label="Loading the team"
      >
        <Skeleton height={86} />
        <Skeleton height={240} />
      </div>
    );

  const total = Object.values(team.by_stage).reduce(
    (sum, value) => sum + value,
    0,
  );
  const saveAuto = async (auto: boolean) => {
    const value = Number(minutes);
    if (!Number.isInteger(value) || value < 5 || value > 1440) {
      setNote("Pick between 5 and 1440 minutes.");
      return;
    }
    setBusy(true);
    setNote(null);
    try {
      const next = await saveSettings(team.settings.revision, {
        auto_reassign: auto,
        reassign_minutes: value,
      });
      setTeam(next);
      setNote(
        auto
          ? `On: new leads move after ${value} minutes without a call.`
          : "Off.",
      );
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };
  const sweep = async () => {
    setBusy(true);
    try {
      const { moved } = await runSweep();
      setNote(
        moved
          ? `Moved ${moved} lead${moved === 1 ? "" : "s"} nobody called in time.`
          : "Nothing to move.",
      );
      await load();
      onChanged();
    } catch (reason) {
      setNote(
        reason instanceof LeadsError
          ? reason.message
          : "Didn't run. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.teamGrid}>
      {canEdit ? null : (
        <p className={styles.hint} role="note">
          You can see the team. Owners, admins and managers change its rules.
        </p>
      )}
      {/* Who gets which leads, first: the routing rules (Lead OS, 27 Oct 2026). */}
      {rulesOnly && canEdit ? <RoutingRules /> : null}
      {rulesOnly ? null : (
        <Tiles label="Team leads">
          <Kpi
            label="All leads"
            value={total}
            note={`${team.waiting_first_call} waiting for a first call`}
          />
          <Kpi
            label="No owner"
            tone={team.unassigned ? "bad" : undefined}
            value={team.unassigned}
            note="Nobody fit the rules"
          />
          <Kpi label="Won" tone="good" value={team.by_stage.won ?? 0} />
          <Kpi
            label="First call"
            value={
              team.first_call_minutes != null
                ? waitWords(team.first_call_minutes)
                : "–"
            }
            note="Median time to first call, last 7 days"
          />
        </Tiles>
      )}

      <Panel
        title={rulesOnly ? "Who takes new leads" : "Sellers"}
        sub={`${team.reps.length}`}
      >
        <div className={styles.tableWrap} data-has-cards="">
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Seller</th>
                <th>Takes leads</th>
                <th>Phone</th>
                {callAi ? <th>AI on calls</th> : null}
                <th data-num>Open</th>
                {rulesOnly ? null : (
                  <>
                    <th data-num>Due now</th>
                    <th data-num>Calls today</th>
                    <th data-num>Connected</th>
                    <th data-num>First call</th>
                  </>
                )}
                <th>Rules</th>
              </tr>
            </thead>
            <tbody>
              {team.reps.map((rep) => (
                <tr key={rep.person_id}>
                  <th scope="row">
                    <span className={styles.repCell}>
                      {/* The name opens the seller's profile (owner, 21 Oct 2026). */}
                      <Link
                        className={styles.repName}
                        href={`/organisation/people/${encodeURIComponent(rep.person_id)}`}
                      >
                        <Avatar name={rep.name} size={24} />
                        {rep.name}
                        {rep.role !== "member" ? (
                          <Badge>{rep.role}</Badge>
                        ) : null}
                      </Link>
                      {canEdit ? (
                        <button
                          type="button"
                          className={styles.repRules}
                          onClick={() => {
                            setEditRound((value) => value + 1);
                            setEditing(rep);
                          }}
                          aria-label={`Edit ${rep.name}'s lead rules`}
                          title="Lead rules"
                        >
                          <SlidersHorizontal size={14} aria-hidden="true" />
                        </button>
                      ) : null}
                    </span>
                  </th>
                  <td>
                    {rep.available ? (
                      <Badge tone="good">Yes</Badge>
                    ) : (
                      <Badge>Away</Badge>
                    )}
                  </td>
                  <td>
                    <PhoneCell rep={rep} />
                  </td>
                  {callAi ? <AiCell callAi={callAi} rep={rep} /> : null}
                  <td data-num>
                    {rep.open_leads}
                    {rep.max_open === null ? null : (
                      <small>/{rep.max_open}</small>
                    )}
                  </td>
                  {rulesOnly ? null : (
                    <>
                      <td data-num>{rep.due_now}</td>
                      <td data-num>{rep.calls_today}</td>
                      <td data-num>{rep.connected_today}</td>
                      <td data-num>
                        {rep.first_call_minutes != null
                          ? waitWords(rep.first_call_minutes)
                          : "–"}
                      </td>
                    </>
                  )}
                  <td className={styles.rules}>
                    {[...rep.languages, ...rep.areas, ...rep.interests].length
                      ? [
                          rep.languages.join(", "),
                          rep.areas.join(", "),
                          rep.interests.slice(0, 3).join(", "),
                        ]
                          .filter(Boolean)
                          .join(" · ")
                      : "No limits"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {/* Phones: one seller in two lines, never a table to scroll sideways
            (house rule; Settings → Lead rules, 22 Oct 2026). */}
        <div className={styles.repCards} role="list" aria-label="Sellers">
          {team.reps.map((rep) => (
            <Card key={rep.person_id}>
              <span className={styles.repCardHead}>
                <Link
                  className={styles.repName}
                  href={`/organisation/people/${encodeURIComponent(rep.person_id)}`}
                >
                  <Avatar name={rep.name} size={24} />
                  {rep.name}
                </Link>
                {rep.available ? (
                  <Badge tone="good">Takes leads</Badge>
                ) : (
                  <Badge>Away</Badge>
                )}
                {canEdit ? (
                  <button
                    type="button"
                    className={styles.repRules}
                    onClick={() => {
                      setEditRound((value) => value + 1);
                      setEditing(rep);
                    }}
                    aria-label={`Edit ${rep.name}'s lead rules`}
                    title="Lead rules"
                  >
                    <SlidersHorizontal size={14} aria-hidden="true" />
                  </button>
                ) : null}
              </span>
              <span>
                {rulesOnly
                  ? `${openWords(rep.open_leads, rep.max_open)} open`
                  : `${openWords(rep.open_leads, rep.max_open)} open · ${rep.due_now} due · ${rep.calls_today} ${rep.calls_today === 1 ? "call" : "calls"} today · ${rep.connected_today} connected`}
                {!rulesOnly && rep.first_call_minutes != null
                  ? ` · first call ${waitWords(rep.first_call_minutes)}`
                  : ""}
              </span>
              <span>
                {[...rep.languages, ...rep.areas, ...rep.interests].length
                  ? [
                      rep.languages.join(", "),
                      rep.areas.join(", "),
                      rep.interests.slice(0, 3).join(", "),
                    ]
                      .filter(Boolean)
                      .join(" · ")
                  : "No limits"}
              </span>
            </Card>
          ))}
        </div>
      </Panel>

      {rulesOnly ? null : (
        <>
          <CaptureRates />
          <CallsReport />

          <SlaPanel onOpen={onOpen} readOnly={!canEdit} />

          <AdSpendPanel />
        </>
      )}

      <div className={styles.teamPair}>
        <Panel
          title="Auto-reassign"
          sub={team.settings.auto_reassign ? "on" : "off"}
        >
          <fieldset className={styles.form} disabled={!canEdit}>
            <p className={styles.hint}>
              When a new lead isn&apos;t called within the time below, it moves
              to the next best seller. Test leads never move.
            </p>
            <Field label="Minutes before it moves">
              <input
                inputMode="numeric"
                value={minutes}
                onChange={(event) => setMinutes(event.target.value)}
              />
            </Field>
            {canEdit ? (
              <div className={styles.row}>
                <Button
                  variant={
                    team.settings.auto_reassign ? "secondary" : "primary"
                  }
                  disabled={busy}
                  onClick={() => saveAuto(!team.settings.auto_reassign)}
                >
                  {team.settings.auto_reassign ? "Turn off" : "Turn on"}
                </Button>
                {team.settings.auto_reassign ? (
                  <Button variant="ghost" disabled={busy} onClick={sweep}>
                    <RefreshCw size={14} aria-hidden="true" />
                    Check now
                  </Button>
                ) : null}
              </div>
            ) : null}
            {note ? (
              <p className={styles.hint} role="status">
                {note}
              </p>
            ) : null}
          </fieldset>
        </Panel>
        <ListsPanel
          key={`lists-${team.settings.revision}`}
          readOnly={!canEdit}
          team={team}
          onSaved={(next) => {
            setTeam(next);
            onChanged();
          }}
        />
        {team.settings.strict_language === undefined ? null : (
          <LanguagesPanel
            readOnly={!canEdit}
            team={team}
            onSaved={(next) => {
              setTeam(next);
              onChanged();
            }}
          />
        )}
        <WorkHoursPanel
          key={`${team.settings.revision}`}
          readOnly={!canEdit}
          team={team}
          onSaved={(next) => {
            setTeam(next);
            onChanged();
          }}
        />
        {rulesOnly ? null : (
          <Panel title="Where leads stand">
            <dl className={styles.bars}>
              {STAGE_ORDER.map((stage) => (
                <div key={stage}>
                  <dt>{STAGE_NAMES[stage]}</dt>
                  <dd>
                    <span className={styles.bar}>
                      <i
                        style={{
                          width: `${total ? ((team.by_stage[stage] ?? 0) / total) * 100 : 0}%`,
                        }}
                      />
                    </span>
                    <span>{team.by_stage[stage] ?? 0}</span>
                  </dd>
                </div>
              ))}
            </dl>
            <dl className={styles.bars}>
              {Object.entries(team.by_source).map(([source, count]) => (
                <div key={source}>
                  <dt>{SOURCE_NAMES[source] ?? source}</dt>
                  <dd>
                    <span className={styles.bar}>
                      <i
                        style={{
                          width: `${total ? (count / total) * 100 : 0}%`,
                        }}
                      />
                    </span>
                    <span>{count}</span>
                  </dd>
                </div>
              ))}
            </dl>
          </Panel>
        )}
      </div>

      <SellerSheet
        key={editRound}
        rep={editing}
        callAi={callAi}
        onCallAiSaved={setCallAi}
        onClose={() => setEditing(null)}
        onSaved={(next) => {
          setTeam(next);
          setEditing(null);
          onChanged();
        }}
      />
    </div>
  );
}

/**
 * Languages (Lead OS, 27 Oct 2026): a seller's languages are a preference, so
 * a lead nobody free speaks to still goes to someone; strict, it waits for a
 * manager to give it out. Saves at once, like auto-reassign.
 */
function LanguagesPanel({
  team,
  onSaved,
  readOnly = false,
}: {
  team: Team;
  onSaved: (team: Team) => void;
  readOnly?: boolean;
}) {
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const strict = team.settings.strict_language === true;
  const save = async (next: boolean) => {
    setBusy(true);
    setNote(null);
    try {
      onSaved(
        await saveSettings(team.settings.revision, {
          auto_reassign: team.settings.auto_reassign,
          reassign_minutes: team.settings.reassign_minutes,
          strict_language: next,
        }),
      );
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel title="Languages" sub={strict ? "strict" : "preferred"}>
      <div className={styles.form}>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={strict}
            disabled={busy || readOnly}
            onChange={(event) => void save(event.target.checked)}
          />
          Only sellers who speak the lead&apos;s language
        </label>
        <p className={styles.hint}>
          {strict
            ? "If nobody free speaks it, the lead waits for a manager to give it out."
            : "Languages are a preference. If nobody free speaks it, the lead still goes to someone."}
        </p>
        {note ? (
          <p className={styles.hint} role="status">
            {note}
          </p>
        ) : null}
      </div>
    </Panel>
  );
}

/**
 * Limits and phone numbers for the whole team (owner, 25 Oct 2026): the
 * open-lead limit of sellers with no rules of their own, and whether lists
 * show whole phone numbers.
 */
function ListsPanel({
  team,
  onSaved,
  readOnly = false,
}: {
  team: Team;
  onSaved: (team: Team) => void;
  readOnly?: boolean;
}) {
  const [draft, setDraft] = useState(() =>
    limitDraft(team.settings.default_max_open),
  );
  const [full, setFull] = useState(team.settings.show_full_phones === true);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    const max = readLimit(draft);
    if (max === undefined) {
      setNote(LIMIT_RULE);
      return;
    }
    setBusy(true);
    setNote(null);
    try {
      onSaved(
        await saveSettings(team.settings.revision, {
          auto_reassign: team.settings.auto_reassign,
          reassign_minutes: team.settings.reassign_minutes,
          default_max_open: max,
          show_full_phones: full,
        }),
      );
      notify({
        id: "lead-limits",
        tone: "success",
        title: "Limits and phone numbers saved",
        timeout: 3000,
      });
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel title="Limits and phone numbers">
      <fieldset className={styles.form} disabled={readOnly}>
        <LimitField
          id="limit-new-sellers"
          label="Open-lead limit for new sellers"
          hint="Sellers without rules of their own use this."
          draft={draft}
          onChange={setDraft}
        />
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={full}
            onChange={(event) => setFull(event.target.checked)}
          />
          Always show full phone numbers
        </label>
        <p className={styles.hint}>
          Off, lists show a number&apos;s last four digits.
        </p>
        {readOnly ? null : (
          <div className={styles.row}>
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => void save()}
            >
              {busy ? "Saving…" : "Save"}
            </Button>
          </div>
        )}
        {note ? (
          <p className={styles.hint} role="status">
            {note}
          </p>
        ) : null}
      </fieldset>
    </Panel>
  );
}
