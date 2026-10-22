"use client";

/**
 * One lead, made for calling from a phone: a big Call button, then "How did
 * the call go?" the moment the seller is back from the dialer, then the
 * details, the owner and the history. CallingLoop is NeoDove's "Start": one
 * lead at a time, and the next one appears only after this one is saved.
 */

import {
  CheckCircle2,
  History as HistoryIcon,
  Mail,
  MessageCircle,
  MessageSquareText,
  Mic,
  Pencil,
  Link2,
  Phone,
  PhoneMissed,
  PhoneOff,
  Radio,
  Shuffle,
  Trash2,
  Workflow,
  X,
} from "lucide-react";
import Link from "next/link";
import {
  Fragment,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { callHref, type UploadPolicy } from "../acquisition-client";
import { notify } from "../notice-center";
import { CallFacts } from "../call-engine/call-facts";
import { Avatar, Badge, Button, Empty, Field } from "../ui/kit";
import {
  leadLink,
  addNote,
  ago,
  dispose,
  displayPhone,
  editLead,
  FIELD_LABELS,
  LeadsError,
  localInputValue,
  logPhoneCall,
  movePipeline,
  setCallPrivacy,
  minutesLabel,
  nextCallTime,
  peekPendingCall,
  readLead,
  readNext,
  reassign,
  rememberCall,
  takePendingCall,
  when,
  type CallTime,
  type Desk,
  type LeadDetail,
  type LeadEvent,
  type Stage,
} from "./leads-client";
import { LastCallBrief } from "./call-brief-card";
import {
  chatDays,
  chatDayTitle,
  useLeadConversations,
  type ChatDay,
} from "./lead-chats";
import { CallNext } from "./call-next";
import { chatFacts, chatOrigin } from "./chat-origin";
import { SocialThread } from "./social-thread";
import { WhatsAppThread } from "./whatsapp-thread";
import { sourceText, whyLine } from "./desk-view";
import { firstCallWords, ownerNote } from "./owner-words";
import { phoneCallText } from "./phone-call-text";
import { several, usePipelines } from "./use-pipelines";
import {
  MessageSetup,
  MessageSheet,
  OpenMessage,
  type MessageTarget,
} from "./message-sheet";
import {
  askCallAccess,
  buzz,
  checkWarning,
  forgetCall,
  inPhoneApp,
  missedReason,
  onPhoneCall,
  onPhoneSignal,
  pendingRecordings,
  phoneStatus,
  readLastCall,
  readPhoneRecording,
  recordingHandled,
  setupOpen,
  startPhoneCall,
  type NativeCall,
  type NativeRecording,
  type PendingRecording,
} from "./native-phone";
import {
  pickSimulation,
  readUploadPolicy,
  runRecordingUpload,
  runSimulatedCall,
  STEP_LABELS,
  type SimulationPick,
  type SimulationStep,
} from "./simulated-call";
import { SuggestedStage, SuggestionHint } from "./journey/stage-suggestion";
import { Sheet as KitSheet } from "../ui/sheet";
import { DeleteLeadsSheet, type Doomed } from "./delete-leads";
import deleteStyles from "./delete-leads.module.css";
import styles from "./leads.module.css";

// Sources whose leads arrive with a form's own answers worth showing.
const FORM_SOURCES = new Set(["meta", "webhook", "sheet", "csv", "google_ads"]);

const NO_RETRY = new Set([
  "invalid_number",
  "incoming_not_available",
  "not_in_use",
]);

/* ---------- Sheet ---------- */

/**
 * Every Leads sheet is the kit Sheet (design system v2): phones swipe it away
 * from the top, computers get the floating panel on the right. The label
 * names the dialog; the content brings its own heading.
 */
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
  return (
    <KitSheet
      open={open}
      onClose={onClose}
      title={label}
      hideTitle
      closeButton={false}
      className={styles.sheet}
    >
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
    </KitSheet>
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

const TONES: Record<string, string> = {
  interested: "warm",
  follow_up: "later",
  won: "good",
  lost: "bad",
};

type Choice = {
  id: string;
  key: Stage;
  step?: string;
  label: string;
  sub: string;
  tone: string;
};

/** What a seller picks after a call that connected: the business's own stages
 *  (Lead stages), else the desk's four. */
export function stageChoices(detail: {
  stage_choices?: LeadDetail["stage_choices"];
}): Choice[] {
  const own = (detail.stage_choices ?? []).filter((item) => TONES[item.kind]);
  if (!own.length) return NEXT.map((item) => ({ ...item, id: item.key }));
  return own.map((item) => ({
    id: item.key,
    key: item.kind,
    step: item.key,
    label: item.label,
    sub: item.meaning,
    tone: TONES[item.kind],
  }));
}

/** The stage a lead already has, chosen again after "We talked" (UX study item 6). */
export function stageAfterTalk(stage: Stage): Stage | null {
  return stage === "interested" || stage === "follow_up" ? stage : null;
}

const TIMES: { key: Pick; label: string }[] = [
  { key: "hour", label: "In 1 hour" },
  { key: "evening", label: "This evening" },
  { key: "morning", label: "Tomorrow morning" },
  { key: "week", label: "Next week" },
  { key: "someday", label: "Someday" },
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
  heard = null,
  onStop,
  upNext = null,
  ask = false,
}: {
  detail: LeadDetail;
  submitLabel: string;
  /** L on a computer: this is the step to fill (it comes into view, focused). */
  ask?: boolean;
  /** Call mode: save and end the round here ("Save and stop here"). */
  onStop?: (next: LeadDetail) => void;
  /** Call mode: who comes after this lead, shown above Save. */
  upNext?: ReactNode;
  /** The seller just came back from the dialer: this card asks first. */
  attention: boolean;
  /** What the phone app saw of the call: it pre-fills the answer. */
  heard?: NativeCall | null;
  /** Logs a call still waiting to be logged; returns the lead as it now is. */
  beforeSave: () => Promise<LeadDetail>;
  onSaved: (next: LeadDetail) => void;
}) {
  const id = useId();
  const ref = useRef<HTMLElement>(null);
  const [talk, setTalk] = useState<Talk>(
    heard?.connected === true
      ? "talked"
      : heard?.connected === false
        ? "missed"
        : null,
  );
  const [reason, setReason] = useState<string | null>(
    heard?.connected === false ? missedReason(heard.result) : null,
  );
  // "No answer" from its own tile: the other reasons stay folded away, so
  // Save is right below (Call mode, 22 Oct 2026).
  const [quick, setQuick] = useState(
    () =>
      heard?.connected === false &&
      missedReason(heard.result) === "did_not_pick",
  );
  const lastStage = stageAfterTalk(detail.lead.stage);
  const choices = stageChoices(detail);
  const lastStep =
    lastStage &&
    detail.lead.step &&
    choices.some((item) => item.step === detail.lead.step)
      ? detail.lead.step
      : null;
  const [stage, setStage] = useState<Stage | null>(lastStage);
  const [step, setStep] = useState<string | null>(lastStep);
  // What the last call suggests, when it is one of the choices (Lead stages).
  const suggested =
    detail.stage_suggestion &&
    choices.some((item) => item.step === detail.stage_suggestion?.step)
      ? detail.stage_suggestion
      : null;
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
    const box = ref.current;
    if (!box || (!attention && !ask)) return;
    // The lead's name and Call stay in view (Redmi at 360 px, 22 Oct 2026): the
    // sheet opens at its top and moves only when the question is out of sight.
    if (box.getBoundingClientRect().top > window.innerHeight * 0.7)
      box.scrollIntoView({ behavior: "smooth", block: "center" });
    if (ask)
      box
        .querySelector<HTMLButtonElement>("button")
        ?.focus({ preventScroll: true });
  }, [attention, ask]);
  // Whose call this is, in the question itself (the name may be above the fold).
  const first = detail.lead.name.split(" ")[0];

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
  // Owner, 22 Oct 2026: Save looked dead after "We talked" until a next step
  // was picked, and nothing said so. It now says what is missing, and a tap
  // on it scrolls there.
  const missing = valid
    ? null
    : talk === "missed"
      ? reason === null
        ? "Pick what happened to save"
        : "Pick when to try again to save"
      : stage === null
        ? "Pick what happens next to save"
        : "Pick when to call next to save";
  // Each Save tap with a step missing lights that step once (Redmi, 22 Oct
  // 2026: the hint was on screen already; the step itself should say "here").
  const [nudges, setNudges] = useState(0);
  const nudged = nudges > 0;
  const nudge = nudges ? (nudges % 2 ? "odd" : "even") : undefined;
  const stepRef = useRef<HTMLDivElement>(null);
  const autoRetry =
    reason === null
      ? null
      : NO_RETRY.has(reason)
        ? "No automatic retry for a bad number."
        : `It comes back on the desk ${detail.lead.attempts ? "tomorrow" : "in 1 hour"}.`;

  const openMessage = useContext(OpenMessage);
  const submit = async (after: (next: LeadDetail) => void = onSaved) => {
    if (!valid || saving) return;
    setSaving(true);
    setError(null);
    try {
      const current = await beforeSave();
      const saved = await dispose(current.lead, {
        connected: talk === "talked",
        reason: talk === "missed" ? (reason ?? undefined) : undefined,
        stage: talk === "talked" ? (stage ?? undefined) : undefined,
        step: talk === "talked" ? (step ?? undefined) : undefined,
        follow_up_at: at ? at.toISOString() : undefined,
        remark: note.trim() || undefined,
        deal_value: deal.trim() || undefined,
      });
      buzz("done");
      after(saved);
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

  // Save, or say what is still missing and light that step.
  const trySave = (after?: (next: LeadDetail) => void) => {
    if (valid) {
      void submit(after);
      return;
    }
    setNudges((count) => count + 1);
    stepRef.current?.scrollIntoView?.({
      block: "center",
      behavior: "smooth",
    });
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
          ? `Back from the call with ${first}. How did it go?`
          : `How did the call with ${first} go?`}
      </h3>
      {heard && heardLine(heard) ? (
        <p className={styles.heard}>
          <HistoryIcon size={14} aria-hidden="true" />
          {heardLine(heard)}
        </p>
      ) : null}
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
            setStage((current) => current ?? lastStage);
          }}
        >
          <CheckCircle2 size={22} aria-hidden="true" />
          We talked
        </button>
        {/* The most common miss in one tap (Call mode, 22 Oct 2026). */}
        <button
          type="button"
          className={styles.choiceTile}
          data-kind="missed"
          aria-pressed={talk === "missed" && quick}
          onClick={() => {
            setTalk("missed");
            setQuick(true);
            setReason("did_not_pick");
            setStage(null);
            setStep(null);
          }}
        >
          <PhoneMissed size={22} aria-hidden="true" />
          No answer
        </button>
        <button
          type="button"
          className={styles.choiceTile}
          data-kind="missed"
          aria-pressed={talk === "missed" && !quick}
          data-span="row"
          onClick={() => {
            setTalk("missed");
            if (quick) setReason(null);
            setQuick(false);
            setStage(null);
            setStep(null);
          }}
        >
          <PhoneOff size={22} aria-hidden="true" />
          Didn&apos;t get through
        </button>
      </div>

      {talk === "missed" ? (
        <div
          ref={stepRef}
          className={styles.outcomeStep}
          data-nudge={missing ? nudge : undefined}
        >
          {quick ? null : (
            <>
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
            </>
          )}
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
        <div
          ref={stepRef}
          className={styles.outcomeStep}
          data-nudge={missing ? nudge : undefined}
        >
          <span className={styles.stepLabel}>What happens next?</span>
          {suggested ? (
            <SuggestionHint
              suggestion={suggested}
              active={step === suggested.step}
              onUse={() => {
                setStage(suggested.kind);
                setStep(suggested.step);
              }}
            />
          ) : null}
          <div
            className={styles.stageGrid}
            role="group"
            aria-label="What happens next"
          >
            {choices.map((item) => (
              <button
                key={item.id}
                type="button"
                className={styles.stageTile}
                data-tone={item.tone}
                aria-pressed={
                  item.step
                    ? step === item.step
                    : stage === item.key && step === null
                }
                onClick={() => {
                  setStage(item.key);
                  setStep(item.step ?? null);
                }}
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
      {talk !== null && missing ? (
        <p
          className={styles.saveHint}
          data-nudged={nudged || undefined}
          role="status"
        >
          {missing}
        </p>
      ) : null}
      {talk !== null ? upNext : null}
      {talk !== null ? (
        <div className={styles.saveRow}>
          {openMessage && detail.phone ? (
            <button
              type="button"
              className={styles.saveMessage}
              aria-label={talk === "missed" ? "Message them" : "Send details"}
              onClick={() =>
                openMessage(talk === "missed" ? "missed_call" : "as_promised")
              }
            >
              <MessageCircle size={18} aria-hidden="true" />
              <span className={styles.saveMessageWords}>
                {talk === "missed" ? "Message them" : "Send details"}
              </span>
            </button>
          ) : null}
          <button
            type="button"
            className={styles.saveButton}
            data-incomplete={!valid || undefined}
            onClick={() => trySave()}
            disabled={saving}
          >
            {saving ? "Saving…" : submitLabel}
          </button>
        </div>
      ) : null}
      {talk !== null && onStop ? (
        <button
          type="button"
          className={`${styles.linkButton} ${styles.stopLink}`}
          disabled={saving}
          onClick={() => trySave(onStop)}
        >
          Save and stop here
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

/** The phone app's call, once it has ended, for the open lead. */
function usePhoneAppCall(
  leadId: string | null,
  onCall: (call: NativeCall) => void,
) {
  const latest = useRef(onCall);
  useEffect(() => {
    latest.current = onCall;
  });
  useEffect(() => {
    if (!leadId || !inPhoneApp()) return;
    const take = (call: NativeCall) => {
      if (call.leadId === leadId && call.endedMs) latest.current(call);
    };
    const check = () => {
      if (document.visibilityState !== "visible") return;
      void readLastCall(leadId).then((call) => {
        if (call) take(call);
      });
    };
    const stop = onPhoneCall(take);
    check();
    document.addEventListener("visibilitychange", check);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", check);
    };
  }, [leadId]);
}

/**
 * Inside the phone app: this lead's newest call the phone logged by itself and
 * the recording it found for it (owner, 22 Oct 2026), and whether the phone
 * hides its recordings. Nothing in a browser or an older app.
 */
function usePendingRecording(leadId: string) {
  const [item, setItem] = useState<PendingRecording | null>(null);
  const [hidden, setHidden] = useState(false);
  const read = useCallback(() => {
    void pendingRecordings().then((pending) => {
      if (!pending) return;
      const mine = pending.items.filter((row) => row.leadId === leadId);
      setItem(mine.find((row) => row.recording) ?? null);
      setHidden(pending.needsAllFiles && pending.allFilesSupported);
    });
  }, [leadId]);
  useEffect(() => {
    if (!inPhoneApp()) return;
    read();
    return onPhoneSignal((event) => {
      if (event === "recordings" || event === "calls" || event === "resume")
        read();
    });
  }, [read]);
  const done = useCallback(() => {
    if (!item) return;
    void recordingHandled(item.eventId).then(() => setItem(null));
  }, [item]);
  return { item, hidden, done };
}

function talkTime(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return whole < 60
    ? `${whole} seconds`
    : `${Math.floor(whole / 60)} min ${whole % 60} s`;
}

const HEARD_MISSED: Partial<Record<NativeCall["result"], string>> = {
  no_answer: "nobody answered",
  busy: "the line was busy",
  rejected: "they cut the call",
  failed: "the call didn't go through",
  no_network: "it had no network",
};

function heardLine(call: NativeCall): string {
  if (call.connected === true)
    return `Your phone says you talked for ${talkTime(call.durationSeconds ?? 0)}.`;
  if (call.connected === false)
    return `Your phone says ${HEARD_MISSED[call.result] ?? "the call didn't connect"}.`;
  return "";
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
            title: `Assigned to ${event.owner_name}`,
            detail: ownerNote(event.allocation_reason) ?? undefined,
          }
        : {
            title: "Waiting for an owner",
            detail: ownerNote(event.allocation_reason) ?? undefined,
          };
    case "reassigned":
      return {
        title: `Reassigned from ${event.previous_owner_name ?? "nobody"} to ${event.owner_name ?? "nobody"}`,
        detail: ownerNote(event.allocation_reason) ?? undefined,
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
      if (event.via === "phone") {
        // Its recording joined this call (owner, 22 Oct 2026): one row, with the Report link.
        const text = phoneCallText(event, who);
        return event.recording
          ? { title: text.title, detail: "From the phone dialer · recorded" }
          : text;
      }
      if (event.recording) return { title: `${who} added the call recording` };
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
    case "message":
      return {
        title: `${who} sent ${event.channel === "SMS" ? "an SMS" : "a WhatsApp"}${
          event.template_label ? ` · ${event.template_label}` : ""
        }`,
      };
    case "stage":
      return {
        title: `${who} moved them to ${event.stage_label ?? "a new stage"}`,
        detail: event.note ?? undefined,
      };
    case "scheduled":
      return {
        title: event.next_action_at
          ? `${who} booked the next call for ${when(event.next_action_at)}`
          : `${who} booked the next call`,
      };
    default:
      return { title: event.note ?? "Updated" };
  }
}

/** Mark private (Salestrail's untracked call): the seller's own phone-logged call. */
function PrivacyButton({
  event,
  onChanged,
}: {
  event: LeadEvent;
  onChanged: (next: LeadDetail) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (!event.can_hide || !event.event_id) return null;
  const eventId = event.event_id;
  const flip = async () => {
    setBusy(true);
    setProblem(null);
    try {
      onChanged(await setCallPrivacy(eventId, !event.private));
    } catch (reason) {
      setProblem(
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button
        type="button"
        className={styles.linkButton}
        disabled={busy}
        onClick={() => void flip()}
      >
        {event.private ? "Show to my team" : "Make private"}
      </button>
      {problem ? (
        <span className={styles.error} role="alert">
          {problem}
        </span>
      ) : null}
    </>
  );
}

/**
 * The lead's story in a few lines, before its history (the ease-of-use wave, 22 Oct
 * 2026: "a lead timeline that reads like a story"): where it came from, how often it
 * was tried and talked to, how the last call went, and where it stands now.
 */
export function storyLines(
  detail: LeadDetail,
  now: Date = new Date(),
): string[] {
  const lead = detail.lead;
  const when_ = ago(lead.created_at, now);
  const lines = [
    lead.source === "manual"
      ? `Added by hand ${when_}.`
      : lead.source === "referral"
        ? `Came in ${when_} as a referral.`
        : `Came in ${when_} from ${
            lead.source_label.startsWith("File:")
              ? "a file import"
              : lead.source_label
          }.`,
  ];
  const results = detail.events.filter((event) => event.kind === "result");
  const talks = results.filter((event) => event.connected).length;
  if (!lead.attempts) lines.push("Not called yet.");
  else
    lines.push(
      `Tried ${lead.attempts} time${lead.attempts === 1 ? "" : "s"}${
        talks
          ? `, talked ${talks === 1 ? "once" : `${talks} times`}`
          : ", not reached yet"
      }.`,
    );
  const last = results[0];
  if (last)
    lines.push(
      last.connected
        ? `Last talk ${ago(last.at, now)}: ${last.stage_label ?? "talked"}.`
        : `Last try ${ago(last.at, now)}: ${(last.reason_label ?? "not reached").toLowerCase()}.`,
    );
  lines.push(
    `Now: ${lead.stage_label}${
      lead.next_action_at ? `, next call ${when(lead.next_action_at, now)}` : ""
    }.`,
  );
  return lines;
}

function StorySoFar({ detail }: { detail: LeadDetail }) {
  return (
    <div className={styles.story}>
      <span className={styles.storyTitle}>The story so far</span>
      <ul>
        {storyLines(detail).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </div>
  );
}

/** "Today", "Yesterday" or "Mon 20 Oct": the history's day headers. */
export function dayLabel(iso: string, now: Date = new Date()): string {
  const at = new Date(iso);
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (at.toDateString() === now.toDateString()) return "Today";
  if (at.toDateString() === yesterday.toDateString()) return "Yesterday";
  return at.toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

export function History({
  events,
  onChanged,
  chats = [],
  brief = null,
}: {
  events: LeadEvent[];
  onChanged?: (next: LeadDetail) => void;
  /** The lead's chats, one line per app per day (lead hub, 22 Oct 2026). */
  chats?: ChatDay[];
  /** Under the newest call with a Report: what that call said. */
  brief?: ReactNode;
}) {
  const briefAt = events.findIndex(
    (event) => event.kind === "call" && event.submission_id,
  );
  // Newest first, calls and chats in one line of time.
  const items: { at: string; index: number; chat?: ChatDay }[] = [
    ...events.map((event, index) => ({ at: event.at, index })),
    ...chats.map((chat, index) => ({
      at: chat.at,
      index: events.length + index,
      chat,
    })),
  ];
  if (chats.length)
    items.sort(
      (a, b) => Date.parse(b.at) - Date.parse(a.at) || a.index - b.index,
    );
  return (
    <ol className={styles.history} aria-label="History">
      {items.map((item, position) => {
        const day = dayLabel(item.at);
        const newDay =
          position === 0 || dayLabel(items[position - 1].at) !== day;
        const header = newDay ? (
          <li className={styles.historyDay} aria-hidden="true">
            {day}
          </li>
        ) : null;
        if (item.chat)
          return (
            <Fragment key={item.chat.key}>
              {header}
              <li data-kind="chat">
                <span className={styles.historyTitle}>
                  {chatDayTitle(item.chat)}
                </span>
                {item.chat.last ? (
                  <span className={styles.historyDetail}>
                    {item.chat.last.mine ? "You: " : ""}
                    {item.chat.last.text}
                  </span>
                ) : null}
                <Link
                  className={styles.historyLink}
                  href={item.chat.href}
                  prefetch={false}
                >
                  Open the chat
                </Link>
              </li>
            </Fragment>
          );
        const event = events[item.index];
        const index = item.index;
        const text = eventText(event);
        return (
          <Fragment key={`${event.at}-${index}`}>
            {header}
            <li
              key={`${event.at}-${index}`}
              data-kind={event.kind}
              data-missed={
                event.direction === "missed" || event.direction === "rejected"
                  ? true
                  : undefined
              }
            >
              <span className={styles.historyTitle}>
                {text.title}
                {event.private ? (
                  <span className={styles.privateTag}>Private</span>
                ) : null}
              </span>
              {text.detail ? (
                <span className={styles.historyDetail}>
                  {event.private
                    ? "Only you see this call. It isn't counted."
                    : text.detail}
                </span>
              ) : null}
              {onChanged ? (
                <PrivacyButton event={event} onChanged={onChanged} />
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
            {index === briefAt && brief ? (
              <li className={styles.historyBrief}>{brief}</li>
            ) : null}
          </Fragment>
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
        Sample calls are started by an owner or admin.
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
        Get a sample recording
      </Button>
    );

  return (
    <div className={styles.simulation} aria-live="polite">
      <strong className={styles.simulationTitle}>Sample call</strong>
      {state === "loading" ? (
        <p className={styles.hint}>Getting a sample recording…</p>
      ) : null}
      {pick && (state === "ready" || state === "running") ? (
        <p>
          Uses a {Math.max(1, Math.round(pick.duration_seconds / 60))}-minute
          sample recording as {pick.owner_name}&apos;s call and analyses it like
          a real one. Nobody is dialled.
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
              Analyse the sample call
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

/* ---------- Call recording ---------- */

type Me = Desk["me"];

const UPLOAD_STEPS: SimulationStep[] = [
  "saving",
  "linking",
  "checking",
  "starting",
];
const AUDIO = "audio/*,.m4a,.mp3,.wav,.aac,.amr,.awb,.ogg,.opus,.3gp,.3ga";

function sizeLabel(bytes: number): string {
  return bytes >= 1_000_000
    ? `${(bytes / 1_000_000).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1_000))} KB`;
}

/** After a real call: the phone's own recording becomes this lead's analysed call. */
function RecordingUpload({
  detail,
  me,
  onDone,
  found = null,
  waiting = false,
  next = false,
  onNext,
  callEventId = null,
  hidden = false,
  onAttached,
}: {
  detail: LeadDetail;
  me: Me;
  onDone: (next: LeadDetail) => void;
  /** The call on this lead the recording belongs to (one the phone logged from its dialer). */
  callEventId?: string | null;
  /** The phone hides its call recordings until All files access is allowed (Redmi audit #49). */
  hidden?: boolean;
  /** The recording is on the lead: the phone stops offering it. */
  onAttached?: () => void;
  /** The step after "How did the call go?": in view, with its own heading. */
  next?: boolean;
  /** Start calling: move on to the next lead, with or without analysing. */
  onNext?: () => void;
  /** The phone app found its own recording of the call that just ended. */
  found?: NativeRecording | null;
  /** The phone app is still looking for that recording. */
  waiting?: boolean;
}) {
  const [state, setState] = useState<
    "idle" | "reading" | "ready" | "running" | "done" | "error"
  >("idle");
  const [file, setFile] = useState<File | null>(null);
  // One attempt per chosen file, so trying again never saves the call twice.
  const [attempt, setAttempt] = useState("");
  const [policy, setPolicy] = useState<UploadPolicy | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [step, setStep] = useState<SimulationStep>("saving");
  const [error, setError] = useState<string | null>(null);
  const [submission, setSubmission] = useState<string | null>(null);
  // The phone's own recording of this call, once read: only it joins the call.
  const [picked, setPicked] = useState<File | null>(null);
  const task = useRef<AbortController | null>(null);
  const panel = useRef<HTMLElement>(null);
  const warning = checkWarning(found);
  const silent = found?.check?.verdict === "silent";

  useEffect(() => () => task.current?.abort(), []);
  useEffect(() => {
    if (next)
      panel.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [next]);

  const choose = async (picked: File | undefined) => {
    if (!picked) return;
    setFile(picked);
    setAttempt(crypto.randomUUID());
    setError(null);
    setState("ready");
    if (policy) return;
    try {
      setPolicy(await readUploadPolicy());
    } catch {
      setError("The recording terms didn't load. Try again.");
      setState("error");
    }
  };

  const takeFound = async () => {
    if (!found) return;
    setError(null);
    setState("reading");
    try {
      const file = await readPhoneRecording(found);
      setPicked(file);
      await choose(file);
    } catch {
      setError(
        "Your phone didn't share the recording. Pick it from your files instead.",
      );
      setState("error");
    }
  };

  const run = async () => {
    if (!file || !policy || !agreed) return;
    const controller = new AbortController();
    task.current = controller;
    setState("running");
    setStep("saving");
    setError(null);
    try {
      const next = await runRecordingUpload({
        lead: detail,
        file,
        me,
        policy,
        attempt,
        onStep: setStep,
        signal: controller.signal,
        callEventId: file === picked ? callEventId : null,
      });
      const call = next.events.find(
        (event) => event.kind === "call" && event.recording,
      );
      setSubmission(call?.submission_id ?? null);
      setState("done");
      if (file === picked) onAttached?.();
      onDone(next);
    } catch (reason) {
      if (controller.signal.aborted) return;
      setError(
        reason instanceof LeadsError
          ? reason.message
          : "The recording didn't upload. Check your connection and try again.",
      );
      setState("error");
    }
  };

  const picker = (label: string, sub: string) => (
    <label className={styles.recordPick}>
      <span className={styles.wayIcon}>
        <Mic size={20} aria-hidden="true" />
      </span>
      <span>
        <strong>{label}</strong>
        <small>{sub}</small>
      </span>
      <input
        type="file"
        accept={AUDIO}
        aria-label={label}
        onChange={(event) => {
          void choose(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
    </label>
  );

  return (
    <section
      ref={panel}
      className={styles.panel}
      aria-label="Call recording"
      aria-live="polite"
    >
      <div className={styles.panelHead}>
        <h3>{next ? "Saved. Analyse the call?" : "Call recording"}</h3>
        {state === "done" ? <Badge tone="good">Added</Badge> : null}
      </div>
      {state === "idle" && hidden && !found ? (
        <>
          <p className={styles.recordWarn}>
            Your phone hides its call recordings. Allow All files access so
            Sales Xray can find this call&apos;s recording.
          </p>
          <div className={styles.row}>
            <Button onClick={() => void setupOpen("allFiles")}>
              Allow All files access
            </Button>
          </div>
        </>
      ) : null}
      {state === "idle" && found && warning ? (
        <p className={styles.recordWarn} role="status">
          {warning}
        </p>
      ) : null}
      {state === "idle" && found && !silent ? (
        <button
          type="button"
          className={styles.recordPick}
          data-found=""
          onClick={() => void takeFound()}
        >
          <span className={styles.wayIcon}>
            <Mic size={20} aria-hidden="true" />
          </span>
          <span>
            <strong>Analyse this call&apos;s recording</strong>
            <small>
              Your phone recorded it: {found.name}
              {found.durationMs
                ? ` · ${talkTime(found.durationMs / 1000)}`
                : ""}
            </small>
          </span>
        </button>
      ) : null}
      {state === "idle" && !found && waiting ? (
        <p className={styles.hint}>
          Looking for your phone&apos;s recording of this call…
        </p>
      ) : null}
      {state === "idle"
        ? picker(
            found ? "Pick a different recording" : "Add the recording",
            found
              ? "From your phone's recordings or files."
              : "Pick the call your phone just recorded. Sales Xray analyses it and puts its Report here.",
          )
        : null}
      {state === "reading" ? (
        <p className={styles.hint}>Getting the recording from your phone…</p>
      ) : null}
      {file && (state === "ready" || state === "running") ? (
        <p className={styles.fileLine}>
          <strong>{file.name}</strong>
          <small>{sizeLabel(file.size)} · saved as your call</small>
        </p>
      ) : null}
      {state === "ready" ? (
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
                onChange={(event) => setAgreed(event.target.checked)}
              />
              The customer knows this call is recorded, and I agree to these
              terms
            </label>
            <div className={styles.row}>
              <Button onClick={() => setState("idle")}>Choose another</Button>
              <Button variant="primary" onClick={run} disabled={!agreed}>
                Analyse the call
              </Button>
            </div>
          </>
        ) : (
          <p className={styles.hint}>Getting the recording terms…</p>
        )
      ) : null}
      {state === "running" ? (
        <>
          <ol className={styles.steps}>
            {UPLOAD_STEPS.map((item) => (
              <li
                key={item}
                data-state={
                  UPLOAD_STEPS.indexOf(item) < UPLOAD_STEPS.indexOf(step)
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
          <p className={styles.hint}>
            Keep this open until the analysis starts.
          </p>
        </>
      ) : null}
      {state === "done" ? (
        <p className={styles.hint}>
          Analysis started. The call&apos;s Report appears in a few minutes.{" "}
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
            <Button onClick={() => setState("idle")}>Choose another</Button>
            {file && policy && agreed ? (
              <Button variant="primary" onClick={run}>
                Try again
              </Button>
            ) : null}
          </div>
        </>
      ) : null}
      {onNext && state !== "running" ? (
        <div className={styles.row}>
          <Button
            variant={state === "done" ? "primary" : "secondary"}
            onClick={onNext}
          >
            {state === "done" ? "Next lead" : "Skip, next lead"}
          </Button>
        </div>
      ) : null}
    </section>
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

export function LeadCard({
  detail,
  me,
  onChanged,
  outcome,
  phoneCall = null,
  intent = null,
  afterCall = null,
}: {
  detail: LeadDetail;
  me: Me | null;
  onChanged: (next: LeadDetail) => void;
  outcome: ReactNode;
  /** The phone app's last call to this lead, once it has ended. */
  phoneCall?: NativeCall | null;
  /** Opened by a swipe, a hold or an alert's Call button: do it straight away. */
  intent?: LeadIntent | null;
  /**
   * Back from a call, one step at a time (owner's phone test, 19 Oct): first
   * "How did the call go?" alone, then the recording to analyse. In Start
   * calling the recording step ends with the next lead.
   */
  afterCall?: { step: "outcome" | "recording"; onNext?: () => void } | null;
}) {
  const { lead } = detail;
  const setup = useContext(MessageSetup);
  const waitingRecording = usePendingRecording(lead.lead_id);
  const [permits, setPermits] = useState(false);
  const [calling, setCalling] = useState(false);
  const [messaging, setMessaging] = useState<{
    round: number;
    preset: string | null;
    channel: "whatsapp" | "sms";
  } | null>(null);
  const openMessage = (
    preset: string | null = null,
    channel: "whatsapp" | "sms" = "whatsapp",
  ) =>
    setMessaging((current) => ({
      round: (current?.round ?? 0) + 1,
      preset,
      channel,
    }));
  const target: MessageTarget | null = detail.phone
    ? {
        leadId: lead.lead_id,
        name: lead.name,
        phone: detail.phone,
        interest: lead.interest,
      }
    : null;

  // Inside the phone app the call is placed and followed by the app.
  const callFromApp = async (askFirst: boolean) => {
    if (!detail.phone) return;
    setCalling(true);
    try {
      if (askFirst) await askCallAccess();
      else {
        const status = await phoneStatus();
        if (status && !status.callAccess) {
          setPermits(true);
          return;
        }
      }
      setPermits(false);
      await startPhoneCall({
        leadId: lead.lead_id,
        number: detail.phone,
        name: lead.name,
      });
    } catch {
      setPermits(false);
      rememberCall(lead.lead_id);
      window.location.href = `tel:${detail.phone}`;
    } finally {
      setCalling(false);
    }
  };
  const placeCall = () => {
    if (!detail.phone) return;
    if (inPhoneApp()) void callFromApp(false);
    else {
      rememberCall(lead.lead_id);
      window.location.href = `tel:${detail.phone}`;
    }
  };
  // Once per opening: the intent came with this lead.
  const acted = useRef(false);
  const act = useRef<() => void>(() => undefined);
  useEffect(() => {
    act.current = () => (intent === "call" ? placeCall() : openMessage(null));
  });
  useEffect(() => {
    // "log" only opens the call's outcome; nothing to place or write.
    if (!intent || intent === "log" || acted.current) return;
    if (!detail.phone || !detail.can_edit) return;
    acted.current = true;
    act.current();
  }, [intent, detail.phone, detail.can_edit]);
  const [editing, setEditing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [moving, setMoving] = useState(false);
  const [picking, setPicking] = useState(false);
  const [find, setFind] = useState("");
  const others = detail.reps.filter(
    (rep) => rep.person_id !== lead.owner_person_id,
  );
  const needle = find.trim().toLocaleLowerCase();
  const shownReps = needle
    ? others.filter((rep) => rep.name.toLocaleLowerCase().includes(needle))
    : others;
  const [moveError, setMoveError] = useState<string | null>(null);
  // The lead's chats, read once for the timeline and the chat sections.
  const conversations = useLeadConversations(lead.lead_id);
  const chats = chatDays(lead.lead_id, conversations.wa, conversations.social);
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
  // A lead that began as a chat has no form either: never Meta's raw ids.
  const origin = chatOrigin(lead);
  const answers = !FORM_SOURCES.has(lead.source)
    ? []
    : origin
      ? chatFacts(detail.source_fields)
      : detail.source_fields;

  const move = async (personId: string | null) => {
    setMoving(true);
    setMoveError(null);
    try {
      onChanged(await reassign(lead, personId));
      setPicking(false);
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
            <CopyLeadLink leadId={lead.lead_id} />
          </div>
        </div>
      </header>
      <p className={styles.why}>{whyLine(lead)}</p>
      <SuggestedStage detail={detail} onChanged={onChanged} />
      {detail.next_action_note ? (
        <p className={styles.nextNote}>Last note: {detail.next_action_note}</p>
      ) : null}

      <div className={styles.actions} data-contact="">
        {detail.phone ? (
          <a
            className={styles.callButton}
            href={`tel:${detail.phone}`}
            aria-busy={calling || undefined}
            onClick={(event) => {
              if (inPhoneApp()) {
                event.preventDefault();
                void callFromApp(false);
              } else rememberCall(lead.lead_id);
            }}
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
          // Owner, 19 Oct: clean WhatsApp and SMS buttons beside Call.
          <>
            <button
              type="button"
              className={styles.contactIcon}
              data-channel="whatsapp"
              aria-label="WhatsApp"
              onClick={() => openMessage(null, "whatsapp")}
            >
              <WhatsAppGlyph />
              <small aria-hidden="true">WhatsApp</small>
            </button>
            <button
              type="button"
              className={styles.contactIcon}
              data-channel="sms"
              aria-label="SMS"
              onClick={() => openMessage(null, "sms")}
            >
              <MessageSquareText size={22} aria-hidden="true" />
              <small aria-hidden="true">SMS</small>
            </button>
          </>
        ) : null}
        {detail.email ? (
          <a className={styles.actionButton} href={`mailto:${detail.email}`}>
            <Mail size={18} aria-hidden="true" />
            Email
          </a>
        ) : null}
      </div>
      {permits ? (
        <section className={styles.permits} aria-label="Allow calling">
          <h3>Call from Sales Xray</h3>
          <p>Your phone asks you to allow three things, once:</p>
          <ul>
            <li>
              <strong>Phone</strong> to place the call
            </li>
            <li>
              <strong>Call history</strong> to see whether it connected and for
              how long
            </li>
            <li>
              <strong>Music and audio</strong> to find your phone&apos;s
              recording of the call
            </li>
          </ul>
          <p className={styles.hint}>
            Nothing leaves your phone until you choose to analyse a recording.
          </p>
          <div className={styles.row}>
            <Button
              onClick={() => {
                setPermits(false);
                rememberCall(lead.lead_id);
                window.location.href = `tel:${detail.phone}`;
              }}
            >
              Just call
            </Button>
            <Button variant="primary" onClick={() => void callFromApp(true)}>
              Allow and call
            </Button>
          </div>
        </section>
      ) : null}
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

      <OpenMessage.Provider value={target ? openMessage : null}>
        {detail.can_edit && afterCall?.step !== "recording" ? outcome : null}
      </OpenMessage.Provider>
      {target ? (
        <MessageSheet
          key={messaging?.round ?? 0}
          open={messaging !== null}
          target={target}
          templates={setup.templates}
          myName={setup.myName || me?.name || ""}
          org={setup.org}
          preset={messaging?.preset}
          channel={messaging?.channel}
          onClose={() => setMessaging(null)}
          onLogged={onChanged}
        />
      ) : null}
      {detail.can_edit &&
      detail.call_mode === "phone" &&
      me &&
      afterCall?.step !== "outcome" &&
      (lead.calls > 0 || phoneCall) ? (
        <RecordingUpload
          detail={detail}
          me={me}
          onDone={onChanged}
          found={
            phoneCall?.recording ?? waitingRecording.item?.recording ?? null
          }
          waiting={phoneCall ? !phoneCall.final : false}
          next={afterCall?.step === "recording"}
          onNext={afterCall?.onNext}
          callEventId={
            phoneCall ? null : (waitingRecording.item?.eventId ?? null)
          }
          hidden={waitingRecording.hidden}
          onAttached={phoneCall ? undefined : waitingRecording.done}
        />
      ) : null}

      {/* Owner, 19 Oct: every call becomes data. What the calls told us, and
          the few things the engine is unsure of, asked one at a time. */}
      <CallFacts detail={detail} onChanged={onChanged} />

      {/* The lead hub (approved map, slice 6, 22 Oct 2026): under the call, one
          line of time: calls (the newest with what it said and its Report),
          chats one line a day, notes and stage changes. Then the chats
          themselves, then about the lead. */}
      <section className={styles.historyBlock} aria-label="History">
        <StorySoFar detail={detail} />
        <h3 className={styles.stepLabel}>History</h3>
        {detail.can_edit ? (
          <NoteBox leadId={lead.lead_id} onSaved={onChanged} />
        ) : null}
        <History
          events={detail.events}
          onChanged={onChanged}
          chats={chats}
          brief={<LastCallBrief detail={detail} onChanged={onChanged} />}
        />
      </section>

      <WhatsAppThread
        leadId={lead.lead_id}
        canSend={detail.can_edit}
        shared={{ chat: conversations.wa }}
      />
      <SocialThread
        leadId={lead.lead_id}
        canSend={detail.can_edit}
        shared={{ chat: conversations.social }}
      />

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
            <span className={styles.stepLabel}>
              {origin ? "From the chat" : "Answers from the form"}
            </span>
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

      {/* Owner, 18 Oct: "With X · 0 open leads (fewest)" and "Move to…" were
          not intuitive. It says who has the lead, why, and offers Reassign. */}
      <section className={styles.panel} aria-label="Owner">
        <div className={styles.ownerRow}>
          <Avatar name={lead.owner_name ?? "No owner"} size={32} />
          <span>
            <strong>
              {!lead.owner_name
                ? "Not assigned yet"
                : me && lead.owner_person_id === me.person_id
                  ? "Assigned to you"
                  : `Assigned to ${lead.owner_name}`}
            </strong>
            {ownerNote(detail.owner_reason) ? (
              <small>{ownerNote(detail.owner_reason)}</small>
            ) : null}
            <small>
              {firstCallWords(detail.first_call_minutes, ago(lead.created_at))}
            </small>
          </span>
          {detail.can_assign && detail.reps.length ? (
            <Button
              aria-expanded={picking}
              disabled={moving}
              onClick={() => {
                setMoveError(null);
                setPicking((open) => !open);
              }}
            >
              <Shuffle size={14} aria-hidden="true" />
              {lead.owner_name ? "Reassign" : "Assign"}
            </Button>
          ) : null}
        </div>
        {picking ? (
          <div
            className={styles.reassignList}
            role="group"
            aria-label={lead.owner_name ? "Reassign to" : "Assign to"}
          >
            <span className={styles.stepLabel}>
              {lead.owner_name ? "Reassign to" : "Assign to"}
            </span>
            <button
              type="button"
              className={styles.repPick}
              disabled={moving}
              onClick={() => void move(null)}
            >
              <span className={styles.repPickIcon} aria-hidden="true">
                <Shuffle size={15} />
              </span>
              <span>
                <strong>Let the lead rules pick</strong>
                <small>
                  Whoever is free, fits this lead and has the fewest open leads
                </small>
              </span>
            </button>
            {others.length > 6 ? (
              <input
                className={styles.repFind}
                type="search"
                value={find}
                placeholder="Find a person"
                aria-label="Find a person"
                onChange={(event) => setFind(event.target.value)}
              />
            ) : null}
            <div className={styles.repPeople}>
              {shownReps.map((rep) => (
                <button
                  key={rep.person_id}
                  type="button"
                  className={styles.repPick}
                  disabled={moving}
                  onClick={() => void move(rep.person_id)}
                >
                  <Avatar name={rep.name} size={28} />
                  <span>
                    <strong>{rep.name}</strong>
                    <small>
                      {rep.open_leads} open lead
                      {rep.open_leads === 1 ? "" : "s"}
                      {rep.available ? "" : " · away now"}
                    </small>
                  </span>
                </button>
              ))}
              {shownReps.length ? null : (
                <p className={styles.hint}>Nobody by that name.</p>
              )}
            </div>
          </div>
        ) : null}
        {moveError ? (
          <p className={styles.error} role="alert">
            {moveError}
          </p>
        ) : null}
      </section>

      {detail.can_assign ? (
        <PipelinePanel detail={detail} onChanged={onChanged} />
      ) : null}
    </div>
  );
}

/** This lead's own link, to send a teammate or keep (Liquid Glass, 22 Oct 2026). */
function CopyLeadLink({ leadId }: { leadId: string }) {
  const copy = async () => {
    const link = leadLink(leadId, window.location.origin);
    try {
      await navigator.clipboard.writeText(link);
      notify({
        id: "lead-link",
        tone: "success",
        title: "Link copied",
        message: "It opens this lead for anyone in your organisation.",
        timeout: 4000,
      });
    } catch {
      notify({
        id: "lead-link",
        tone: "error",
        title: "This browser didn't copy it",
        message: link,
      });
    }
  };
  return (
    <button
      type="button"
      className={styles.copyLink}
      onClick={() => void copy()}
    >
      <Link2 size={13} aria-hidden="true" />
      Copy link
    </button>
  );
}

/* ---------- Lead sheet ---------- */

/** What a lead opens for: a call, a message, or saying how a call went (L). */
export type LeadIntent = "call" | "message" | "log";

/**
 * Which pipeline the lead is in, and a move to another (owners and admins, when the
 * organisation runs several; owner, 22 Oct 2026). It keeps its owner and follow-ups
 * and lands in the new pipeline's stage for where it is.
 */
function PipelinePanel({
  detail,
  onChanged,
}: {
  detail: LeadDetail;
  onChanged: (next: LeadDetail) => void;
}) {
  const pipes = usePipelines();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (!several(pipes)) return null;
  const lead = detail.lead;
  const here = lead.pipeline ?? "main";
  const name =
    pipes.pipelines.find((item) => item.key === here)?.name ?? "Leads";
  return (
    <section className={styles.panel} aria-label="Pipeline">
      <div className={styles.ownerRow}>
        <span className={styles.pipelineMark} aria-hidden="true">
          <Workflow size={16} />
        </span>
        <span>
          <small>Pipeline</small>
          <strong>{name}</strong>
        </span>
        <label className={styles.pipelineMove}>
          <span className={styles.srOnly}>Move to pipeline</span>
          <select
            value=""
            disabled={busy}
            onChange={async (event) => {
              const key = event.target.value;
              if (!key) return;
              setBusy(true);
              setProblem(null);
              try {
                onChanged(await movePipeline(lead, key));
              } catch (reason) {
                setProblem(
                  reason instanceof LeadsError
                    ? reason.message
                    : "Not moved. Try again.",
                );
              } finally {
                setBusy(false);
              }
            }}
          >
            <option value="">{busy ? "Moving…" : "Move to…"}</option>
            {pipes.pipelines
              .filter((item) => item.key !== here)
              .map((item) => (
                <option key={item.key} value={item.key}>
                  {item.name}
                </option>
              ))}
          </select>
        </label>
      </div>
      {problem ? (
        <p className={styles.error} role="alert">
          {problem}
        </p>
      ) : null}
    </section>
  );
}

export function LeadSheet({
  leadId,
  me,
  onClose,
  onChanged,
  intent = null,
  onNext,
}: {
  leadId: string | null;
  me: Me | null;
  onClose: () => void;
  onChanged: () => void;
  /** Do this as soon as the lead is open (swipe, hold, an alert's Call). */
  intent?: LeadIntent | null;
  /** After an outcome is saved: call the next lead on the desk. */
  onNext?: (leadId: string) => void;
}) {
  // Saved here: who is next on the desk, so one tap calls them (the
  // ease-of-use wave, 22 Oct 2026: "Call next" everywhere, not only in
  // Start calling).
  const [nextUp, setNextUp] = useState<{
    after: string;
    lead: LeadDetail | null;
  } | null>(null);
  const [loaded, setLoaded] = useState<LeadDetail | null>(null);
  const [failed, setFailed] = useState<{
    leadId: string;
    message: string;
  } | null>(null);
  // "Try again" on a lead that didn't open reads it once more.
  const [attempt, setAttempt] = useState(0);
  const [formKey, setFormKey] = useState(0);
  const [backFrom, setBackFrom] = useState<string | null>(null);
  const [heard, setHeard] = useState<NativeCall | null>(null);
  const logged = useRef("");
  const [answered, setAnswered] = useState(0);
  // Owners and admins: Delete lead, confirmed in its own sheet (21 Oct 2026).
  const [removing, setRemoving] = useState<{
    round: number;
    open: boolean;
    lead: Doomed;
  } | null>(null);
  const phoneCall = heard?.leadId === leadId ? heard : null;
  // The phone's call pre-fills the answer until that answer is saved.
  const asked =
    phoneCall && phoneCall.startedMs !== answered ? phoneCall : null;
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
  }, [leadId, attempt]);

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

  usePhoneAppCall(leadId, (call) => {
    setHeard(call);
    const key = `${call.leadId}:${call.startedMs}`;
    if (logged.current !== key) {
      logged.current = key;
      setBackFrom(call.leadId);
      logPhoneCall(call.leadId, call.durationSeconds ?? 0)
        .then(update)
        .catch(() => undefined);
    }
    if (call.final) void forgetCall(call.leadId);
  });

  return (
    <>
      <Sheet
        open={leadId !== null}
        label={detail?.lead.name ?? "Lead"}
        onClose={onClose}
      >
        {error ? (
          <Empty
            icon={PhoneOff}
            title="This lead didn't open"
            text={error}
            action={{
              label: "Try again",
              onClick: () => {
                setFailed(null);
                setAttempt((value) => value + 1);
              },
            }}
          />
        ) : detail ? (
          <>
            <LeadCard
              detail={detail}
              me={me}
              onChanged={update}
              phoneCall={phoneCall}
              intent={intent}
              afterCall={
                backFrom === leadId || asked || intent === "log"
                  ? { step: "outcome" }
                  : null
              }
              outcome={
                <CallOutcome
                  key={`${formKey}-${asked?.startedMs ?? 0}`}
                  detail={detail}
                  submitLabel="Save"
                  heard={asked}
                  attention={backFrom === leadId}
                  ask={intent === "log"}
                  beforeSave={() => logWaitingCall(detail)}
                  onSaved={(next) => {
                    setBackFrom(null);
                    if (asked) setAnswered(asked.startedMs);
                    update(next);
                    if (onNext && leadId) {
                      const after = leadId;
                      readNext(after).then(
                        (lead) => setNextUp({ after, lead }),
                        () => undefined,
                      );
                    }
                  }}
                />
              }
            />
            {detail.can_assign ? (
              <div className={deleteStyles.leadFoot}>
                <button
                  type="button"
                  className={deleteStyles.deleteLead}
                  onClick={() =>
                    setRemoving((current) => ({
                      round: (current?.round ?? 0) + 1,
                      open: true,
                      lead: {
                        lead_id: detail.lead.lead_id,
                        name: detail.lead.name,
                      },
                    }))
                  }
                >
                  <Trash2 size={15} aria-hidden="true" />
                  Delete lead
                </button>
              </div>
            ) : null}
            {onNext && nextUp && nextUp.after === leadId ? (
              <CallNext lead={nextUp.lead} saved onCall={onNext} />
            ) : null}
          </>
        ) : (
          <div className={styles.sheetLoading} aria-busy="true">
            Opening the lead…
          </div>
        )}
      </Sheet>
      {removing ? (
        <DeleteLeadsSheet
          key={removing.round}
          open={removing.open && removing.lead.lead_id === leadId}
          leads={[removing.lead]}
          onClose={() =>
            setRemoving((current) => current && { ...current, open: false })
          }
          onDeleted={() => {
            setRemoving((current) => current && { ...current, open: false });
            onClose();
            onChanged();
          }}
        />
      ) : null}
    </>
  );
}

/* ---------- Start calling ---------- */

export function CallingLoop({
  open,
  me,
  onClose,
  onChanged,
}: {
  open: boolean;
  me: Me | null;
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
  const [heard, setHeard] = useState<NativeCall | null>(null);
  const logged = useRef("");
  // Saved "How did it go?": the recording step, then the next lead.
  const [recordingStep, setRecordingStep] = useState<string | null>(null);
  // Call mode (approved map, slice 3, 22 Oct 2026): who comes after the lead on
  // screen is read while it is open, so one tap saves and calls them.
  const [upNext, setUpNext] = useState<{
    after: string;
    lead: LeadDetail | null;
  } | null>(null);
  // The lead "Save and call <name>" opened: its card places the call once.
  const [dialing, setDialing] = useState<string | null>(null);

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
    setRecordingStep(null);
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
  useEffect(() => {
    if (!current) return;
    const controller = new AbortController();
    readNext(current, controller.signal)
      .then((lead) => setUpNext({ after: current, lead }))
      .catch(() => undefined);
    return () => controller.abort();
  }, [current]);
  // Unknown yet (still reading), nobody, or the next lead.
  const following =
    upNext && upNext.after === current ? upNext.lead : undefined;
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

  usePhoneAppCall(current, (call) => {
    setHeard(call);
    const key = `${call.leadId}:${call.startedMs}`;
    if (logged.current !== key) {
      logged.current = key;
      setBackFrom(call.leadId);
      logPhoneCall(call.leadId, call.durationSeconds ?? 0)
        .then((next) => {
          setDetail(next);
          onChanged();
        })
        .catch(() => undefined);
    }
    if (call.final) void forgetCall(call.leadId);
  });
  const phoneCall = heard && heard.leadId === current ? heard : null;
  // A phone call with a recording: Save leads to the recording step first.
  const recordingFirst = detail?.call_mode === "phone" && !!phoneCall;

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
          me={me}
          phoneCall={phoneCall}
          intent={dialing === detail.lead.lead_id ? "call" : null}
          onChanged={(next) => {
            setDetail(next);
            onChanged();
          }}
          afterCall={
            recordingStep === detail.lead.lead_id
              ? { step: "recording", onNext: loadNext }
              : backFrom === detail.lead.lead_id
                ? { step: "outcome" }
                : null
          }
          outcome={
            <CallOutcome
              key={`${detail.lead.lead_id}-${detail.lead.revision}-${phoneCall?.startedMs ?? 0}`}
              detail={detail}
              submitLabel={
                recordingFirst
                  ? "Save and next lead"
                  : following
                    ? `Save and call ${following.lead.name.split(" ")[0]}`
                    : following === null
                      ? "Save and finish"
                      : "Save and next lead"
              }
              heard={phoneCall}
              attention={backFrom === detail.lead.lead_id}
              beforeSave={() => logWaitingCall(detail)}
              upNext={
                following ? (
                  <p className={styles.upNextLine}>
                    Next: <strong>{following.lead.name}</strong> ·{" "}
                    {whyLine(following.lead)}
                  </p>
                ) : following === null ? (
                  <p className={styles.upNextLine}>
                    Nobody else is due after this one.
                  </p>
                ) : null
              }
              onSaved={(saved) => {
                setBackFrom(null);
                setDone((value) => value + 1);
                onChanged();
                // A phone call with a recording to analyse: that step first.
                if (saved.call_mode === "phone" && phoneCall) {
                  setDetail(saved);
                  setRecordingStep(saved.lead.lead_id);
                } else if (following) {
                  // The tap that saved is the tap that calls the next lead.
                  setRecordingStep(null);
                  setDetail(following);
                  setDialing(following.lead.lead_id);
                } else if (following === null) setState("done");
                else loadNext();
              }}
              onStop={
                recordingFirst
                  ? undefined
                  : () => {
                      setBackFrom(null);
                      setDone((value) => value + 1);
                      onChanged();
                      onClose();
                    }
              }
            />
          }
        />
      )}
    </Sheet>
  );
}

/** WhatsApp's mark, drawn in the button's own colour (simple-icons, CC0). */
function WhatsAppGlyph() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="22"
      height="22"
      aria-hidden="true"
      fill="currentColor"
    >
      <path d="M17.47 14.38c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.17-.17.2-.35.22-.65.07-.3-.15-1.26-.46-2.4-1.47-.89-.79-1.49-1.77-1.66-2.07-.17-.3-.02-.46.13-.61.13-.13.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.02-.52-.08-.15-.67-1.62-.92-2.22-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.79.37-.27.3-1.04 1.02-1.04 2.48s1.07 2.88 1.21 3.08c.15.2 2.1 3.2 5.08 4.49.71.31 1.26.49 1.69.63.71.22 1.36.19 1.87.12.57-.09 1.76-.72 2.01-1.41.25-.69.25-1.29.17-1.41-.07-.12-.27-.2-.57-.35M12.05 21.79h-.01a9.87 9.87 0 0 1-5.03-1.38l-.36-.21-3.74.98 1-3.65-.24-.37a9.86 9.86 0 0 1-1.51-5.26c0-5.45 4.44-9.88 9.89-9.88a9.82 9.82 0 0 1 6.99 2.9 9.82 9.82 0 0 1 2.89 6.99c0 5.45-4.44 9.88-9.88 9.88m8.41-18.3A11.81 11.81 0 0 0 12.05 0C5.5 0 .16 5.34.16 11.89c0 2.1.55 4.14 1.59 5.95L.06 24l6.31-1.65a11.88 11.88 0 0 0 5.68 1.45h.01c6.55 0 11.89-5.34 11.89-11.89 0-3.18-1.24-6.16-3.48-8.41" />
    </svg>
  );
}
