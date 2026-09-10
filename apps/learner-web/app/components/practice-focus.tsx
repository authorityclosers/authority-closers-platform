"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ActionButton, actionClassName } from "@ac/ui";
import { Sparkles } from "lucide-react";
import {
  practiceFocusApi,
  PracticeFocusRequestError,
  type PracticeFocusApi,
  type FocusSummary,
  type FocusRun,
} from "../lib/practice-focus-api";
import type { PracticeAttempt } from "../lib/practice-engine-api";
import styles from "./practice-focus.module.css";

type Command = {
  kind: "start" | "end";
  target: string;
  body: { expected_revision: number; expected_attempt_revision: number };
  key: string;
};
/** Optional authority is loaded independently; unavailable Focus never blocks standard practice. */
export function usePracticeFocus(
  attempt: PracticeAttempt | null,
  api: PracticeFocusApi = practiceFocusApi,
) {
  const [loadedScope, setLoadedScope] = useState<{
    id: string | undefined;
    api: PracticeFocusApi;
  } | null>(null);
  const scopeMatches =
    loadedScope?.id === attempt?.id && loadedScope?.api === api;
  const [summary, setSummary] = useState<FocusSummary | null>(null);
  const [ended, setEnded] = useState<FocusRun | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const pending = useRef<Command | null>(null);
  const mutation = useRef<AbortController | null>(null);
  const read = useRef<AbortController | null>(null);
  const locked = useRef(false);
  useEffect(
    () => () => {
      mutation.current?.abort();
      pending.current = null;
      locked.current = false;
    },
    [api, attempt?.id],
  );
  useEffect(() => {
    const controller = new AbortController();
    read.current = controller;
    void api
      .summary(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setSummary(value);
          setError(null);
          setLoading(false);
          if (!pending.current) setConflict(false);
          if (!scopeMatches) {
            setBusy(false);
            setUncertain(false);
            setConflict(false);
            setEnded(null);
          }
          setLoadedScope({ id: attempt?.id, api });
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason);
          setLoading(false);
          if (!scopeMatches) {
            setSummary(null);
            setBusy(false);
            setUncertain(false);
            setConflict(false);
            setEnded(null);
          }
          setLoadedScope({ id: attempt?.id, api });
        }
      });
    return () => controller.abort();
    // Scope identity is captured for this request; successful loading must not retrigger itself.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, epoch, attempt?.id, attempt?.state]);
  useEffect(
    () => () => {
      mutation.current?.abort();
    },
    [],
  );
  const active =
    summary?.active_run?.attempt_id === attempt?.id
      ? summary?.active_run
      : null;
  const run = async (kind: "start" | "end") => {
    if (!scopeMatches || !attempt || !summary || locked.current || conflict)
      return;
    if (pending.current && pending.current.kind !== kind) return;
    if (!pending.current) {
      if (
        kind === "start" &&
        (attempt.revision !== 0 || summary.active_run || summary.charges === 0)
      )
        return;
      if (kind === "end" && !active) return;
      pending.current = {
        kind,
        target: kind === "start" ? attempt.id : active!.id,
        body: {
          expected_revision: summary.revision,
          expected_attempt_revision: attempt.revision,
        },
        key: crypto.randomUUID(),
      };
    }
    locked.current = true;
    setBusy(true);
    setError(null);
    read.current?.abort();
    const controller = new AbortController();
    mutation.current = controller;
    const command = pending.current;
    try {
      const result = await api[command.kind](
        command.target,
        command.body,
        command.key,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setSummary(result.summary);
        setLoading(false);
        setUncertain(false);
        pending.current = null;
        if (kind === "end") setEnded(result.run);
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(reason);
        if (
          reason instanceof PracticeFocusRequestError &&
          reason.status >= 400 &&
          reason.status < 500
        ) {
          pending.current = null;
          setUncertain(false);
          setConflict(true);
        } else setUncertain(true);
      }
    } finally {
      if (!controller.signal.aborted) {
        locked.current = false;
        setBusy(false);
      }
    }
  };
  const reload = () => {
    if (locked.current) return;
    // A snapshot cannot disprove a timed-out command that is still committing.
    // Reconcile through the original idempotent command and keep answers gated.
    if (pending.current) {
      void run(pending.current.kind);
      return;
    }
    setLoading(true);
    setEpoch((value) => value + 1);
  };
  return {
    summary: scopeMatches ? summary : null,
    active: scopeMatches ? active : null,
    ended: scopeMatches ? ended : null,
    error: scopeMatches ? error : null,
    loading: !scopeMatches || loading,
    busy: scopeMatches && busy,
    uncertain: scopeMatches && uncertain,
    conflict: scopeMatches && conflict,
    run,
    reload,
  };
}
type FocusController = ReturnType<typeof usePracticeFocus>;

