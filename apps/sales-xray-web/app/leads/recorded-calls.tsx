"use client";

/**
 * Lead calls recorded on this phone (owner, 22 Oct 2026: calls made from the
 * phone's own dialer to or from a lead are logged on the lead with their
 * recording). Inside the Sales Xray phone app, call logging puts each dialer
 * call on its lead and the phone finds the recording its dialer saved, by the
 * lead's number and the call's time. This card on Leads lists those calls.
 * The seller agrees to the recording terms for the calls in view, as for any
 * upload, and Sales Xray analyses each one; its Report joins the call on the
 * lead. Recordings the phone found silent are flagged and left out (Redmi
 * audit #53). When MIUI hides the recordings folder, the card asks for All
 * files access instead (#49). Nothing shows in a browser or an older app.
 */

import { FileAudio, FolderLock } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { UploadPolicy } from "../acquisition-client";
import { displayName } from "../display-name";
import { Badge, Button } from "../ui/kit";
import { Sheet } from "./lead-sheet";
import {
  LeadsError,
  readLead,
  when,
  type Desk,
  type LeadDetail,
} from "./leads-client";
import {
  checkWarning,
  inPhoneApp,
  onPhoneSignal,
  pendingRecordings,
  readPhoneRecording,
  recordingHandled,
  setupOpen,
  type PendingRecording,
  type PendingRecordings,
} from "./native-phone";
import { clockTime } from "./phone-call-text";
import { readUploadPolicy, runRecordingUpload } from "./simulated-call";
import styles from "./leads.module.css";

type RowState = "waiting" | "reading" | "running" | "done" | "error";

/** "You called · 2:14 · Today 2:44 AM", or "They called · …". */
export function recordedLine(
  item: PendingRecording,
  now: Date = new Date(),
): string {
  const who = item.direction === "incoming" ? "They called" : "You called";
  return `${who} · ${clockTime(item.seconds)} · ${when(new Date(item.startedMs).toISOString(), now)}`;
}

/** The calls whose recording can be analysed now: found, readable and not silent. */
export function readyCalls(
  pending: PendingRecordings | null,
): PendingRecording[] {
  return (pending?.items ?? []).filter(
    (item) =>
      item.recording?.supported && item.recording.check?.verdict !== "silent",
  );
}

/** Calls the phone recorded silent: shown so the seller can fix the phone. */
export function silentCalls(
  pending: PendingRecordings | null,
): PendingRecording[] {
  return (pending?.items ?? []).filter(
    (item) => item.recording?.check?.verdict === "silent",
  );
}

/** The phone hides its recordings and a call is still waiting for one. */
export function hiddenRecordings(pending: PendingRecordings | null): boolean {
  return (
    !!pending?.needsAllFiles &&
    pending.allFilesSupported &&
    pending.items.some((item) => !item.recording)
  );
}

export function RecordedCallsCard({ me }: { me: Desk["me"] }) {
  const [pending, setPending] = useState<PendingRecordings | null>(null);
  const [leads, setLeads] = useState<Record<string, LeadDetail | null>>({});
  const [open, setOpen] = useState(false);
  const known = useRef(leads);
  useEffect(() => {
    known.current = leads;
  });

  const load = useCallback(
    () =>
      pendingRecordings().then((next) => {
        if (!next) return;
        setPending(next);
        // Each call's lead, for its name; a lead that's gone or not mine stays out.
        const missing = [
          ...new Set(next.items.map((item) => item.leadId)),
        ].filter((id) => !(id in known.current));
        if (!missing.length) return;
        return Promise.all(
          missing.map((id) =>
            readLead(id).then(
              (detail) => [id, detail] as const,
              () => [id, null] as const,
            ),
          ),
        ).then((found) =>
          setLeads((current) => ({ ...current, ...Object.fromEntries(found) })),
        );
      }),
    [],
  );

  useEffect(() => {
    if (!inPhoneApp()) return;
    void load();
    // New calls logged, a recording found, or back from the settings screen.
    return onPhoneSignal((event) => {
      if (event === "calls" || event === "recordings" || event === "resume")
        void load();
    });
  }, [load]);

  const onLead = (item: PendingRecording) => leads[item.leadId] ?? null;
  const ready = readyCalls(pending).filter(onLead);
  const silent = silentCalls(pending).filter(onLead);
  const hidden = hiddenRecordings(pending);
  if (!ready.length && !silent.length && !hidden) return null;

  if (!ready.length && !silent.length)
    return (
      <section className={styles.recordedCard} aria-label="Call recordings">
        <FolderLock size={20} aria-hidden="true" />
        <span>
          <strong>Your phone hides its call recordings</strong>
          <small>
            Allow All files access so Sales Xray can find your lead calls&apos;
            recordings.
          </small>
        </span>
        <Button onClick={() => void setupOpen("allFiles")}>Allow</Button>
      </section>
    );

  const count = ready.length || silent.length;
  return (
    <>
      <section className={styles.recordedCard} aria-label="Recorded lead calls">
        <FileAudio size={20} aria-hidden="true" />
        <span>
          <strong>
            {count === 1
              ? "1 lead call recorded"
              : `${count} lead calls recorded`}
          </strong>
          <small>
            {ready.length
              ? "Analyse them to get each call's Report on its lead."
              : "Your phone saved silent recordings. Check its call recording."}
          </small>
        </span>
        <Button variant="primary" onClick={() => setOpen(true)}>
          {ready.length ? "Analyse" : "See"}
        </Button>
      </section>
      <RecordedCallsSheet
        open={open}
        ready={ready}
        silent={silent}
        leads={leads}
        me={me}
        onPending={setPending}
        onClose={() => {
          setOpen(false);
          void load();
        }}
      />
    </>
  );
}

