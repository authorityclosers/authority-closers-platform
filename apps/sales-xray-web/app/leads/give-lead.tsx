"use client";

/**
 * A seller gives their own lead to a colleague, always with a reason (owner, Wise Life,
 * 19 Nov 2026: "reassign with a reason (escalation/importance), and a setting per
 * organisation: sellers may reassign on/off"). Shown only when the server says this
 * person may (`can_give`: the lead is theirs and the workspace switched it on); owners
 * and admins move leads with the owner picker as before. The reason and its note go on
 * the lead's history. Built from the kit's own sheet, rows, field and buttons: no look
 * of its own (UI lane, 18 Nov 2026).
 */
import { ArrowRightLeft, UsersRound } from "lucide-react";
import { useState } from "react";
import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { ActionList, ActionRow, Button, Field } from "../ui/kit";
import { Sheet } from "../ui/sheet";
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
  if (!detail.can_give || !detail.reps.length) return null;
  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        <ArrowRightLeft size={16} aria-hidden="true" />
        Give to a colleague
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
  const person = detail.reps.find((rep) => rep.person_id === to) ?? null;
  const needsNote = reason === "other" && !note.trim();
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
      title={
        person ? `Give to ${displayName(person.name)}` : "Give to a colleague"
      }
      wide="center"
      footer={
        person ? (
          <Button
            variant="primary"
            disabled={!reason || needsNote || busy}
            onClick={() => void give()}
          >
            {busy ? "Giving…" : "Give lead"}
          </Button>
        ) : null
      }
    >
      {person === null ? (
        <ActionList label="Colleagues">
          {detail.reps.map((rep) => (
            <ActionRow
              key={rep.person_id}
              icon={<UsersRound size={20} />}
              title={displayName(rep.name)}
              note={`${rep.open_leads} open lead${rep.open_leads === 1 ? "" : "s"}${rep.available ? "" : " · away now"}`}
              onClick={() => setTo(rep.person_id)}
            />
          ))}
        </ActionList>
      ) : (
        <>
          <ActionList label="Why">
            {REASSIGN_REASONS.map((item) => (
              <ActionRow
                key={item.key}
                title={item.label}
                note={reason === item.key ? "Chosen" : undefined}
                chevron={false}
                disabled={busy}
                onClick={() => setReason(item.key)}
              />
            ))}
          </ActionList>
          <Field
            label={
              reason === "other" ? "Why, in a few words" : "Note (optional)"
            }
          >
            <textarea
              value={note}
              maxLength={300}
              rows={2}
              onChange={(event) => setNote(event.target.value)}
            />
          </Field>
          <Button variant="ghost" disabled={busy} onClick={() => setTo(null)}>
            Someone else
          </Button>
        </>
      )}
    </Sheet>
  );
}
