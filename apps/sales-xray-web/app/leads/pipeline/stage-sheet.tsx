"use client";

/**
 * Move a lead (Lead OS, 24 Oct 2026). One sheet, two steps: where to (only the
 * stages its stage list allows, for this person), then only what that move
 * asks for: when to follow up, the meeting, a reason, why a call didn't
 * connect. The one button says what happens ("Book meeting", "Close as Lost").
 * The same lead record moves; its history keeps the step.
 */

import { ArrowLeft, ArrowRight } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { notify } from "../../notice-center";
import { track, waitBand } from "../../telemetry";
import { tick } from "../../ui/haptics";
import { Button } from "../../ui/kit";
import { Sheet } from "../../ui/sheet";
import {
  LeadsError,
  readLead,
  type LeadDetail,
  type LeadRow,
} from "../leads-client";
import {
  EMPTY_MEETING,
  MeetingBlock,
  NcReasonBlock,
  NoteBlock,
  ReasonBlock,
  WhenBlock,
  meetingReady,
  meetingStart,
  whenOf,
  type MeetingDraft,
  type WhenPick,
} from "./blocks";
import { moveLead, type MoveInput, type MoveOption } from "./pipeline-client";
import styles from "./pipeline.module.css";
import { finalLine, leadKind, moveVerb } from "./words";

export type StageSheetProps = {
  open: boolean;
  lead: Pick<LeadRow, "lead_id" | "revision" | "name" | "stage_label"> &
    Partial<Pick<LeadRow, "stage">>;
  moves: MoveOption[];
  /** Straight to this stage's questions (a drag onto its column, a suggestion). */
  initial?: string | null;
  /** Filled from a suggestion: the sheet shows only Confirm when it is complete. */
  preset?: Partial<Draft>;
  via?: MoveInput["via"];
  onClose: () => void;
  onMoved: (detail: LeadDetail) => void;
};

/** Milliseconds since a moment, or -1 when there was none. */
function msSince(start: number): number {
  return start ? Date.now() - start : -1;
}

export type Draft = {
  when: WhenPick | null;
  custom: string;
  reason: string | null;
  reasonNote: string;
  ncReason: string | null;
  note: string;
  meeting: MeetingDraft;
};

const BLANK: Draft = {
  when: null,
  custom: "",
  reason: null,
  reasonNote: "",
  ncReason: null,
  note: "",
  meeting: EMPTY_MEETING,
};

/** What the move still lacks (the server refuses it without these). */
export function missing(move: MoveOption, draft: Draft): string[] {
  const out: string[] = [];
  for (const need of move.needs) {
    if (need === "next_action" && !whenOf(draft.when, draft.custom))
      out.push(need);
    if (need === "meeting" && !meetingReady(draft.meeting)) out.push(need);
    if (need === "reason" && !draft.reason) out.push(need);
    if (need === "nc_reason" && !draft.ncReason) out.push(need);
  }
  if (draft.reason === "other" && !draft.reasonNote.trim())
    out.push("reason_note");
  return out;
}

/** The request for a move, from what the seller filled in. */
export function moveInput(move: MoveOption, draft: Draft): MoveInput {
  const asks = new Set([...move.needs, ...move.asks]);
  const at = asks.has("next_action") ? whenOf(draft.when, draft.custom) : null;
  const start = asks.has("meeting") ? meetingStart(draft.meeting) : null;
  return {
    note: draft.note.trim() || undefined,
    reason: asks.has("reason") ? (draft.reason ?? undefined) : undefined,
    reasonNote:
      draft.reason === "other"
        ? draft.reasonNote.trim() || undefined
        : undefined,
    ncReason: asks.has("nc_reason") ? (draft.ncReason ?? undefined) : undefined,
    nextActionAt: at ? at.toISOString() : undefined,
    meeting:
      start && draft.meeting.mode
        ? {
            startsAt: start.toISOString(),
            mode: draft.meeting.mode,
            link: draft.meeting.link.trim() || undefined,
            location: draft.meeting.location.trim() || undefined,
          }
        : undefined,
  };
}

const GROUP_WORDS = {
  active: "Open stages",
  won: "Won",
  lost: "Lost",
  junk: "Junk",
} as const;

function hintFor(move: MoveOption): string {
  if (move.action === "reopen") return "Back to work, history kept";
  if (move.needs.includes("meeting")) return "Asks for the meeting";
  if (move.needs.includes("reason")) return "Asks why";
  if (move.needs.includes("nc_reason")) return "Asks why it didn't connect";
  if (move.needs.includes("next_action")) return "Asks when to follow up";
  return "Moves at once";
}

