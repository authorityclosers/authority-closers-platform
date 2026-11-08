"use client";
import {
  ArrowDown,
  ArrowUp,
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
import { keepDraft, readDraft } from "../../leads/drafts";
import { OVERLAY_DEPTH_KEY, OVERLAY_FORWARD_EVENT } from "../../ui/back-close";
import { Button } from "../../ui/kit";
import { Sheet } from "../../ui/sheet";
import { useWorkspaceAccess } from "../../workspace-access";
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

/**
 * The open sheet in the address: ?stage=<stage id> for that stage's More,
 * ?add=stage for a stage of your own (a stage's id can be "new").
 */
type SheetAddress = ["stage", string] | ["add", "stage"];

function sheetInAddress(): Open {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  if (params.get("add") === "stage") return { kind: "custom" };
  const id = params.get("stage");
  return id ? { kind: "more", id } : null;
}

/** Whether the current history entry is an open sheet's own (back-close). */
function onSheetEntry(): boolean {
  const state: unknown = window.history.state;
  const depth =
    state && typeof state === "object"
      ? (state as Record<string, unknown>)[OVERLAY_DEPTH_KEY]
      : 0;
  return typeof depth === "number" && depth > 0;
}

function writeSheetAddress(sheet: SheetAddress | null) {
  const before = new URLSearchParams(window.location.search);
  const next = new URLSearchParams(before);
  next.delete("stage");
  if (next.get("add") === "stage") next.delete("add");
  if (sheet) next.set(sheet[0], sheet[1]);
  const query = next.toString();
  if (query === before.toString()) return;
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
  );
}

/** Unsaved changes kept on this device, only for the list they were made on. */
function keptDraft(key: string, version: number, ids: string): Draft[] | null {
  try {
    const kept = JSON.parse(readDraft(key) || "null") as {
      version?: number;
      ids?: string;
      list?: unknown;
    } | null;
    return kept?.version === version &&
      kept.ids === ids &&
      Array.isArray(kept.list)
      ? (kept.list as Draft[])
      : null;
  } catch {
    return null;
  }
}

