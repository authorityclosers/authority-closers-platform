"use client";

/**
 * Hold a lead in a list (or right-click it) for its quick actions, as Kylas
 * and Privyr do: call, message, book the next call or move it to someone else,
 * without opening the lead.
 */

import { CalendarClock, MessageCircle, Phone, UserRound } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "../ui/kit";
import { Picker } from "../ui/picker";
import { ActionSheet } from "./action-sheet";
import { whyLine } from "./desk-view";
import {
  LeadsError,
  readLead,
  reassign,
  setFollowUp,
  when,
  type LeadDetail,
  type LeadRow,
} from "./leads-client";
import { buzz } from "./native-phone";
import { ReminderTime, reminderAt, type ReminderPick } from "./reminder-time";
import styles from "./leads.module.css";

export function LeadActions({
  row,
  canManage,
  onClose,
  onCall,
  onMessage,
  onOpen,
  onChanged,
}: {
  row: LeadRow | null;
  canManage: boolean;
  onClose: () => void;
  onCall: (row: LeadRow) => void;
  onMessage: (row: LeadRow) => void;
  onOpen: (leadId: string) => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<LeadDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  // Book the next call: a preset books at once; a picked date and time waits
  // for Book (owner, 22 Nov 2026: the shared reminder times).
  const [pick, setPick] = useState<ReminderPick | null>(null);
  const [custom, setCustom] = useState("");
  const leadId = row?.lead_id ?? null;

  // The owners list (managers) and the lead's current revision.
  useEffect(() => {
    if (!leadId) return;
    const controller = new AbortController();
    readLead(leadId, controller.signal)
      .then((next) =>
        setDetail({ ...next, reps: Array.isArray(next.reps) ? next.reps : [] }),
      )
      .catch(() => undefined);
    return () => controller.abort();
  }, [leadId]);

  if (!row) return null;
  const current = detail?.lead.lead_id === row.lead_id ? detail.lead : row;
  const reachable = !!row.phone_last4;
  const closed = row.stage === "won" || row.stage === "lost";

  const book = async (choice: ReminderPick, picked: string = custom) => {
    if (busy) return;
    const at = reminderAt(choice, picked, new Date(), detail?.work_hours);
    if (!at) return;
    if (at.getTime() < Date.now() - 30_000) {
      setError("That time has passed. Pick a later one.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await setFollowUp(current, at);
      buzz("done");
      setDone(`Next call ${when(at.toISOString())}`);
      onChanged();
      window.setTimeout(onClose, 700);
    } catch (reason) {
      setError(
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  const move = async (personId: string | null) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await reassign(current, personId);
      buzz("done");
      onChanged();
      onClose();
    } catch (reason) {
      setError(
        reason instanceof LeadsError ? reason.message : "Not moved. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <ActionSheet open title={row.name} sub={whyLine(row)} onClose={onClose}>
      <div className={styles.quickActions}>
        <button
          type="button"
          className={styles.quickAction}
          data-kind="call"
          disabled={!reachable}
          onClick={() => onCall(row)}
        >
          <Phone size={20} aria-hidden="true" />
          Call
        </button>
        <button
          type="button"
          className={styles.quickAction}
          data-kind="message"
          disabled={!reachable}
          onClick={() => onMessage(row)}
        >
          <MessageCircle size={20} aria-hidden="true" />
          Message
        </button>
        <button
          type="button"
          className={styles.quickAction}
          onClick={() => onOpen(row.lead_id)}
        >
          <UserRound size={20} aria-hidden="true" />
          Open
        </button>
      </div>
      {closed ? null : (
        <div className={styles.outcomeStep}>
          <span className={styles.stepLabel}>
            <CalendarClock size={14} aria-hidden="true" /> Book the next call
          </span>
          <ReminderTime
            pick={pick}
            custom={custom}
            hours={detail?.work_hours ?? null}
            onPick={(next) => {
              setPick(next);
              if (next !== "custom") void book(next);
            }}
            onCustom={setCustom}
          />
          {pick === "custom" ? (
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => void book("custom")}
            >
              Book the next call
            </Button>
          ) : null}
        </div>
      )}
      {canManage && detail?.reps.length ? (
        <label className={styles.messageField}>
          <span className={styles.stepLabel}>Reassign</span>
          <Picker
            title="Reassign"
            mode="inline"
            value={null}
            disabled={busy}
            placeholder={
              row.owner_name
                ? `Assigned to ${row.owner_name}`
                : "Not assigned yet"
            }
            options={[
              { key: "__rules", label: "Let the lead rules pick" },
              ...detail.reps
                .filter((rep) => rep.person_id !== row.owner_person_id)
                .map((rep) => ({
                  key: rep.person_id,
                  label: `${rep.name} · ${rep.open_leads} open${rep.available ? "" : " · away"}`,
                })),
            ]}
            onChange={(key) => {
              if (key) void move(key === "__rules" ? null : key);
            }}
          />
        </label>
      ) : null}
      {done ? (
        <p className={styles.doneLine} role="status">
          {done}
        </p>
      ) : null}
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
    </ActionSheet>
  );
}
