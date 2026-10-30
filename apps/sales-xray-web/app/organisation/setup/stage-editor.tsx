"use client";
import {
  Ban,
  CalendarCheck,
  CircleDashed,
  CircleX,
  Ellipsis,
  Eye,
  EyeOff,
  GripVertical,
  MessagesSquare,
  PhoneMissed,
  Plus,
  Sparkles,
  Star,
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
import { Button, Segmented } from "../../ui/kit";
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
  MEETING_STAGES,
  addStage,
  destinations,
  live,
  meaningBlock,
  meaningLabel,
  meaningOf,
  meetingOn,
  meetingStage,
  moveTo,
  readyLeft,
  recommendedMap,
  removeBlock,
  removed,
  withMeaning,
  type Meaning,
  type MeetingStage,
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

// What a custom stage may mean (New and Not reached are one each).
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

type Tool = "color" | "meaning" | "more";
type Drag = { id: string; from: number; to: number; dy: number; step: number };

/**
 * The stage editor (stages-views-sources.md §3, owner + Dipak, 30 Oct 2026): a live
 * preview of the seller's Leads screen, then one card per stage. Every change saves at
 * once and offers Undo; a stage's meaning, not its name, drives the numbers.
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
  // The list as the manager last left it, until the server has every change.
  const [pending, setPending] = useState<Draft[] | null>(null);
  const list = pending ?? saved;
  const order = live(list);
  const canEdit = view.canEdit;
  const [side, setSide] = useState<Side>("inbound");
  const [open, setOpen] = useState<{ id: string; tool: Tool } | null>(null);
  const [renaming, setRenaming] = useState<{
    id: string;
    label: string;
    cold: string;
  } | null>(null);
  const [adding, setAdding] = useState<null | "pick" | "custom">(null);
  const [custom, setCustom] = useState<{ label: string; meaning: Meaning }>({
    label: "",
    meaning: "interested",
  });
  const [removing, setRemoving] = useState<Draft | null>(null);
  const [recommending, setRecommending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState<Drag | null>(null);
  const version = useRef(view.version);
  const stages = useRef(view.stages);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const ticket = useRef(0);
  const rows = useRef(new Map<string, HTMLLIElement>());
  const grabbed = useRef<{ y: number; centers: number[] } | null>(null);
  useEffect(() => {
    version.current = view.version;
    stages.current = view.stages;
  }, [view]);

  const recommended = templates?.find((item) => item.id === "recommended");

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
          title: "That change wasn't saved",
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
    const cold = editing.cold.trim();
    if (!label) return;
    if (label === stage.label && cold === (stage.coldLabel ?? "")) return;
    commit(
      change(stage.id, {
        label,
        ...(stage.kind === "new" ? { coldLabel: cold || null } : {}),
      }),
      `Renamed ${label}`,
      { undo: list },
    );
  }

  function remove(stage: Draft) {
    setOpen(null);
    if (stage.leads > 0) {
      setRemoving(stage);
      return;
    }
    commit(removed(list, stage.id), `Removed ${stage.label}`, { undo: list });
  }

  function removeTo(stage: Draft, target: Draft) {
    setRemoving(null);
    if (!stage.key || !target.key) return;
    commit(removed(list, stage.id), `Removed ${stage.label}`, {
      map: { [stage.key]: target.key },
      message: `${leadsWords(stage.leads)} moved to ${target.label}, with their history.`,
    });
  }

  function add(stage: { label: string; meaning: Meaning; milestone?: string }) {
    const meaning = MEANINGS.find((item) => item.key === stage.meaning)!;
    setAdding(null);
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

  function meeting(which: MeetingStage, on: boolean) {
    const stage = meetingStage(list, which);
    if (on)
      commit(meetingOn(list, which), `${which.label} is on`, { undo: list });
    else if (stage) remove(stage);
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
      setRecommending(false);
      notify({
        id: "org-stage",
        tone: "success",
        title: "Recommended stages in use",
        message: "Leads kept their meaning and their history.",
      });
    } catch (reason) {
      notify({
        id: "org-stage",
        tone: "error",
        title: "Stages were not changed",
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
    event.currentTarget.setPointerCapture(event.pointerId);
    const boxes = order.map((item) =>
      rows.current.get(item.id)?.getBoundingClientRect(),
    );
    grabbed.current = {
      y: event.clientY,
      centers: boxes.map((box) => (box ? box.top + box.height / 2 : 0)),
    };
    const height = boxes[index]?.height ?? 0;
    setOpen(null);
    setRenaming(null);
    setDrag({ id: stage.id, from: index, to: index, dy: 0, step: height + 8 });
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
    const stage = order[done.from];
    commit(moveTo(list, done.id, done.to), `Moved ${stage.label}`, {
      undo: list,
    });
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
    if (next !== list) commit(next, `Moved ${stage.label}`, { undo: list });
  }

  function shift(index: number): number {
    if (!drag || index === drag.from) return 0;
    if (drag.from < drag.to && index > drag.from && index <= drag.to)
      return -drag.step;
    if (drag.to < drag.from && index >= drag.to && index < drag.from)
      return drag.step;
    return 0;
  }

  const customTaken = order.some(
    (stage) =>
      stage.label.trim().toLocaleLowerCase() ===
      custom.label.trim().toLocaleLowerCase(),
  );
  const hasJunk = order.some((stage) => stage.kind === "junk");

  return (
    <div className={styles.editor}>
      <section className={styles.previewPane} aria-label="Preview">
        <Segmented
          label="Preview side"
          value={side}
          onChange={setSide}
          items={[
            { key: "inbound", label: "Inbound" },
            { key: "cold", label: "Cold" },
          ]}
        />
        <Preview list={list} side={side} />
      </section>

      <section className={styles.listPane} aria-label="Stages">
        <header className={styles.listHead}>
          <h3>
            {order.length} {order.length === 1 ? "stage" : "stages"}
          </h3>
          {canEdit && recommended ? (
            <button
              type="button"
              className={styles.chip}
              disabled={busy}
              onClick={() => setRecommending(true)}
            >
              <Sparkles size={16} aria-hidden="true" />
              Use recommended
            </button>
          ) : null}
        </header>

        <ol className={styles.cards} aria-label="Your lead stages">
          {order.map((stage, index) => {
            const meaning = meaningOf(stage);
            const Icon = ICONS[meaning];
            const first = index === 0;
            const locked =
              stage.kind === "new" || stage.kind === "not_connected";
            // A stage just added has no key until its save comes back: it waits.
            const editable = canEdit && !!stage.key;
            const tool = open?.id === stage.id ? open.tool : null;
            const dragged = drag?.id === stage.id;
            const visible = stage.visible !== false;
            const toggle = (next: Tool) =>
              setOpen(tool === next ? null : { id: stage.id, tool: next });
            const panel = `stage-${stage.id}-${tool ?? "none"}`;
            return (
              <li
                key={stage.id}
                ref={(node) => {
                  if (node) rows.current.set(stage.id, node);
                  else rows.current.delete(stage.id);
                }}
                className={styles.card}
                data-dragged={dragged || undefined}
                data-hidden={!visible || undefined}
                style={{
                  ...tone(stageTone(stage)),
                  transform:
                    dragged && drag
                      ? `translateY(${drag.dy}px)`
                      : shift(index)
                        ? `translateY(${shift(index)}px)`
                        : undefined,
                }}
              >
                <div className={styles.cardRow}>
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
                    aria-expanded={tool === "color"}
                    aria-controls={tool === "color" ? panel : undefined}
                    disabled={!editable}
                    onClick={() => toggle("color")}
                  />
                  <div className={styles.words}>
                    {renaming?.id === stage.id ? (
                      <form
                        className={styles.rename}
                        onSubmit={(event) => {
                          event.preventDefault();
                          finishRename();
                        }}
                        onBlur={(event) => {
                          if (
                            !event.currentTarget.contains(
                              event.relatedTarget as Node | null,
                            )
                          )
                            finishRename();
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Escape") setRenaming(null);
                        }}
                      >
                        <input
                          className={styles.input}
                          aria-label={
                            first ? "Inbound Leads name" : "Stage name"
                          }
                          maxLength={40}
                          autoFocus
                          value={renaming.label}
                          onChange={(event) =>
                            setRenaming({
                              ...renaming,
                              label: event.target.value,
                            })
                          }
                        />
                        {first ? (
                          <input
                            className={styles.input}
                            aria-label="Cold Leads name"
                            placeholder="Cold Leads name"
                            maxLength={40}
                            value={renaming.cold}
                            onChange={(event) =>
                              setRenaming({
                                ...renaming,
                                cold: event.target.value,
                              })
                            }
                          />
                        ) : null}
                        <button type="submit" className={styles.textButton}>
                          Done
                        </button>
                      </form>
                    ) : (
                      <button
                        type="button"
                        className={styles.name}
                        disabled={!editable}
                        aria-label={`Rename ${stage.label}`}
                        onClick={() => {
                          setOpen(null);
                          setRenaming({
                            id: stage.id,
                            label: stage.label,
                            cold: stage.coldLabel ?? "",
                          });
                        }}
                      >
                        <strong>{stage.label}</strong>
                        {first ? (
                          <small>Cold Leads: {stageName(stage, "cold")}</small>
                        ) : null}
                      </button>
                    )}
                    <span className={styles.meta}>
                      {locked || !editable ? (
                        <span className={styles.meaningStill}>
                          <Icon size={14} aria-hidden="true" />
                          {meaningLabel(meaning)}
                        </span>
                      ) : (
                        <button
                          type="button"
                          className={styles.meaning}
                          aria-expanded={tool === "meaning"}
                          aria-controls={tool === "meaning" ? panel : undefined}
                          aria-label={`Meaning of ${stage.label}: ${meaningLabel(meaning)}`}
                          onClick={() => toggle("meaning")}
                        >
                          <Icon size={14} aria-hidden="true" />
                          {meaningLabel(meaning)}
                        </button>
                      )}
                      <span>· {leadsWords(stage.leads)}</span>
                      {visible ? null : <span>· Hidden from sellers</span>}
                    </span>
                  </div>
                  <button
                    type="button"
                    className={styles.iconButton}
                    aria-pressed={visible}
                    aria-label={`Sellers see ${stage.label}`}
                    title={
                      first
                        ? "Sellers always see the first stage"
                        : "Sellers see this"
                    }
                    disabled={!editable || first}
                    onClick={() =>
                      commit(
                        change(stage.id, { visible: !visible }),
                        visible
                          ? `Sellers don't see ${stage.label}`
                          : `Sellers see ${stage.label}`,
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
                      aria-expanded={tool === "more"}
                      aria-controls={tool === "more" ? panel : undefined}
                      disabled={!editable}
                      onClick={() => toggle("more")}
                    >
                      <Ellipsis size={18} aria-hidden="true" />
                    </button>
                  ) : null}
                </div>

                {tool === "color" ? (
                  <div
                    className={styles.panel}
                    id={panel}
                    role="group"
                    aria-label="Colour"
                  >
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
                            setOpen(null);
                            if (stage.color !== color)
                              commit(
                                change(stage.id, { color }),
                                `${stage.label} is ${COLOR_WORDS[color].toLowerCase()}`,
                                { undo: list },
                              );
                          }}
                        />
                      ))}
                      <button
                        type="button"
                        className={styles.textButton}
                        aria-pressed={!stage.color}
                        onClick={() => {
                          setOpen(null);
                          if (stage.color)
                            commit(
                              change(stage.id, { color: null }),
                              `${stage.label} takes its meaning's colour`,
                              { undo: list },
                            );
                        }}
                      >
                        By meaning
                      </button>
                    </div>
                  </div>
                ) : null}

                {tool === "meaning" ? (
                  <div
                    className={styles.panel}
                    id={panel}
                    role="group"
                    aria-label="Meaning"
                  >
                    <p className={styles.help}>
                      {stage.leads > 0
                        ? "It has leads, so only Interested and Meeting swap."
                        : "Its meaning drives the numbers, whatever its name."}
                    </p>
                    <div className={styles.meanings}>
                      {MEANINGS.map((item) => {
                        const ItemIcon = ICONS[item.key];
                        const block = meaningBlock(list, stage, item.key);
                        return (
                          <button
                            key={item.key}
                            type="button"
                            className={styles.meaningChoice}
                            aria-pressed={meaning === item.key}
                            disabled={!!block}
                            title={block ?? undefined}
                            onClick={() => {
                              setOpen(null);
                              if (meaning !== item.key)
                                commit(
                                  list.map((each) =>
                                    each.id === stage.id
                                      ? withMeaning(each, item.key)
                                      : each,
                                  ),
                                  `${stage.label} means ${item.label}`,
                                  { undo: list },
                                );
                            }}
                          >
                            <ItemIcon size={18} aria-hidden="true" />
                            {item.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ) : null}

                {tool === "more" ? (
                  <div className={styles.panel} id={panel}>
                    <button
                      type="button"
                      className={styles.danger}
                      disabled={!!removeBlock(list, stage)}
                      onClick={() => remove(stage)}
                    >
                      Remove stage
                    </button>
                    <p className={styles.help}>
                      {removeBlock(list, stage) ??
                        (stage.leads
                          ? "You pick where its leads go."
                          : "History keeps it.")}
                    </p>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
        {canEdit ? (
          <p className={styles.srOnly} id="stage-move-help">
            Drag to move, or use the up and down arrow keys.
          </p>
        ) : null}

        {canEdit ? (
          <>
            <button
              type="button"
              className={styles.add}
              disabled={order.length >= MAX_STAGES}
              onClick={() => setAdding("pick")}
            >
              <Plus size={18} aria-hidden="true" />
              Add stage
            </button>
            {order.length >= MAX_STAGES ? (
              <p className={styles.help}>{MAX_STAGES} stages at most.</p>
            ) : null}
            <section className={styles.meetings} aria-label="Meetings">
              <h3>Meetings</h3>
              {MEETING_STAGES.map((which) => (
                <label className={styles.switch} key={which.key}>
                  <span>{meetingStage(list, which)?.label ?? which.label}</span>
                  <input
                    type="checkbox"
                    role="switch"
                    checked={!!meetingStage(list, which)}
                    onChange={(event) => meeting(which, event.target.checked)}
                  />
                </label>
              ))}
              <p className={styles.help}>
                Turn off what your business doesn&apos;t do.
              </p>
            </section>
          </>
        ) : null}
      </section>

      <Sheet
        open={adding !== null}
        onClose={() => setAdding(null)}
        title={adding === "custom" ? "Your own stage" : "Add a stage"}
        footer={
          adding === "custom" ? (
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
          ) : undefined
        }
      >
        {adding === "custom" ? (
          <div className={styles.customForm}>
            <label className={styles.field}>
              Name
              <input
                className={styles.input}
                maxLength={40}
                autoFocus
                value={custom.label}
                onChange={(event) =>
                  setCustom({ ...custom, label: event.target.value })
                }
              />
            </label>
            {customTaken ? (
              <p className={styles.help}>There is a stage with this name.</p>
            ) : null}
            <div className={styles.meanings} role="group" aria-label="It means">
              {ADDABLE.map((key) => {
                const ItemIcon = ICONS[key];
                return (
                  <button
                    key={key}
                    type="button"
                    className={styles.meaningChoice}
                    aria-pressed={custom.meaning === key}
                    disabled={key === "junk" && hasJunk}
                    onClick={() => setCustom({ ...custom, meaning: key })}
                  >
                    <ItemIcon size={18} aria-hidden="true" />
                    {meaningLabel(key)}
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          <div className={styles.addList}>
            {readyLeft(list).map((item) => {
              const meaning = meaningOf({
                kind: "interested",
                milestone: item.milestone,
              });
              const ItemIcon = ICONS[meaning];
              return (
                <button
                  key={item.label}
                  type="button"
                  className={styles.addRow}
                  onClick={() =>
                    add({
                      label: item.label,
                      meaning,
                      milestone: item.milestone,
                    })
                  }
                >
                  <span className={styles.addIcon}>
                    <ItemIcon size={20} aria-hidden="true" />
                  </span>
                  <span className={styles.addWords}>
                    <strong>{item.label}</strong>
                    <small>{meaningLabel(meaning)}</small>
                  </span>
                </button>
              );
            })}
            <button
              type="button"
              className={styles.addRow}
              onClick={() => setAdding("custom")}
            >
              <span className={styles.addIcon}>
                <Plus size={20} aria-hidden="true" />
              </span>
              <span className={styles.addWords}>
                <strong>Custom</strong>
                <small>Your own name and meaning</small>
              </span>
            </button>
          </div>
        )}
      </Sheet>

      <Sheet
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={
          removing
            ? `Where do the ${leadsWords(removing.leads)} go?`
            : "Where do the leads go?"
        }
      >
        {removing ? (
          <div className={styles.addList}>
            <p className={styles.help}>
              They leave {removing.label} with their history.
            </p>
            {destinations(list, removing)
              .filter((stage) => stage.key)
              .map((stage) => (
                <button
                  key={stage.id}
                  type="button"
                  className={styles.addRow}
                  style={tone(stageTone(stage))}
                  onClick={() => removeTo(removing, stage)}
                >
                  <span className={styles.dotStill} aria-hidden="true" />
                  <span className={styles.addWords}>
                    <strong>{stage.label}</strong>
                    <small>{meaningLabel(meaningOf(stage))}</small>
                  </span>
                </button>
              ))}
          </div>
        ) : null}
      </Sheet>

      <Sheet
        open={recommending}
        onClose={() => setRecommending(false)}
        title="Use the recommended stages?"
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
        <ol className={styles.recommended}>
          {recommended?.stages.map((stage) => (
            <li key={stage.label}>{stage.label}</li>
          ))}
        </ol>
        <p className={styles.help}>
          Leads move to the stage with the same meaning, with their history.
        </p>
      </Sheet>
    </div>
  );
}

/** What a seller sees on Leads, drawn from the list as it is now. */
function Preview({ list, side }: { list: Draft[]; side: Side }) {
  const shown = live(list).filter((stage) => stage.visible !== false);
  const first = shown[0];
  const firstName = first ? stageName(first, side) : "";
  const numbers =
    side === "inbound"
      ? [firstName, "To call", "Follow-ups"]
      : ["Imported", firstName, "Attempted"];
  return (
    <div
      className={styles.phone}
      data-side={side}
      role="group"
      aria-label={`What sellers see on ${side === "inbound" ? "Inbound" : "Cold"} Leads`}
    >
      <div className={styles.selector} aria-hidden="true">
        <span data-on={side === "inbound" || undefined}>Inbound Leads</span>
        <span data-on={side === "cold" || undefined}>Cold Leads</span>
      </div>
      <div className={styles.sideHead}>
        <strong>{side === "inbound" ? "Inbound Leads" : "Cold Leads"}</strong>
        <small>
          {side === "inbound" ? "Fresh enquiries" : "Outbound work"}
        </small>
      </div>
      <dl className={styles.numbers}>
        {numbers.map((words) => (
          <div key={words}>
            <dt>{words}</dt>
            <dd>–</dd>
          </div>
        ))}
      </dl>
      <div className={styles.tabs}>
        {shown.map((stage, index) => (
          <span
            key={stage.id}
            className={styles.tab}
            data-on={index === 0 || undefined}
            style={tone(stageTone(stage))}
          >
            {stageName(stage, side)}
          </span>
        ))}
        <span className={styles.tab}>All</span>
      </div>
      <div className={styles.leadCard} aria-hidden="true">
        <span className={styles.bar} />
        {first ? (
          <span className={styles.leadChip} style={tone(stageTone(first))}>
            {firstName}
          </span>
        ) : null}
        <span className={styles.barShort} />
      </div>
    </div>
  );
}
