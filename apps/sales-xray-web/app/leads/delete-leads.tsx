"use client";

/**
 * Delete chosen leads for good (owner, 21 Oct 2026: "a simple option with
 * confirmation for the deletion of certain leads, for example test leads").
 *
 * Owners and admins pick leads in All leads (Select) or open one lead, then
 * confirm once in a sheet that says how many, shows the first few names and
 * says it can't be undone. A problem shows as a corner card and the sheet
 * stays open: Delete again sends the same command, so nothing goes twice.
 */

import { Check, Trash2 } from "lucide-react";
import { useState } from "react";

import { notify } from "../notice-center";
import { Avatar, Badge, Button } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import {
  commandId,
  deleteLeads,
  DELETE_LIMIT,
  LeadsError,
  type LeadRow,
  type LeadsDeleted,
} from "./leads-client";
import styles from "./delete-leads.module.css";

/** A lead to delete: its id, and its name for the confirm. */
export type Doomed = { lead_id: string; name: string };

/** How many names the confirm shows before "and N more". */
export const NAMES_SHOWN = 5;

const plural = (count: number, one: string, many: string) =>
  `${count} ${count === 1 ? one : many}`;

export function deleteTitle(leads: Doomed[]): string {
  return leads.length === 1
    ? `Delete ${leads[0].name}?`
    : `Delete ${plural(leads.length, "lead", "leads")}?`;
}

export function deletedWords(result: LeadsDeleted, leads: Doomed[]): string {
  if (result.deleted === 0)
    return leads.length === 1
      ? "This lead was already deleted."
      : "These leads were already deleted.";
  if (result.deleted === 1 && leads.length === 1)
    return `${leads[0].name} deleted.`;
  return `${plural(result.deleted, "lead", "leads")} deleted.`;
}

/**
 * The one confirm. Mount a fresh sheet (a new key) for each confirm, so each
 * gets its own command id.
 */
export function DeleteLeadsSheet({
  open,
  leads,
  onClose,
  onDeleted,
}: {
  open: boolean;
  leads: Doomed[];
  onClose: () => void;
  onDeleted: (result: LeadsDeleted) => void;
}) {
  const [command] = useState(commandId);
  const [busy, setBusy] = useState(false);
  const one = leads.length === 1;
  const shown = leads.slice(0, NAMES_SHOWN);
  const more = leads.length - shown.length;
  const confirm = async () => {
    if (busy || !leads.length) return;
    setBusy(true);
    try {
      const result = await deleteLeads(
        leads.map((lead) => lead.lead_id),
        command,
      );
      notify({
        id: "lead-delete",
        tone: "success",
        title: deletedWords(result, leads),
        timeout: 5000,
      });
      onDeleted(result);
    } catch (reason) {
      notify({
        id: "lead-delete",
        tone: "error",
        title: one ? "The lead wasn't deleted" : "The leads weren't deleted",
        message:
          reason instanceof LeadsError
            ? reason.message
            : "Sales X-Ray isn't answering. Try again.",
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet
      open={open}
      onClose={() => {
        if (!busy) onClose();
      }}
      title={deleteTitle(leads)}
      description="This can't be undone."
      lead={
        <span className={styles.mark} aria-hidden="true">
          <Trash2 size={18} />
        </span>
      }
      closeButton={false}
      wide="center"
      className={styles.sheet}
      footer={
        <div className={styles.actions}>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Cancel
          </Button>
          <button
            type="button"
            className={styles.danger}
            disabled={busy || !leads.length}
            onClick={() => void confirm()}
          >
            <Trash2 size={15} aria-hidden="true" />
            {busy
              ? "Deleting…"
              : one
                ? "Delete lead"
                : `Delete ${plural(leads.length, "lead", "leads")}`}
          </button>
        </div>
      }
    >
      <ul className={styles.names} aria-label={one ? "Lead" : "Leads"}>
        {shown.map((lead) => (
          <li key={lead.lead_id}>
            <Avatar name={lead.name} size={24} />
            <span>{lead.name}</span>
          </li>
        ))}
        {more > 0 ? <li className={styles.more}>and {more} more</li> : null}
      </ul>
      <p className={styles.text}>
        {one ? "It leaves" : "They leave"} Leads for good, with{" "}
        {one ? "its" : "their"} history, notes, follow-ups and chat messages.
      </p>
      <p className={styles.keep}>
        Calls recorded with {one ? "this lead" : "them"} stay in Calls.
      </p>
    </Sheet>
  );
}

/** A lead row in Select: tap to tick it. */
export function SelectLine({
  row,
  selected,
  onToggle,
}: {
  row: LeadRow;
  selected: boolean;
  onToggle: (row: LeadRow) => void;
}) {
  const sub = [row.interest, row.company, row.city].filter(Boolean).join(" · ");
  return (
    <li className={styles.line}>
      <button
        type="button"
        role="checkbox"
        aria-checked={selected}
        className={styles.pick}
        onClick={() => onToggle(row)}
      >
        <span className={styles.box} data-on={selected || undefined}>
          {selected ? (
            <Check size={14} strokeWidth={3} aria-hidden="true" />
          ) : null}
        </span>
        <span className={styles.main}>
          <span className={styles.name}>
            <span className={styles.nameText}>{row.name}</span>
            {row.test_data ? <span className={styles.test}>Test</span> : null}
          </span>
          <span className={styles.sub}>
            {sub || row.owner_name || "No owner yet"}
          </span>
        </span>
        <Badge
          tone={
            row.stage === "won"
              ? "good"
              : row.stage === "lost"
                ? "bad"
                : "neutral"
          }
        >
          {row.stage_label}
        </Badge>
      </button>
    </li>
  );
}

/** What is ticked, and Delete. Sits at the bottom of the list in Select. */
export function SelectBar({
  count,
  total,
  loaded,
  busy,
  onAll,
  onClear,
  onDelete,
  onActions,
}: {
  count: number;
  /** Leads in this list on the server. */
  total: number;
  /** Rows on screen. */
  loaded: number;
  busy: boolean;
  onAll: () => void;
  onClear: () => void;
  onDelete: () => void;
  /** Give, re-stage or move the ticked leads (owners and admins). */
  onActions?: () => void;
}) {
  const most = Math.min(total, DELETE_LIMIT);
  return (
    <div className={styles.bar} role="group" aria-label="Selected leads">
      <span className={styles.count} aria-live="polite">
        {count ? `${count} selected` : "Tap leads to select them"}
      </span>
      <span className={styles.barActions}>
        {count < most ? (
          <Button variant="ghost" disabled={busy} onClick={onAll}>
            {busy
              ? "Loading…"
              : total > DELETE_LIMIT
                ? `Select first ${DELETE_LIMIT}`
                : total > loaded
                  ? `Select all ${total}`
                  : "Select all"}
          </Button>
        ) : (
          <Button variant="ghost" onClick={onClear}>
            Clear
          </Button>
        )}
        {onActions ? (
          <Button disabled={!count || busy} onClick={onActions}>
            Actions
          </Button>
        ) : null}
        <button
          type="button"
          className={styles.danger}
          disabled={!count || busy}
          onClick={onDelete}
        >
          <Trash2 size={15} aria-hidden="true" />
          Delete
        </button>
      </span>
    </div>
  );
}
