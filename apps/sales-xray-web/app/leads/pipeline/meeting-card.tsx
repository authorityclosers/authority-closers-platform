"use client";

/**
 * The lead's booked meeting (Lead OS): when, how, Join. It happened (the lead
 * moves to the meeting-held stage, with the next follow-up), Reschedule (the
 * same meeting moves; its history keeps the old time), or Didn't happen
 * (missed or cancelled, and where the lead stands now).
 */

import { CalendarClock, Video } from "lucide-react";
import { useState } from "react";

import { notify } from "../../notice-center";
import { tick } from "../../ui/haptics";
import { Button, kitStyles } from "../../ui/kit";
import { Sheet } from "../../ui/sheet";
import { LeadsError, when, type LeadDetail } from "../leads-client";
import {
  EMPTY_MEETING,
  MeetingBlock,
  NcReasonBlock,
  NoteBlock,
  WhenBlock,
  capital,
  meetingReady,
  meetingStart,
  whenOf,
  type MeetingDraft,
  type WhenPick,
} from "./blocks";
import {
  meetingDone,
  meetingNotHeld,
  scheduleMeeting,
  type MeetingView,
} from "./pipeline-client";
import styles from "./pipeline.module.css";

type Mode = "done" | "move" | "not_held" | null;

export function meetingLine(
  meeting: Pick<MeetingView, "starts_at" | "mode_label">,
) {
  return `${capital(when(meeting.starts_at))} · ${meeting.mode_label}`;
}

