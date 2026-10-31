"use client";
import {
  Ban,
  CalendarCheck,
  ChevronDown,
  CircleDashed,
  CircleX,
  Ellipsis,
  Eye,
  EyeOff,
  GripVertical,
  MessagesSquare,
  Phone,
  PhoneMissed,
  Plus,
  Smartphone,
  Sparkles,
  Star,
  Trash2,
  Trophy,
  type LucideIcon,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { notify } from "../../notice-center";
import { Button } from "../../ui/kit";
import { Sheet } from "../../ui/sheet";
import {
  STAGE_COLORS,
  applyTemplate,
  drafts,
  previewTemplate,
  problem,
  saveStages,
  type Draft,
  type JourneyView,
  type TemplateView,
} from "../../leads/journey/journey-client";
import {
  COLOR_WORDS,
  colorTone,
  stageColor,
  stageName,
  stageTone,
  type Side,
} from "../../leads/journey/stage-look";
import {
  MAX_STAGES,
  MEANINGS,
  addStage,
  destinations,
  live,
  meaningBlock,
  meaningLabel,
  meaningOf,
  moveTo,
  readyLeft,
  recommendedMap,
  removeBlock,
  removed,
  withMeaning,
  type Meaning,
} from "./stage-editor-model";
import styles from "./stage-editor.module.css";

const ICONS: Record<Meaning, LucideIcon> = {
  untouched: CircleDashed,
  not_reached: PhoneMissed,
  in_talks: MessagesSquare,
  interested: Star,
  meeting: CalendarCheck,
  won: Trophy,
  lost: CircleX,
  junk: Ban,
};

// What a stage of your own may count as (the first stage and Not Connected are one each).
const ADDABLE: Meaning[] = [
  "in_talks",
  "interested",
  "meeting",
  "won",
  "lost",
  "junk",
];

const tone = (value: string) => ({ "--stage": value }) as CSSProperties;
const leadsWords = (count: number) =>
  `${count} ${count === 1 ? "lead" : "leads"}`;
const same = (a: string, b: string) =>
  a.trim().toLocaleLowerCase() === b.trim().toLocaleLowerCase();

type Open =
  | { kind: "more"; id: string }
  | { kind: "move"; id: string }
  | { kind: "custom" }
  | { kind: "recommend" }
  | null;
type Drag = { id: string; from: number; to: number; dy: number; step: number };
type Swipe = { id: string; x: number; y: number; dx: number; on: boolean };

// How far a row slides left before letting go removes it.
const SWIPE_REMOVES = 88;

/**
 * Lead stages, as the owner and Dipak want them (31 Oct 2026): a small live preview of the
 * seller's Leads screen, then one plain row per stage (drag, colour, name, sellers see it,
 * more). Every change saves at once, with Undo in the corner.
 */
export function StageEditor({
  view,
  pipeline,
  templates,
  onSaved,
}: {
  view: JourneyView;
  pipeline: string;
  templates: TemplateView[] | null;
  onSaved: (next: JourneyView) => void;
}) {
  const saved = useMemo(() => drafts(view), [view]);
  // The list as the owner last left it, until the server has every change.
  const [pending, setPending] = useState<Draft[] | null>(null);
  const list = pending ?? saved;
  const order = live(list);
  const canEdit = view.canEdit;
  const [side, setSide] = useState<Side>("inbound");
  const [open, setOpen] = useState<Open>(null);
  const [renaming, setRenaming] = useState<{
    id: string;
    label: string;
  } | null>(null);
  const [custom, setCustom] = useState<{ label: string; meaning: Meaning }>({
    label: "",
    meaning: "interested",
  });
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [swipe, setSwipe] = useState<Swipe | null>(null);
  const version = useRef(view.version);
  const stages = useRef(view.stages);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const ticket = useRef(0);
  const rows = useRef(new Map<string, HTMLLIElement>());
  const grabbed = useRef<{ y: number; centers: number[] } | null>(null);
  // A swipe ends in a click on whatever was under the finger: that click is ignored.
  const swiped = useRef(false);
  useEffect(() => {
    version.current = view.version;
    stages.current = view.stages;
  }, [view]);

  const recommended = templates?.find((item) => item.id === "recommended");
  // Use recommended's preview: today's stages and where their leads go.
  const [moves, setMoves] = useState<
    { from: string; leads: number; to: string }[] | null
  >(null);
  const differs =
    !!recommended &&
    (recommended.stages.length !== order.length ||
      recommended.stages.some(
        (item, index) => !same(item.label, order[index]?.label ?? ""),
      ));
  const sheetStage =
    open && "id" in open
      ? list.find((stage) => stage.id === open.id)
      : undefined;

  /** Saves the whole list now, one save after another, then offers Undo. */
  function commit(
    next: Draft[],
    title: string,
    options: {
      undo?: Draft[];
      map?: Record<string, string>;
      message?: string;
    } = {},
  ) {
    const issue = problem(next);
    if (issue) {
      notify({ id: "org-stage", tone: "error", title: issue });
      return;
    }
    const mine = ++ticket.current;
    setPending(next);
    queue.current = queue.current.then(async () => {
      try {
        const fresh = await saveStages(
          version.current,
          next,
          pipeline,
          options.map,
        );
        version.current = fresh.version;
        stages.current = fresh.stages;
        if (mine === ticket.current) setPending(null);
        onSaved(fresh);
        const undo = options.undo;
        notify({
          id: "org-stage",
          tone: "success",
          title,
          ...(options.message ? { message: options.message } : {}),
          ...(undo
            ? { action: { label: "Undo", run: () => commit(undo, "Undone") } }
            : {}),
        });
      } catch (reason) {
        if (mine === ticket.current) setPending(null);
        notify({
          id: "org-stage",
          tone: "error",
          title: "Not saved",
          message: reason instanceof Error ? reason.message : "Try again.",
        });
      }
    });
  }

  const change = (id: string, patch: Partial<Draft>) =>
    list.map((stage) => (stage.id === id ? { ...stage, ...patch } : stage));

  function finishRename() {
    const editing = renaming;
    setRenaming(null);
    const stage = editing && list.find((item) => item.id === editing.id);
    if (!editing || !stage) return;
    const label = editing.label.trim();
    if (!label || label === stage.label) return;
    commit(change(stage.id, { label }), "Renamed", { undo: list });
  }

  function remove(stage: Draft) {
    if (removeBlock(list, stage)) {
      notify({
        id: "org-stage",
        tone: "info",
        title: removeBlock(list, stage) ?? "",
      });
      return;
    }
    if (stage.leads > 0) {
      setOpen({ kind: "move", id: stage.id });
      return;
    }
    setOpen(null);
    commit(removed(list, stage.id), `Removed ${stage.label}`, { undo: list });
  }

  function removeTo(stage: Draft, target: Draft) {
    setOpen(null);
    if (!stage.key || !target.key) return;
    commit(removed(list, stage.id), `Removed ${stage.label}`, {
      map: { [stage.key]: target.key },
      message: `${leadsWords(stage.leads)} moved to ${target.label}.`,
    });
  }

  function add(stage: { label: string; meaning: Meaning; milestone?: string }) {
    const meaning = MEANINGS.find((item) => item.key === stage.meaning)!;
    setOpen(null);
    setCustom({ label: "", meaning: "interested" });
    commit(
      addStage(list, {
        label: stage.label,
        kind: meaning.kind,
        milestone: stage.milestone ?? meaning.milestone,
      }),
      `Added ${stage.label.trim()}`,
      { undo: list },
    );
  }

  // What moves where, before the switch (phone personas, 1 Nov 2026: Use
  // recommended switched with no preview of where the leads go).
  async function openRecommended() {
    setOpen({ kind: "recommend" });
    setMoves(null);
    try {
      await queue.current;
      const preview = await previewTemplate(
        version.current,
        "recommended",
        pipeline,
      );
      const map = recommendedMap(stages.current, preview);
      setMoves(
        preview.landings
          .filter((landing) => landing.leads > 0)
          .map((landing) => ({
            from: landing.fromLabel,
            leads: landing.leads,
            to:
              preview.stages.find(
                (stage) =>
                  stage.key === (map[landing.fromKey] ?? landing.toKey),
              )?.label ?? landing.toLabel,
          })),
      );
    } catch {
      setMoves([]);
    }
  }

  async function adoptRecommended() {
    setBusy(true);
    try {
      await queue.current;
      const preview = await previewTemplate(
        version.current,
        "recommended",
        pipeline,
      );
      const fresh = await applyTemplate(
        version.current,
        "recommended",
        pipeline,
        recommendedMap(stages.current, preview),
      );
      version.current = fresh.version;
      stages.current = fresh.stages;
      setPending(null);
      onSaved(fresh);
      setOpen(null);
      notify({ id: "org-stage", tone: "success", title: "Stages updated" });
    } catch (reason) {
      notify({
        id: "org-stage",
        tone: "error",
        title: "Not changed",
        message: reason instanceof Error ? reason.message : "Try again.",
      });
    } finally {
      setBusy(false);
    }
  }

  /* ----- drag to reorder (the grip); arrow keys do the same ----- */

  function grab(
    event: PointerEvent<HTMLButtonElement>,
    stage: Draft,
    index: number,
  ) {
    if (!canEdit || index === 0 || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    const boxes = order.map((item) =>
      rows.current.get(item.id)?.getBoundingClientRect(),
    );
    grabbed.current = {
      y: event.clientY,
      centers: boxes.map((box) => (box ? box.top + box.height / 2 : 0)),
    };
    setRenaming(null);
    setDrag({
      id: stage.id,
      from: index,
      to: index,
      dy: 0,
      step: boxes[index]?.height ?? 48,
    });
  }

  function drift(event: PointerEvent<HTMLButtonElement>) {
    const start = grabbed.current;
    if (!drag || !start) return;
    const dy = event.clientY - start.y;
    const center = start.centers[drag.from] + dy;
    const above = start.centers.filter(
      (value, index) => index !== drag.from && value < center,
    ).length;
    setDrag({ ...drag, dy, to: Math.max(1, above) });
  }

  function drop() {
    const done = drag;
    setDrag(null);
    grabbed.current = null;
    if (!done || done.to === done.from) return;
    commit(moveTo(list, done.id, done.to), "Order saved", { undo: list });
  }

  function nudge(
    event: KeyboardEvent<HTMLButtonElement>,
    stage: Draft,
    index: number,
  ) {
    const by = event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0;
    if (!by) return;
    event.preventDefault();
    const next = moveTo(list, stage.id, index + by);
    if (next !== list) commit(next, "Order saved", { undo: list });
  }

  function shift(index: number): number {
    if (!drag || index === drag.from) return 0;
    if (drag.from < drag.to && index > drag.from && index <= drag.to)
      return -drag.step;
    if (drag.to < drag.from && index >= drag.to && index < drag.from)
      return drag.step;
    return 0;
  }

  /* ----- swipe left to remove (never from the screen's edge: that is Back) ----- */

  function touch(event: PointerEvent<HTMLDivElement>, stage: Draft) {
    const edge = 24;
    if (
      !canEdit ||
      !stage.key ||
      event.clientX < edge ||
      event.clientX > window.innerWidth - edge
    )
      return;
    setSwipe({
      id: stage.id,
      x: event.clientX,
      y: event.clientY,
      dx: 0,
      on: false,
    });
  }

  function slide(event: PointerEvent<HTMLDivElement>) {
    if (!swipe) return;
    const dx = event.clientX - swipe.x;
    const dy = event.clientY - swipe.y;
    if (!swipe.on) {
      if (Math.abs(dy) > 10 && Math.abs(dy) > Math.abs(dx)) {
        setSwipe(null);
        return;
      }
      if (dx > -10) return;
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    setSwipe({
      ...swipe,
      on: true,
      dx: Math.max(-SWIPE_REMOVES - 24, Math.min(0, dx)),
    });
  }

  function release(stage: Draft) {
    const done = swipe;
    setSwipe(null);
    if (!done?.on) return;
    swiped.current = true;
    window.setTimeout(() => {
      swiped.current = false;
    }, 0);
    if (done.dx <= -SWIPE_REMOVES) remove(stage);
  }

  const customTaken = order.some((stage) => same(stage.label, custom.label));
  const hasJunk = order.some((stage) => stage.kind === "junk");

  return (
    <div className={styles.editor}>
      <section className={styles.previewPane} aria-label="Preview">
        <Preview list={list} side={side} onSide={setSide} />
      </section>

      <section className={styles.listPane} aria-label="Stages">
        <ol className={styles.rows} aria-label="Your lead stages">
          {order.map((stage, index) => {
            const first = index === 0;
            // A stage just added has no key until its save comes back: it waits.
            const editable = canEdit && !!stage.key;
            const dragged = drag?.id === stage.id;
            const visible = stage.visible !== false;
            const sliding = swipe?.id === stage.id && swipe.on ? swipe.dx : 0;
            const moved = dragged && drag ? drag.dy : shift(index);
            return (
              <li
                key={stage.id}
                ref={(node) => {
                  if (node) rows.current.set(stage.id, node);
                  else rows.current.delete(stage.id);
                }}
                className={styles.row}
                data-dragged={dragged || undefined}
                data-hidden={!visible || undefined}
                style={{
                  ...tone(stageTone(stage)),
                  transform: moved ? `translateY(${moved}px)` : undefined,
                }}
              >
                <span
                  className={styles.swipeBack}
                  aria-hidden="true"
                  data-ready={sliding <= -SWIPE_REMOVES || undefined}
                >
                  <Trash2 size={18} />
                  Remove
                </span>
                <div
                  className={styles.rowFront}
                  data-sliding={sliding ? "" : undefined}
                  style={
                    sliding
                      ? { transform: `translateX(${sliding}px)` }
                      : undefined
                  }
                  onPointerDown={(event) => touch(event, stage)}
                  onPointerMove={slide}
                  onPointerUp={() => release(stage)}
                  onPointerCancel={() => setSwipe(null)}
                  onClickCapture={(event) => {
                    if (swiped.current) {
                      event.stopPropagation();
                      event.preventDefault();
                    }
                  }}
                >
                  {canEdit ? (
                    <button
                      type="button"
                      className={styles.grip}
                      aria-label={
                        first
                          ? `${stage.label} stays first`
                          : `Move ${stage.label}`
                      }
                      aria-describedby={first ? undefined : "stage-move-help"}
                      disabled={first || !editable}
                      onPointerDown={(event) => grab(event, stage, index)}
                      onPointerMove={drift}
                      onPointerUp={drop}
                      onPointerCancel={() => {
                        setDrag(null);
                        grabbed.current = null;
                      }}
                      onKeyDown={(event) => nudge(event, stage, index)}
                    >
                      <GripVertical size={18} aria-hidden="true" />
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className={styles.dot}
                    aria-label={`Colour of ${stage.label}: ${COLOR_WORDS[stageColor(stage)]}`}
                    disabled={!editable}
                    onClick={() => setOpen({ kind: "more", id: stage.id })}
                  />
                  {renaming?.id === stage.id ? (
                    <input
                      className={styles.nameInput}
                      aria-label="Stage name"
                      maxLength={40}
                      autoFocus
                      value={renaming.label}
                      onChange={(event) =>
                        setRenaming({ ...renaming, label: event.target.value })
                      }
                      onBlur={finishRename}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") event.currentTarget.blur();
                        if (event.key === "Escape") setRenaming(null);
                      }}
                    />
                  ) : (
                    <button
                      type="button"
                      className={styles.name}
                      disabled={!editable}
                      aria-label={`Rename ${stage.label}`}
                      onClick={() =>
                        setRenaming({ id: stage.id, label: stage.label })
                      }
                    >
                      <span>{stage.label}</span>
                      {first && stage.coldLabel ? (
                        <small>{stage.coldLabel}</small>
                      ) : null}
                    </button>
                  )}
                  <button
                    type="button"
                    className={styles.iconButton}
                    aria-pressed={visible}
                    aria-label={`Sellers see ${stage.label}`}
                    disabled={!editable || first}
                    onClick={() =>
                      commit(
                        change(stage.id, { visible: !visible }),
                        visible ? "Hidden from sellers" : "Shown to sellers",
                        { undo: list },
                      )
                    }
                  >
                    {visible ? (
                      <Eye size={18} aria-hidden="true" />
                    ) : (
                      <EyeOff size={18} aria-hidden="true" />
                    )}
                  </button>
                  {canEdit ? (
                    <button
                      type="button"
                      className={styles.iconButton}
                      aria-label={`More for ${stage.label}`}
                      aria-haspopup="dialog"
                      disabled={!editable}
                      onClick={() => setOpen({ kind: "more", id: stage.id })}
                    >
                      <Ellipsis size={18} aria-hidden="true" />
                    </button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
        {canEdit ? (
          <p className={styles.srOnly} id="stage-move-help">
            Drag to move, or use the up and down arrow keys.
          </p>
        ) : null}

        {canEdit && order.length < MAX_STAGES ? (
          <div className={styles.addStage} role="group" aria-label="Add stage">
            <span className={styles.addLabel}>Add stage</span>
            <div className={styles.chips}>
              {readyLeft(list).map((item) => (
                <button
                  key={item.label}
                  type="button"
                  className={styles.chip}
                  onClick={() =>
                    add({
                      label: item.label,
                      meaning: meaningOf({
                        kind: "interested",
                        milestone: item.milestone,
                      }),
                      milestone: item.milestone,
                    })
                  }
                >
                  <Plus size={14} aria-hidden="true" />
                  {item.label}
                </button>
              ))}
              <button
                type="button"
                className={styles.chip}
                onClick={() => setOpen({ kind: "custom" })}
              >
                <Plus size={14} aria-hidden="true" />
                Custom
              </button>
            </div>
          </div>
        ) : null}

        {canEdit && differs ? (
          <button
            type="button"
            className={styles.quiet}
            disabled={busy}
            onClick={() => void openRecommended()}
          >
            <Sparkles size={16} aria-hidden="true" />
            Use recommended
          </button>
        ) : null}
      </section>

      {/* More: what the stage counts as, its colour, the Cold name, remove. */}
      <Sheet
        open={open?.kind === "more" && !!sheetStage}
        onClose={() => setOpen(null)}
        title={sheetStage?.label ?? ""}
      >
        {open?.kind === "more" && sheetStage ? (
          <MoreSheet
            stage={sheetStage}
            first={order[0]?.id === sheetStage.id}
            list={list}
            onCountsAs={(meaning) =>
              commit(
                list.map((each) =>
                  each.id === sheetStage.id ? withMeaning(each, meaning) : each,
                ),
                "Saved",
                { undo: list },
              )
            }
            onColor={(color) =>
              commit(change(sheetStage.id, { color }), "Colour saved", {
                undo: list,
              })
            }
            onColdName={(coldLabel) =>
              commit(change(sheetStage.id, { coldLabel }), "Renamed", {
                undo: list,
              })
            }
            onRemove={() => remove(sheetStage)}
          />
        ) : null}
      </Sheet>

      <Sheet
        open={open?.kind === "move" && !!sheetStage}
        onClose={() => setOpen(null)}
        title={
          sheetStage
            ? `Move ${leadsWords(sheetStage.leads)} to`
            : "Move leads to"
        }
      >
        {open?.kind === "move" && sheetStage ? (
          <div className={styles.sheetList}>
            {destinations(list, sheetStage)
              .filter((stage) => stage.key)
              .map((stage) => (
                <button
                  key={stage.id}
                  type="button"
                  className={styles.sheetRow}
                  style={tone(stageTone(stage))}
                  onClick={() => removeTo(sheetStage, stage)}
                >
                  <span className={styles.dotStill} aria-hidden="true" />
                  {stage.label}
                </button>
              ))}
          </div>
        ) : null}
      </Sheet>

      <Sheet
        open={open?.kind === "custom"}
        onClose={() => setOpen(null)}
        title="New stage"
        footer={
          <Button
            variant="primary"
            disabled={
              !custom.label.trim() ||
              customTaken ||
              (custom.meaning === "junk" && hasJunk)
            }
            onClick={() => add(custom)}
          >
            Add stage
          </Button>
        }
      >
        {open?.kind === "custom" ? (
          <div className={styles.sheetBody}>
            <input
              className={styles.field}
              aria-label="New stage name"
              placeholder="Stage name"
              maxLength={40}
              autoFocus
              value={custom.label}
              onChange={(event) =>
                setCustom({ ...custom, label: event.target.value })
              }
            />
            <span className={styles.sheetLabel}>Counts as</span>
            <div className={styles.choices}>
              {ADDABLE.map((key) => {
                const Icon = ICONS[key];
                return (
                  <button
                    key={key}
                    type="button"
                    className={styles.choice}
                    aria-pressed={custom.meaning === key}
                    disabled={key === "junk" && hasJunk}
                    onClick={() => setCustom({ ...custom, meaning: key })}
                  >
                    <Icon size={18} aria-hidden="true" />
                    {meaningLabel(key)}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}
      </Sheet>

      <Sheet
        open={open?.kind === "recommend"}
        onClose={() => setOpen(null)}
        title="Use recommended"
        footer={
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => void adoptRecommended()}
          >
            Use recommended
          </Button>
        }
      >
        {open?.kind === "recommend" ? (
          <div className={styles.sheetBody}>
            <ol className={styles.recommended}>
              {recommended?.stages.map((stage, index) => (
                <li key={stage.label}>
                  {stage.label}
                  {index === 0 ? <small> · Unworked</small> : null}
                </li>
              ))}
            </ol>
            {moves === null ? (
              <p className={styles.help}>Checking where your leads go…</p>
            ) : moves.length ? (
              <>
                <p className={styles.help}>Where today&apos;s leads go</p>
                <ul
                  className={styles.recommended}
                  aria-label="What moves where"
                >
                  {moves.map((move) => (
                    <li key={move.from}>
                      {move.from} · {move.leads}{" "}
                      {move.leads === 1 ? "lead" : "leads"} → {move.to}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
            <p className={styles.help}>
              Each lead moves to its matching stage.
            </p>
          </div>
        ) : null}
      </Sheet>
    </div>
  );
}

/** A stage's other settings: what it counts as, its colour, the Cold name, remove. */
function MoreSheet({
  stage,
  first,
  list,
  onCountsAs,
  onColor,
  onColdName,
  onRemove,
}: {
  stage: Draft;
  first: boolean;
  list: Draft[];
  onCountsAs: (meaning: Meaning) => void;
  onColor: (color: Draft["color"]) => void;
  onColdName: (name: string | null) => void;
  onRemove: () => void;
}) {
  const meaning = meaningOf(stage);
  const locked = stage.kind === "new" || stage.kind === "not_connected";
  const [cold, setCold] = useState(stage.coldLabel ?? "");
  const blocked = removeBlock(list, stage);
  return (
    <div className={styles.sheetBody}>
      {first ? (
        <label className={styles.sheetLabel}>
          Name on Cold Leads
          <input
            className={styles.field}
            maxLength={40}
            placeholder={stage.label}
            value={cold}
            onChange={(event) => setCold(event.target.value)}
            onBlur={() => {
              const next = cold.trim() || null;
              if (next !== (stage.coldLabel ?? null)) onColdName(next);
            }}
          />
        </label>
      ) : null}

      <span className={styles.sheetLabel}>Counts as</span>
      <div className={styles.choices}>
        {MEANINGS.map((item) => {
          const Icon = ICONS[item.key];
          const block = locked
            ? item.key === meaning
              ? null
              : "locked"
            : meaningBlock(list, stage, item.key);
          return (
            <button
              key={item.key}
              type="button"
              className={styles.choice}
              aria-pressed={meaning === item.key}
              disabled={!!block}
              onClick={() => {
                if (meaning !== item.key) onCountsAs(item.key);
              }}
            >
              <Icon size={16} aria-hidden="true" />
              {item.label}
            </button>
          );
        })}
      </div>
      {stage.leads > 0 && !locked ? (
        <p className={styles.help}>
          It has leads: only Interested and Meeting swap.
        </p>
      ) : null}

      <span className={styles.sheetLabel}>Colour</span>
      <div className={styles.swatches}>
        {STAGE_COLORS.map((color) => (
          <button
            key={color}
            type="button"
            className={styles.swatch}
            style={tone(colorTone(color))}
            aria-label={COLOR_WORDS[color]}
            aria-pressed={stage.color === color}
            onClick={() => {
              if (stage.color !== color) onColor(color);
            }}
          />
        ))}
        <button
          type="button"
          className={styles.auto}
          aria-pressed={!stage.color}
          onClick={() => {
            if (stage.color) onColor(null);
          }}
        >
          Auto
        </button>
      </div>

      <button
        type="button"
        className={styles.danger}
        disabled={!!blocked}
        onClick={onRemove}
      >
        <Trash2 size={16} aria-hidden="true" />
        Remove stage
      </button>
      {blocked ? <p className={styles.help}>{blocked}</p> : null}
    </div>
  );
}

/** What a seller sees on Leads (Dipak's screen), drawn from the list as it is now. Folded
 *  on a phone so the stages come first (owner, 31 Oct 2026); one tap opens it: the side
 *  selector, the three work views, the stage picker and one lead row. */
function Preview({
  list,
  side,
  onSide,
}: {
  list: Draft[];
  side: Side;
  onSide: (next: Side) => void;
}) {
  // Open from the start where it sits beside the list (a computer).
  const [open, setOpen] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(min-width: 900px)").matches,
  );
  const shown = live(list).filter((stage) => stage.visible !== false);
  const first = shown[0];
  return (
    <div className={styles.previewBox}>
      <button
        type="button"
        className={styles.previewToggle}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Smartphone size={18} aria-hidden="true" />
        <span>Preview what sellers see</span>
        <ChevronDown
          size={18}
          aria-hidden="true"
          className={styles.previewChevron}
          data-open={open || undefined}
        />
      </button>
      {open ? (
        <div
          className={styles.phone}
          data-side={side}
          role="group"
          aria-label={`What sellers see on ${side === "inbound" ? "Inbound" : "Cold"} Leads`}
        >
          <div
            className={styles.selector}
            role="group"
            aria-label="Preview side"
          >
            <button
              type="button"
              aria-pressed={side === "inbound"}
              onClick={() => onSide("inbound")}
            >
              Inbound Leads
            </button>
            <button
              type="button"
              aria-pressed={side === "cold"}
              onClick={() => onSide("cold")}
            >
              Cold Leads
            </button>
          </div>
          <div className={styles.views} aria-hidden="true">
            <span data-on="">To Call</span>
            <span>Follow-ups</span>
            <span>All Leads</span>
          </div>
          <div className={styles.dropHead} aria-hidden="true">
            <span>All stages</span>
            <ChevronDown size={14} />
          </div>
          {/* A sample row as Dipak's mockup draws one (orchestrator, 31 Oct 2026): a
              made-up person in the first stage sellers see. */}
          <div className={styles.leadRow} aria-hidden="true">
            <span className={styles.avatar}>NK</span>
            <span className={styles.leadLines}>
              <strong>Neha Kapoor</strong>
              {first ? (
                <small style={tone(stageTone(first))}>
                  <i />
                  <span>
                    {stageName(first, side)} ·{" "}
                    {side === "cold" ? "Bulk Import" : "Meta Ads"}
                  </span>
                </small>
              ) : null}
              <small>
                <span>First call pending</span>
              </small>
            </span>
            <span className={styles.call}>
              <Phone size={16} />
            </span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
