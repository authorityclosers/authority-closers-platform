"use client";

/**
 * The pipeline board (Lead OS, 24 Oct 2026; the sales team's spec section 8):
 * every stage a column, grouped Active, Won, Lost and Junk, each lead in
 * exactly one column. A card says three things and nothing is cut mid-word
 * (owner, 24 Oct 2026: "things inside the cards do not fit"): the name; one
 * line with where the lead came from (or why it closed) and when we last heard
 * from them, or how long it has sat in its stage; and the next step as its one
 * chip (late in red, with a red edge; none in amber), beside the seller.
 *
 * Phones: a strip of stage chips with counts, one column at a time, swiped
 * sideways inside the board (never the page). Computers: columns of one fixed
 * width side by side, Won, Lost and Junk after the open ones; the edge fades
 * and says how many stages are out of view. Drag a card and only the columns
 * it may go to light up. A move that needs nothing happens at once with Undo;
 * one that needs something opens the stage sheet. Every move is also on the
 * card's Move button and the lead page: no one has to drag.
 */

import {
  ArrowRightLeft,
  ChevronLeft,
  ChevronRight,
  Phone,
  Users,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DragEvent,
} from "react";

import { notify } from "../../notice-center";
import { track } from "../../telemetry";
import { tick } from "../../ui/haptics";
import { Avatar, Button, Empty, initials } from "../../ui/kit";
import { LeadsError, type LeadRow } from "../leads-client";
import {
  moveLead,
  readBoard,
  readColumn,
  type Board,
  type BoardColumn,
  type BoardFilters,
  type MoveOption,
} from "./pipeline-client";
import styles from "./pipeline.module.css";
import { StageSheet } from "./stage-sheet";
import { cardTime, leadKind, nextStep } from "./words";

/** How long a move waits for Undo before it is sent. */
export const UNDO_MS = 5000;

type Moving = {
  lead: LeadRow;
  from: BoardColumn;
  initial: string | null;
};

export function BoardCard({
  lead,
  column,
  showOwner,
  now,
  onOpen,
  onCall,
  onMove,
  onDragStart,
  onDragEnd,
}: {
  lead: LeadRow;
  column: BoardColumn;
  showOwner: boolean;
  now: Date;
  onOpen: (leadId: string) => void;
  /** Phones: one tap calls, through the lead page's own Call. */
  onCall?: (leadId: string) => void;
  onMove: (lead: LeadRow, column: BoardColumn) => void;
  onDragStart?: (lead: LeadRow, column: BoardColumn) => void;
  onDragEnd?: () => void;
}) {
  const callable = !!onCall && (!lead.group || lead.group === "active");
  const next = nextStep(lead, now);
  const time = cardTime(lead, column.rot_hours, now);
  // Why it closed, else where it came from; it gives way before the time does.
  const context = lead.outcome_reason_label ?? lead.source_label ?? null;
  return (
    <li
      className={styles.card}
      data-late={next.tone === "late" ? "" : undefined}
      draggable={column.moves.length > 0}
      onDragStart={(event: DragEvent<HTMLLIElement>) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", lead.lead_id);
        onDragStart?.(lead, column);
      }}
      onDragEnd={() => onDragEnd?.()}
    >
      <button
        type="button"
        className={styles.cardOpen}
        // Telemetry times the open (telemetry-auto.tsx): tap to the lead on screen.
        data-lead-row=""
        data-sx-feature="lead_board"
        onClick={() => onOpen(lead.lead_id)}
        aria-label={`Open ${lead.name}`}
      >
        <span className={styles.cardName}>{lead.name}</span>
        {/* The time comes first in the code and is drawn second: when both
            don't fit, the context wraps out of sight whole, never cut. */}
        <span className={styles.cardMeta}>
          <span
            className={styles.cardTime}
            data-old={time.old ? "" : undefined}
          >
            {time.text}
          </span>
          {context ? (
            <span className={styles.cardContext}>{context}</span>
          ) : null}
        </span>
        <span className={styles.cardFoot}>
          {next.text ? (
            <span className={styles.next} data-tone={next.tone}>
              {next.text}
            </span>
          ) : (
            <span />
          )}
          {showOwner && lead.owner_name ? (
            <span className={styles.owner} title={lead.owner_name}>
              <Avatar name={lead.owner_name} size={24} />
              <span className={styles.srOnly}>{initials(lead.owner_name)}</span>
            </span>
          ) : null}
        </span>
      </button>
      {callable || column.moves.length ? (
        <span className={styles.cardRail}>
          {callable ? (
            // A lead with no number shows Call greyed, with why, not hidden.
            <button
              type="button"
              className={styles.cardCall}
              aria-label={
                lead.phone_last4
                  ? `Call ${lead.name}`
                  : `No number to call ${lead.name}`
              }
              disabled={!lead.phone_last4}
              onClick={() => onCall?.(lead.lead_id)}
            >
              <Phone size={18} aria-hidden="true" />
            </button>
          ) : null}
          {column.moves.length ? (
            <button
              type="button"
              className={styles.cardMove}
              aria-label={`Move ${lead.name}`}
              onClick={() => onMove(lead, column)}
            >
              <ArrowRightLeft size={16} aria-hidden="true" />
            </button>
          ) : null}
        </span>
      ) : null}
    </li>
  );
}

