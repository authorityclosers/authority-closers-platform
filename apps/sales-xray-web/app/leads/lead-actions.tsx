"use client";

/**
 * Hold a lead in a list (or right-click it) for its quick actions, as Kylas
 * and Privyr do: call, message, book the next call or move it to someone else,
 * without opening the lead.
 */

import { CalendarClock, MessageCircle, Phone, UserRound } from "lucide-react";
import { useEffect, useState } from "react";

import { ActionSheet } from "./action-sheet";
import { whyLine } from "./desk-view";
import {
  LeadsError,
  nextCallTime,
  readLead,
  reassign,
  setFollowUp,
  when,
  type CallTime,
  type LeadDetail,
  type LeadRow,
} from "./leads-client";
import { buzz } from "./native-phone";
import styles from "./leads.module.css";

const TIMES: { key: CallTime; label: string }[] = [
  { key: "hour", label: "In 1 hour" },
  { key: "evening", label: "This evening" },
  { key: "morning", label: "Tomorrow morning" },
  { key: "week", label: "Next week" },
];

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
  const leadId = row?.lead_id ?? null;

  // The owners list (managers) and the lead's current revision.
  useEffect(() => {
    if (!leadId) return;
    const controller = new AbortController();
    readLead(leadId, controller.signal)
      .then(setDetail)
      .catch(() => undefined);
    return () => controller.abort();
  }, [leadId]);

  if (!row) return null;
  const current = detail?.lead.lead_id === row.lead_id ? detail.lead : row;
  const reachable = !!row.phone_last4;
  const closed = row.stage === "won" || row.stage === "lost";

  const book = async (choice: CallTime) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const at = nextCallTime(choice);
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
          <div className={styles.chips} role="group" aria-label="Next call">
            {TIMES.map((item) => (
              <button
                key={item.key}
                type="button"
                className={styles.chip}
                disabled={busy}
                onClick={() => void book(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {canManage && detail?.reps.length ? (
        <label className={styles.messageField}>
          <span className={styles.stepLabel}>Reassign</span>
          <select
            value=""
            disabled={busy}
            onChange={(event) => {
              const value = event.target.value;
              if (value) void move(value === "__rules" ? null : value);
            }}
          >
            <option value="">
              {row.owner_name
                ? `Assigned to ${row.owner_name}`
                : "Not assigned yet"}
            </option>
            <option value="__rules">Let the lead rules pick</option>
            {detail.reps
              .filter((rep) => rep.person_id !== row.owner_person_id)
              .map((rep) => (
                <option key={rep.person_id} value={rep.person_id}>
                  {rep.name} · {rep.open_leads} open
                  {rep.available ? "" : " · away"}
                </option>
              ))}
          </select>
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
