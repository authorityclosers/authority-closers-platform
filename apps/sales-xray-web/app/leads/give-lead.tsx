"use client";

/**
 * A seller gives their own lead to a colleague, always with a reason (owner, Wise Life,
 * 19 Nov 2026: "reassign with a reason (escalation/importance), and a setting per
 * organisation: sellers may reassign on/off"). Shown only when the server says this
 * person may (`can_give`: the lead is theirs and the workspace switched it on); owners
 * and admins move leads with the owner picker as before. The reason and its note go on
 * the lead's history. Built from the kit's own sheet, rows, field and buttons: no look
 * of its own (UI lane, 18 Nov 2026).
 *
 * Round-2 board 3 (owner's pick C, 20 Nov 2026): one sheet, not two steps. Who (each
 * colleague's open leads, and "away now"), Why (required) and a note, then Give lead;
 * the lead's own owner is not offered.
 */
import { ArrowRightLeft, Check, Circle } from "lucide-react";
import { useState } from "react";
import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { ActionList, ActionRow, Avatar, Button, Field } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import styles from "./give-lead.module.css";
import {
  LeadsError,
  REASSIGN_REASONS,
  reassign,
  type LeadDetail,
  type ReassignReason,
} from "./leads-client";

export function GiveLead({
  detail,
  onGiven,
}: {
  detail: LeadDetail;
  /** The lead after the move: it is no longer this seller's. */
  onGiven: (next: LeadDetail) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!detail.can_give || !colleagues(detail).length) return null;
  return (
    <>
      <Button
        variant="secondary"
        aria-haspopup="dialog"
        data-sx-feature="give_lead_open"
        onClick={() => setOpen(true)}
      >
        <ArrowRightLeft size={16} aria-hidden="true" />
        Give lead
      </Button>
      <GiveLeadSheet
        detail={detail}
        open={open}
        onClose={() => setOpen(false)}
        onGiven={(next) => {
          setOpen(false);
          onGiven(next);
        }}
      />
    </>
  );
}

/** Who may take it: the team, less whoever has it now. */
function colleagues(detail: LeadDetail) {
  return detail.reps.filter(
    (rep) => rep.person_id !== detail.lead.owner_person_id,
  );
}

/** A chosen row's mark: a tick in a filled circle, else an empty one. */
function Mark({ on }: { on: boolean }) {
  return on ? (
    <Check
      className={styles.chosen}
      size={20}
      strokeWidth={2.5}
      aria-label="Chosen"
    />
  ) : (
    <Circle className={styles.free} size={20} aria-hidden="true" />
  );
}

export function GiveLeadSheet({
  detail,
  open,
  onClose,
  onGiven,
}: {
  detail: LeadDetail;
  open: boolean;
  onClose: () => void;
  onGiven: (next: LeadDetail) => void;
}) {
  const [to, setTo] = useState<string | null>(null);
  const [reason, setReason] = useState<ReassignReason | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const team = colleagues(detail);
  const person = team.find((rep) => rep.person_id === to) ?? null;
  const needsNote = reason === "other" && !note.trim();
  const ready = !!person && !!reason && !needsNote && !busy;
  const close = () => {
    setTo(null);
    setReason(null);
    setNote("");
    onClose();
  };
  const give = async () => {
    if (!person || !reason || needsNote || busy) return;
    setBusy(true);
    try {
      const next = await reassign(detail.lead, person.person_id, undefined, {
        reason,
        note: note.trim() || undefined,
      });
      notify({
        id: "give-lead",
        tone: "success",
        title: `Given to ${displayName(person.name)}`,
        message: "They have it now; the reason is on its history.",
      });
      setTo(null);
      setReason(null);
      setNote("");
      onGiven(next);
    } catch (problem) {
      notify({
        id: "give-lead",
        tone: "error",
        title: "Not given",
        message:
          problem instanceof LeadsError
            ? problem.message
            : "That didn't work. Try again.",
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet
      open={open}
      onClose={close}
      title={`Give ${detail.lead.name} to…`}
      wide="center"
      footer={
        <>
          <Button variant="secondary" disabled={busy} onClick={close}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!ready}
            data-sx-feature="give_lead_sent"
            onClick={() => void give()}
          >
            {busy ? "Giving…" : "Give lead"}
          </Button>
        </>
      }
    >
      <p className={styles.ask}>Who takes it</p>
      <ActionList label="Colleagues">
        {team.map((rep) => (
          <ActionRow
            key={rep.person_id}
            icon={
              <Avatar
                name={displayName(rep.name)}
                photoUrl={rep.photo_url}
                size={32}
              />
            }
            title={displayName(rep.name)}
            note={`${rep.open_leads} open lead${rep.open_leads === 1 ? "" : "s"}${rep.available ? "" : " · away now"}`}
            end={<Mark on={to === rep.person_id} />}
            chevron={false}
            disabled={busy}
            onClick={() => setTo(rep.person_id)}
          />
        ))}
      </ActionList>
      <p className={styles.ask}>
        Why? <span className={styles.needed}>Needed</span>
      </p>
      <ActionList label="Why">
        {REASSIGN_REASONS.map((item) => (
          <ActionRow
            key={item.key}
            title={item.label}
            end={<Mark on={reason === item.key} />}
            chevron={false}
            disabled={busy}
            onClick={() => setReason(item.key)}
          />
        ))}
      </ActionList>
      <Field
        label={reason === "other" ? "Why, in a few words" : "Note (optional)"}
      >
        <textarea
          value={note}
          maxLength={300}
          rows={2}
          onChange={(event) => setNote(event.target.value)}
        />
      </Field>
    </Sheet>
  );
}