function ColumnView({
  column,
  showOwner,
  now,
  drop,
  onOpen,
  onCall,
  onMove,
  onDragStart,
  onDragEnd,
  onDrop,
  onMore,
}: {
  column: BoardColumn;
  showOwner: boolean;
  now: Date;
  /** While a card is dragged: whether it may land here. */
  drop: "allowed" | "blocked" | "source" | null;
  onOpen: (leadId: string) => void;
  onCall?: (leadId: string) => void;
  onMove: (lead: LeadRow, column: BoardColumn) => void;
  onDragStart: (lead: LeadRow, column: BoardColumn) => void;
  onDragEnd: () => void;
  onDrop: (column: BoardColumn) => void;
  onMore: (column: BoardColumn) => void;
}) {
  return (
    <section
      className={styles.column}
      data-step={column.step}
      data-kind={column.kind}
      data-drop={drop ?? undefined}
      aria-label={`${column.label}, ${column.count}`}
      onDragOver={(event) => {
        if (drop === "allowed") event.preventDefault();
      }}
      onDrop={(event) => {
        event.preventDefault();
        if (drop === "allowed") onDrop(column);
      }}
    >
      {/* Every head is the same height: the name takes up to two lines, the
          count and the late badge sit on the right. Each card says its own
          "No next step". */}
      <header className={styles.columnHead}>
        <h3 title={column.label}>{column.label}</h3>
        <span className={styles.headBadges}>
          {column.overdue ? (
            <span className={styles.flag} data-tone="late">
              {column.overdue} late
            </span>
          ) : null}
          <span className={styles.headCount}>{column.count}</span>
        </span>
      </header>
      {column.cards.length ? (
        <ul className={styles.cards}>
          {column.cards.map((lead) => (
            <BoardCard
              key={lead.lead_id}
              lead={lead}
              column={column}
              showOwner={showOwner}
              now={now}
              onOpen={onOpen}
              onCall={onCall}
              onMove={onMove}
              onDragStart={onDragStart}
              onDragEnd={onDragEnd}
            />
          ))}
        </ul>
      ) : (
        <p className={styles.columnEmpty}>
          No leads in {column.label}. Move one here with a card&apos;s Move
          button.
        </p>
      )}
      {column.next_cursor ? (
        <Button variant="ghost" onClick={() => onMore(column)}>
          Show more
        </Button>
      ) : null}
    </section>
  );
}

