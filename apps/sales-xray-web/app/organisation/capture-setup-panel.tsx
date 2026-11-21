"use client";

/**
 * Team: who has set up call capture, and why not (owner, 30 Oct 2026: "the
 * organisation owner sees who hasn't set it up"). Owners, admins and managers;
 * the sellers who still need it come first. A seller's line never shows a phone
 * number, only the phone's model.
 */

import { ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";

import {
  readCaptureTeam,
  type CaptureRecording,
  type CaptureTeam,
  type CaptureTeamDevice,
  type CaptureTeamRow,
  type CaptureTeamState,
} from "../capture-setup/capture-setup-client";
import { openCaptureSetup } from "../capture-setup/capture-setup-gate";
import own from "../capture-setup/capture-setup.module.css";
import { named } from "../capture-setup/product-name";
import { inPhoneApp, setupStatus } from "../leads/native-phone";
import { Sheet } from "../ui/sheet";
import { useWorkspaceAccess } from "../workspace-access";
import { PersonDisplayName } from "./people/person-display-name";
import family from "./family.module.css";
import { Initials, Ring } from "./family";

// "Set up" is always something to do (Settings' Phone setup); a seller who has
// done it is Ready (phone personas ph1-38, 1 Nov 2026: the same words meant
// done here and an action there). Ready only while the phone records: never
// beside a red "Call recording off" (ph1-46).
const BADGE: Record<CaptureTeamState, string> = {
  set_up: "Ready",
  recording_off: "Recording off",
  phone_pending: "Phone not set up",
  declined: "Said not now",
  turned_off: "Turned off",
  consent_changed: "Asked again",
  not_started: "Not set up",
};

function day(at: string | null): string | null {
  if (!at) return null;
  const moment = new Date(at);
  return Number.isNaN(moment.getTime())
    ? null
    : moment.toLocaleDateString("en-IN", {
        day: "numeric",
        month: "short",
        timeZone: "Asia/Kolkata",
      });
}

const calls = (count: number) => (count === 1 ? "1 call" : `${count} calls`);

const RECORDING_FIX: Record<NonNullable<CaptureRecording["fix"]>, string> = {
  folder: "Allow folder",
  recorder: "Turn on call recording",
  test: "Place a test call",
};

/** How long ago, in Team's few words: "12 min ago", "3 h ago", "yesterday". */
function since(at: number, now: number): string {
  const minutes = Math.max(0, Math.floor((now - at) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h ago`;
  return minutes < 48 * 60
    ? "yesterday"
    : `on ${day(new Date(at).toISOString())}`;
}

/** The day, as a seller would say it: "Tue", or "28 Oct" further back. */
function dayName(at: number, now: number): string {
  return now - at < 6 * 86_400_000
    ? new Date(at).toLocaleDateString("en-IN", {
        weekday: "short",
        timeZone: "Asia/Kolkata",
      })
    : (day(new Date(at).toISOString()) ?? "");
}

/**
 * Recording on a seller's phone, in one line with its fix (competitor teardown
 * #7, 1 Nov 2026): "Recording OK · last file 12 min ago", "No recordings since
 * Tue · Turn on call recording", "No recordings folder · Allow folder".
 */
export function recordingLine(
  recording: CaptureRecording | null | undefined,
  now: number,
): string | null {
  const parts = recordingParts(recording, now);
  return parts ? [parts.what, parts.fix].filter(Boolean).join(" · ") : null;
}

/** The line's words, and its fix apart: the fix is a button (ph1-46: it was dead text). */
export function recordingParts(
  recording: CaptureRecording | null | undefined,
  now: number,
): { what: string; fix: string | null } | null {
  if (!recording) return null;
  const last = recording.last_at ? Date.parse(recording.last_at) : NaN;
  const fix = recording.fix ? RECORDING_FIX[recording.fix] : null;
  if (recording.state === "ok")
    return {
      what: Number.isFinite(last)
        ? `Recording OK · last file ${since(last, now)}`
        : "Recording OK",
      fix: null,
    };
  const what =
    recording.state === "off"
      ? recording.fix === "folder"
        ? "No recordings folder"
        : "Call recording off"
      : Number.isFinite(last)
        ? `No recordings since ${dayName(last, now)}`
        : "No call recording found yet";
  return { what, fix };
}

/** What a seller does on their own phone for each fix (Selling's Set up opens the check). */
const FIX_STEP: Record<NonNullable<CaptureRecording["fix"]>, string> = {
  folder: "Choose the recordings folder when Android asks.",
  recorder:
    "Turn on call recording in the Phone app, as the check shows for that phone.",
  test: "Place the 10-second test call the check asks for.",
};

/**
 * A recording line's fix, as a button (phone personas ph1-46, v1.25: "Turn on
 * call recording" was dead text). A seller's own row opens the recording check
 * on this phone; anyone else's says what that seller does on their phone.
 */
function RecordingFixButton({
  row,
  recording,
  label,
  mine,
}: {
  row: CaptureTeamRow;
  recording: CaptureRecording;
  label: string;
  mine: boolean;
}) {
  const [open, setOpen] = useState(false);
  const phone = recording.phone ?? row.phone ?? "their phone";
  return (
    <>
      <button
        type="button"
        className={own.fixLink}
        onClick={() => (mine ? openCaptureSetup("recordings") : setOpen(true))}
      >
        {label}
      </button>
      {mine ? null : (
        <Sheet
          open={open}
          onClose={() => setOpen(false)}
          title={`${label}: ${row.name}`}
        >
          <ol className={own.fixSteps}>
            <li>{`On ${phone}, open Sales X-Ray.`}</li>
            <li>Settings, Selling, Phone setup, then Set up.</li>
            {recording.fix ? <li>{FIX_STEP[recording.fix]}</li> : null}
          </ol>
          <p className={own.fixAfter}>
            This line reads Recording OK once a call&apos;s recording arrives.
          </p>
        </Sheet>
      )}
    </>
  );
}

/** The one line under a seller's name, with today's calls that have no recording
    and a phone with work-call logging off (the rule Connections uses, ph1-23). */
export function captureLine(row: CaptureTeamRow): string {
  return [
    row.missing_today
      ? `${calls(row.missing_today)} without a recording today`
      : null,
    row.call_log_off
      ? `Call logging off on ${row.call_log_off}: on that phone, Settings, Selling, Log work calls`
      : null,
    stateLine(row),
  ]
    .filter(Boolean)
    .join(" · ");
}

function stateLine(row: CaptureTeamRow): string {
  const on = day(row.at);
  // Every phone they finished on, not only the newest (ph1-46).
  const phones = row.phones?.length ? row.phones : row.phone ? [row.phone] : [];
  switch (row.state) {
    case "set_up":
    case "recording_off":
      return [...phones, on ? `since ${on}` : null].filter(Boolean).join(" · ");
    // The badge beside the name says the state ("Phone not set up", "Said not
    // now"); a sentence repeating it made Team a wall of text (owner, bug 183,
    // 6 Nov 2026). Only the day is added.
    case "phone_pending":
    case "not_started":
      return "";
    case "declined":
    case "turned_off":
      return on ? `on ${on}` : "";
    case "consent_changed":
      return "New terms to agree to";
  }
}

/** A state that needs someone to act: anything but a recording phone with logging on. */
export function needsAction(row: CaptureTeamRow): boolean {
  return row.state !== "set_up" || Boolean(row.call_log_off);
}

/** The chip's colour: red for a phone that doesn't record, amber for set up to do. */
const TONE: Record<CaptureTeamState, string | undefined> = {
  set_up: "good",
  recording_off: "red",
  phone_pending: "amber",
  not_started: "amber",
  consent_changed: "amber",
  declined: undefined,
  turned_off: undefined,
};

export function captureBadge(row: CaptureTeamRow): {
  label: string;
  tone?: string;
} {
  return { label: BADGE[row.state], tone: TONE[row.state] };
}

/** The team's capture list, read once (Team's hero and Sellers' phones). */
export function useCaptureTeam(on = true): {
  team: CaptureTeam | null;
  failed: boolean;
} {
  const [team, setTeam] = useState<CaptureTeam | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!on) return;
    const controller = new AbortController();
    readCaptureTeam(controller.signal).then(setTeam, () => {
      if (!controller.signal.aborted) setFailed(true);
    });
    return () => controller.abort();
  }, [on]);
  return { team, failed };
}

const firstName = (name: string) => name.trim().split(/\s+/)[0] || name;

/**
 * What each seller who still needs it does on their own phone, in a sheet
 * (there is no link to send: the steps are said plainly). Your own row opens
 * the setup on this phone instead.
 */
export function SetupStepsSheet({
  rows,
  open,
  onClose,
}: {
  rows: readonly CaptureTeamRow[];
  open: boolean;
  onClose: () => void;
}) {
  const title =
    rows.length === 1
      ? `Help ${firstName(rows[0].name)} set up`
      : `Help ${rows.length} people set up`;
  return (
    <Sheet open={open} onClose={onClose} title={title} wide="center">
      <div className={family.sheetForm}>
        {rows.length > 1 ? (
          <p className={family.note}>
            {rows.map((row) => firstName(row.name)).join(", ")} each do this on
            their own phone.
          </p>
        ) : null}
        <ol className={family.steps}>
          <li>
            On {rows.length === 1 ? `${firstName(rows[0].name)}'s` : "their"}{" "}
            phone, open Sales X-Ray.
          </li>
          <li>Settings, Selling, Phone setup, then Set up.</li>
          <li>Allow call recording and place the 10-second test call.</li>
        </ol>
        <p className={family.hint}>
          Their line here reads Ready once a call&apos;s recording arrives.
        </p>
      </div>
    </Sheet>
  );
}

export function CaptureSetupPanel() {
  const me = useWorkspaceAccess()?.context?.personId ?? null;
  const { team, failed } = useCaptureTeam();
  const [now] = useState(() => Date.now());
  // This phone's install, in the phone app: its own fix opens here.
  const [here, setHere] = useState<string | null>(null);
  const [helping, setHelping] = useState<readonly CaptureTeamRow[] | null>(
    null,
  );
  const [shownHelp, setShownHelp] = useState(helping);
  if (helping && helping !== shownHelp) setShownHelp(helping);

  useEffect(() => {
    if (!inPhoneApp()) return;
    let live = true;
    void setupStatus().then(
      (status) => {
        if (live) setHere(status?.device ?? null);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, []);

  const rows = team?.people ?? null;
  if (failed || (rows && !rows.length)) return null;
  const waiting = rows?.filter(needsAction) ?? [];
  const ready = rows?.filter((row) => !needsAction(row)) ?? [];
  const missing = rows?.filter((row) => row.state !== "set_up").length ?? 0;
  // Never "Everyone is set up" while Connections names a phone (ph1-23).
  const logOff = rows?.filter((row) => row.call_log_off).length ?? 0;
  // Owner, 30 Oct 2026 (fix 5): "calls without recordings today".
  const unrecorded = team?.missingToday ?? 0;
  const others = waiting.filter((row) => row.person_id !== me);
  const mine = waiting.find((row) => row.person_id === me) ?? null;
  const summary = !rows
    ? "Checking…"
    : [
        missing
          ? `${missing} ${missing === 1 ? "phone needs" : "phones need"} your action`
          : logOff
            ? `Call logging off on ${logOff === 1 ? "1 phone" : `${logOff} phones`}`
            : "Everyone is set up",
        unrecorded ? `${calls(unrecorded)} without a recording today` : null,
      ]
        .filter(Boolean)
        .join(" · ");

  const renderRow = (row: CaptureTeamRow) => {
    // Each phone's own recording line (ph1-55, ph1-46); an older server's
    // one line for the seller otherwise.
    const lines: readonly CaptureTeamDevice[] = row.devices?.length
      ? row.devices
      : row.recording
        ? [
            {
              device: null,
              name: row.recording.phone ?? row.phone ?? "Phone",
              recording: row.recording,
              call_log_off: false,
            },
          ]
        : [];
    const several = lines.length > 1 || (row.phones?.length ?? 0) > 1;
    const badge = captureBadge(row);
    const hasFix = lines.some((line) => line.recording?.fix);
    const isMe = row.person_id === me;
    // A row with nothing inline to tap opens its steps (or, your own, the
    // setup on this phone): the whole row, with a chevron.
    const opens = needsAction(row) && !hasFix && row.state !== "set_up";
    const body = (
      <>
        <Initials name={row.name} id={row.person_id} />
        <span className={family.rowText}>
          <strong className={family.rowTitle}>
            <PersonDisplayName name={row.name} />
          </strong>
          {captureLine(row) ? (
            <small className={family.rowSub} data-wrap="">
              {named(captureLine(row))}
            </small>
          ) : null}
          {lines.map((line, at) => {
            const parts = recordingParts(line.recording, now);
            if (!line.recording || !parts) return null;
            return (
              <small
                key={line.device ?? at}
                className={`${own.recording} ${family.rowSub}`}
                data-wrap=""
                data-state={line.recording.state}
              >
                {/* One run of words, so the fix flows with them. */}
                <span>
                  {several ? `${line.name}: ` : ""}
                  {parts.what}
                  {parts.fix ? (
                    <>
                      {" · "}
                      <RecordingFixButton
                        row={row}
                        recording={{ ...line.recording, phone: line.name }}
                        label={parts.fix}
                        // This phone's own fix opens here; another phone's
                        // steps are said in a sheet.
                        mine={
                          isMe &&
                          (lines.length === 1 ||
                            (line.device !== null && line.device === here))
                        }
                      />
                    </>
                  ) : null}
                </span>
              </small>
            );
          })}
        </span>
        <span className={family.rowEnd}>
          <span
            className={family.chip}
            data-tone={badge.tone}
            data-state={row.state}
          >
            {badge.label}
          </span>
          {opens ? (
            <ChevronRight className={family.chevron} aria-hidden="true" />
          ) : null}
        </span>
      </>
    );
    return (
      <li key={row.person_id}>
        {opens ? (
          <button
            type="button"
            className={`${family.row} ${family.personRow}`}
            aria-label={`${row.name}: ${badge.label}. ${isMe ? "Set up my phone" : "Show the steps"}`}
            onClick={() => (isMe ? openCaptureSetup() : setHelping([row]))}
          >
            {body}
          </button>
        ) : (
          <div className={`${family.row} ${family.personRow}`}>{body}</div>
        )}
      </li>
    );
  };

  return (
    <section className={family.stack} aria-labelledby="org-capture-setup">
      <div
        className={family.hero}
        data-tone={rows && waiting.length ? "amber" : undefined}
      >
        <Ring
          done={rows ? rows.length - missing : 0}
          total={rows?.length ?? 0}
          label={
            rows
              ? `${rows.length - missing} of ${rows.length} phones ready`
              : "Checking"
          }
        >
          <b>{rows ? `${rows.length - missing} of ${rows.length}` : "…"}</b>
          <small>ready</small>
        </Ring>
        <div className={family.heroBody}>
          <h2 id="org-capture-setup" className={family.heroTitle}>
            {!rows
              ? "Checking phones…"
              : waiting.length
                ? `${rows.length - missing} of ${rows.length} phones ready`
                : "Every phone is ready"}
          </h2>
          <p className={family.heroLine}>{summary}</p>
          {mine || others.length ? (
            <div className={family.heroActions}>
              {others.length ? (
                <button
                  type="button"
                  className={family.primary}
                  onClick={() => setHelping(others)}
                >
                  {others.length === 1
                    ? `Help ${firstName(others[0].name)} set up`
                    : `Help ${others.length} people set up`}
                </button>
              ) : (
                <button
                  type="button"
                  className={family.primary}
                  onClick={() => openCaptureSetup()}
                >
                  Set up my phone
                </button>
              )}
            </div>
          ) : null}
        </div>
      </div>

      <div className={family.card}>
        {!rows ? (
          <span className={family.skeleton} />
        ) : (
          <>
            {waiting.length ? (
              <>
                <h3 className={family.sectionLabel}>
                  Needs action ({waiting.length})
                </h3>
                <ul
                  className={family.plainList}
                  aria-label="Phones that need action"
                >
                  {waiting.map(renderRow)}
                </ul>
              </>
            ) : null}
            {ready.length ? (
              <>
                <h3 className={family.sectionLabel}>Ready ({ready.length})</h3>
                <ul className={family.plainList} aria-label="Phones ready">
                  {ready.map(renderRow)}
                </ul>
              </>
            ) : null}
          </>
        )}
      </div>
      <SetupStepsSheet
        rows={shownHelp ?? []}
        open={helping !== null}
        onClose={() => setHelping(null)}
      />
    </section>
  );
}
