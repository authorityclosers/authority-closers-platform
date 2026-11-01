"use client";

/**
 * The AI notes' Apply chips on a call's Report (competitor teardown 24, the
 * approved plan, 1 Nov 2026): the Report asks which lead the call belongs to,
 * and only when the viewer may change that lead do the chips show. A chip
 * opens the sheet the lead page uses, filled in from the call: Move for a
 * stage or an amount, the follow-up picker for the next call. Nothing is
 * written until the seller taps Save; closing the sheet leaves the lead as it
 * was and the chip ready again.
 */

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "../ui/kit";
import { ActionSheet } from "../leads/action-sheet";
import {
  LeadsError,
  readCallLead,
  setFollowUp,
  type LeadDetail,
} from "../leads/leads-client";
import type { MoveOption } from "../leads/pipeline/pipeline-client";
import type { Draft } from "../leads/pipeline/stage-sheet";
import { localInput } from "../leads/task-words";
import type { NoteSuggestion } from "./ai-notes";
import styles from "./apply-updates.module.css";

// The Move sheet loads only when a chip opens it.
const StageSheet = dynamic(
  () => import("../leads/pipeline/stage-sheet").then((part) => part.StageSheet),
  { ssr: false },
);

/** The lead this call belongs to, when the viewer may open it; else null. */
export function useCallLead(
  callId: string | null,
): [LeadDetail | null, (next: LeadDetail) => void] {
  const [found, setFound] = useState<{
    callId: string;
    lead: LeadDetail;
  } | null>(null);
  useEffect(() => {
    if (!callId) return;
    const controller = new AbortController();
    readCallLead(callId, controller.signal)
      .then((lead) => {
        // Only a lead's own answer counts; null (no lead, or not theirs) shows nothing.
        if (
          !controller.signal.aborted &&
          typeof lead?.lead?.lead_id === "string"
        )
          setFound({ callId, lead });
      })
      // Outside a team, or the server didn't answer: the notes show no chips.
      .catch(() => undefined);
    return () => controller.abort();
  }, [callId]);
  const update = useCallback(
    (lead: LeadDetail) =>
      setFound((current) => (current ? { ...current, lead } : current)),
    [],
  );
  return [found?.callId === callId ? found.lead : null, update];
}

/** The move a stage chip means on this lead's list, if it may go there. */
export function moveFor(
  moves: readonly MoveOption[],
  suggestion: NoteSuggestion,
): MoveOption | null {
  const kind =
    suggestion.key === "stage"
      ? suggestion.outcome
      : suggestion.key === "amount"
        ? "won"
        : null;
  if (!kind) return null;
  return (
    moves.find((move) => move.kind === kind && move.action !== "reopen") ?? null
  );
}

/** A date the call named, as a time to call: its own time, else 11 AM that day. */
export function callTimeOf(date: string): Date | null {
  const at = new Date(/T\d/.test(date) ? date : `${date}T11:00:00`);
  return Number.isNaN(at.getTime()) ? null : at;
}

type Opened =
  | { kind: "move"; move: MoveOption; preset: Partial<Draft> }
  | { kind: "next_call"; at: Date };

/**
 * The chips' onApply and the sheets they open. ``apply`` resolves true once
 * the seller saved, false when they closed the sheet without saving.
 */
export function useApplyUpdates({
  lead,
  amount,
  date,
  onChanged,
}: {
  lead: LeadDetail | null;
  /** The amount the call named, for a Won move. */
  amount: string | null;
  /** The next date the call named, for a move that asks when. */
  date: string | null;
  onChanged: (next: LeadDetail) => void;
}) {
  const [opened, setOpened] = useState<Opened | null>(null);
  const settle = useRef<((saved: boolean) => void) | null>(null);
  const finish = (saved: boolean) => {
    settle.current?.(saved);
    settle.current = null;
    setOpened(null);
  };
  const editable = !!lead?.can_edit;
  const apply = useCallback(
    (suggestion: NoteSuggestion): Promise<boolean> => {
      if (!lead) return Promise.resolve(false);
      settle.current?.(false);
      let next: Opened | null = null;
      if (suggestion.key === "next_call") {
        const at = callTimeOf(suggestion.date);
        if (at) next = { kind: "next_call", at };
      } else {
        const move = moveFor(lead.moves ?? [], suggestion);
        const when = date ? callTimeOf(date) : null;
        if (move)
          next = {
            kind: "move",
            move,
            preset: {
              ...(amount ? { amount } : {}),
              ...(when ? { when: "custom", custom: localInput(when) } : {}),
            },
          };
      }
      if (!next)
        return Promise.reject(
          new LeadsError("This lead can't take that update from here.", 409),
        );
      setOpened(next);
      return new Promise<boolean>((resolve) => {
        settle.current = resolve;
      });
    },
    [lead, amount, date],
  );
  const sheets =
    editable && lead ? (
      <>
        {opened?.kind === "move" ? (
          <StageSheet
            open
            lead={lead.lead}
            moves={lead.moves ?? []}
            initial={opened.move.step}
            preset={opened.preset}
            onClose={() => finish(false)}
            onMoved={(moved) => {
              onChanged(moved);
              finish(true);
            }}
          />
        ) : null}
        <NextCallSheet
          lead={lead}
          at={opened?.kind === "next_call" ? opened.at : null}
          onClose={() => finish(false)}
          onSaved={(saved) => {
            onChanged(saved);
            finish(true);
          }}
        />
      </>
    ) : null;
  const applicable = useCallback(
    (suggestion: NoteSuggestion) =>
      suggestion.key === "next_call"
        ? callTimeOf(suggestion.date) !== null
        : moveFor(lead?.moves ?? [], suggestion) !== null,
    [lead],
  );
  return { apply: editable ? apply : undefined, applicable, sheets };
}

/** The follow-up picker, opened on the time the call named. */
function NextCallSheet({
  lead,
  at,
  onClose,
  onSaved,
}: {
  lead: LeadDetail;
  at: Date | null;
  onClose: () => void;
  onSaved: (next: LeadDetail) => void;
}) {
  const [value, setValue] = useState("");
  const [shownFor, setShownFor] = useState<Date | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (at !== shownFor) {
    setShownFor(at);
    setValue(at ? localInput(at) : "");
    setError(null);
  }
  const chosen = value ? new Date(value) : null;
  const valid = !!chosen && !Number.isNaN(chosen.getTime());
  return (
    <ActionSheet
      open={at !== null}
      title={`Next call · ${lead.lead.name}`}
      onClose={onClose}
    >
      <label className={styles.applyField}>
        <span>When</span>
        <input
          type="datetime-local"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      </label>
      {error ? (
        <p className={styles.applyError} role="alert">
          {error}
        </p>
      ) : null}
      <Button
        variant="primary"
        disabled={!valid || saving}
        onClick={async () => {
          if (!valid || !chosen) return;
          setSaving(true);
          setError(null);
          try {
            onSaved(await setFollowUp(lead.lead, chosen));
          } catch (reason) {
            setError(
              reason instanceof LeadsError
                ? reason.message
                : "Not saved. Try again.",
            );
          } finally {
            setSaving(false);
          }
        }}
      >
        {saving ? "Saving…" : "Save next call"}
      </Button>
    </ActionSheet>
  );
}