/** A board after one card moved: out of its column, on top of the other. */
export function moveCard(
  board: Board,
  lead: LeadRow,
  from: string,
  to: string,
): Board {
  const groups = board.groups.map((group) => ({
    ...group,
    columns: group.columns.map((column) => {
      if (column.step === from)
        return {
          ...column,
          count: Math.max(0, column.count - 1),
          cards: column.cards.filter((card) => card.lead_id !== lead.lead_id),
        };
      if (column.step === to)
        return {
          ...column,
          count: column.count + 1,
          cards: [lead, ...column.cards],
        };
      return column;
    }),
  }));
  return {
    ...board,
    groups: groups.map((group) => ({
      ...group,
      count: group.columns.reduce((sum, column) => sum + column.count, 0),
    })),
  };
}

export function PipelineBoard({
  filters,
  canManage,
  onOpen,
  onCall,
  refreshKey = 0,
  initialBoard = null,
}: {
  filters: BoardFilters;
  canManage: boolean;
  onOpen: (leadId: string) => void;
  /** Opens the lead and calls, as a list row's Call does (phones). */
  onCall?: (leadId: string) => void;
  /** Changes when something else changed a lead (a call, the lead sheet). */
  refreshKey?: number;
  /** A board already read (review fixtures). */
  initialBoard?: Board | null;
}) {
  const [board, setBoard] = useState<Board | null>(initialBoard);
  const [failed, setFailed] = useState(false);
  // Each change reads the board again (a move, Retry).
  const [reads, setReads] = useState(0);
  const [moving, setMoving] = useState<Moving | null>(null);
  const [dragging, setDragging] = useState<{
    lead: LeadRow;
    from: BoardColumn;
  } | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());
  const scroller = useRef<HTMLDivElement>(null);
  // Computers: how many stages are out of view on each side of the columns.
  const [edges, setEdges] = useState({ left: 0, right: 0 });
  const measure = useCallback(() => {
    const root = scroller.current;
    if (!root) return;
    const box = root.getBoundingClientRect();
    let left = 0;
    let right = 0;
    root.querySelectorAll<HTMLElement>("[data-step]").forEach((element) => {
      const rect = element.getBoundingClientRect();
      if (rect.right > box.right + 1) right += 1;
      else if (rect.left < box.left - 1) left += 1;
    });
    setEdges((value) =>
      value.left === left && value.right === right ? value : { left, right },
    );
  }, []);
  const page = (direction: 1 | -1) => {
    const root = scroller.current;
    root?.scrollBy?.({
      left: direction * Math.max(240, root.clientWidth - 96),
      behavior: "smooth",
    });
  };
  const pending = useRef(
    new Map<string, { timer: number; send: () => void }>(),
  );
  const key = JSON.stringify(filters);

  // Read the board: on opening, when the filters change, after a move, on Retry.
  const load = useCallback(() => setReads((count) => count + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    readBoard(JSON.parse(key) as BoardFilters, controller.signal).then(
      (next) => {
        setBoard(next);
        setFailed(false);
        setNow(new Date());
      },
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        setFailed(true);
        notify({
          id: "board-failed",
          tone: "error",
          title: "The board didn't load",
          message: reason instanceof LeadsError ? reason.message : "Try again.",
          action: { label: "Retry", run: () => setReads((count) => count + 1) },
        });
      },
    );
    return () => controller.abort();
  }, [key, refreshKey, reads]);

  // A move waiting for Undo goes now if the page closes.
  useEffect(() => {
    const flush = () => {
      for (const item of pending.current.values()) {
        window.clearTimeout(item.timer);
        item.send();
      }
      pending.current.clear();
    };
    const hidden = () => {
      if (document.visibilityState === "hidden") flush();
    };
    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("pagehide", flush);
      document.removeEventListener("visibilitychange", hidden);
      flush();
    };
  }, []);

  const columns = board?.groups.flatMap((group) => group.columns) ?? [];
  const shown = current ?? columns[0]?.step ?? null;

  // Phones: the chosen chip's column scrolls into view inside the board.
  const show = (step: string) => {
    setCurrent(step);
    // Stage keys are letters, digits and underscores: safe in a selector.
    const target = scroller.current?.querySelector<HTMLElement>(
      `[data-step="${step}"]`,
    );
    target?.scrollIntoView?.({
      behavior: "smooth",
      block: "nearest",
      inline: "start",
    });
  };
  useEffect(() => {
    const root = scroller.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    const seen = new IntersectionObserver(
      (entries) => {
        const best = entries
          .filter(
            (entry) => entry.isIntersecting && entry.intersectionRatio > 0.6,
          )
          .map((entry) => (entry.target as HTMLElement).dataset.step)
          .find(Boolean);
        if (best) setCurrent(best);
      },
      { root, threshold: [0.6] },
    );
    root
      .querySelectorAll("[data-step]")
      .forEach((element) => seen.observe(element));
    return () => seen.disconnect();
  }, [board]);
  // The edge counts: measured when the board draws and whenever it is resized.
  useEffect(() => {
    const root = scroller.current;
    if (!root || typeof ResizeObserver === "undefined") return;
    const sized = new ResizeObserver(() => measure());
    sized.observe(root);
    return () => sized.disconnect();
  }, [board, measure]);

  const commit = (lead: LeadRow, from: BoardColumn, move: MoveOption) => {
    const before = board;
    if (!before) return;
    setBoard(moveCard(before, lead, from.step, move.step));
    tick();
    const send = () => {
      pending.current.delete(lead.lead_id);
      moveLead(lead, move.step, { via: "board" }).then(
        () => {
          load();
          const to = leadKind(move.kind);
          if (to)
            track("sx.lead_stage_moved", {
              via: "board",
              source: "seller",
              from_kind: leadKind(from.kind),
              to_kind: to,
              needs: 0,
            });
        },
        (reason: unknown) => {
          if (reason instanceof LeadsError && reason.kept) {
            // Kept on this phone: the card stays where it was dropped.
            notify({
              id: `board-move-${lead.lead_id}`,
              tone: "info",
              title: `${lead.name}: saved on this phone`,
              message: "It's sent as soon as Sales X-Ray answers.",
            });
            return;
          }
          track("sx.board_drag", { result: "refused" });
          setBoard(before);
          notify({
            id: `board-move-${lead.lead_id}`,
            tone: "error",
            title: `${lead.name} wasn't moved`,
            message:
              reason instanceof LeadsError ? reason.message : "Try again.",
          });
        },
      );
    };
    const timer = window.setTimeout(send, UNDO_MS);
    pending.current.set(lead.lead_id, { timer, send });
    notify({
      id: `board-move-${lead.lead_id}`,
      tone: "success",
      title: `${lead.name}: ${move.label}`,
      timeout: UNDO_MS,
      action: {
        label: "Undo",
        run: () => {
          window.clearTimeout(timer);
          pending.current.delete(lead.lead_id);
          setBoard(before);
          track("sx.board_drag", { result: "undone" });
        },
      },
    });
  };

  const dropOn = (column: BoardColumn) => {
    const drag = dragging;
    setDragging(null);
    if (!drag) return;
    const move = drag.from.moves.find((item) => item.step === column.step);
    if (!move) return;
    if (move.needs.length === 0 && move.group === "active") {
      commit(drag.lead, drag.from, move);
      track("sx.board_drag", { result: "moved" });
    } else {
      setMoving({ lead: drag.lead, from: drag.from, initial: move.step });
      track("sx.board_drag", { result: "sheet" });
    }
  };

  const more = async (column: BoardColumn) => {
    if (!column.next_cursor) return;
    try {
      const next = await readColumn(column.step, column.next_cursor, filters);
      if (!next) return;
      setBoard((value) =>
        value
          ? {
              ...value,
              groups: value.groups.map((group) => ({
                ...group,
                columns: group.columns.map((item) =>
                  item.step === column.step
                    ? {
                        ...item,
                        cards: [...item.cards, ...next.cards],
                        next_cursor: next.next_cursor,
                      }
                    : item,
                ),
              })),
            }
          : value,
      );
    } catch (reason) {
      notify({
        id: "board-more",
        tone: "error",
        title: "No more leads loaded",
        message: reason instanceof LeadsError ? reason.message : "Try again.",
      });
    }
  };

  const dropState = (column: BoardColumn) => {
    if (!dragging) return null;
    if (dragging.from.step === column.step) return "source" as const;
    return dragging.from.moves.some((move) => move.step === column.step)
      ? ("allowed" as const)
      : ("blocked" as const);
  };

  if (!board)
    return (
      <div className={styles.board} aria-busy="true" data-loading="">
        <div className={styles.strip} aria-hidden="true">
          {[0, 1, 2, 3].map((index) => (
            <span key={index} className={styles.chipSkeleton} />
          ))}
        </div>
        <div className={styles.columns}>
          {[0, 1, 2].map((index) => (
            <div key={index} className={styles.column}>
              {[0, 1, 2].map((card) => (
                <div key={card} className={styles.cardSkeleton} />
              ))}
            </div>
          ))}
        </div>
        {failed ? (
          <p className={styles.columnEmpty}>The board will appear here.</p>
        ) : null}
      </div>
    );

  if (board.total === 0 && !filters.q && !filters.owner && !filters.source)
    return (
      <Empty
        icon={Users}
        title="No leads yet"
        text="Add your first lead with +, or connect your ad form in Sources."
      />
    );

  const active = board.groups.find((group) => group.group === "active");
  const closed = board.groups.filter((group) => group.group !== "active");
  const column = (item: BoardColumn) => (
    <ColumnView
      key={item.step}
      column={item}
      showOwner={canManage}
      now={now}
      drop={dropState(item)}
      onOpen={onOpen}
      onCall={onCall}
      onMove={(lead, from) => setMoving({ lead, from, initial: null })}
      onDragStart={(lead, from) => setDragging({ lead, from })}
      onDragEnd={() => setDragging(null)}
      onDrop={dropOn}
      onMore={(target) => void more(target)}
    />
  );

  return (
    <div className={styles.board} data-dragging={dragging ? "" : undefined}>
      <nav className={styles.strip} aria-label="Stages">
        {board.groups.map((group) => (
          <div
            key={group.group}
            className={styles.stripGroup}
            data-group={group.group}
          >
            {group.columns.map((item) => (
              <button
                key={item.step}
                type="button"
                className={styles.stripChip}
                data-group={group.group}
                aria-pressed={shown === item.step}
                onClick={() => show(item.step)}
              >
                <span>{item.label}</span>
                <span className={styles.count}>{item.count}</span>
                {item.overdue ? (
                  <span
                    className={styles.dot}
                    aria-label={`${item.overdue} late`}
                  />
                ) : null}
              </button>
            ))}
          </div>
        ))}
      </nav>
      <div
        className={styles.columnsWrap}
        data-fade-left={edges.left ? "" : undefined}
        data-fade-right={edges.right ? "" : undefined}
      >
        <div className={styles.columns} ref={scroller} onScroll={measure}>
          {active?.columns.map(column)}
          <div className={styles.rail}>
            {closed.map((group) => group.columns.map(column))}
          </div>
        </div>
        {edges.left ? (
          <button
            type="button"
            className={styles.edgeButton}
            data-side="left"
            aria-label={`${edges.left} earlier ${edges.left === 1 ? "stage" : "stages"}`}
            onClick={() => page(-1)}
          >
            <ChevronLeft size={16} aria-hidden="true" />
          </button>
        ) : null}
        {edges.right ? (
          <button
            type="button"
            className={styles.edgeButton}
            data-side="right"
            onClick={() => page(1)}
          >
            {edges.right} more
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        ) : null}
      </div>
      {moving ? (
        <StageSheet
          open
          lead={moving.lead}
          moves={moving.from.moves}
          initial={moving.initial}
          via="board"
          onClose={() => setMoving(null)}
          onMoved={() => void load()}
        />
      ) : null}
    </div>
  );
}
