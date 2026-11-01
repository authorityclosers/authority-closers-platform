"use client";

/**
 * Team: who has set up call capture, and why not (owner, 30 Oct 2026: "the
 * organisation owner sees who hasn't set it up"). Owners, admins and managers;
 * the sellers who still need it come first. A seller's line never shows a phone
 * number, only the phone's model.
 */

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
import styles from "./seats.module.css";

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
    case "phone_pending":
      return "Agreed, but hasn't opened the app on a phone yet";
    case "declined":
      return on ? `Said not now on ${on}. Asked again daily.` : "Said not now";
    case "turned_off":
      return on
        ? `Turned call capture off on ${on}`
        : "Turned call capture off";
    case "consent_changed":
      return "The terms changed: needs to agree again";
    case "not_started":
      return "Sees the setup the next time they open Sales X-Ray";
  }
}

export function CaptureSetupPanel() {
  const me = useWorkspaceAccess()?.context?.personId ?? null;
  const [team, setTeam] = useState<CaptureTeam | null>(null);
  const [failed, setFailed] = useState(false);
  const [now] = useState(() => Date.now());
  // This phone's install, in the phone app: its own fix opens here.
  const [here, setHere] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    readCaptureTeam(controller.signal).then(setTeam, () => {
      if (!controller.signal.aborted) setFailed(true);
    });
    if (inPhoneApp())
      void setupStatus().then(
        (status) => {
          if (!controller.signal.aborted) setHere(status?.device ?? null);
        },
        () => undefined,
      );
    return () => controller.abort();
  }, []);

  const rows = team?.people ?? null;
  if (failed || (rows && !rows.length)) return null;
  const missing = rows?.filter((row) => row.state !== "set_up").length ?? 0;
  // Never "Everyone is set up" while Connections names a phone (ph1-23).
  const logOff = rows?.filter((row) => row.call_log_off).length ?? 0;
  // Owner, 30 Oct 2026 (fix 5): "calls without recordings today".
  const unrecorded = team?.missingToday ?? 0;
  return (
    <section className={styles.section} aria-labelledby="org-capture-setup">
      <div className={styles.head}>
        <h2 id="org-capture-setup" className={styles.title}>
          Call capture
        </h2>
        <span className={styles.summary}>
          {!rows
            ? "Checking…"
            : [
                missing
                  ? `${missing} of ${rows.length} not set up`
                  : logOff
                    ? `Call logging off on ${logOff === 1 ? "1 phone" : `${logOff} phones`}`
                    : "Everyone is set up",
                unrecorded
                  ? `${calls(unrecorded)} without a recording today`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
        </span>
      </div>
      <div className={styles.card} data-list="">
        {!rows ? (
          <span className={styles.skeletonLine} />
        ) : (
          <ul className={own.team} aria-label="Call capture, not set up first">
            {rows.map((row) => {
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
              return (
                <li key={row.person_id}>
                  <span>
                    <strong>
                      <PersonDisplayName name={row.name} />
                    </strong>
                    <small>{named(captureLine(row))}</small>
                    {lines.map((line, at) => {
                      const parts = recordingParts(line.recording, now);
                      if (!line.recording || !parts) return null;
                      return (
                        <small
                          key={line.device ?? at}
                          className={own.recording}
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
                                  recording={{
                                    ...line.recording,
                                    phone: line.name,
                                  }}
                                  label={parts.fix}
                                  // This phone's own fix opens here; another phone's
                                  // steps are said in a sheet.
                                  mine={
                                    row.person_id === me &&
                                    (lines.length === 1 ||
                                      (line.device !== null &&
                                        line.device === here))
                                  }
                                />
                              </>
                            ) : null}
                          </span>
                        </small>
                      );
                    })}
                  </span>
                  <span className={own.badge} data-state={row.state}>
                    {BADGE[row.state]}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
