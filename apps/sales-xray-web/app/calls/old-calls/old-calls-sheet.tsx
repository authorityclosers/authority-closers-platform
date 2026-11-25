"use client";

/**
 * Find my old calls, the sheet (owner, 20 Nov 2026; board ~/orch/boards/
 * old-calls, option C "Summary first"): the phone looks back 14 days, then
 * - with "Analyse my calls automatically" on, the sure and likely matches go
 *   up by themselves, one at a time, with a calm list and Stop;
 * - otherwise one choice: Analyse all, Pick calls or Not now, the recording
 *   terms box unticked and nothing picked for the seller.
 * A time-only match goes up only on the seller's own tap. Recordings the
 * phone couldn't place can be put on a lead, or set aside. Each upload joins
 * its call's own row (the same attempt each time), so a retry never saves a
 * call twice. Every step is counted in sx.old_calls, never a name or number.
 */

import { CheckCircle2, FileAudio, Search } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { UploadPolicy } from "../../acquisition-client";
import { displayName } from "../../display-name";
import {
  LeadsError,
  readLead,
  readLeads,
  when,
  type LeadDetail,
  type LeadRow,
} from "../../leads/leads-client";
import { readPhoneRecording } from "../../leads/native-phone";
import { clockTime } from "../../leads/phone-call-text";
import { Sheet } from "../../leads/sheet-frame";
import {
  readUploadPolicy,
  runRecordingUpload,
} from "../../leads/simulated-call";
import {
  readAutoAnalysis,
  type AutoAnalysis,
} from "../../settings/auto-analysis-client";
import { track, type TelemetryEvents } from "../../telemetry";
import { Button } from "../../ui/kit";
import { markHandled, markLooked, scanOldCalls } from "./old-calls-client";
import {
  LOOK_BACK_DAYS,
  ROW_WORDS,
  autoCalls,
  buckets,
  consentPath,
  consentWord,
  fitWord,
  headline,
  progressLine,
  type OldCall,
  type OldCallsScan,
  type RowState,
  type Unplaced,
} from "./old-calls-rules";
import styles from "./old-calls.module.css";

type Phase =
  | "scanning"
  | "found"
  | "pick"
  | "running"
  | "done"
  | "empty"
  | "no_app"
  | "old_app"
  | "failed";

export type OldCallsEntry = "calls" | "card" | "setup";

type Counts = {
  found?: number;
  sure?: number;
  likely?: number;
  time_only?: number;
  unplaced?: number;
  scanned?: number;
  done?: number;
  failed?: number;
  took_ms?: number;
};