export function MeetingCard({
  detail,
  onChanged,
}: {
  detail: LeadDetail;
  onChanged: (next: LeadDetail) => void;
}) {
  const meeting = detail.meeting;
  const [mode, setMode] = useState<Mode>(null);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState("");
  const [pick, setPick] = useState<WhenPick | null>(null);
  const [custom, setCustom] = useState("");
  const [draft, setDraft] = useState<MeetingDraft>(EMPTY_MEETING);
  const [status, setStatus] = useState<"missed" | "cancelled">("missed");
  const [step, setStep] = useState<string | null>(null);
  const [ncReason, setNcReason] = useState<string | null>(null);
  if (!meeting) return null;
  const lead = detail.lead;
  // Where it can go when the meeting didn't happen: open stages, not the held one.
  const where = (detail.moves ?? []).filter(
    (move) =>
      move.group === "active" &&
      move.milestone !== "appointment_done" &&
      !move.needs.includes("meeting"),
  );
  const chosen = where.find((move) => move.step === step) ?? null;
  const at = whenOf(pick, custom);

  const open = (next: Mode) => {
    setNote("");
    setPick(null);
    setCustom("");
    setStep(null);
    setNcReason(null);
    setDraft({ ...EMPTY_MEETING, mode: meeting.mode });
    setMode(next);
  };
  const run = async (work: () => Promise<LeadDetail>) => {
    setSaving(true);
    try {
      onChanged(await work());
      tick();
      setMode(null);
    } catch (reason) {
      if (reason instanceof LeadsError && reason.kept) {
        // Kept on this phone and sent when Sales X-Ray answers: saved, not failed
        // (durable sync, 41b2e08d), so nobody taps Save again.
        notify({
          id: `meeting-${meeting.meeting_id}`,
          tone: "info",
          title: "Saved on this phone",
          message: "It's sent as soon as Sales X-Ray answers.",
        });
        setMode(null);
        return;
      }
      notify({
        id: `meeting-${meeting.meeting_id}`,
        tone: "error",
        title: "Not saved",
        message: reason instanceof LeadsError ? reason.message : "Try again.",
      });
    } finally {
      setSaving(false);
    }
  };
  const ready =
    mode === "done"
      ? at !== null
      : mode === "move"
        ? meetingReady(draft)
        : mode === "not_held"
          ? chosen !== null &&
            (chosen.kind === "not_connected"
              ? ncReason !== null
              : !chosen.needs.includes("next_action") || at !== null)
          : false;
  const save = () => {
    if (!ready || saving) return;
    if (mode === "done")
      void run(() =>
        meetingDone(lead, meeting.meeting_id, {
          note: note.trim() || undefined,
          next_action_at: at?.toISOString(),
        }),
      );
    else if (mode === "move") {
      const start = meetingStart(draft);
      if (!start || !draft.mode) return;
      void run(() =>
        scheduleMeeting(lead, {
          starts_at: start.toISOString(),
          mode: draft.mode ?? meeting.mode,
          link: draft.link.trim() || undefined,
          location: draft.location.trim() || undefined,
        }),
      );
    } else if (mode === "not_held" && chosen)
      void run(() =>
        meetingNotHeld(lead, meeting.meeting_id, {
          status,
          step: chosen.step,
          nc_reason: ncReason ?? undefined,
          next_action_at: at?.toISOString(),
          note: note.trim() || undefined,
        }),
      );
  };
  const titles = {
    done: "How did the meeting go?",
    move: "Move the meeting",
    not_held: "The meeting didn't happen",
  } as const;
  const buttons = {
    done: "Save: it happened",
    move: "Move the meeting",
    not_held: "Save where they stand",
  } as const;

  return (
    <section className={styles.meetingCard} aria-label="Meeting">
      <div className={styles.meetingHead}>
        <CalendarClock size={20} aria-hidden="true" />
        <div className={styles.meetingText}>
          <strong>{meetingLine(meeting)}</strong>
          {meeting.location ? <span>{meeting.location}</span> : null}
        </div>
        {meeting.link ? (
          <a
            className={kitStyles.button}
            data-variant="secondary"
            href={meeting.link}
            target="_blank"
            rel="noopener noreferrer"
          >
            <Video size={16} aria-hidden="true" />
            Join
          </a>
        ) : null}
      </div>
      {detail.can_edit ? (
        <div className={styles.chips}>
          <button
            type="button"
            className={styles.chip}
            onClick={() => open("done")}
          >
            It happened
          </button>
          <button
            type="button"
            className={styles.chip}
            onClick={() => open("move")}
          >
            Reschedule
          </button>
          <button
            type="button"
            className={styles.chip}
            onClick={() => open("not_held")}
          >
            Didn&apos;t happen
          </button>
        </div>
      ) : null}
      <Sheet
        open={mode !== null}
        onClose={() => setMode(null)}
        title={mode ? titles[mode] : "Meeting"}
        footer={
          mode ? (
            <div className={styles.sheetFooter}>
              <Button
                variant="primary"
                className={styles.wide}
                disabled={!ready || saving}
                aria-busy={saving || undefined}
                onClick={save}
              >
                {buttons[mode]}
              </Button>
            </div>
          ) : null
        }
      >
        <div className={styles.sheetBody}>
          {mode === "done" ? (
            <>
              <NoteBlock
                label="What was discussed"
                value={note}
                onChange={setNote}
              />
              <WhenBlock
                label="Next follow-up"
                pick={pick}
                custom={custom}
                required
                onPick={setPick}
                onCustom={setCustom}
              />
            </>
          ) : null}
          {mode === "move" ? (
            <MeetingBlock draft={draft} onChange={setDraft} />
          ) : null}
          {mode === "not_held" ? (
            <>
              <div
                className={styles.chips}
                role="group"
                aria-label="What happened"
              >
                {(["missed", "cancelled"] as const).map((item) => (
                  <button
                    key={item}
                    type="button"
                    className={styles.chip}
                    aria-pressed={status === item}
                    onClick={() => setStatus(item)}
                  >
                    {item === "missed" ? "They missed it" : "Cancelled"}
                  </button>
                ))}
              </div>
              <fieldset className={styles.block}>
                <legend className={styles.blockLabel}>
                  Where do they stand now?
                </legend>
                <div className={styles.chips}>
                  {where.map((move) => (
                    <button
                      key={move.step}
                      type="button"
                      className={styles.chip}
                      aria-pressed={step === move.step}
                      onClick={() => setStep(move.step)}
                    >
                      {move.label}
                    </button>
                  ))}
                </div>
              </fieldset>
              {chosen?.kind === "not_connected" ? (
                <NcReasonBlock value={ncReason} onPick={setNcReason} />
              ) : null}
              {chosen && chosen.kind !== "not_connected" ? (
                <WhenBlock
                  label="Next follow-up"
                  pick={pick}
                  custom={custom}
                  required={chosen.needs.includes("next_action")}
                  onPick={setPick}
                  onCustom={setCustom}
                />
              ) : null}
              <NoteBlock value={note} onChange={setNote} />
            </>
          ) : null}
        </div>
      </Sheet>
    </section>
  );
}
