"use client";

/**
 * Withhold or release transcript passages by segment id. Every change needs
 * a reference (for example a ticket id), goes through the platform API with
 * an idempotency key, and is audited there; the page reloads from the server.
 */
import { EyeOff, Undo2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { command, newKey } from "../lib/client-api";
import { Field, kitStyles } from "../ui/kit";
import { CATEGORIES, REASON_PATTERN } from "./safety-data";
import styles from "./safety.module.css";

export function MarkSegments({
  recordingId,
  revisions,
}: {
  recordingId: string;
  revisions: string[];
}) {
  const router = useRouter();
  const key = useRef(newKey());
  const [revision, setRevision] = useState(revisions[0] ?? "");
  const [segments, setSegments] = useState("");
  const [category, setCategory] = useState<string>(CATEGORIES[0].value);
  const [reason, setReason] = useState("");
  const [state, setState] = useState<{
    kind: "idle" | "saving" | "error" | "done";
    message?: string;
  }>({
    kind: "idle",
  });
  const ids = segments
    .split(/[\s,]+/)
    .map((value) => value.trim())
    .filter(Boolean);
  const valid =
    revision &&
    ids.length > 0 &&
    ids.length <= 20 &&
    REASON_PATTERN.test(reason.trim());
  return (
    <form
      className={styles.form}
      onSubmit={async (event) => {
        event.preventDefault();
        if (!valid || state.kind === "saving") return;
        setState({ kind: "saving" });
        const result = await command(
          `/v1/platform/sensitive-segments/recordings/${recordingId}/marks`,
          {
            transcript_revision: revision,
            segments: ids.map((segment_id) => ({ segment_id, category })),
            reason_ref: reason.trim(),
          },
          key.current,
        );
        if (!result.ok) {
          setState({ kind: "error", message: result.message });
          return;
        }
        key.current = newKey();
        setSegments("");
        setState({
          kind: "done",
          message: `${ids.length} passage${ids.length === 1 ? "" : "s"} withheld.`,
        });
        router.refresh();
      }}
    >
      <Field label="Transcript revision">
        <select
          value={revision}
          onChange={(event) => setRevision(event.target.value)}
        >
          {revisions.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Segment ids" hint="Up to 20, separated by commas or spaces">
        <input
          value={segments}
          onChange={(event) => setSegments(event.target.value)}
          placeholder="seg_014, seg_015"
        />
      </Field>
      <Field label="Category">
        <select
          value={category}
          onChange={(event) => setCategory(event.target.value)}
        >
          {CATEGORIES.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label="Reference"
        hint="A ticket or request id, e.g. AUT-1820"
        error={
          reason && !REASON_PATTERN.test(reason.trim())
            ? "3-80 letters, digits, spaces or . _ : # / -"
            : undefined
        }
      >
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={80}
        />
      </Field>
      <div className={styles.formActions}>
        <button
          type="submit"
          className={kitStyles.button}
          data-variant="primary"
          disabled={!valid || state.kind === "saving"}
        >
          <EyeOff size={14} aria-hidden="true" />
          {state.kind === "saving" ? "Withholding…" : "Withhold passages"}
        </button>
        {state.message ? (
          <small
            role={state.kind === "error" ? "alert" : "status"}
            className={
              state.kind === "error"
                ? kitStyles.fieldError
                : kitStyles.fieldHint
            }
          >
            {state.message}
          </small>
        ) : null}
      </div>
    </form>
  );
}

export function ReleaseMark({ markId }: { markId: string }) {
  const router = useRouter();
  const key = useRef(newKey());
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  if (!open)
    return (
      <button
        type="button"
        className={kitStyles.button}
        data-variant="ghost"
        onClick={() => setOpen(true)}
      >
        <Undo2 size={14} aria-hidden="true" />
        Release
      </button>
    );
  return (
    <form
      className={styles.inline}
      onSubmit={async (event) => {
        event.preventDefault();
        if (!REASON_PATTERN.test(reason.trim()) || saving) return;
        setSaving(true);
        const result = await command(
          `/v1/platform/sensitive-segments/marks/${markId}/release`,
          { reason_ref: reason.trim() },
          key.current,
        );
        setSaving(false);
        if (!result.ok) {
          setMessage(result.message);
          return;
        }
        router.refresh();
      }}
    >
      <input
        aria-label="Reference for releasing"
        placeholder="Reference"
        value={reason}
        maxLength={80}
        onChange={(event) => setReason(event.target.value)}
      />
      <button
        type="submit"
        className={kitStyles.button}
        disabled={!REASON_PATTERN.test(reason.trim()) || saving}
      >
        {saving ? "Releasing…" : "Release"}
      </button>
      <button
        type="button"
        className={kitStyles.button}
        data-variant="ghost"
        onClick={() => setOpen(false)}
      >
        Cancel
      </button>
      {message ? (
        <small role="alert" className={kitStyles.fieldError}>
          {message}
        </small>
      ) : null}
    </form>
  );
}
