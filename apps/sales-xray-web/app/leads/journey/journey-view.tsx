"use client";

/**
 * Leads → Lead stages (owner, 20 Oct: "every business tracks leads its own way";
 * the old Meta card was "extremely ugly" and nobody knew what to match with what).
 *
 * - A business picks its kind of business and has working stages at once.
 * - Its stages read as one path from enquiry to sale, with Couldn't reach and
 *   Lost as other outcomes. Tap a stage to rename it, change its type or what it means,
 *   move it or archive it; add one in its own words and the page says what it
 *   probably means. Nothing is saved until Save.
 * - Beside the stages, each ad platform shows what it hears for each stage, in
 *   plain words, confirmed with one tap. Sales Xray does the matching.
 *
 * Sellers and members see the stages; owners and admins change them.
 * - An organisation can run several pipelines, each with its own stages and the lead
 *   sources it takes (owner, 22 Oct 2026); a strip on top picks whose stages show.
 */

import {
  Archive,
  ArchiveRestore,
  ArrowDown,
  ArrowUp,
  Briefcase,
  Building2,
  Car,
  Check,
  GraduationCap,
  GripVertical,
  HeartPulse,
  House,
  Landmark,
  MonitorSmartphone,
  Plane,
  Plus,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
} from "react";

import { notify } from "../../notice-center";
import { Sheet } from "../../ui/sheet";
import { Button, Segmented, Skeleton } from "../../ui/kit";
import { SaveBar } from "../app-card";
import { LeadsError } from "../leads-client";
import { AdPlatforms } from "./ad-platforms";
import {
  ADDABLE,
  MAIN_PIPELINE,
  applyTemplate,
  changed,
  drafts,
  guess,
  move,
  newId,
  problem,
  readJourney,
  readPipelines,
  readSuggestions,
  readTemplates,
  reorder,
  saveJourney,
  split,
  type Draft,
  type Guess,
  type Suggestion,
  type JourneyView,
  type Kind,
  type PipelinesView,
  type TemplateView,
} from "./journey-client";
import styles from "./journey.module.css";
import { forgetPipelines } from "../use-pipelines";
import { PipelineBar, PipelineCard, PipelineSheet } from "./pipelines";
import pipelineStyles from "./pipelines.module.css";
import { StagesExplainer } from "./stages-explainer";

const ICONS: Record<string, LucideIcon> = {
  spark: Sparkles,
  building: Building2,
  cap: GraduationCap,
  shield: ShieldCheck,
  heart: HeartPulse,
  briefcase: Briefcase,
  car: Car,
  bank: Landmark,
  home: House,
  screen: MonitorSmartphone,
  plane: Plane,
  bag: ShoppingBag,
};

export const KIND_WORDS: Record<Kind, string> = {
  new: "New lead",
  not_connected: "Couldn't reach",
  follow_up: "In talks",
  interested: "Hot",
  won: "Won",
  lost: "Lost",
};
const KIND_HINT: Record<Kind, string> = {
  new: "Where every lead starts.",
  not_connected: "Calls that didn't connect land here.",
  follow_up: "Still talking. Needs a follow-up time.",
  interested: "Keen to buy. Needs a follow-up time.",
  won: "They bought. The lead closes.",
  lost: "They won't buy. The lead closes.",
};

const failed = (reason: unknown, title: string) =>
  notify({
    id: "journey-error",
    tone: "error",
    title,
    message:
      reason instanceof LeadsError
        ? reason.message
        : "Check your connection and try again.",
  });

/* ---------- the tab ---------- */

type Pane = "stages" | "ads";

/** The pipeline in the address (`&pipeline=`), else the first one. */
function addressPipeline(): string {
  if (typeof window === "undefined") return MAIN_PIPELINE;
  return (
    new URLSearchParams(window.location.search).get("pipeline") || MAIN_PIPELINE
  );
}

