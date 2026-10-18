"use client";

/**
 * Team: who takes new leads and why. Rules per seller (available, open-lead
 * cap, languages, areas, products) feed the allocation; managers see each
 * seller's load and today's calls, and switch on auto-reassign.
 */

import { RefreshCw, Users } from "lucide-react";
import { useEffect, useState } from "react";

import {
  Avatar,
  Badge,
  Button,
  Dialog,
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
  saveRep,
  saveSettings,
  saveWorkHours,
  splitList,
  type RepView,
  type Team,
} from "./leads-client";
import { phoneDot } from "./phone-setup-words";
import styles from "./leads.module.css";

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
}: {
  team: Team;
  onSaved: (team: Team) => void;
}) {
  const current = team.settings.work_hours ?? null;
  const [days, setDays] = useState<number[]>(
    current?.days ?? [0, 1, 2, 3, 4, 5],
  );
  const [start, setStart] = useState(current?.start ?? "09:30");
  const [end, setEnd] = useState(current?.end ?? "19:00");
  const [pause, setPause] = useState(current?.pause_leads ?? true);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async (clear = false) => {
    if (!clear && start >= end) {
      setNote("Work ends after it starts. Pick the hours again.");
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
      <div className={styles.form}>
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
        {note ? (
          <p className={styles.hint} role="status">
            {note}
          </p>
        ) : null}
      </div>
    </Panel>
  );
}

function RulesDialog({
  rep,
  onClose,
  onSaved,
}: {
  rep: RepView | null;
  onClose: () => void;
  onSaved: (team: Team) => void;
}) {
  // TeamView gives each opening a new key, so these start from this seller.
  const [available, setAvailable] = useState(rep?.available ?? true);
  const [cap, setCap] = useState(String(rep?.max_open ?? 50));
  const [languages, setLanguages] = useState(rep?.languages.join(", ") ?? "");
  const [areas, setAreas] = useState(rep?.areas.join(", ") ?? "");
  const [interests, setInterests] = useState(rep?.interests.join(", ") ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!rep) return;
    const max = Number(cap);
    if (!Number.isInteger(max) || max < 1 || max > 1000) {
      setError("Open-lead limit is a whole number from 1 to 1000.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      onSaved(
        await saveRep(rep, {
          available,
          max_open: max,
          languages: splitList(languages).slice(0, 12),
          areas: splitList(areas),
          interests: splitList(interests),
        }),
      );
    } catch (reason) {
      setError(
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={rep !== null}
      title={rep ? `${rep.name}'s lead rules` : "Lead rules"}
      description="Empty boxes mean no limit. New leads go to whoever fits and has the fewest open leads."
      onClose={onClose}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save rules"}
          </Button>
        </>
      }
    >
      <div className={styles.form}>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={available}
            onChange={(event) => setAvailable(event.target.checked)}
          />
          Takes new leads now
        </label>
        <Field label="Most open leads at once">
          <input
            inputMode="numeric"
            value={cap}
            onChange={(event) => setCap(event.target.value)}
          />
        </Field>
        <Field
          label="Languages"
          hint="Comma separated, e.g. Hindi, Marathi, English"
        >
          <input
            value={languages}
            onChange={(event) => setLanguages(event.target.value)}
          />
        </Field>
        <Field label="Areas" hint="Cities or regions this seller covers">
          <input
            value={areas}
            onChange={(event) => setAreas(event.target.value)}
          />
        </Field>
        <Field label="Products" hint="What this seller sells, as leads name it">
          <input
            value={interests}
            onChange={(event) => setInterests(event.target.value)}
          />
        </Field>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}

export function TeamView({
  onChanged,
}: {
  onChanged: () => void;
  onOpen: (leadId: string) => void;
}) {
  const [team, setTeam] = useState<Team | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<RepView | null>(null);
  const [editRound, setEditRound] = useState(0);
  const [minutes, setMinutes] = useState("10");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
    return () => controller.abort();
  }, []);

  if (error)
    return <Empty icon={Users} title="The team didn't load" text={error} />;
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
          value={team.first_call_minutes ?? "–"}
          unit={team.first_call_minutes != null ? "min" : undefined}
          note="Median time to first call, last 7 days"
        />
      </Tiles>

      <Panel title="Sellers" sub={`${team.reps.length}`}>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Seller</th>
                <th>Takes leads</th>
                <th>Phone</th>
                <th data-num>Open</th>
                <th data-num>Due now</th>
                <th data-num>Calls today</th>
                <th data-num>Connected</th>
                <th data-num>First call</th>
                <th>Rules (click a name to change)</th>
              </tr>
            </thead>
            <tbody>
              {team.reps.map((rep) => (
                <tr key={rep.person_id}>
                  <th scope="row">
                    <button
                      type="button"
                      className={styles.repName}
                      onClick={() => {
                        setEditRound((value) => value + 1);
                        setEditing(rep);
                      }}
                      aria-label={`Edit ${rep.name}'s lead rules`}
                    >
                      <Avatar name={rep.name} size={24} />
                      {rep.name}
                      {rep.role !== "member" ? <Badge>{rep.role}</Badge> : null}
                    </button>
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
                  <td data-num>
                    {rep.open_leads}
                    <small>/{rep.max_open}</small>
                  </td>
                  <td data-num>{rep.due_now}</td>
                  <td data-num>{rep.calls_today}</td>
                  <td data-num>{rep.connected_today}</td>
                  <td data-num>
                    {rep.first_call_minutes != null
                      ? `${rep.first_call_minutes} min`
                      : "–"}
                  </td>
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
      </Panel>

      <div className={styles.teamPair}>
        <Panel
          title="Auto-reassign"
          sub={team.settings.auto_reassign ? "on" : "off"}
        >
          <div className={styles.form}>
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
            <div className={styles.row}>
              <Button
                variant={team.settings.auto_reassign ? "secondary" : "primary"}
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
            {note ? (
              <p className={styles.hint} role="status">
                {note}
              </p>
            ) : null}
          </div>
        </Panel>
        <WorkHoursPanel
          key={`${team.settings.revision}`}
          team={team}
          onSaved={(next) => {
            setTeam(next);
            onChanged();
          }}
        />
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
                      style={{ width: `${total ? (count / total) * 100 : 0}%` }}
                    />
                  </span>
                  <span>{count}</span>
                </dd>
              </div>
            ))}
          </dl>
        </Panel>
      </div>

      <RulesDialog
        key={editRound}
        rep={editing}
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