export function OldCallsSheet({
  open,
  entry,
  onClose,
  onScanned,
}: {
  open: boolean;
  entry: OldCallsEntry;
  onClose: () => void;
  /** The look's result, for the card on Calls. */
  onScanned?: (scan: OldCallsScan) => void;
}) {
  const [phase, setPhase] = useState<Phase>("scanning");
  const [scan, setScan] = useState<OldCallsScan | null>(null);
  const [leads, setLeads] = useState<Record<string, LeadDetail>>({});
  const [auto, setAuto] = useState<AutoAnalysis | null>(null);
  const [policy, setPolicy] = useState<UploadPolicy | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const [running, setRunning] = useState<OldCall[]>([]);
  const [placed, setPlaced] = useState<ReadonlySet<string>>(new Set());
  const [assigning, setAssigning] = useState<Unplaced | null>(null);
  const task = useRef<AbortController | null>(null);
  const started = useRef(0);
  // Where it opened from and who hears the result, as last rendered (the look
  // runs once per opening, whatever changes meanwhile).
  const entryRef = useRef(entry);
  const scannedRef = useRef(onScanned);
  useEffect(() => {
    entryRef.current = entry;
    scannedRef.current = onScanned;
  });

  const say = useCallback(
    (stage: TelemetryEvents["sx.old_calls"]["stage"], counts: Counts = {}) =>
      track("sx.old_calls", {
        stage,
        entry,
        consent: consentWord(auto),
        ...counts,
      }),
    [auto, entry],
  );

  const run = useCallback(
    async (
      list: OldCall[],
      how: "standing" | "accepted",
      by: AutoAnalysis | null,
      leads: Readonly<Record<string, LeadDetail>>,
      policy: UploadPolicy | null,
    ) => {
      if (!policy || !list.length) return;
      const controller = new AbortController();
      task.current?.abort();
      task.current = controller;
      setRunning(list);
      setRows(
        Object.fromEntries(list.map((call) => [call.eventId, "waiting"])),
      );
      setPhase("running");
      let done = 0;
      let failed = 0;
      for (const call of list) {
        if (controller.signal.aborted) break;
        const lead = leads[call.leadId];
        if (!lead) continue;
        const mark = (state: RowState) =>
          setRows((current) => ({ ...current, [call.eventId]: state }));
        try {
          mark("reading");
          const file = await readPhoneRecording(call.recording);
          mark("uploading");
          await runRecordingUpload({
            lead,
            file,
            policy,
            // The call's own row and attempt: a retry finds the first try's upload.
            attempt: `old-call:${call.eventId}`,
            callEventId: call.eventId,
            consent: how,
            onStep: () => undefined,
            signal: controller.signal,
          });
          mark("done");
          done++;
          markHandled([call.eventId]);
        } catch (reason) {
          if (controller.signal.aborted) break;
          // Standing consent went off meanwhile: stop and ask, never carry on.
          if (
            how === "standing" &&
            reason instanceof LeadsError &&
            reason.status === 409
          ) {
            mark("waiting");
            setAuto(by ? { ...by, can_start: false, state: "ask" } : null);
            setPhase("found");
            return;
          }
          mark("failed");
          failed++;
        }
      }
      if (controller.signal.aborted) {
        setRows((current) =>
          Object.fromEntries(
            Object.entries(current).map(([id, state]) => [
              id,
              state === "waiting" ||
              state === "reading" ||
              state === "uploading"
                ? "stopped"
                : state,
            ]),
          ),
        );
      }
      setPhase("done");
      track("sx.old_calls", {
        stage: controller.signal.aborted ? "stopped" : "done",
        entry: entryRef.current,
        consent: consentWord(by),
        done,
        failed,
        took_ms: Math.min(
          3_600_000,
          Math.round(performance.now() - started.current),
        ),
      });
    },
    [],
  );

  // One look each time the sheet opens (the card mounts a fresh sheet per opening).
  useEffect(() => {
    if (!open) return;
    const entry = entryRef.current;
    const controller = new AbortController();
    started.current = performance.now();
    track("sx.old_calls", { stage: "scan_started", entry });
    void Promise.all([
      scanOldCalls(controller.signal),
      readAutoAnalysis(controller.signal).catch(() => null),
      readUploadPolicy(controller.signal).catch(() => null),
    ]).then(([outcome, standing, terms]) => {
      if (controller.signal.aborted) return;
      setAuto(standing);
      setPolicy(terms);
      const consent = consentWord(standing);
      if ("error" in outcome) {
        setPhase(outcome.error);
        track("sx.old_calls", {
          stage: outcome.error === "failed" ? "failed" : "no_app",
          entry,
          consent,
        });
        return;
      }
      markLooked();
      setScan(outcome.scan);
      setLeads(outcome.leads);
      scannedRef.current?.(outcome.scan);
      const split = buckets(outcome.scan.calls);
      track("sx.old_calls", {
        stage: "scan_done",
        entry,
        consent,
        found: outcome.scan.calls.length,
        sure: split.sure,
        likely: split.likely,
        time_only: split.time,
        unplaced: outcome.scan.unplaced.length,
        scanned: Math.min(10_000, outcome.scan.scanned),
        took_ms: Math.min(
          3_600_000,
          Math.round(performance.now() - started.current),
        ),
      });
      if (!outcome.scan.calls.length && !outcome.scan.unplaced.length) {
        setPhase("empty");
        return;
      }
      // Standing consent on: the sure and likely matches start by themselves.
      const first =
        consentPath(standing) === "auto" ? autoCalls(outcome.scan.calls) : [];
      if (first.length && terms) {
        track("sx.old_calls", {
          stage: "auto_started",
          entry,
          consent,
          found: first.length,
        });
        void run(first, "standing", standing, outcome.leads, terms);
        return;
      }
      setPhase("found");
      track("sx.old_calls", { stage: "asked", entry, consent });
    });
    return () => controller.abort();
  }, [open, run]);

  useEffect(() => () => task.current?.abort(), []);

  const path = consentPath(auto);
  const how = path === "auto" ? "standing" : "accepted";
  const canSend = !!policy && (path === "auto" || agreed);
  const calls = scan?.calls ?? [];
  const split = buckets(calls);
  const pickedCalls = calls.filter((call) => picked.has(call.eventId));
  const unplaced = (scan?.unplaced ?? []).filter(
    (item) => !placed.has(item.recording.source),
  );

  const close = () => {
    task.current?.abort();
    onClose();
  };

  const terms =
    path === "ask" && policy ? (
      <div className={styles.terms}>
        <details>
          <summary>{policy.title}</summary>
          <p>{policy.description}</p>
        </details>
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={agreed}
            onChange={(event) => setAgreed(event.target.checked)}
          />
          <span>
            The customers know these calls are recorded, and I agree to these
            terms
          </span>
        </label>
      </div>
    ) : path === "auto" ? (
      <p className={styles.note}>
        You turned on Analyse my calls automatically. Time-only matches wait for
        your tap.
      </p>
    ) : null;

  return (
    <Sheet open={open} label="Find my old calls" onClose={close}>
      <div className={styles.sheet} data-phase={phase}>
        {phase === "scanning" ? (
          <section className={styles.hero} aria-live="polite">
            <h2>Looking for your old calls</h2>
            <ol className={styles.scanSteps}>
              <li>Your call history: lead calls with no recording</li>
              <li>Your recordings folder: the last {LOOK_BACK_DAYS} days</li>
              <li>Matching each call to its recording…</li>
            </ol>
            <p className={styles.note}>Nothing is uploaded yet.</p>
          </section>
        ) : null}

        {phase === "no_app" || phase === "old_app" || phase === "failed" ? (
          <section className={styles.hero}>
            <h2>
              {phase === "old_app"
                ? "Update the app to find old calls"
                : phase === "no_app"
                  ? "Open Sales X-Ray on your Android phone"
                  : "We couldn't look this time"}
            </h2>
            <p className={styles.note}>
              {phase === "old_app"
                ? "This version can't look through older recordings. Update Sales X-Ray from Google Play, then try again."
                : phase === "no_app"
                  ? "Your phone keeps the recordings, so the look runs in the phone app."
                  : "Check your connection and try again."}
            </p>
            <div className={styles.actions}>
              <Button variant="primary" onClick={close}>
                OK
              </Button>
            </div>
          </section>
        ) : null}

        {phase === "empty" ? (
          <section className={styles.hero}>
            <h2>No old calls to add</h2>
            <p className={styles.note}>
              {scan?.missing
                ? `${scan.missing} lead calls had no recording, and your phone has none for them.`
                : `Every lead call of the last ${LOOK_BACK_DAYS} days already has its recording.`}
            </p>
            <div className={styles.actions}>
              <Button variant="primary" onClick={close}>
                Done
              </Button>
            </div>
          </section>
        ) : null}

        {phase === "found" && scan ? (
          <section className={styles.hero}>
            {calls.length ? (
              <>
                <p className={styles.eyebrow}>Last {LOOK_BACK_DAYS} days</p>
                <h2>
                  <span className={styles.count}>{calls.length}</span>{" "}
                  {headline(calls.length).replace(/^\d+ /, "")}
                </h2>
                <ul
                  className={styles.buckets}
                  aria-label="How sure each match is"
                >
                  {split.sure ? (
                    <li data-fit="number">
                      <strong>{split.sure}</strong> Sure
                    </li>
                  ) : null}
                  {split.likely ? (
                    <li data-fit="contact">
                      <strong>{split.likely}</strong> Likely
                    </li>
                  ) : null}
                  {split.time ? (
                    <li data-fit="time">
                      <strong>{split.time}</strong> Time only, check it
                    </li>
                  ) : null}
                </ul>
                {terms}
                <div className={styles.actions}>
                  <Button
                    variant="primary"
                    disabled={!canSend}
                    onClick={() => {
                      say("chose_all", { found: calls.length });
                      void run([...calls], how, auto, leads, policy);
                    }}
                  >
                    {calls.length === 1
                      ? "Analyse the call"
                      : `Analyse all ${calls.length}`}
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      say("chose_pick", { found: calls.length });
                      setPhase("pick");
                    }}
                  >
                    Pick calls
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      say("not_now", { found: calls.length });
                      markHandled(calls.map((call) => call.eventId));
                      close();
                    }}
                  >
                    Not now
                  </Button>
                </div>
              </>
            ) : (
              <h2>No lead calls to add</h2>
            )}
            {unplaced.length ? (
              <UnplacedList
                items={unplaced}
                canSend={canSend}
                onAssign={setAssigning}
                onSetAside={(item) => {
                  say("not_lead");
                  markHandled([item.recording.source]);
                  setPlaced(
                    (current) => new Set([...current, item.recording.source]),
                  );
                }}
              />
            ) : null}
            {!calls.length && path === "ask" && unplaced.length ? terms : null}
          </section>
        ) : null}

        {phase === "pick" ? (
          <section className={styles.hero}>
            <h2>Pick calls</h2>
            <ol className={styles.list} aria-label="Found calls">
              {calls.map((call) => (
                <li key={call.eventId}>
                  <label className={styles.pickRow}>
                    <input
                      type="checkbox"
                      checked={picked.has(call.eventId)}
                      onChange={(event) =>
                        setPicked((current) => {
                          const next = new Set(current);
                          if (event.target.checked) next.add(call.eventId);
                          else next.delete(call.eventId);
                          return next;
                        })
                      }
                    />
                    <CallLine call={call} />
                  </label>
                </li>
              ))}
            </ol>
            {terms}
            <div className={styles.actions}>
              <Button
                variant="primary"
                disabled={!canSend || !pickedCalls.length}
                onClick={() => void run(pickedCalls, how, auto, leads, policy)}
              >
                {pickedCalls.length === 1
                  ? "Analyse 1 call"
                  : `Analyse ${pickedCalls.length} calls`}
              </Button>
              <Button variant="ghost" onClick={() => setPhase("found")}>
                Back
              </Button>
            </div>
          </section>
        ) : null}

        {phase === "running" || phase === "done" ? (
          <section className={styles.hero} aria-live="polite">
            {phase === "done" ? (
              <CheckCircle2
                className={styles.doneIcon}
                size={36}
                aria-hidden="true"
              />
            ) : null}
            <h2>
              {phase === "running"
                ? `Analysing your ${running.length === 1 ? "old call" : `${running.length} old calls`}`
                : (() => {
                    const done = Object.values(rows).filter(
                      (state) => state === "done",
                    ).length;
                    return done === 1
                      ? "1 Report is on its way to its lead"
                      : `${done} Reports are on their way to your leads`;
                  })()}
            </h2>
            <p className={styles.note}>
              {progressLine(rows, running.length)}. Each Report appears on its
              lead in a few minutes.
            </p>
            <ol className={styles.list} aria-label="Old calls">
              {running.map((call) => (
                <li key={call.eventId} data-state={rows[call.eventId]}>
                  <CallLine
                    call={call}
                    state={rows[call.eventId] ?? "waiting"}
                  />
                </li>
              ))}
            </ol>
            <div className={styles.actions}>
              {phase === "running" ? (
                <Button variant="ghost" onClick={() => task.current?.abort()}>
                  Stop
                </Button>
              ) : (
                <>
                  <Button variant="primary" onClick={close}>
                    Done
                  </Button>
                  {calls.some((call) => rows[call.eventId] !== "done") ? (
                    <Button variant="ghost" onClick={() => setPhase("pick")}>
                      Pick more calls
                    </Button>
                  ) : null}
                </>
              )}
            </div>
            {phase === "done" && unplaced.length ? (
              <UnplacedList
                items={unplaced}
                canSend={canSend}
                onAssign={setAssigning}
                onSetAside={(item) => {
                  say("not_lead");
                  markHandled([item.recording.source]);
                  setPlaced(
                    (current) => new Set([...current, item.recording.source]),
                  );
                }}
              />
            ) : null}
          </section>
        ) : null}

        {assigning && policy ? (
          <AssignPanel
            item={assigning}
            policy={policy}
            consent={how}
            onCancel={() => setAssigning(null)}
            onPlaced={(item) => {
              say("assign");
              markHandled([item.recording.source]);
              setPlaced(
                (current) => new Set([...current, item.recording.source]),
              );
              setAssigning(null);
            }}
          />
        ) : null}
      </div>
    </Sheet>
  );
}