/**
 * Lead stages, as the owner and Dipak want them (31 Oct 2026): a small live preview of the
 * seller's Leads screen, then one plain row per stage (drag, colour, name, sellers see it,
 * more). Changes wait until Save, with Undo in the corner after it (owner, production
 * reports 151 and 133, 3 Nov 2026: a swipe moved and saved real stages). A finger never
 * drags or removes: the mouse drags by the grip, a phone moves from More.
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
  const tenant = useWorkspaceAccess()?.context?.tenantId ?? "";
  const draftKey = `stages:${tenant}:${pipeline}`;
  const savedIds = saved.map((stage) => stage.id).join(" ");
  // Changes not saved yet: nothing reaches the server before Save. They stay on
  // this device until Save or Discard, so Back, Forward or a refresh never lose
  // them (QA robot, 8 Nov 2026: a Cold name typed in More was gone after each).
  const [draft, setDraft] = useState<Draft[] | null>(() =>
    keptDraft(draftKey, view.version, savedIds),
  );
  useEffect(() => {
    keepDraft(
      draftKey,
      draft
        ? JSON.stringify({ version: view.version, ids: savedIds, list: draft })
        : "",
    );
  }, [draft, draftKey, savedIds, view.version]);
  // The list as the owner last left it, until the server has every change.
  const [pending, setPending] = useState<Draft[] | null>(null);
  const list = draft ?? pending ?? saved;
  const order = live(list);
  const canEdit = view.canEdit;
  const [side, setSide] = useState<Side>("inbound");
  const [open, setOpen] = useState<Open>(() =>
    canEdit ? sheetInAddress() : null,
  );
  const [renaming, setRenaming] = useState<{
    id: string;
    label: string;
  } | null>(null);
  // A stage of your own: its name is kept as typed, like the list.
  const customKey = `${draftKey}:new`;
  const [custom, setCustomNow] = useState<{ label: string; meaning: Meaning }>(
    () => ({ label: readDraft(customKey), meaning: "interested" }),
  );
  const setCustom = (next: { label: string; meaning: Meaning }) => {
    setCustomNow(next);
    keepDraft(customKey, next.label);
  };
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

  // The open sheet is in the address, as Leads keeps ?lead=<id> (orchestrator,
  // 8 Nov 2026): on the sheet's own Back entry, so Back closes it, and Forward
  // or a refresh opens it again.
  const address: SheetAddress | null =
    open?.kind === "custom"
      ? ["add", "stage"]
      : open?.kind === "more" && sheetStage
        ? ["stage", open.id]
        : null;
  const [addressName, addressValue] = address ?? [null, null];
  useEffect(() => {
    const sheet =
      addressName === "add"
        ? (["add", "stage"] as SheetAddress)
        : addressName === "stage" && addressValue
          ? (["stage", addressValue] as SheetAddress)
          : null;
    if (!sheet) {
      // A refresh with a sheet open left it on the page's own entry.
      if (!onSheetEntry()) writeSheetAddress(null);
      return;
    }
    // Only on the sheet's own entry, never the page's: Back must land clean.
    let timer = 0;
    let tries = 0;
    const write = () => {
      if (onSheetEntry()) writeSheetAddress(sheet);
      else if (++tries < 30) timer = window.setTimeout(write, 100);
    };
    timer = window.setTimeout(write, 0);
    return () => window.clearTimeout(timer);
  }, [addressName, addressValue]);
  useEffect(() => {
    if (!canEdit) return;
    const claim = (event: Event) => {
      const again = sheetInAddress();
      if (!again) return;
      event.preventDefault();
      setOpen(again);
    };
    window.addEventListener(OVERLAY_FORWARD_EVENT, claim);
    return () => window.removeEventListener(OVERLAY_FORWARD_EVENT, claim);
  }, [canEdit]);

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
    setDraft(null);
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

  /** Keeps a change on screen until Save; a list that can't be saved says why now. */
  function edit(next: Draft[]) {
    const issue = problem(next);
    if (issue) {
      notify({ id: "org-stage", tone: "error", title: issue });
      return;
    }
    setDraft(next);
  }

  const save = () => {
    if (draft) commit(draft, "Stages saved", { undo: saved });
  };

  const change = (id: string, patch: Partial<Draft>) =>
    list.map((stage) => (stage.id === id ? { ...stage, ...patch } : stage));

  function finishRename() {
    const editing = renaming;
    setRenaming(null);
    const stage = editing && list.find((item) => item.id === editing.id);
    if (!editing || !stage) return;
    const label = editing.label.trim();
    if (!label || label === stage.label) return;
    edit(change(stage.id, { label }));
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
    edit(removed(list, stage.id));
  }

  // Moving a stage's leads is confirmed in its own sheet, so it saves there,
  // with any changes waiting beside it.
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
    edit(
      addStage(list, {
        label: stage.label,
        kind: meaning.kind,
        milestone: stage.milestone ?? meaning.milestone,
      }),
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
      setDraft(null);
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

  /* ----- drag to reorder (the grip, by mouse); arrow keys and More do the same ----- */

  function grab(
    event: PointerEvent<HTMLButtonElement>,
    stage: Draft,
    index: number,
  ) {
    // A finger on the grip is someone scrolling the list, never a drag.
    if (event.pointerType !== "mouse") return;
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
    edit(moveTo(list, done.id, done.to));
  }

  /** One place up or down; the list itself when the stage can't go there. */
  const moved = (stage: Draft, by: number) =>
    moveTo(list, stage.id, order.indexOf(stage) + by);

  function nudge(event: KeyboardEvent<HTMLButtonElement>, stage: Draft) {
    const by = event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0;
    if (!by) return;
    event.preventDefault();
    const next = moved(stage, by);
    if (next !== list) edit(next);
  }

  function shift(index: number): number {
    if (!drag || index === drag.from) return 0;
    if (drag.from < drag.to && index > drag.from && index <= drag.to)
      return -drag.step;
    if (drag.to < drag.from && index >= drag.to && index < drag.from)
      return drag.step;
    return 0;
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
            const offset = dragged && drag ? drag.dy : shift(index);
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
                  transform: offset ? `translateY(${offset}px)` : undefined,
                }}
              >
                <div className={styles.rowFront}>
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
                      onKeyDown={(event) => nudge(event, stage)}
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
                      edit(change(stage.id, { visible: !visible }))
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
        {draft ? (
          <div
            className={styles.saveBar}
            role="group"
            aria-label="Unsaved changes"
          >
            <span>Not saved yet</span>
            <Button variant="ghost" onClick={() => setDraft(null)}>
              Discard
            </Button>
            <Button variant="primary" onClick={save}>
              Save
            </Button>
          </div>
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
            onMove={(by) => edit(moved(sheetStage, by))}
            canMove={(by) => moved(sheetStage, by) !== list}
            onCountsAs={(meaning) =>
              edit(
                list.map((each) =>
                  each.id === sheetStage.id ? withMeaning(each, meaning) : each,
                ),
              )
            }
            onColor={(color) => edit(change(sheetStage.id, { color }))}
            onColdName={(coldLabel) =>
              edit(change(sheetStage.id, { coldLabel }))
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

/** A stage's other settings: its place, what it counts as, its colour, the Cold name, remove. */
function MoreSheet({
  stage,
  first,
  list,
  onMove,
  canMove,
  onCountsAs,
  onColor,
  onColdName,
  onRemove,
}: {
  stage: Draft;
  first: boolean;
  list: Draft[];
  onMove: (by: -1 | 1) => void;
  canMove: (by: -1 | 1) => boolean;
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
            onChange={(event) => {
              // Into the unsaved list as it is typed: Back closing the sheet
              // keeps it (QA robot, 8 Nov 2026).
              setCold(event.target.value);
              const next = event.target.value.trim() || null;
              if (next !== (stage.coldLabel ?? null)) onColdName(next);
            }}
          />
        </label>
      ) : (
        // A phone moves a stage here, never by a swipe (production 151).
        <div
          className={styles.chips}
          role="group"
          aria-label="Place in the list"
        >
          <button
            type="button"
            className={styles.chip}
            disabled={!canMove(-1)}
            onClick={() => onMove(-1)}
          >
            <ArrowUp size={14} aria-hidden="true" />
            Move up
          </button>
          <button
            type="button"
            className={styles.chip}
            disabled={!canMove(1)}
            onClick={() => onMove(1)}
          >
            <ArrowDown size={14} aria-hidden="true" />
            Move down
          </button>
        </div>
      )}

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