export function JourneyTab({ canManage }: { canManage: boolean }) {
  const [view, setView] = useState<JourneyView | null>(null);
  const [templates, setTemplates] = useState<TemplateView[] | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [pane, setPane] = useState<Pane>("stages");
  const [pipes, setPipes] = useState<PipelinesView | null>(null);
  const [pipeline, setPipeline] = useState(addressPipeline);
  // "new", or the key of the pipeline being changed; a fresh sheet each time.
  const [editing, setEditing] = useState<{ key: string | null; n: number }>({
    key: null,
    n: 0,
  });
  const [sheetOpen, setSheetOpen] = useState(false);

  useEffect(() => {
    let live = true;
    readPipelines()
      .then((next) => {
        if (live) setPipes(next);
      })
      .catch(() => undefined);
    if (canManage)
      readTemplates()
        .then((next) => {
          if (live) setTemplates(next);
        })
        .catch(() => {
          if (live) setTemplates([]);
        });
    return () => {
      live = false;
    };
  }, [canManage]);

  useEffect(() => {
    let live = true;
    readJourney(pipeline)
      .then((next) => {
        if (live) setView(next);
      })
      .catch((reason: unknown) =>
        failed(reason, "Your lead stages didn't load"),
      );
    return () => {
      live = false;
    };
  }, [pipeline]);

  const pick = (key: string) => {
    if (key === pipeline) return;
    setView(null);
    setChoosing(false);
    setPipeline(key);
    try {
      const url = new URL(window.location.href);
      if (key === MAIN_PIPELINE) url.searchParams.delete("pipeline");
      else url.searchParams.set("pipeline", key);
      window.history.replaceState(window.history.state, "", url);
    } catch {
      // The pipeline still shows; only the address keeps the old one.
    }
  };
  const active = pipes?.pipelines.find((item) => item.key === pipeline);
  const several = (pipes?.pipelines.length ?? 0) > 1;
  const pipelineParts = pipes ? (
    <>
      {canManage || several ? (
        <PipelineBar
          view={pipes}
          current={pipeline}
          canEdit={canManage}
          onPick={pick}
          onNew={() => {
            setEditing((value) => ({ key: null, n: value.n + 1 }));
            setSheetOpen(true);
          }}
        />
      ) : null}
      {several && active ? (
        <PipelineCard
          pipeline={active}
          view={pipes}
          canEdit={canManage}
          onEdit={() => {
            setEditing((value) => ({ key: active.key, n: value.n + 1 }));
            setSheetOpen(true);
          }}
        />
      ) : null}
      {canManage ? (
        <PipelineSheet
          key={editing.n}
          open={sheetOpen}
          view={pipes}
          pipeline={
            editing.key === null
              ? null
              : (pipes.pipelines.find((item) => item.key === editing.key) ??
                null)
          }
          templates={templates}
          onClose={() => setSheetOpen(false)}
          onSaved={(next, key) => {
            forgetPipelines();
            setPipes(next);
            setSheetOpen(false);
            pick(key);
          }}
        />
      ) : null}
    </>
  ) : null;

  if (!view)
    return (
      <div className={styles.root}>
        {pipelineParts}
        <JourneySkeleton manager={canManage} />
      </div>
    );

  if (!canManage)
    return (
      <div className={styles.root}>
        {pipelineParts}
        <StagesExplainer />
        <p className={styles.readOnly}>
          Owners and admins set lead stages. These are the ones your team uses.
        </p>
        <StageList view={view} />
      </div>
    );

  // Never saved: pick a kind of business first (the "under a minute" path).
  if (view.version === 0 || choosing)
    return (
      <div className={styles.root}>
        {pipelineParts}
        <TemplatePicker
          templates={templates}
          current={view.industry}
          first={view.version === 0}
          onCancel={view.version === 0 ? undefined : () => setChoosing(false)}
          leads={view.stages.reduce((sum, stage) => sum + stage.leads, 0)}
          onUse={async (template) => {
            try {
              const next = await applyTemplate(
                view.version,
                template,
                view.pipeline,
              );
              setView(next);
              setChoosing(false);
              notify({
                id: "journey-saved",
                tone: "success",
                title: "Your lead stages are ready",
                message: "Sellers see them after their next call.",
                timeout: 4000,
              });
            } catch (reason) {
              failed(reason, "Those stages weren't saved");
            }
          }}
        />
      </div>
    );

  const profile = templates?.find((item) => item.id === view.industry);
  const mainName =
    pipes?.pipelines.find((item) => item.main)?.name ?? "your first pipeline";
  return (
    <div className={styles.root}>
      {pipelineParts}
      <BusinessCard
        profile={profile ?? null}
        loading={templates === null}
        custom={view.version > 0 && !view.industry}
        onChange={() => setChoosing(true)}
      />
      <StagesExplainer />
      <div className={styles.phoneOnly}>
        <Segmented<Pane>
          label="Show"
          value={pane}
          onChange={setPane}
          items={[
            { key: "stages", label: "Stages" },
            { key: "ads", label: "Ad platforms" },
          ]}
        />
      </div>
      <div className={styles.columns} data-pane={pane}>
        <section className={styles.stagesPane} aria-label="Your lead stages">
          <StageBuilder key={view.version} view={view} onSaved={setView} />
        </section>
        <section className={styles.adsPane} aria-label="Ad platforms">
          {(view.pipeline ?? MAIN_PIPELINE) === MAIN_PIPELINE ? (
            <AdPlatforms version={view.version} />
          ) : (
            <p className={pipelineStyles.otherAds}>
              Ad platforms learn from {mainName}’s stages. Leads in this
              pipeline aren’t sent to them.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

/* ---------- the kind of business, up front ---------- */

/**
 * Owner, 22 Oct 2026: the kind of business picked at setup decides the
 * stages, and it was hard to see or change. One card says which it is,
 * what it gives, and changes it in one tap.
 */
function BusinessCard({
  profile,
  loading,
  custom = false,
  onChange,
}: {
  profile: TemplateView | null;
  loading: boolean;
  /** Stages set by hand, from no kind of business. */
  custom?: boolean;
  onChange: () => void;
}) {
  const Icon = (profile && ICONS[profile.icon]) || Sparkles;
  return (
    <section className={styles.business} aria-label="Your kind of business">
      <span className={styles.businessIcon} aria-hidden="true">
        <Icon size={20} strokeWidth={1.9} />
      </span>
      <span className={styles.businessText}>
        <small>Your kind of business</small>
        {loading ? (
          <Skeleton width="50%" height={16} />
        ) : (
          <strong>
            {profile
              ? profile.name
              : custom
                ? "Your own stages"
                : "Not chosen yet"}
          </strong>
        )}
        <span>
          {profile
            ? `Gives ${profile.stages.length} stages that fit it. Change it any time; your leads stay where they are.`
            : custom
              ? "Set to fit how you sell. Change starts again from a kind of business; your leads stay where they are."
              : "Pick the closest one to get stages that fit how you sell."}
        </span>
      </span>
      <Button onClick={onChange}>Change</Button>
    </section>
  );
}

/* ---------- picking a kind of business ---------- */

function TemplatePicker({
  templates,
  current,
  first,
  leads,
  onUse,
  onCancel,
}: {
  templates: TemplateView[] | null;
  current: string | null;
  first: boolean;
  /** Leads on the stages now: changing kind keeps them where they are. */
  leads: number;
  onUse: (template: string) => Promise<void>;
  onCancel?: () => void;
}) {
  const [picked, setPicked] = useState<string | null>(current);
  const [busy, setBusy] = useState(false);
  const chosen = templates?.find((item) => item.id === picked) ?? null;
  return (
    <section className={styles.picker} aria-labelledby="journey-picker-title">
      <header className={styles.pickerHead}>
        <span className={styles.pickerMark} aria-hidden="true">
          <Sparkles size={18} />
        </span>
        <div>
          <h2 id="journey-picker-title">
            {first
              ? "What does your business sell?"
              : "Change your kind of business"}
          </h2>
          <p>
            Pick the closest one. You get stages that fit, and can rename, add
            or remove any of them later.
          </p>
        </div>
      </header>
      <ul className={styles.templateGrid} aria-label="Kinds of business">
        {templates
          ? templates.map((item) => {
              const Icon = ICONS[item.icon] ?? Sparkles;
              const on = item.id === picked;
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    className={styles.templateCard}
                    aria-pressed={on}
                    onClick={() => setPicked(item.id)}
                  >
                    <span
                      className={styles.templateIcon}
                      data-icon={item.icon}
                      aria-hidden="true"
                    >
                      <Icon size={18} strokeWidth={1.9} />
                    </span>
                    <span className={styles.templateText}>
                      <strong>
                        {item.name}
                        {item.id === current && !first ? (
                          <span className={styles.templateNow}>Now</span>
                        ) : null}
                      </strong>
                      <small>{item.blurb}</small>
                    </span>
                    {on ? (
                      <span className={styles.templateCheck} aria-hidden="true">
                        <Check size={13} strokeWidth={2.6} />
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })
          : Array.from({ length: 12 }, (_, index) => (
              <li key={index} aria-hidden="true">
                <span className={styles.templateCard}>
                  <Skeleton width={34} height={34} />
                  <span className={styles.templateText}>
                    <Skeleton width="70%" height={13} />
                    <Skeleton width="90%" height={11} />
                  </span>
                </span>
              </li>
            ))}
      </ul>
      <div className={styles.pickerFoot}>
        {!first && leads ? (
          <p className={styles.pickerNote}>
            {`Your ${leads} ${leads === 1 ? "lead stays" : "leads stay"} put; old stages are kept, so nothing is lost.`}
          </p>
        ) : null}
        <ol className={styles.preview} aria-label="Stages you get">
          {chosen ? (
            chosen.stages.map((stage, index) => (
              <li key={index} data-kind={stage.kind}>
                {stage.label}
              </li>
            ))
          ) : (
            <li data-kind="hint">Pick one to see its stages</li>
          )}
        </ol>
        <span className={styles.pickerActions}>
          {onCancel ? (
            <Button variant="ghost" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
          ) : null}
          <Button
            variant="primary"
            disabled={!chosen || busy}
            onClick={async () => {
              if (!chosen) return;
              setBusy(true);
              await onUse(chosen.id);
              setBusy(false);
            }}
          >
            {busy ? "Setting up…" : "Use these stages"}
          </Button>
        </span>
      </div>
    </section>
  );
}

/* ---------- the business's stages ---------- */

function StageList({ view }: { view: JourneyView }) {
  const { path, beside } = split(drafts(view));
  return (
    <div className={styles.builder}>
      <ol className={styles.path} aria-label="From enquiry to sale">
        {path.map((item) => (
          <StageRow key={item.id} item={item} />
        ))}
      </ol>
      <h3 className={styles.besideTitle}>Other outcomes</h3>
      <ul className={styles.path} data-beside="" aria-label="Other outcomes">
        {beside.map((item) => (
          <StageRow key={item.id} item={item} />
        ))}
      </ul>
    </div>
  );
}

type Drag = {
  onDragStart: (event: DragEvent) => void;
  onDragOver: (event: DragEvent) => void;
  onDrop: (event: DragEvent) => void;
  onDragEnd: () => void;
  dragging: boolean;
  over: boolean;
};

function StageRow({
  item,
  onOpen,
  onMove,
  first,
  last,
  drag,
}: {
  item: Draft;
  onOpen?: () => void;
  onMove?: (by: -1 | 1) => void;
  first?: boolean;
  last?: boolean;
  drag?: Drag;
}) {
  const kind = item.kind ?? "follow_up";
  const movable = !!onMove && kind !== "new";
  return (
    <li
      className={styles.stage}
      data-kind={kind}
      data-new={item.key ? undefined : ""}
      data-dragging={drag?.dragging ? "" : undefined}
      data-over={drag?.over ? "" : undefined}
      onDragOver={drag?.onDragOver}
      onDrop={drag?.onDrop}
    >
      <span className={styles.node} aria-hidden="true" />
      {movable && drag ? (
        <span
          className={styles.grip}
          draggable
          onDragStart={drag.onDragStart}
          onDragEnd={drag.onDragEnd}
          title="Drag to move"
          aria-hidden="true"
        >
          <GripVertical size={14} />
        </span>
      ) : (
        <span className={styles.gripSpace} aria-hidden="true" />
      )}
      {onOpen ? (
        <button type="button" className={styles.stageMain} onClick={onOpen}>
          <StageText item={item} kind={kind} />
        </button>
      ) : (
        <span className={styles.stageMain}>
          <StageText item={item} kind={kind} />
        </span>
      )}
      {movable ? (
        <span className={styles.moves}>
          <Button
            variant="icon"
            aria-label={`Move ${item.label} up`}
            disabled={first}
            onClick={() => onMove?.(-1)}
          >
            <ArrowUp size={14} />
          </Button>
          <Button
            variant="icon"
            aria-label={`Move ${item.label} down`}
            disabled={last}
            onClick={() => onMove?.(1)}
          >
            <ArrowDown size={14} />
          </Button>
        </span>
      ) : null}
    </li>
  );
}

function StageText({ item, kind }: { item: Draft; kind: Kind }) {
  return (
    <>
      <span className={styles.stageName}>
        <strong>{item.label || "New stage"}</strong>
        <small>{item.meaning ?? "Something else"}</small>
      </span>
      <span className={styles.kindChip} data-kind={kind}>
        {KIND_WORDS[kind]}
      </span>
      <span
        className={styles.leadCount}
        data-zero={item.leads ? undefined : ""}
      >
        {item.leads ? `${item.leads} lead${item.leads === 1 ? "" : "s"}` : "—"}
      </span>
    </>
  );
}

function StageBuilder({
  view,
  onSaved,
}: {
  view: JourneyView;
  onSaved: (next: JourneyView) => void;
}) {
  const [list, setList] = useState<Draft[]>(() => drafts(view));
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  const dirty = changed(view, list);
  const { path, beside, archived } = split(list);

  useEffect(() => {
    if (!saved) return;
    const timer = setTimeout(() => setSaved(false), 2500);
    return () => clearTimeout(timer);
  }, [saved]);

  const update = (id: string, patch: Partial<Draft>) =>
    setList((items) =>
      items.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );

  const save = async () => {
    const issue = problem(list);
    if (issue) {
      notify({
        id: "journey-error",
        tone: "error",
        title: "Not saved yet",
        message: issue,
      });
      return;
    }
    setBusy(true);
    try {
      const next = await saveJourney(view.version, list, view.pipeline);
      setSaved(true);
      onSaved(next);
    } catch (reason) {
      failed(reason, "Your stages weren't saved");
    } finally {
      setBusy(false);
    }
  };

  const dragFor = (item: Draft): Drag => ({
    dragging: dragId === item.id,
    over: overId === item.id && dragId !== item.id,
    onDragStart: (event) => {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", item.id);
      setDragId(item.id);
    },
    onDragOver: (event) => {
      if (!dragId || item.kind === "new") return;
      event.preventDefault();
      setOverId(item.id);
    },
    onDrop: (event) => {
      event.preventDefault();
      if (!dragId || dragId === item.id) return;
      const order = path.map((stage) => stage.id).filter((id) => id !== dragId);
      order.splice(order.indexOf(item.id), 0, dragId);
      setList((items) => reorder(items, order));
      setDragId(null);
      setOverId(null);
    },
    onDragEnd: () => {
      setDragId(null);
      setOverId(null);
    },
  });

  const add = (draft: Draft) =>
    setList((items) => {
      if (draft.kind === "won" || draft.kind === "lost")
        return [...items, draft];
      // An open stage goes before the first Won stage: the sale comes last.
      const at = items.findIndex(
        (item) => !item.archived && item.kind === "won",
      );
      const next = [...items];
      next.splice(at < 0 ? next.length : at, 0, draft);
      return next;
    });

  const open = list.find((item) => item.id === editing) ?? null;
  return (
    <div className={styles.builder}>
      <header className={styles.paneHead}>
        <div>
          <h2>Your lead stages</h2>
          <p>
            How a lead moves from enquiry to sale. Sellers pick these after each
            call.
          </p>
        </div>
      </header>

      <ol className={styles.path} aria-label="From enquiry to sale">
        {path.map((item, index) => (
          <StageRow
            key={item.id}
            item={item}
            first={index <= 1}
            last={index === path.length - 1}
            onOpen={() => setEditing(item.id)}
            onMove={(by) => setList((items) => move(items, item.id, by))}
            drag={dragFor(item)}
          />
        ))}
      </ol>
      <AddStage onAdd={add} />
      <FromApps list={list} pipeline={view.pipeline} onAdd={add} />

      <h3 className={styles.besideTitle}>Other outcomes</h3>
      <ul className={styles.path} data-beside="" aria-label="Other outcomes">
        {beside.map((item) => (
          <StageRow
            key={item.id}
            item={item}
            onOpen={() => setEditing(item.id)}
          />
        ))}
      </ul>

      {archived.length ? (
        <div className={styles.archived}>
          <button
            type="button"
            className={styles.archivedToggle}
            aria-expanded={showArchived}
            onClick={() => setShowArchived((on) => !on)}
          >
            Archived ({archived.length})
          </button>
          {showArchived ? (
            <ul className={styles.archivedList}>
              {archived.map((item) => (
                <li key={item.id}>
                  <span>
                    {item.label}
                    {item.leads ? (
                      <small>
                        {" "}
                        · {item.leads} lead{item.leads === 1 ? "" : "s"} still
                        here
                      </small>
                    ) : null}
                  </span>
                  <Button
                    variant="ghost"
                    onClick={() => update(item.id, { archived: false })}
                  >
                    <ArchiveRestore size={14} aria-hidden="true" />
                    Bring back
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <SaveBar
        dirty={dirty}
        busy={busy}
        saved={saved}
        savedText="Saved. Sellers see the new stages after their next call."
        onSave={save}
        onDiscard={() => setList(drafts(view))}
      />

      <StageSheet
        item={open}
        path={path}
        meanings={view.meanings}
        onClose={() => setEditing(null)}
        onChange={(patch) => {
          if (open) update(open.id, patch);
        }}
        onMove={(by) => {
          if (open) setList((items) => move(items, open.id, by));
        }}
        onArchive={() => {
          if (!open) return;
          if (!open.key)
            setList((items) => items.filter((item) => item.id !== open.id));
          else update(open.id, { archived: true });
          setEditing(null);
        }}
      />
    </div>
  );
}

/* ---------- stages the business already uses: connected apps and its calls ---------- */

function FromApps({
  list,
  pipeline,
  onAdd,
}: {
  list: Draft[];
  pipeline?: string;
  onAdd: (draft: Draft) => void;
}) {
  const [found, setFound] = useState<Suggestion[]>([]);
  useEffect(() => {
    let live = true;
    readSuggestions(pipeline)
      .then((next) => {
        if (live && Array.isArray(next)) setFound(next);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [pipeline]);
  const taken = new Set(
    list.flatMap((item) => [
      item.ref ?? "",
      item.label.trim().toLocaleLowerCase(),
    ]),
  );
  const shown = found.filter(
    (item) =>
      !taken.has(item.ref) && !taken.has(item.label.toLocaleLowerCase()),
  );
  if (!shown.length) return null;
  const sources = [...new Set(shown.map((item) => item.source))];
  return (
    <>
      {sources.map((source) => (
        <div key={source} className={styles.fromApps}>
          <small>
            {source === "your calls"
              ? "Heard in your calls and notes"
              : `From your ${source} workflows`}
          </small>
          <span className={styles.fromAppsList}>
            {shown
              .filter((item) => item.source === source)
              .map((item) => (
                <button
                  key={item.ref}
                  type="button"
                  className={styles.fromApp}
                  data-kind={item.kind}
                  title={`${item.workflow}: ${item.meaning}`}
                  onClick={() =>
                    onAdd({
                      id: newId(),
                      label: item.label,
                      kind: ADDABLE.includes(item.kind)
                        ? item.kind
                        : "follow_up",
                      milestone: item.milestone,
                      meaning: item.meaning,
                      archived: false,
                      leads: 0,
                      origin: item.ref.startsWith("pulse:")
                        ? "pulse"
                        : "suggested",
                      ref: item.ref.startsWith("pulse:") ? item.ref : undefined,
                    })
                  }
                >
                  <Plus size={12} aria-hidden="true" />
                  {item.label}
                  {item.source === "your calls" ? (
                    <small className={styles.fromWhy}>{item.workflow}</small>
                  ) : null}
                </button>
              ))}
          </span>
        </div>
      ))}
    </>
  );
}

/* ---------- adding a stage ---------- */

function AddStage({ onAdd }: { onAdd: (draft: Draft) => void }) {
  const [label, setLabel] = useState("");
  const [hint, setHint] = useState<{ words: string; guess: Guess } | null>(
    null,
  );
  const latest = useRef("");
  const words = label.trim();

  useEffect(() => {
    latest.current = words;
    if (words.length < 3) return;
    const timer = setTimeout(() => {
      guess(words)
        .then((next) => {
          if (latest.current === words) setHint({ words, guess: next });
        })
        .catch(() => undefined);
    }, 280);
    return () => clearTimeout(timer);
  }, [words]);

  const shown = hint && hint.words === words ? hint.guess : null;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!words) return;
    const kind: Kind =
      shown && ADDABLE.includes(shown.kind) ? shown.kind : "follow_up";
    onAdd({
      id: newId(),
      label: words,
      kind,
      milestone: shown?.milestone,
      meaning: shown?.meaning,
      archived: false,
      leads: 0,
    });
    setLabel("");
    setHint(null);
  };
  return (
    <form className={styles.add} onSubmit={submit}>
      <span className={styles.addMark} aria-hidden="true">
        <Plus size={14} />
      </span>
      <input
        className={styles.addInput}
        value={label}
        maxLength={40}
        placeholder="Add a stage, like “Site visit done”"
        aria-label="New stage name"
        onChange={(event) => setLabel(event.target.value)}
      />
      <span className={styles.addGuess} aria-live="polite">
        {shown ? (
          <>
            <span className={styles.kindChip} data-kind={shown.kind}>
              {KIND_WORDS[shown.kind]}
            </span>
            <small>{shown.meaning}</small>
          </>
        ) : null}
      </span>
      <Button type="submit" disabled={!words}>
        Add
      </Button>
    </form>
  );
}

/* ---------- one stage, in a sheet ---------- */

function StageSheet({
  item,
  path,
  meanings,
  onClose,
  onChange,
  onMove,
  onArchive,
}: {
  item: Draft | null;
  path: Draft[];
  meanings: Record<string, string>;
  onClose: () => void;
  onChange: (patch: Partial<Draft>) => void;
  onMove: (by: -1 | 1) => void;
  onArchive: () => void;
}) {
  const kind = item?.kind ?? "follow_up";
  const fixed = kind === "new" || kind === "not_connected";
  const locked = !!item?.leads && !!item?.key;
  const at = item ? path.findIndex((stage) => stage.id === item.id) : -1;
  const options = useMemo(
    () =>
      Object.entries(meanings).filter(
        ([key]) => key !== "lead" && key !== "unreachable",
      ),
    [meanings],
  );
  const onlyOne =
    (kind === "won" || kind === "lost") &&
    path.concat().filter((stage) => stage.kind === kind).length <= 1;
  return (
    <Sheet
      open={!!item}
      onClose={onClose}
      title={item?.label || "Stage"}
      description={item ? KIND_HINT[kind] : undefined}
      footer={
        <span className={styles.sheetFoot}>
          {item && !fixed ? (
            <Button variant="ghost" onClick={onArchive} disabled={onlyOne}>
              <Archive size={14} aria-hidden="true" />
              {item.key ? "Archive" : "Remove"}
            </Button>
          ) : (
            <span />
          )}
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        </span>
      }
    >
      {item ? (
        <div className={styles.sheetBody}>
          <label className={styles.sheetField}>
            <span>Name</span>
            <input
              value={item.label}
              maxLength={40}
              onChange={(event) => onChange({ label: event.target.value })}
            />
          </label>
          {fixed ? null : (
            <div className={styles.sheetField} role="group" aria-label="Type">
              <span>Type</span>
              <span className={styles.kindPicker}>
                {ADDABLE.map((option) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={kind === option}
                    data-kind={option}
                    disabled={locked && kind !== option}
                    onClick={() => onChange({ kind: option })}
                  >
                    {KIND_WORDS[option]}
                  </button>
                ))}
              </span>
              <small>
                {locked
                  ? "Leads sit in this stage, so its type stays. Add a new stage instead."
                  : KIND_HINT[kind]}
              </small>
            </div>
          )}
          {fixed ? null : (
            <label className={styles.sheetField}>
              <span>What it means</span>
              <select
                value={item.milestone ?? "other"}
                onChange={(event) =>
                  onChange({
                    milestone: event.target.value,
                    meaning: meanings[event.target.value],
                  })
                }
              >
                {options.map(([key, words]) => (
                  <option key={key} value={key}>
                    {words}
                  </option>
                ))}
              </select>
              <small>
                Sales Xray uses this to tell your ad platforms what happened.
              </small>
            </label>
          )}
          {at > 0 ? (
            <div className={styles.sheetMoves}>
              <Button onClick={() => onMove(-1)} disabled={at <= 1}>
                <ArrowUp size={14} aria-hidden="true" />
                Move up
              </Button>
              <Button
                onClick={() => onMove(1)}
                disabled={at >= path.length - 1}
              >
                <ArrowDown size={14} aria-hidden="true" />
                Move down
              </Button>
            </div>
          ) : null}
          {item.leads ? (
            <p className={styles.sheetNote}>
              {item.leads} lead{item.leads === 1 ? " is" : "s are"} in this
              stage now.
            </p>
          ) : null}
        </div>
      ) : null}
    </Sheet>
  );
}

/* ---------- loading, in the final layout ---------- */

export function JourneySkeleton({ manager = true }: { manager?: boolean }) {
  return (
    <div className={styles.root} aria-busy="true">
      <div className={styles.columns} data-pane="stages">
        <section className={styles.stagesPane} aria-label="Loading lead stages">
          <div className={styles.builder}>
            <header className={styles.paneHead}>
              <div>
                <Skeleton width={160} height={18} />
                <Skeleton width="80%" height={12} />
              </div>
            </header>
            <ol className={styles.path}>
              {Array.from({ length: 7 }, (_, index) => (
                <li key={index} className={styles.stage} data-kind="skeleton">
                  <span className={styles.node} aria-hidden="true" />
                  <span className={styles.gripSpace} />
                  <span className={styles.stageMain}>
                    <span className={styles.stageName}>
                      <Skeleton width="55%" height={13} />
                      <Skeleton width="40%" height={10} />
                    </span>
                    <Skeleton width={64} height={22} />
                    <Skeleton width={48} height={12} />
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </section>
        {manager ? (
          <section className={styles.adsPane} aria-label="Loading ad platforms">
            <div className={styles.adCardSkeleton}>
              <Skeleton width={40} height={40} />
              <Skeleton width="60%" height={14} />
              <Skeleton width="90%" height={11} />
              <Skeleton height={120} />
            </div>
          </section>
        ) : null}
      </div>
    </div>
  );
}