function CallLine({ call, state }: { call: OldCall; state?: RowState }) {
  return (
    <span className={styles.callLine}>
      <strong>{displayName(call.leadName) || "Lead"}</strong>
      <small>
        {when(call.at)} · {clockTime(call.seconds)}
      </small>
      {state ? (
        <small className={styles.state} data-state={state}>
          {ROW_WORDS[state]}
        </small>
      ) : (
        <small className={styles.chip} data-fit={call.fit}>
          {fitWord(call.fit)}
        </small>
      )}
    </span>
  );
}

function UnplacedList({
  items,
  canSend,
  onAssign,
  onSetAside,
}: {
  items: ReadonlyArray<Unplaced>;
  canSend: boolean;
  onAssign: (item: Unplaced) => void;
  onSetAside: (item: Unplaced) => void;
}) {
  return (
    <div className={styles.unplaced}>
      <h3>
        {items.length === 1
          ? "1 recording we couldn't place"
          : `${items.length} recordings we couldn't place`}
      </h3>
      <ol className={styles.list} aria-label="Recordings not placed">
        {items.map((item) => (
          <li key={item.recording.source}>
            <span className={styles.callLine}>
              <strong>
                <FileAudio size={16} aria-hidden="true" /> Recording
              </strong>
              <small>
                {item.startedMs
                  ? when(new Date(item.startedMs).toISOString())
                  : "Date unknown"}
                {item.seconds ? ` · ${clockTime(item.seconds)}` : ""}
              </small>
            </span>
            <span className={styles.rowActions}>
              <Button
                variant="secondary"
                disabled={!canSend}
                onClick={() => onAssign(item)}
              >
                Assign to a lead
              </Button>
              <Button variant="ghost" onClick={() => onSetAside(item)}>
                Not a lead call
              </Button>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function AssignPanel({
  item,
  policy,
  consent,
  onCancel,
  onPlaced,
}: {
  item: Unplaced;
  policy: UploadPolicy;
  consent: "standing" | "accepted";
  onCancel: () => void;
  onPlaced: (item: Unplaced) => void;
}) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<LeadRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      readLeads({ scope: "mine", search: query }, controller.signal).then(
        (page) => setFound(page.leads.slice(0, 6)),
        () => undefined,
      );
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  const place = async (row: LeadRow) => {
    setBusy(true);
    setProblem(null);
    const controller = new AbortController();
    try {
      const lead = await readLead(row.lead_id, controller.signal);
      const file = await readPhoneRecording(item.recording);
      await runRecordingUpload({
        lead,
        file,
        policy,
        attempt: `old-recording:${item.recording.size}:${item.startedMs}`,
        consent,
        onStep: () => undefined,
        signal: controller.signal,
      });
      onPlaced(item);
    } catch (reason) {
      setProblem(
        reason instanceof LeadsError
          ? reason.message
          : "This one didn't upload. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.assign} aria-label="Assign to a lead">
      <h3>Which lead was this call with?</h3>
      <label className={styles.search}>
        <Search size={18} aria-hidden="true" />
        <input
          type="search"
          value={query}
          placeholder="Search leads"
          aria-label="Search leads"
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <ol className={styles.list} aria-label="Leads">
        {found.map((row) => (
          <li key={row.lead_id}>
            <button
              type="button"
              className={styles.leadPick}
              disabled={busy}
              onClick={() => void place(row)}
            >
              <strong>{displayName(row.name)}</strong>
              {row.phone_last4 ? <small>…{row.phone_last4}</small> : null}
            </button>
          </li>
        ))}
      </ol>
      {problem ? (
        <p className={styles.error} role="alert">
          {problem}
        </p>
      ) : null}
      <div className={styles.actions}>
        <Button variant="ghost" disabled={busy} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </section>
  );
}
