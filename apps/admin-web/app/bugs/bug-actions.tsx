"use client";

/**
 * Moving a bug along: status, severity and area, with an optional note for
 * the team (a note is required to close one). Each save adds to the bug's
 * history; nothing is overwritten. POST /v1/admin/bugs/{id}/events.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { send } from "../lib/client-api";
import { Field, kitStyles } from "../ui/kit";
import {
  AREAS,
  AREA_LABEL,
  SEVERITIES,
  SEVERITY_LABEL,
  STATUSES,
  STATUS_LABEL,
  type Area,
  type Severity,
  type Status,
} from "./bugs-data";
import styles from "./bugs.module.css";

/** The next step most bugs take from each status. */
const NEXT: Partial<Record<Status, Status>> = {
  new: "triaged",
  triaged: "in_progress",
  in_progress: "fixed",
  fixed: "verified",
};

export function BugActions({
  bugId,
  status,
  severity,
  area,
}: {
  bugId: string;
  status: Status;
  severity: Severity | null;
  area: Area;
}) {
  const router = useRouter();
  const [nextStatus, setNextStatus] = useState<Status>(NEXT[status] ?? status);
  const [nextSeverity, setNextSeverity] = useState<Severity | "">(
    severity ?? "",
  );
  const [nextArea, setNextArea] = useState<Area>(area);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{
    tone: "error" | "done";
    text: string;
  } | null>(null);

  const changed =
    nextStatus !== status ||
    (nextSeverity !== "" && nextSeverity !== severity) ||
    nextArea !== area ||
    note.trim() !== "";
  const needsNote = nextStatus === "closed" && status !== "closed";

  const save = async () => {
    if (!changed || saving) return;
    if (needsNote && !note.trim()) {
      setMessage({
        tone: "error",
        text: "Say why it is closed (a duplicate, or not a bug).",
      });
      return;
    }
    setSaving(true);
    setMessage(null);
    const body = {
      ...(nextStatus !== status ? { status: nextStatus } : {}),
      ...(nextSeverity && nextSeverity !== severity
        ? { severity: nextSeverity }
        : {}),
      ...(nextArea !== area ? { area: nextArea } : {}),
      ...(note.trim() ? { note: note.trim() } : {}),
    };
    const result = await send(
      "POST",
      `/v1/admin/bugs/${bugId}/events`,
      body,
      null,
    );
    setSaving(false);
    if (!result.ok) {
      setMessage({ tone: "error", text: result.message });
      return;
    }
    setNote("");
    setMessage({ tone: "done", text: "Saved to the bug's history." });
    router.refresh();
  };

  return (
    <form
      className={styles.actions}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <div className={styles.actionFields}>
        <Field label="Status">
          <select
            value={nextStatus}
            onChange={(event) => setNextStatus(event.target.value as Status)}
          >
            {STATUSES.map((item) => (
              <option key={item} value={item}>
                {STATUS_LABEL[item]}
                {item === status ? " (now)" : ""}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Severity">
          <select
            value={nextSeverity}
            onChange={(event) =>
              setNextSeverity(event.target.value as Severity | "")
            }
          >
            {severity === null ? <option value="">Not set yet</option> : null}
            {SEVERITIES.map((item) => (
              <option key={item} value={item}>
                {SEVERITY_LABEL[item]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Area">
          <select
            value={nextArea}
            onChange={(event) => setNextArea(event.target.value as Area)}
          >
            {AREAS.map((item) => (
              <option key={item} value={item}>
                {AREA_LABEL[item]}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field
        label={needsNote ? "Why it is closed" : "Note for the team"}
        hint={
          needsNote
            ? "A duplicate (say which), or not a bug."
            : "Optional: what you found, the fix, the commit."
        }
        wide
      >
        <textarea
          value={note}
          maxLength={2000}
          rows={3}
          onChange={(event) => setNote(event.target.value)}
        />
      </Field>
      <div className={styles.actionRow}>
        <button
          type="submit"
          className={kitStyles.button}
          data-variant="primary"
          disabled={!changed || saving}
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {message ? (
          <small
            className={
              message.tone === "error" ? kitStyles.fieldError : kitStyles.muted
            }
            role={message.tone === "error" ? "alert" : "status"}
          >
            {message.text}
          </small>
        ) : null}
      </div>
    </form>
  );
}