export function StageSheet({
  open,
  lead,
  moves,
  initial = null,
  preset,
  via = "sheet",
  onClose,
  onMoved,
}: StageSheetProps) {
  const [target, setTarget] = useState<string | null>(initial);
  const [draft, setDraft] = useState<Draft>({ ...BLANK, ...preset });
  const [saving, setSaving] = useState(false);
  // A new opening starts again from its own target.
  const [openedFor, setOpenedFor] = useState({ open, initial });
  // When this opening began: telemetry's time from open to Save.
  const opened = useRef(0);
  if (openedFor.open !== open || openedFor.initial !== initial) {
    setOpenedFor({ open, initial });
    if (open) {
      setTarget(initial);
      setDraft({ ...BLANK, ...preset });
    }
  }
  useEffect(() => {
    if (open) opened.current = Date.now();
  }, [open, initial]);
  const move = moves.find((item) => item.step === target) ?? null;
  const grouped = useMemo(
    () =>
      (["active", "won", "lost", "junk"] as const)
        .map((group) => ({
          group,
          moves: moves.filter((item) => item.group === group),
        }))
        .filter((part) => part.moves.length),
    [moves],
  );
  const lacking = move ? missing(move, draft) : [];
  const asks = new Set(move ? [...move.needs, ...move.asks] : []);
  const set = (next: Partial<Draft>) =>
    setDraft((current) => ({ ...current, ...next }));

  const save = async () => {
    if (!move || lacking.length || saving) return;
    setSaving(true);
    try {
      // A reopen is a move too: the same lead, back to work, its history kept.
      await moveLead(lead, move.step, { ...moveInput(move, draft), via });
      onMoved(await readLead(lead.lead_id));
      tick();
      const to = leadKind(move.kind);
      if (to) {
        const took = msSince(opened.current);
        track("sx.lead_stage_moved", {
          via:
            via === "board" || via === "table" || via === "meeting"
              ? via
              : "sheet",
          source: "seller",
          from_kind: leadKind(lead.stage),
          to_kind: to,
          needs: Math.min(4, move.needs.length),
          wait: waitBand(took),
          ...(took >= 0 && took <= 3_600_000 ? { wait_ms: took } : {}),
        });
      }
      notify({
        id: `moved-${lead.lead_id}`,
        tone: "success",
        title: `${lead.name}: ${move.label}`,
        timeout: 4000,
      });
      onClose();
    } catch (reason) {
      notify({
        id: `move-failed-${lead.lead_id}`,
        tone: "error",
        title: "Not moved",
        message:
          reason instanceof LeadsError
            ? reason.status === 409
              ? `${reason.message} It was reloaded.`
              : reason.message
            : "Try again.",
      });
      // Changed by a teammate: show the lead as it is now.
      if (reason instanceof LeadsError && reason.status === 409)
        void readLead(lead.lead_id).then(onMoved, () => undefined);
    } finally {
      setSaving(false);
    }
  };

  const title = move ? `Move ${lead.name}` : `Move ${lead.name} to…`;
  const footer = move ? (
    <div className={styles.sheetFooter}>
      {finalLine(move) ? (
        <p className={styles.finalLine}>{finalLine(move)}</p>
      ) : null}
      <Button
        variant="primary"
        className={styles.wide}
        data-group={move.group}
        disabled={lacking.length > 0 || saving}
        aria-busy={saving || undefined}
        onClick={() => void save()}
      >
        {moveVerb(move)}
      </Button>
    </div>
  ) : null;

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={title}
      lead={
        move && !initial ? (
          <button
            type="button"
            className={styles.backStep}
            aria-label="Back to the stages"
            onClick={() => setTarget(null)}
          >
            <ArrowLeft size={18} aria-hidden="true" />
          </button>
        ) : undefined
      }
      footer={footer}
    >
      {move ? (
        <div className={styles.sheetBody}>
          <p className={styles.fromTo}>
            <span>{lead.stage_label}</span>
            <ArrowRight size={16} aria-hidden="true" />
            <strong>{move.label}</strong>
          </p>
          {asks.has("meeting") ? (
            <MeetingBlock
              draft={draft.meeting}
              onChange={(meeting) => set({ meeting })}
            />
          ) : null}
          {asks.has("nc_reason") ? (
            <NcReasonBlock
              value={draft.ncReason}
              onPick={(ncReason) => set({ ncReason })}
            />
          ) : null}
          {asks.has("reason") ? (
            <ReasonBlock
              label={
                move.group === "junk" ? "Why is it junk?" : "Why was it lost?"
              }
              reasons={move.reasons}
              value={draft.reason}
              note={draft.reasonNote}
              required={move.needs.includes("reason")}
              onPick={(reason) => set({ reason })}
              onNote={(reasonNote) => set({ reasonNote })}
            />
          ) : null}
          {asks.has("next_action") && !asks.has("meeting") ? (
            <WhenBlock
              label={
                move.kind === "not_connected" ? "Try again" : "Next follow-up"
              }
              pick={draft.when}
              custom={draft.custom}
              required={move.needs.includes("next_action")}
              onPick={(when) => set({ when })}
              onCustom={(custom) => set({ custom })}
            />
          ) : null}
          {asks.has("note") ? (
            <NoteBlock value={draft.note} onChange={(note) => set({ note })} />
          ) : null}
        </div>
      ) : grouped.length ? (
        <div className={styles.sheetBody}>
          {grouped.map((part) => (
            <section key={part.group} aria-label={GROUP_WORDS[part.group]}>
              <h3 className={styles.groupLabel} data-group={part.group}>
                {GROUP_WORDS[part.group]}
              </h3>
              <ul className={styles.targets}>
                {part.moves.map((item) => (
                  <li key={item.step}>
                    <button
                      type="button"
                      className={styles.target}
                      data-group={item.group}
                      onClick={() => setTarget(item.step)}
                    >
                      <span className={styles.targetLabel}>{item.label}</span>
                      <span className={styles.targetHint}>{hintFor(item)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      ) : (
        <p className={styles.sheetEmpty}>
          This lead can&apos;t move from here. An owner or admin can reopen it.
        </p>
      )}
    </Sheet>
  );
}