export function PracticeFocusStatus({
  focus,
  attempt,
  onReload,
}: {
  focus: FocusController;
  attempt: PracticeAttempt | null;
  onReload: () => void;
}) {
  return (
    <details
      className={styles.panel}
      open={focus.busy || focus.uncertain || focus.conflict || undefined}
    >
      <summary>
        <Sparkles size={16} aria-hidden="true" />
        <span>{focus.active ? "Focus run" : "Optional Focus"}</span>
        {focus.summary ? (
          <span
            className={styles.charges}
            aria-label={`${focus.summary.charges} of 3 Focus charges`}
          >
            {[0, 1, 2].map((index) => (
              <i
                key={index}
                data-filled={index < focus.summary!.charges}
                aria-hidden="true"
              />
            ))}
          </span>
        ) : null}
      </summary>
      <div className={styles.content}>
        <strong>A little commitment. Always your choice.</strong>
        <p>
          Ending a Focus run after your first saved prompt uses 1 Focus charge.
          Pausing, connection problems and mistakes cost nothing.
        </p>
        <p>
          Finish a Focus run to restore 1 charge, up to 3. Charges refill on
          your next practice day. Your earned credits and XP never change.
        </p>
        {focus.loading ? (
          <p role="status">Checking your Focus…</p>
        ) : focus.summary ? (
          <>
            <p className={styles.balance}>
              {focus.summary.charges} / 3 Focus charges
            </p>
            {focus.active ? (
              <p role="status">
                Focus is on for this run. Use the exit button whenever you need
                to pause.
              </p>
            ) : focus.summary.active_run ? (
              <Link
                className={actionClassName("secondary")}
                href={`/practice?set=${encodeURIComponent(focus.summary.active_run.set_id)}&attempt=${focus.summary.active_run.attempt_id}`}
              >
                Resume your Focus run
              </Link>
            ) : attempt?.state === "in_progress" && attempt.revision === 0 ? (
              <ActionButton
                disabled={
                  focus.busy || focus.conflict || focus.summary.charges === 0
                }
                onClick={() => void focus.run("start")}
              >
                {focus.busy
                  ? "Enabling…"
                  : focus.uncertain
                    ? "Retry enabling Focus"
                    : "Enable Focus for this run"}
              </ActionButton>
            ) : (
              <p>
                Choose Focus before answering the first prompt of a new
                practice. Standard practice stays available.
              </p>
            )}
            {focus.summary.charges === 0 ? (
              <p>
                Keep practising in standard mode, or come back next practice day
                for 3 Focus charges.
              </p>
            ) : null}
          </>
        ) : null}
        {focus.error ? (
          <div role={focus.uncertain || focus.conflict ? "alert" : undefined}>
            <p>
              {focus.uncertain
                ? "That change is not confirmed. Retry the same request or check your saved Focus state."
                : "Focus couldn’t be confirmed. Standard practice is still available."}
            </p>
            <ActionButton
              variant="quiet"
              disabled={focus.busy}
              onClick={onReload}
            >
              Check saved Focus
            </ActionButton>
          </div>
        ) : null}
      </div>
    </details>
  );
}

export function PracticeFocusEnd({
  focus,
  attempt,
  onReload,
}: {
  focus: FocusController;
  attempt: PracticeAttempt;
  onReload: () => void;
}) {
  if (focus.ended?.attempt_id === attempt.id)
    return (
      <p role="status" className={styles.ended}>
        Focus run ended.{" "}
        {focus.ended.exit_cost ? "1 Focus charge used." : "No charge used."}{" "}
        Your saved answers and earned rewards are safe.
      </p>
    );
  if (!focus.active) return null;
  const cost = attempt.acknowledged_item_ids.length > 0 ? 1 : 0;
  return (
    <div className={styles.end}>
      <p>
        You can pause and return free. Deliberately ending this Focus run{" "}
        {cost
          ? "uses 1 Focus charge"
          : "is free before your first saved prompt"}
        ; your answers remain available in standard practice.
      </p>
      <ActionButton
        variant="quiet"
        disabled={focus.busy || focus.conflict}
        onClick={() => void focus.run("end")}
      >
        {focus.busy
          ? "Confirming…"
          : focus.uncertain
            ? "Retry ending Focus"
            : `End Focus run · ${cost ? "1 charge" : "no charge"}`}
      </ActionButton>
      {focus.error ? (
        <div role="alert">
          <p>
            {focus.uncertain
              ? "The result isn’t confirmed. Retry safely; one run can only be charged once."
              : "Your saved state changed. Check it before trying again."}
          </p>
          <ActionButton
            variant="quiet"
            disabled={focus.busy}
            onClick={onReload}
          >
            Check saved Focus
          </ActionButton>
        </div>
      ) : null}
    </div>
  );
}
