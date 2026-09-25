"use client";

import { Pencil, RefreshCw } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { AcquisitionError } from "./acquisition-client";
import {
  MAX_CALL_LABEL_LENGTH,
  validateCallLabel,
  type CallLabel,
} from "./call-label";
import styles from "./call-label-editor.module.css";

type SaveFn = (
  displayName: string | null,
  revision: number,
  signal: AbortSignal,
) => Promise<CallLabel>;
type RefreshFn = (signal: AbortSignal) => Promise<CallLabel | null>;

/**
 * Why writes are paused. "conflict" and "uncertain" require a successful
 * GET of the current label before another PATCH; "unavailable" means the
 * server supplied no label contract, so renaming stays off.
 */
type Gate = "conflict" | "uncertain" | "unavailable" | null;

type Problem = { message: string; gate: Gate };

/**
 * Only a definite rejection proves nothing changed. Any other failure after a
 * PATCH (transport loss, 5xx/timeout, a malformed or missing confirmation)
 * may follow a committed rename, so its outcome is reported as unconfirmed.
 */
function failureAfterSave(error: unknown): Problem {
  const status = error instanceof AcquisitionError ? error.status : 0;
  if (status === 409)
    return {
      message:
        "This call was renamed elsewhere. Refresh to load the current name; your text stays here.",
      gate: "conflict",
    };
  if (status === 403 || status === 401)
    return {
      message:
        "Only the signed-in account that saved this call can rename it. Your text stays here.",
      gate: null,
    };
  if (status === 404)
    return {
      message: "This call is no longer available, so it can't be renamed.",
      gate: null,
    };
  if (status === 422 || status === 400)
    return {
      message: "The server didn't accept this name. Check it and try again.",
      gate: null,
    };
  return {
    message:
      "We couldn't confirm whether the name was saved. Your text is kept. Check the saved name before trying again.",
    gate: "uncertain",
  };
}

/**
 * Inline rename for one saved call. Nothing reads as saved until the server
 * confirms it; the draft survives every failure, and a conflict offers a
 * refresh of the current server name instead of overwriting it.
 */
