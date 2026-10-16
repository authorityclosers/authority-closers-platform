"use client";

/**
 * One lead: its card, NeoDove's dispose screen and its history, in a side
 * sheet. CallingLoop is NeoDove's "Start": one lead at a time, and the next
 * one appears only after this one is disposed.
 */

import { CheckCircle2, Phone, PhoneOff, Radio, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { callHref, type UploadPolicy } from "../acquisition-client";
import { Avatar, Badge, Button, Empty, Field } from "../ui/kit";
import {
  addNote,
  ago,
  CONNECTED_STAGES,
  dispose,
  editLead,
  FIELD_LABELS,
  LeadsError,
  localInputValue,
  minutesLabel,
  NOT_CONNECTED_REASONS,
  quickFollowUp,
  readLead,
  readNext,
  reassign,
  when,
  type LeadDetail,
  type LeadEvent,
  type Stage,
} from "./leads-client";
import { whyLine } from "./desk-view";
import {
  pickSimulation,
  readUploadPolicy,
  runSimulatedCall,
  STEP_LABELS,
  type SimulationPick,
  type SimulationStep,
} from "./simulated-call";
import styles from "./leads.module.css";

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

/* ---------- Dispose ("Was the call connected?") ---------- */

type Follow = "hour" | "tomorrow" | "week" | "custom" | null;

export function DisposeForm({
  detail,
  submitLabel,
  onSaved,
}: {
  detail: LeadDetail;
  submitLabel: string;
  onSaved: (next: LeadDetail) => void;
}) {
  const id = useId();
  const [connected, setConnected] = useState<boolean | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage | null>(null);
  const [follow, setFollow] = useState<Follow>(null);
  const [custom, setCustom] = useState(() =>
    localInputValue(quickFollowUp("tomorrow")),
  );
  const [remark, setRemark] = useState("");
  const [deal, setDeal] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const closes = stage === "won" || stage === "lost";
  const needsFollow = connected === true && stage !== null && !closes;
  const followAt =
    follow === null
      ? null
      : follow === "custom"
        ? custom
          ? new Date(custom)
          : null
        : quickFollowUp(follow);
  const valid =
    connected === false
      ? reason !== null
      : connected === true &&
        stage !== null &&
        (!needsFollow ||
          (followAt !== null && !Number.isNaN(followAt.getTime())));
  const retryNote =
    connected === false && reason
      ? NO_RETRY.has(reason)
        ? "No automatic retry for a bad number."
        : `If you don't pick a time, it comes back ${detail.lead.attempts ? "tomorrow" : "in 1 hour"}.`
      : null;

  const submit = async () => {
    if (!valid || saving) return;
    setSaving(true);
    setError(null);
    try {
      const next = await dispose(detail.lead, {
        connected: connected === true,
        reason: connected === false ? (reason ?? undefined) : undefined,
        stage: connected === true ? (stage ?? undefined) : undefined,
        follow_up_at:
          followAt && (needsFollow || connected === false)
            ? followAt.toISOString()
            : undefined,
        remark: remark.trim() || undefined,
        deal_value: deal.trim() || undefined,
      });
      onSaved(next);
    } catch (reason) {
      setError(
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.",
      );
    } finally {
      setSaving(false);
    }
  };

  const chip = (
    key: string,
    label: string,
    on: boolean,
    pick: () => void,
    tone?: string,
  ) => (
    <button
      key={key}
      type="button"
      className={styles.chip}
      aria-pressed={on}
      data-tone={tone}
      onClick={pick}
    >
      {label}
    </button>
  );

  return (
    <section className={styles.dispose} aria-labelledby={`${id}-q`}>
      <h3 id={`${id}-q`} className={styles.disposeQuestion}>
        Was the call connected?
      </h3>
      <div className={styles.connectRow}>
        <button
          type="button"
          className={styles.connectButton}
          aria-pressed={connected === true}
          data-kind="yes"
          onClick={() => {
            setConnected(true);
            setReason(null);
          }}
        >
          <CheckCircle2 size={16} aria-hidden="true" />
          Yes, connected
        </button>
        <button
          type="button"
          className={styles.connectButton}
          aria-pressed={connected === false}
          data-kind="no"
          onClick={() => {
            setConnected(false);
            setStage(null);
          }}
        >
          <PhoneOff size={16} aria-hidden="true" />
          Not connected
        </button>
      </div>

      {connected === false ? (
        <div className={styles.disposeBlock}>
          <span className={styles.blockLabel}>Why didn't it connect?</span>
          <div className={styles.chips} role="group" aria-label="Reason">
            {NOT_CONNECTED_REASONS.map((item) =>
              chip(item.key, item.label, reason === item.key, () =>
                setReason(item.key),
              ),
            )}
          </div>
          {retryNote ? <p className={styles.hint}>{retryNote}</p> : null}
        </div>
      ) : null}

      {connected === true ? (
        <div className={styles.disposeBlock}>
          <span className={styles.blockLabel}>Where does the lead stand?</span>
          <div className={styles.chips} role="group" aria-label="Stage">
            {CONNECTED_STAGES.map((item) =>
              chip(
                item.key,
                item.label,
                stage === item.key,
                () => setStage(item.key),
                item.key === "won"
                  ? "good"
                  : item.key === "lost"
                    ? "bad"
                    : undefined,
              ),
            )}
          </div>
          {stage === "won" || stage === "lost" ? (
            <p className={styles.hint}>
              {stage === "won" ? "Won" : "Lost"} closes the lead. It reopens if
              they get in touch again.
            </p>
          ) : null}
        </div>
      ) : null}

      {connected !== null &&
      (connected === false ? reason : stage && !closes) ? (
        <div className={styles.disposeBlock}>
          <span className={styles.blockLabel}>
            {connected ? "Next follow-up" : "Try again (optional)"}
          </span>
          <div
            className={styles.chips}
            role="group"
            aria-label="Follow-up time"
          >
            {chip("hour", "One hour", follow === "hour", () =>
              setFollow("hour"),
            )}
            {chip("tomorrow", "Tomorrow", follow === "tomorrow", () =>
              setFollow("tomorrow"),
            )}
            {chip("week", "Next week", follow === "week", () =>
              setFollow("week"),
            )}
            {chip("custom", "Pick a time", follow === "custom", () =>
              setFollow("custom"),
            )}
          </div>
          {follow === "custom" ? (
            <Field label="Follow-up date and time">
              <input
                type="datetime-local"
                value={custom}
                min={localInputValue(new Date())}
                onChange={(event) => setCustom(event.target.value)}
              />
            </Field>
          ) : followAt ? (
            <p className={styles.hint}>
              Follow up {when(followAt.toISOString())}.
            </p>
          ) : null}
        </div>
      ) : null}

      {connected !== null ? (
        <div className={styles.disposeFields}>
          {connected && (stage === "interested" || stage === "won") ? (
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
          <Field label="Notes from the call" wide>
            <textarea
              value={remark}
              maxLength={1000}
              placeholder={
                connected
                  ? "What they said, what you promised"
                  : "Anything to know before the next try"
              }
              onChange={(event) => setRemark(event.target.value)}
            />
          </Field>
        </div>
      ) : null}

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      <div className={styles.disposeActions}>
        <Button variant="primary" onClick={submit} disabled={!valid || saving}>
          {saving ? "Saving…" : submitLabel}
        </Button>
      </div>
    </section>
  );
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
        title: `${who} ${event.simulated ? "made a simulated call" : "called"}${
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
                Open the call's Report
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
        Simulated calls are started by an owner or admin for now. Real calling
        comes once the calling provider is approved.
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
        Simulated call
      </Button>
    );

  return (
    <div className={styles.simulation} aria-live="polite">
      <strong className={styles.simulationTitle}>Simulated call</strong>
      {state === "loading" ? (
        <p className={styles.hint}>Finding a test recording for this lead…</p>
      ) : null}
      {pick && (state === "ready" || state === "running") ? (
        <p>
          A {Math.max(1, Math.round(pick.duration_seconds / 60))}-minute test
          call ({pick.language_mix}, {pick.business_name}) becomes{" "}
          {pick.owner_name}&apos;s call and goes through the normal analysis.
          Nobody is dialled. It uses about{" "}
          {Math.max(1, Math.round(pick.duration_seconds / 60))} analysis
          minutes.
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
            I agree to these upload terms for this test recording
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
    <section className={styles.dispose} aria-label="Edit details">
      <div className={styles.formGrid}>
        {EDITABLE.map((key) => (
          <Field key={key} label={FIELD_LABELS[key]}>
            <input
              value={form[key]}
              maxLength={key === "email" ? 320 : key === "phone" ? 40 : 200}
              inputMode={
                key === "phone" ? "tel" : key === "email" ? "email" : undefined
              }
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
    </section>
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
      <Field label="Add a note">
        <textarea
          value={note}
          maxLength={1000}
          placeholder="Anything the next caller should know"
          onChange={(event) => setNote(event.target.value)}
        />
      </Field>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      <div className={styles.row}>
        <Button onClick={save} disabled={saving || !note.trim()}>
          {saving ? "Saving…" : "Add note"}
        </Button>
      </div>
    </div>
  );
}

/* ---------- Lead card ---------- */

function LeadCard({
  detail,
  onChanged,
  dispose: disposeSlot,
}: {
  detail: LeadDetail;
  onChanged: (next: LeadDetail) => void;
  dispose: ReactNode;
}) {
  const { lead } = detail;
  const [moving, setMoving] = useState(false);
  const [moveError, setMoveError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const sub = [lead.company, lead.city, lead.language]
    .filter(Boolean)
    .join(" · ");

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
      <header className={styles.cardHead}>
        <Avatar name={lead.name} size={44} />
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
            <Badge>{lead.source_label}</Badge>
            {lead.test_data ? <Badge tone="warn">Test data</Badge> : null}
            {detail.can_edit && !editing ? (
              <Button variant="ghost" onClick={() => setEditing(true)}>
                Edit details
              </Button>
            ) : null}
          </div>
        </div>
      </header>
      {editing ? (
        <EditDetails
          detail={detail}
          onCancel={() => setEditing(false)}
          onSaved={(next) => {
            setEditing(false);
            onChanged(next);
          }}
        />
      ) : null}

      <div className={styles.contact}>
        {detail.phone ? (
          <>
            <a className={styles.dial} href={`tel:${detail.phone}`}>
              <Phone size={16} aria-hidden="true" />
              {detail.phone}
            </a>
            <span className={styles.hint}>
              Dial from your phone, then record what happened below.
            </span>
          </>
        ) : (
          <span className={styles.hint}>No phone number on this lead.</span>
        )}
        {detail.email ? (
          <span className={styles.contactLine}>{detail.email}</span>
        ) : null}
        {detail.call_mode === "simulated" && detail.can_edit ? (
          <SimulatedCall detail={detail} onDone={onChanged} />
        ) : null}
      </div>

      <p className={styles.why}>{whyLine(lead)}</p>
      {detail.next_action_note ? (
        <p className={styles.nextNote}>Last note: {detail.next_action_note}</p>
      ) : null}

      <div className={styles.owner}>
        <span>
          {lead.owner_name ? `With ${lead.owner_name}` : "No owner yet"}
          {detail.owner_reason ? <small>{detail.owner_reason}</small> : null}
          <small>
            {detail.first_call_minutes != null
              ? `First call ${detail.first_call_minutes} min after it came in`
              : `Not called yet · came in ${ago(lead.created_at)}`}
          </small>
        </span>
        {detail.can_assign ? (
          <span className={styles.ownerControls}>
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
          </span>
        ) : null}
      </div>
      {moveError ? (
        <p className={styles.error} role="alert">
          {moveError}
        </p>
      ) : null}

      {detail.can_edit ? disposeSlot : null}

      {detail.fields.length ? (
        <dl className={styles.fields}>
          {detail.fields.map((field) => (
            <div key={field.label}>
              <dt>{field.label}</dt>
              <dd>{field.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {detail.source_fields.length ? (
        <details className={styles.sourceFields}>
          <summary>
            Everything the source sent ({detail.source_fields.length})
          </summary>
          <dl className={styles.fields}>
            {detail.source_fields.map((field, index) => (
              <div key={`${field.label}-${index}`}>
                <dt>{field.label}</dt>
                <dd>{field.value}</dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}

      <section className={styles.historyBlock} aria-label="History">
        <h3 className={styles.blockLabel}>History</h3>
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
  const [detail, setDetail] = useState<LeadDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formKey, setFormKey] = useState(0);

  useEffect(() => {
    if (!leadId) return;
    const controller = new AbortController();
    setDetail(null);
    setError(null);
    readLead(leadId, controller.signal)
      .then(setDetail)
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          reason instanceof LeadsError
            ? reason.message
            : "This lead didn't load.",
        );
      });
    return () => controller.abort();
  }, [leadId]);

  const update = (next: LeadDetail) => {
    setDetail(next);
    setFormKey((value) => value + 1);
    onChanged();
  };

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
          dispose={
            <DisposeForm
              key={formKey}
              detail={detail}
              submitLabel="Save"
              onSaved={update}
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

  const load = (signal?: AbortSignal) => {
    setState("loading");
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

  useEffect(() => {
    if (!open) return;
    setDone(0);
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [open]);

  return (
    <Sheet open={open} label="Start calling" onClose={onClose}>
      <div className={styles.loopHead}>
        <span className={styles.loopTitle}>Calling</span>
        <span className={styles.hint}>
          {done ? `${done} done this round · ` : ""}One lead at a time. Save
          what happened to get the next one.
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
          action={{ onClick: () => load(), label: "Try again" }}
        />
      ) : (
        <LeadCard
          key={detail.lead.lead_id}
          detail={detail}
          onChanged={(next) => {
            setDetail(next);
            onChanged();
          }}
          dispose={
            <DisposeForm
              key={`${detail.lead.lead_id}-${detail.lead.revision}`}
              detail={detail}
              submitLabel="Save and next lead"
              onSaved={() => {
                setDone((value) => value + 1);
                onChanged();
                load();
              }}
            />
          }
        />
      )}
    </Sheet>
  );
}
