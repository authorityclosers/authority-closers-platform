"use client";

/**
 * One lead, made for calling from a phone: a big Call button, then "How did
 * the call go?" the moment the seller is back from the dialer, then the
 * details, the owner and the history. CallingLoop is NeoDove's "Start": one
 * lead at a time, and the next one appears only after this one is saved.
 */

import {
  CheckCircle2,
  Mail,
  MessageCircle,
  Pencil,
  Phone,
  PhoneMissed,
  PhoneOff,
  Radio,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { callHref, type UploadPolicy } from "../acquisition-client";
import { Avatar, Badge, Button, Empty, Field } from "../ui/kit";
import {
  addNote,
  ago,
  dispose,
  displayPhone,
  editLead,
  FIELD_LABELS,
  LeadsError,
  localInputValue,
  logPhoneCall,
  minutesLabel,
  nextCallTime,
  peekPendingCall,
  readLead,
  readNext,
  reassign,
  rememberCall,
  takePendingCall,
  whatsappHref,
  when,
  type CallTime,
  type LeadDetail,
  type LeadEvent,
  type Stage,
} from "./leads-client";
import { sourceText, whyLine } from "./desk-view";
import {
  pickSimulation,
  readUploadPolicy,
  runSimulatedCall,
  STEP_LABELS,
  type SimulationPick,
  type SimulationStep,
} from "./simulated-call";
import styles from "./leads.module.css";

// Sources whose leads arrive with a form's own answers worth showing.
const FORM_SOURCES = new Set(["meta", "webhook", "sheet", "csv", "google_ads"]);

const NO_RETRY = new Set([
  "invalid_number",
  "incoming_not_available",
  "not_in_use",
]);

/* ---------- Sheet ---------- */

export function Sheet({
  open,
  label,
  onClose,
  children,
}: {
  open: boolean;
  label: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className={styles.sheet}
      aria-label={label}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      {open ? (
        <div className={styles.sheetBody}>
          <button
            type="button"
            className={styles.sheetClose}
            onClick={onClose}
            aria-label="Close"
          >
            <X size={18} aria-hidden="true" />
          </button>
          {children}
        </div>
      ) : null}
    </dialog>
  );
}

/* ---------- After the call ---------- */

type Talk = "talked" | "missed" | null;
type Pick = CallTime | "custom";

const MISSED: { key: string; label: string }[] = [
  { key: "did_not_pick", label: "No answer" },
  { key: "busy", label: "Busy" },
  { key: "disconnected", label: "Cut the call" },
  { key: "switched_off", label: "Phone switched off" },
  { key: "out_of_coverage", label: "No network" },
  { key: "not_connected", label: "Call didn't go through" },
  { key: "invalid_number", label: "Wrong number" },
  { key: "not_in_use", label: "Number not in use" },
  { key: "incoming_not_available", label: "Can't take calls" },
  { key: "other", label: "Something else" },
];

const NEXT: { key: Stage; label: string; sub: string; tone: string }[] = [
  {
    key: "interested",
    label: "Interested",
    sub: "Wants to buy or see more",
    tone: "warm",
  },
  {
    key: "follow_up",
    label: "Call back later",
    sub: "Asked to talk another time",
    tone: "later",
  },
  { key: "won", label: "Won", sub: "They bought", tone: "good" },
  { key: "lost", label: "Not interested", sub: "Close this lead", tone: "bad" },
];

const TIMES: { key: Pick; label: string }[] = [
  { key: "hour", label: "In 1 hour" },
  { key: "evening", label: "This evening" },
  { key: "morning", label: "Tomorrow morning" },
  { key: "week", label: "Next week" },
  { key: "custom", label: "Pick a time" },
];

function timeOf(pick: Pick | null, custom: string): Date | null {
  if (pick === null) return null;
  if (pick !== "custom") return nextCallTime(pick);
  const at = custom ? new Date(custom) : null;
  return at && !Number.isNaN(at.getTime()) ? at : null;
}

function TimePicker({
  label,
  pick,
  custom,
  onPick,
  onCustom,
}: {
  label: string;
  pick: Pick;
  custom: string;
  onPick: (pick: Pick) => void;
  onCustom: (value: string) => void;
}) {
  const at = timeOf(pick, custom);
  return (
    <div className={styles.outcomeStep}>
      <span className={styles.stepLabel}>{label}</span>
      <div className={styles.chips} role="group" aria-label={label}>
        {TIMES.map((item) => (
          <button
            key={item.key}
            type="button"
            className={styles.chip}
            aria-pressed={pick === item.key}
            onClick={() => onPick(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {pick === "custom" ? (
        <Field label="Date and time">
          <input
            type="datetime-local"
            value={custom}
            min={localInputValue(new Date())}
            onChange={(event) => onCustom(event.target.value)}
          />
        </Field>
      ) : at ? (
        <p className={styles.hint}>{when(at.toISOString())}</p>
      ) : null}
    </div>
  );
}

export function CallOutcome({
  detail,
  submitLabel,
  attention,
  beforeSave,
  onSaved,
}: {
  detail: LeadDetail;
  submitLabel: string;
  /** The seller just came back from the dialer: this card asks first. */
  attention: boolean;
  /** Logs a call still waiting to be logged; returns the lead as it now is. */
  beforeSave: () => Promise<LeadDetail>;
  onSaved: (next: LeadDetail) => void;
}) {
  const id = useId();
  const ref = useRef<HTMLElement>(null);
  const [talk, setTalk] = useState<Talk>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage | null>(null);
  const [next, setNext] = useState<Pick>("morning");
  const [retry, setRetry] = useState<Pick | null>(null);
  const [custom, setCustom] = useState(() =>
    localInputValue(nextCallTime("morning")),
  );
  const [note, setNote] = useState("");
  const [deal, setDeal] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (attention)
      ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [attention]);

  const closes = stage === "won" || stage === "lost";
  const needsTime = talk === "talked" && stage !== null && !closes;
  const at = needsTime
    ? timeOf(next, custom)
    : talk === "missed"
      ? timeOf(retry, custom)
      : null;
  const valid =
    talk === "missed"
      ? reason !== null && (retry === null || at !== null)
      : talk === "talked" && stage !== null && (!needsTime || at !== null);
  const autoRetry =
    reason === null
      ? null
      : NO_RETRY.has(reason)
        ? "No automatic retry for a bad number."
        : `It comes back on the desk ${detail.lead.attempts ? "tomorrow" : "in 1 hour"}.`;

  const submit = async () => {
    if (!valid || saving) return;
    setSaving(true);
    setError(null);
    try {
      const current = await beforeSave();
      onSaved(
        await dispose(current.lead, {
          connected: talk === "talked",
          reason: talk === "missed" ? (reason ?? undefined) : undefined,
          stage: talk === "talked" ? (stage ?? undefined) : undefined,
          follow_up_at: at ? at.toISOString() : undefined,
          remark: note.trim() || undefined,
          deal_value: deal.trim() || undefined,
        }),
      );
    } catch (failure) {
      setError(
        failure instanceof LeadsError
          ? failure.message
          : "Not saved. Try again.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      ref={ref}
      className={styles.outcome}
      data-attention={attention || undefined}
      aria-labelledby={`${id}-q`}
    >
      <h3 id={`${id}-q`} className={styles.outcomeTitle}>
        {attention
          ? "Back from the call. How did it go?"
          : "How did the call go?"}
      </h3>
      <div
        className={styles.choiceRow}
        role="group"
        aria-label="Did you talk to them?"
      >
        <button
          type="button"
          className={styles.choiceTile}
          data-kind="talked"
          aria-pressed={talk === "talked"}
          onClick={() => {
            setTalk("talked");
            setReason(null);
            setRetry(null);
          }}
        >
          <CheckCircle2 size={22} aria-hidden="true" />
          We talked
        </button>
        <button
          type="button"
          className={styles.choiceTile}
          data-kind="missed"
          aria-pressed={talk === "missed"}
          onClick={() => {
            setTalk("missed");
            setStage(null);
          }}
        >
          <PhoneMissed size={22} aria-hidden="true" />
          Didn&apos;t get through
        </button>
      </div>

      {talk === "missed" ? (
        <div className={styles.outcomeStep}>
          <span className={styles.stepLabel}>What happened?</span>
          <div
            className={styles.reasonGrid}
            role="group"
            aria-label="What happened"
          >
            {MISSED.map((item) => (
              <button
                key={item.key}
                type="button"
                className={styles.reasonTile}
                aria-pressed={reason === item.key}
                onClick={() => setReason(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>
          {reason && retry === null ? (
            <p className={styles.retryLine}>
              {autoRetry}
              {!NO_RETRY.has(reason) ? (
                <button
                  type="button"
                  className={styles.linkButton}
                  onClick={() => setRetry("evening")}
                >
                  Pick a time instead
                </button>
              ) : null}
            </p>
          ) : null}
          {reason && retry !== null ? (
            <TimePicker
              label="Try again"
              pick={retry}
              custom={custom}
              onPick={setRetry}
              onCustom={setCustom}
            />
          ) : null}
        </div>
      ) : null}

      {talk === "talked" ? (
        <div className={styles.outcomeStep}>
          <span className={styles.stepLabel}>What happens next?</span>
          <div
            className={styles.stageGrid}
            role="group"
            aria-label="What happens next"
          >
            {NEXT.map((item) => (
              <button
                key={item.key}
                type="button"
                className={styles.stageTile}
                data-tone={item.tone}
                aria-pressed={stage === item.key}
                onClick={() => setStage(item.key)}
              >
                <strong>{item.label}</strong>
                <small>{item.sub}</small>
              </button>
            ))}
          </div>
          {needsTime ? (
            <TimePicker
              label="Next call"
              pick={next}
              custom={custom}
              onPick={setNext}
              onCustom={setCustom}
            />
          ) : null}
          {closes ? (
            <p className={styles.hint}>
              This closes the lead. It reopens if they get in touch again.
            </p>
          ) : null}
          {stage === "interested" || stage === "won" ? (
            <Field label="Deal value (₹, optional)">
              <input
                inputMode="decimal"
                placeholder="60,000"
                value={deal}
                maxLength={24}
                onChange={(event) => setDeal(event.target.value)}
              />
            </Field>
          ) : null}
        </div>
      ) : null}

      {talk !== null ? (
        <Field
          label={talk === "talked" ? "What did they say?" : "Note (optional)"}
          wide
        >
          <textarea
            rows={2}
            value={note}
            maxLength={1000}
            placeholder={
              talk === "talked"
                ? "What they need, what you promised"
                : "Anything to know before the next try"
            }
            onChange={(event) => setNote(event.target.value)}
          />
        </Field>
      ) : null}

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {talk !== null ? (
        <button
          type="button"
          className={styles.saveButton}
          onClick={submit}
          disabled={!valid || saving}
        >
          {saving ? "Saving…" : submitLabel}
        </button>
      ) : null}
    </section>
  );
}

/* ---------- Back from the dialer ---------- */

/**
 * Calls `onReturn` with the seconds away when the seller comes back to the
 * page after tapping Call for this lead (the dialer hid the page). It also
 * runs once on open, for a phone that reloaded the page while calling.
 */
function useCallReturn(
  leadId: string | null,
  onReturn: (seconds: number) => void,
) {
  const latest = useRef(onReturn);
  useEffect(() => {
    latest.current = onReturn;
  });
  useEffect(() => {
    if (!leadId) return;
    const check = () => {
      if (document.visibilityState !== "visible") return;
      const pending = peekPendingCall();
      if (!pending || pending.leadId !== leadId) return;
      const seconds = (Date.now() - pending.at) / 1000;
      if (seconds < 4) return;
      takePendingCall();
      latest.current(seconds);
    };
    const timer = window.setTimeout(check, 0);
    document.addEventListener("visibilitychange", check);
    window.addEventListener("focus", check);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("focus", check);
    };
  }, [leadId]);
}

/** A call tapped on a computer (no dialer came up) is logged when its result is saved. */
async function logWaitingCall(detail: LeadDetail): Promise<LeadDetail> {
  const pending = peekPendingCall();
  if (!pending || pending.leadId !== detail.lead.lead_id) return detail;
  takePendingCall();
  return logPhoneCall(detail.lead.lead_id, (Date.now() - pending.at) / 1000);
}

/* ---------- History ---------- */

function eventText(event: LeadEvent): { title: string; detail?: string } {
  const who = event.actor_name ?? "The desk";
  switch (event.kind) {
    case "captured":
      return { title: `Came in from ${event.source_label ?? "a source"}` };
    case "repeat":
      return {
        title: `Asked again from ${event.source_label ?? "a source"}`,
        detail: "Same phone number: kept on this lead, not a new one.",
      };
    case "assigned":
      return event.owner_name
        ? {
            title: `Given to ${event.owner_name}`,
            detail: event.allocation_reason ?? undefined,
          }
        : {
            title: "Waiting for an owner",
            detail: event.allocation_reason ?? undefined,
          };
    case "reassigned":
      return {
        title: `Moved from ${event.previous_owner_name ?? "nobody"} to ${event.owner_name ?? "nobody"}`,
        detail: event.allocation_reason ?? undefined,
      };
    case "result": {
      const next = event.next_action_at
        ? ` · next ${when(event.next_action_at)}`
        : "";
      return event.connected
        ? {
            title: `${who} talked to them: ${event.stage_label ?? ""}${next}`,
            detail: event.note ?? undefined,
          }
        : {
            title: `${who}: not connected, ${(event.reason_label ?? "").toLowerCase()}${next}`,
            detail: event.note ?? undefined,
          };
    }
    case "call":
      return {
        title: `${who} ${event.simulated ? "made a sample call" : "called"}${
          event.duration_seconds
            ? ` · ${minutesLabel(event.duration_seconds)}`
            : ""
        }`,
      };
    case "edited":
      return {
        title: `${who} changed ${(event.changed ?? [])
          .map((name) => (FIELD_LABELS[name] ?? name).toLowerCase())
          .join(", ")}`,
      };
    case "note":
      return { title: `${who} added a note`, detail: event.note ?? undefined };
    default:
      return { title: event.note ?? "Updated" };
  }
}

function History({ events }: { events: LeadEvent[] }) {
  return (
    <ol className={styles.history} aria-label="History">
      {events.map((event, index) => {
        const text = eventText(event);
        return (
          <li key={`${event.at}-${index}`} data-kind={event.kind}>
            <span className={styles.historyTitle}>{text.title}</span>
            {text.detail ? (
              <span className={styles.historyDetail}>{text.detail}</span>
            ) : null}
            {event.kind === "call" && event.submission_id ? (
              <Link
                className={styles.historyLink}
                href={callHref(event.submission_id)}
              >
                Open the call&apos;s Report
              </Link>
            ) : null}
            <time className={styles.historyTime} dateTime={event.at}>
              {when(event.at)}
            </time>
          </li>
        );
      })}
    </ol>
  );
}

/* ---------- Simulated call ---------- */

const STEPS: SimulationStep[] = [
  "recording",
  "saving",
  "linking",
  "checking",
  "starting",
];

function SimulatedCall({
  detail,
  onDone,
}: {
  detail: LeadDetail;
  onDone: (next: LeadDetail) => void;
}) {
  const [state, setState] = useState<
    "idle" | "loading" | "ready" | "running" | "done" | "error"
  >("idle");
  const [pick, setPick] = useState<SimulationPick | null>(null);
  const [policy, setPolicy] = useState<UploadPolicy | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [step, setStep] = useState<SimulationStep>("recording");
  const [error, setError] = useState<string | null>(null);
  const [submission, setSubmission] = useState<string | null>(null);
  const task = useRef<AbortController | null>(null);

  useEffect(() => () => task.current?.abort(), []);

  if (!detail.can_assign)
    return (
      <p className={styles.hint}>
        Practice calls are started by an owner or admin for now.
      </p>
    );

  const prepare = async () => {
    setState("loading");
    setError(null);
    try {
      const [nextPick, nextPolicy] = await Promise.all([
        pickSimulation(detail.lead.lead_id),
        readUploadPolicy(),
      ]);
      setPick(nextPick);
      setPolicy(nextPolicy);
      setState("ready");
    } catch (reason) {
      setError(
        reason instanceof LeadsError
          ? reason.message
          : "The simulated call couldn't start.",
      );
      setState("error");
    }
  };

  const run = async () => {
    if (!pick || !policy || !agreed) return;
    const controller = new AbortController();
    task.current = controller;
    setState("running");
    setError(null);
    try {
      const next = await runSimulatedCall({
        lead: detail,
        pick,
        policy,
        onStep: setStep,
        signal: controller.signal,
      });
      const call = next.events.find((event) => event.kind === "call");
      setSubmission(call?.submission_id ?? null);
      setState("done");
      onDone(next);
    } catch (reason) {
      if (controller.signal.aborted) return;
      setError(
        reason instanceof LeadsError
          ? reason.message
          : "The simulated call stopped. Try again.",
      );
      setState("error");
    }
  };

  if (state === "idle")
    return (
      <Button onClick={prepare}>
        <Radio size={14} aria-hidden="true" />
        Practice call
      </Button>
    );

  return (
    <div className={styles.simulation} aria-live="polite">
      <strong className={styles.simulationTitle}>Practice call</strong>
      {state === "loading" ? (
        <p className={styles.hint}>Getting a practice recording…</p>
      ) : null}
      {pick && (state === "ready" || state === "running") ? (
        <p>
          Plays a {Math.max(1, Math.round(pick.duration_seconds / 60))}-minute
          practice recording as {pick.owner_name}&apos;s call and analyses it
          like a real one. Nobody is dialled.
        </p>
      ) : null}
      {state === "ready" && policy ? (
        <>
          <details className={styles.terms}>
            <summary>{policy.title}</summary>
            <p>{policy.description}</p>
          </details>
          <label className={styles.toggle}>
            <input
              type="checkbox"
              checked={agreed}
              onChange={(event) => setAgreed(event.target.checked)}
            />
            I agree to these terms
          </label>
          <div className={styles.row}>
            <Button onClick={() => setState("idle")}>Cancel</Button>
            <Button variant="primary" onClick={run} disabled={!agreed}>
              Make the simulated call
            </Button>
          </div>
        </>
      ) : null}
      {state === "running" ? (
        <ol className={styles.steps}>
          {STEPS.map((item) => (
            <li
              key={item}
              data-state={
                STEPS.indexOf(item) < STEPS.indexOf(step)
                  ? "done"
                  : item === step
                    ? "now"
                    : "later"
              }
            >
              {STEP_LABELS[item]}
            </li>
          ))}
        </ol>
      ) : null}
      {state === "done" ? (
        <p>
          Analysis started. The call&apos;s Report appears in a few minutes;
          record what happened below in the meantime.{" "}
          {submission ? (
            <Link className={styles.historyLink} href={callHref(submission)}>
              Open the call
            </Link>
          ) : null}
        </p>
      ) : null}
      {state === "error" ? (
        <>
          <p className={styles.error} role="alert">
            {error}
          </p>
          <div className={styles.row}>
            <Button onClick={prepare}>Try again</Button>
          </div>
        </>
      ) : null}
    </div>
  );
}

/* ---------- Edit details and notes ---------- */

const EDITABLE = [
  "name",
  "phone",
  "email",
  "company",
  "city",
  "language",
  "interest",
] as const;

function EditDetails({
  detail,
  onSaved,
  onCancel,
}: {
  detail: LeadDetail;
  onSaved: (next: LeadDetail) => void;
  onCancel: () => void;
}) {
  const start: Record<(typeof EDITABLE)[number], string> = {
    name: detail.lead.name,
    phone: detail.phone ?? "",
    email: detail.email ?? "",
    company: detail.lead.company ?? "",
    city: detail.lead.city ?? "",
    language: detail.lead.language ?? "",
    interest: detail.lead.interest ?? "",
  };
  const [form, setForm] = useState(start);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    const changed = Object.fromEntries(
      EDITABLE.filter((key) => form[key].trim() !== start[key].trim()).map(
        (key) => [key, form[key].trim()],
      ),
    );
    if (!Object.keys(changed).length) {
      onCancel();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      onSaved(await editLead(detail.lead, changed));
    } catch (reason) {
      setError(
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.editForm}>
      <div className={styles.formGrid}>
        {EDITABLE.map((key) => (
          <Field key={key} label={FIELD_LABELS[key]}>
            <input
              value={form[key]}
              maxLength={key === "email" ? 320 : key === "phone" ? 40 : 200}
              inputMode={
                key === "phone" ? "tel" : key === "email" ? "email" : undefined
              }
              autoComplete="off"
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  [key]: event.target.value,
                }))
              }
            />
          </Field>
        ))}
      </div>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      <div className={styles.row}>
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant="primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save details"}
        </Button>
      </div>
    </div>
  );
}

function NoteBox({
  leadId,
  onSaved,
}: {
  leadId: string;
  onSaved: (next: LeadDetail) => void;
}) {
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    if (!note.trim()) return;
    setSaving(true);
    setError(null);
    try {
      onSaved(await addNote(leadId, note.trim()));
      setNote("");
    } catch (reason) {
      setError(
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.",
      );
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className={styles.noteBox}>
      <div className={styles.noteRow}>
        <textarea
          aria-label="Add a note"
          rows={1}
          value={note}
          maxLength={1000}
          placeholder="Add a note for the next caller"
          onChange={(event) => setNote(event.target.value)}
        />
        <Button onClick={save} disabled={saving || !note.trim()}>
          {saving ? "Adding…" : "Add"}
        </Button>
      </div>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/* ---------- Lead card ---------- */

function LeadCard({
  detail,
  onChanged,
  outcome,
}: {
  detail: LeadDetail;
  onChanged: (next: LeadDetail) => void;
  outcome: ReactNode;
}) {
  const { lead } = detail;
  const [editing, setEditing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [moving, setMoving] = useState(false);
  const [moveError, setMoveError] = useState<string | null>(null);
  const sub = [lead.company, lead.city, lead.language]
    .filter(Boolean)
    .join(" · ");
  const rows: { label: string; value: ReactNode }[] = [
    ...(detail.phone
      ? [
          {
            label: "Phone",
            value: (
              <a href={`tel:${detail.phone}`}>{displayPhone(detail.phone)}</a>
            ),
          },
        ]
      : []),
    ...(detail.email
      ? [
          {
            label: "Email",
            value: <a href={`mailto:${detail.email}`}>{detail.email}</a>,
          },
        ]
      : []),
    ...detail.fields
      .filter(
        (field) => !["phone", "email"].includes(field.label.toLowerCase()),
      )
      .map((field) => ({ label: field.label, value: field.value })),
  ];
  // A lead typed in by hand has no form: its answers are the details above.
  const answers = FORM_SOURCES.has(lead.source) ? detail.source_fields : [];

  const move = async (personId: string | null) => {
    setMoving(true);
    setMoveError(null);
    try {
      onChanged(await reassign(lead, personId));
    } catch (reason) {
      setMoveError(
        reason instanceof LeadsError ? reason.message : "Not moved. Try again.",
      );
    } finally {
      setMoving(false);
    }
  };

  return (
    <div className={styles.card}>
      <header className={styles.leadHead}>
        <Avatar name={lead.name} size={52} />
        <div className={styles.cardTitle}>
          <h2>{lead.name}</h2>
          {sub ? <p>{sub}</p> : null}
          <div className={styles.cardBadges}>
            <Badge
              tone={
                lead.stage === "won"
                  ? "good"
                  : lead.stage === "lost"
                    ? "bad"
                    : "accent"
              }
            >
              {lead.stage_label}
            </Badge>
            <Badge>{sourceText(lead)}</Badge>
          </div>
        </div>
      </header>
      <p className={styles.why}>{whyLine(lead)}</p>
      {detail.next_action_note ? (
        <p className={styles.nextNote}>Last note: {detail.next_action_note}</p>
      ) : null}

      <div className={styles.actions}>
        {detail.phone ? (
          <a
            className={styles.callButton}
            href={`tel:${detail.phone}`}
            onClick={() => rememberCall(lead.lead_id)}
          >
            <Phone size={20} aria-hidden="true" />
            <span>
              <strong>Call</strong>
              <small>{displayPhone(detail.phone)}</small>
            </span>
          </a>
        ) : detail.can_edit ? (
          <button
            type="button"
            className={styles.callButton}
            data-empty=""
            onClick={() => setEditing(true)}
          >
            <Phone size={20} aria-hidden="true" />
            <span>
              <strong>Add a phone number</strong>
              <small>to call this lead</small>
            </span>
          </button>
        ) : (
          <p className={styles.hint}>No phone number on this lead.</p>
        )}
        {detail.phone ? (
          <a
            className={styles.actionButton}
            href={whatsappHref(detail.phone)}
            target="_blank"
            rel="noreferrer"
          >
            <MessageCircle size={18} aria-hidden="true" />
            WhatsApp
          </a>
        ) : null}
        {detail.email ? (
          <a className={styles.actionButton} href={`mailto:${detail.email}`}>
            <Mail size={18} aria-hidden="true" />
            Email
          </a>
        ) : null}
      </div>
      {detail.call_mode === "simulated" && detail.can_edit ? (
        testing ? (
          <SimulatedCall detail={detail} onDone={onChanged} />
        ) : (
          <button
            type="button"
            className={styles.linkButton}
            onClick={() => setTesting(true)}
          >
            Test workspace: try with a sample recording
          </button>
        )
      ) : null}

      {detail.can_edit ? outcome : null}

      <section className={styles.panel} aria-label="Details">
        <div className={styles.panelHead}>
          <h3>Details</h3>
          {detail.can_edit && !editing ? (
            <button
              type="button"
              className={styles.linkButton}
              onClick={() => setEditing(true)}
            >
              <Pencil size={14} aria-hidden="true" />
              Edit
            </button>
          ) : null}
        </div>
        {editing ? (
          <EditDetails
            detail={detail}
            onCancel={() => setEditing(false)}
            onSaved={(next) => {
              setEditing(false);
              onChanged(next);
            }}
          />
        ) : rows.length ? (
          <dl className={styles.detailRows}>
            {rows.map((row) => (
              <div key={row.label}>
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className={styles.hint}>No details yet.</p>
        )}
        {answers.length ? (
          <div className={styles.formAnswers}>
            <span className={styles.stepLabel}>Answers from the form</span>
            <dl className={styles.detailRows}>
              {answers.map((field, index) => (
                <div key={`${field.label}-${index}`}>
                  <dt>{field.label}</dt>
                  <dd>{field.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        ) : null}
      </section>

      <section className={styles.panel} aria-label="Owner">
        <div className={styles.ownerRow}>
          <Avatar name={lead.owner_name ?? "No owner"} size={32} />
          <span>
            <strong>
              {lead.owner_name ? `With ${lead.owner_name}` : "No owner yet"}
            </strong>
            {detail.owner_reason ? <small>{detail.owner_reason}</small> : null}
            <small>
              {detail.first_call_minutes != null
                ? `First call ${detail.first_call_minutes} min after it came in`
                : `Not called yet · came in ${ago(lead.created_at)}`}
            </small>
          </span>
          {detail.can_assign ? (
            <select
              aria-label="Move this lead to"
              value=""
              disabled={moving}
              onChange={(event) => {
                const value = event.target.value;
                if (value) void move(value === "__rules" ? null : value);
              }}
            >
              <option value="">Move to…</option>
              <option value="__rules">Whoever the rules pick</option>
              {detail.reps
                .filter((rep) => rep.person_id !== lead.owner_person_id)
                .map((rep) => (
                  <option key={rep.person_id} value={rep.person_id}>
                    {rep.name} · {rep.open_leads} open
                    {rep.available ? "" : " · away"}
                  </option>
                ))}
            </select>
          ) : null}
        </div>
        {moveError ? (
          <p className={styles.error} role="alert">
            {moveError}
          </p>
        ) : null}
      </section>

      <section className={styles.historyBlock} aria-label="History">
        <h3 className={styles.stepLabel}>History</h3>
        {detail.can_edit ? (
          <NoteBox leadId={lead.lead_id} onSaved={onChanged} />
        ) : null}
        <History events={detail.events} />
      </section>
    </div>
  );
}

/* ---------- Lead sheet ---------- */

export function LeadSheet({
  leadId,
  onClose,
  onChanged,
}: {
  leadId: string | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [loaded, setLoaded] = useState<LeadDetail | null>(null);
  const [failed, setFailed] = useState<{
    leadId: string;
    message: string;
  } | null>(null);
  const [formKey, setFormKey] = useState(0);
  const [backFrom, setBackFrom] = useState<string | null>(null);
  // Only the open lead's own detail (or error) shows; anything else is stale.
  const detail = loaded?.lead.lead_id === leadId ? loaded : null;
  const error = failed?.leadId === leadId ? failed.message : null;

  useEffect(() => {
    if (!leadId) return;
    const controller = new AbortController();
    readLead(leadId, controller.signal)
      .then((next) => {
        setFailed(null);
        setLoaded(next);
        setFormKey((value) => value + 1);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setFailed({
          leadId,
          message:
            reason instanceof LeadsError
              ? reason.message
              : "This lead didn't load.",
        });
      });
    return () => controller.abort();
  }, [leadId]);

  const update = (next: LeadDetail) => {
    setLoaded(next);
    setFormKey((value) => value + 1);
    onChanged();
  };

  useCallReturn(leadId, (seconds) => {
    if (!leadId) return;
    setBackFrom(leadId);
    logPhoneCall(leadId, seconds)
      .then(update)
      .catch(() => undefined);
  });

  return (
    <Sheet
      open={leadId !== null}
      label={detail?.lead.name ?? "Lead"}
      onClose={onClose}
    >
      {error ? (
        <Empty icon={PhoneOff} title="This lead didn't open" text={error} />
      ) : detail ? (
        <LeadCard
          detail={detail}
          onChanged={update}
          outcome={
            <CallOutcome
              key={formKey}
              detail={detail}
              submitLabel="Save"
              attention={backFrom === leadId}
              beforeSave={() => logWaitingCall(detail)}
              onSaved={(next) => {
                setBackFrom(null);
                update(next);
              }}
            />
          }
        />
      ) : (
        <div className={styles.sheetLoading} aria-busy="true">
          Opening the lead…
        </div>
      )}
    </Sheet>
  );
}

/* ---------- Start calling ---------- */

export function CallingLoop({
  open,
  onClose,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<LeadDetail | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "done" | "error">(
    "loading",
  );
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(0);
  const [backFrom, setBackFrom] = useState<string | null>(null);

  // The page gives each opening a new key, so a round starts at zero, loading.
  const load = (signal?: AbortSignal) => {
    readNext(undefined, signal)
      .then((next) => {
        setDetail(next);
        setState(next ? "ready" : "done");
      })
      .catch((reason: unknown) => {
        if (signal?.aborted) return;
        setError(
          reason instanceof LeadsError
            ? reason.message
            : "The next lead didn't load.",
        );
        setState("error");
      });
  };

  const loadNext = () => {
    setState("loading");
    load();
  };

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [open]);

  const current =
    open && state === "ready" ? (detail?.lead.lead_id ?? null) : null;
  useCallReturn(current, (seconds) => {
    if (!current) return;
    setBackFrom(current);
    logPhoneCall(current, seconds)
      .then((next) => {
        setDetail(next);
        onChanged();
      })
      .catch(() => undefined);
  });

  return (
    <Sheet open={open} label="Start calling" onClose={onClose}>
      <div className={styles.loopHead}>
        <span className={styles.loopTitle}>Calling</span>
        <span className={styles.hint}>
          {done ? `${done} done this round · ` : ""}One lead at a time. Call,
          then say how it went to get the next one.
        </span>
      </div>
      {state === "loading" ? (
        <div className={styles.sheetLoading} aria-busy="true">
          Finding your next lead…
        </div>
      ) : state === "done" ? (
        <Empty
          icon={CheckCircle2}
          title={
            done ? "That's everyone due right now" : "Nobody to call right now"
          }
          text="New leads and follow-ups appear here as soon as they're due."
          action={{ onClick: onClose, label: "Back to my desk" }}
        />
      ) : state === "error" || !detail ? (
        <Empty
          icon={PhoneOff}
          title="The next lead didn't load"
          text={error ?? undefined}
          action={{ onClick: loadNext, label: "Try again" }}
        />
      ) : (
        <LeadCard
          key={detail.lead.lead_id}
          detail={detail}
          onChanged={(next) => {
            setDetail(next);
            onChanged();
          }}
          outcome={
            <CallOutcome
              key={`${detail.lead.lead_id}-${detail.lead.revision}`}
              detail={detail}
              submitLabel="Save and next lead"
              attention={backFrom === detail.lead.lead_id}
              beforeSave={() => logWaitingCall(detail)}
              onSaved={() => {
                setBackFrom(null);
                setDone((value) => value + 1);
                onChanged();
                loadNext();
              }}
            />
          }
        />
      )}
    </Sheet>
  );
}