function RecordedCallsSheet({
  open,
  ready,
  silent,
  leads,
  me,
  onPending,
  onClose,
}: {
  open: boolean;
  ready: PendingRecording[];
  silent: PendingRecording[];
  leads: Record<string, LeadDetail | null>;
  me: Desk["me"];
  onPending: (next: PendingRecordings) => void;
  onClose: () => void;
}) {
  const [policy, setPolicy] = useState<UploadPolicy | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const task = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!open || policy) return;
    const controller = new AbortController();
    readUploadPolicy(controller.signal).then(setPolicy, () => {
      if (!controller.signal.aborted)
        setProblem("The recording terms didn't load. Close and try again.");
    });
    return () => controller.abort();
  }, [open, policy]);
  useEffect(() => () => task.current?.abort(), []);

  const mark = (eventId: string, state: RowState, error?: string) => {
    setRows((current) => ({ ...current, [eventId]: state }));
    if (error) setErrors((current) => ({ ...current, [eventId]: error }));
  };

  const drop = async (item: PendingRecording) => {
    const next = await recordingHandled(item.eventId);
    if (next) onPending(next);
  };

  const todo = ready.filter((item) => rows[item.eventId] !== "done");

  const run = async () => {
    if (!policy || !agreed || running) return;
    const controller = new AbortController();
    task.current = controller;
    setRunning(true);
    // One call at a time: each reads its file from the phone, then uploads.
    for (const item of todo) {
      const lead = leads[item.leadId];
      if (!lead || !item.recording || controller.signal.aborted) continue;
      try {
        mark(item.eventId, "reading");
        const file = await readPhoneRecording(item.recording);
        mark(item.eventId, "running");
        await runRecordingUpload({
          lead,
          file,
          me,
          policy,
          // The same call always reuses its upload, so a retry never saves it twice.
          attempt: item.eventId,
          callEventId: item.eventId,
          onStep: () => undefined,
          signal: controller.signal,
        });
        mark(item.eventId, "done");
        await recordingHandled(item.eventId);
      } catch (reason) {
        if (controller.signal.aborted) break;
        mark(
          item.eventId,
          "error",
          reason instanceof LeadsError
            ? reason.message
            : "This one didn't upload. Check your connection and try again.",
        );
      }
    }
    setRunning(false);
  };

  const status = (item: PendingRecording) => {
    switch (rows[item.eventId]) {
      case "reading":
        return "Getting it from your phone…";
      case "running":
        return "Starting the analysis…";
      case "done":
        return "Analysis started";
      case "error":
        return errors[item.eventId] ?? "Didn't upload";
      default:
        return checkWarning(item.recording) ?? item.recording?.name ?? "";
    }
  };

  return (
    <Sheet open={open} label="Recorded lead calls" onClose={onClose}>
      <div className={styles.setupSheet}>
        <header className={styles.setupHead}>
          <h2>Recorded lead calls</h2>
          <p>
            Your phone recorded these calls with your leads. Each one&apos;s
            Report appears on its lead in a few minutes.
          </p>
        </header>
        <ol className={styles.recordedList} aria-label="Recorded lead calls">
          {ready.map((item) => (
            <li key={item.eventId} data-state={rows[item.eventId]}>
              <span>
                <strong>
                  {displayName(leads[item.leadId]?.lead.name ?? "")}
                </strong>
                <small>{recordedLine(item)}</small>
                <small
                  data-warn={checkWarning(item.recording) ? "" : undefined}
                >
                  {status(item)}
                </small>
              </span>
              {rows[item.eventId] === "done" ? (
                <Badge tone="good">Added</Badge>
              ) : (
                <Button
                  variant="ghost"
                  disabled={running}
                  onClick={() => void drop(item)}
                >
                  Not this call
                </Button>
              )}
            </li>
          ))}
          {silent.map((item) => (
            <li key={item.eventId} data-state="silent">
              <span>
                <strong>
                  {displayName(leads[item.leadId]?.lead.name ?? "")}
                </strong>
                <small>{recordedLine(item)}</small>
                <small data-warn="">{checkWarning(item.recording)}</small>
              </span>
              <Button
                variant="ghost"
                disabled={running}
                onClick={() => void drop(item)}
              >
                Remove
              </Button>
            </li>
          ))}
        </ol>
        {todo.length ? (
          policy ? (
            <>
              <details className={styles.terms}>
                <summary>{policy.title}</summary>
                <p>{policy.description}</p>
              </details>
              <label className={styles.toggle}>
                <input
                  type="checkbox"
                  checked={agreed}
                  disabled={running}
                  onChange={(event) => setAgreed(event.target.checked)}
                />
                The customers know these calls are recorded, and I agree to
                these terms
              </label>
            </>
          ) : problem ? (
            <p className={styles.error} role="alert">
              {problem}
            </p>
          ) : (
            <p className={styles.hint}>Getting the recording terms…</p>
          )
        ) : null}
        <div className={styles.row}>
          {todo.length ? (
            <Button
              variant="primary"
              disabled={!policy || !agreed || running}
              aria-busy={running || undefined}
              onClick={() => void run()}
            >
              {todo.length === 1
                ? "Analyse the call"
                : `Analyse ${todo.length} calls`}
            </Button>
          ) : null}
          <Button variant="ghost" onClick={onClose}>
            {todo.length ? "Not now" : "Done"}
          </Button>
        </div>
      </div>
    </Sheet>
  );
}