export function CallLabelEditor({
  label,
  onSave,
  onRefresh,
  onConfirmed,
  onClose,
}: {
  label: CallLabel;
  onSave: SaveFn;
  onRefresh: RefreshFn;
  /** Called with the server-confirmed label only. */
  onConfirmed: (label: CallLabel) => void;
  onClose: () => void;
}) {
  const inputId = useId();
  const [draft, setDraft] = useState(label.displayName ?? "");
  const [current, setCurrent] = useState(label);
  const [busy, setBusy] = useState<"saving" | "refreshing" | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  // Writes stay paused until a GET confirms the current label.
  const gate = problem?.gate ?? null;
  const writeBlocked = gate !== null;
  const controller = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
    input.current?.select();
    return () => controller.current?.abort();
  }, []);

  const begin = () => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    return next;
  };

  // What the last PATCH asked for, so a later GET can tell whether it landed,
  // and the exact input text at that moment, so a newer draft is never lost.
  const attempted = useRef<string | null | undefined>(undefined);
  const draftAtAttempt = useRef<string | null>(null);
  // Mirrors the input for async reads; updated only in the change handler.
  const draftNow = useRef(draft);

  async function save(value: string | null) {
    if (busy || writeBlocked) return;
    const request = begin();
    attempted.current = value;
    draftAtAttempt.current = draft;
    setBusy("saving");
    setProblem(null);
    try {
      const confirmed = await onSave(value, current.revision, request.signal);
      if (request.signal.aborted) return;
      onConfirmed(confirmed);
      onClose();
    } catch (error) {
      if (request.signal.aborted) return;
      setProblem(failureAfterSave(error));
      setBusy(null);
    }
  }

  /** GET-only status check; the only way to lift a conflict/uncertain gate. */
  async function refresh() {
    if (busy) return;
    const previousGate = gate;
    const request = begin();
    setBusy("refreshing");
    try {
      const latest = await onRefresh(request.signal);
      if (request.signal.aborted) return;
      if (!latest) {
        // No label contract in the response: neither "unnamed" nor writable.
        setProblem({
          message:
            "Call names aren't available from the server right now, so this call can't be renamed. Your text is kept.",
          gate: "unavailable",
        });
        return;
      }
      setCurrent(latest);
      onConfirmed(latest);
      const shown = latest.displayName ?? "no name saved";
      const earlierLanded =
        previousGate === "uncertain" &&
        attempted.current !== undefined &&
        latest.displayName === attempted.current;
      // Text typed after the uncertain save, not yet sent anywhere.
      const newerDraft = draftNow.current !== draftAtAttempt.current;
      if (earlierLanded && !newerDraft) {
        // The earlier save did land; the server's read confirms it.
        onClose();
        return;
      }
      setProblem({
        message: earlierLanded
          ? // Keep the reader's newer text open; only the earlier value is saved.
            `Current name: ${shown}. Your earlier change is the saved name; your newer text isn't saved yet.`
          : previousGate === "uncertain"
            ? // A concurrent writer may have replaced an earlier save that did land.
              `Current name: ${shown}. Your earlier change is not the current saved name. Save again to replace it with your text.`
            : `Current name: ${shown}. Save again to replace it with your text.`,
        gate: null,
      });
    } catch {
      if (request.signal.aborted) return;
      // Still unconfirmed: keep the same gate and offer the check again.
      setProblem({
        message:
          "The saved name couldn't be checked. Your text is kept. Try the check again.",
        gate: previousGate === "conflict" ? "conflict" : "uncertain",
      });
    } finally {
      if (!request.signal.aborted) setBusy(null);
    }
  }

  const checked = validateCallLabel(draft);
  const unchanged = checked.ok && checked.name === current.displayName;

  return (
    <form
      className={styles.editor}
      data-call-label-editor
      onSubmit={(event) => {
        event.preventDefault();
        if (checked.ok && !unchanged && !writeBlocked) void save(checked.name);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !busy) {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <label className={styles.label} htmlFor={inputId}>
        Call name
      </label>
      <div className={styles.row}>
        <input
          ref={input}
          id={inputId}
          className={styles.input}
          value={draft}
          maxLength={MAX_CALL_LABEL_LENGTH * 2}
          aria-invalid={!checked.ok && draft !== "" ? true : undefined}
          aria-describedby={`${inputId}-help`}
          onChange={(event) => {
            draftNow.current = event.target.value;
            setDraft(event.target.value);
          }}
          disabled={busy === "saving"}
        />
        <button
          type="submit"
          className={styles.primary}
          disabled={!!busy || !checked.ok || unchanged || writeBlocked}
        >
          {busy === "saving" ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          className={styles.secondary}
          disabled={busy === "saving"}
          onClick={onClose}
        >
          Cancel
        </button>
      </div>
      <p id={`${inputId}-help`} className={styles.help}>
        {!checked.ok && draft !== ""
          ? checked.message
          : `Up to ${MAX_CALL_LABEL_LENGTH} characters. Private to your account.`}
      </p>
      {current.displayName && gate !== "unavailable" ? (
        <button
          type="button"
          className={styles.link}
          disabled={!!busy || writeBlocked}
          onClick={() => void save(null)}
        >
          Clear name
        </button>
      ) : null}
      {problem ? (
        <p
          className={styles.problem}
          role="alert"
          data-call-label-gate={gate ?? undefined}
        >
          {problem.message}{" "}
          {gate === "conflict" || gate === "uncertain" ? (
            <button
              type="button"
              className={styles.link}
              disabled={!!busy}
              onClick={() => void refresh()}
            >
              <RefreshCw size={13} aria-hidden="true" />{" "}
              {busy === "refreshing"
                ? "Checking…"
                : gate === "conflict"
                  ? "Refresh name"
                  : "Check saved name"}
            </button>
          ) : null}
        </p>
      ) : null}
    </form>
  );
}

/** A small, labelled trigger for the editor. */
export function RenameCallButton({
  onClick,
  callTitle,
}: {
  onClick: () => void;
  callTitle: string;
}) {
  return (
    <button
      type="button"
      className={styles.trigger}
      aria-label={`Rename call: ${callTitle}`}
      title="Rename call"
      onClick={onClick}
    >
      <Pencil size={15} aria-hidden="true" />
    </button>
  );
}
