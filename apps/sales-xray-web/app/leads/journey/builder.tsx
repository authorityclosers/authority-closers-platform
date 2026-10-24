"use client";

/**
 * Lead OS L4: setting up lead stages in short steps, phone first (owner, 24 Oct 2026:
 * "I can't set up the leads ... looks cluttered overall"). It replaces the one long
 * picker page:
 *
 * 1. Kind: the kinds of business as one list (no cards inside cards).
 * 2. Stages: the stages that kind gives, in order, each with what it asks when a lead
 *    moves in and where a lead can go next (the stage list's rules, from the preview).
 * 3. Leads: only when there are leads. Where the leads of each of today's stages go;
 *    each starts on its closest new stage and can be changed.
 * 4. Save: what will happen, in words, and "Use these stages".
 *
 * Nothing is saved before the last step. The server checks the choices again
 * (POST /journey/template with `map`). A lead moved there keeps its record and its
 * history, and the move never counts as progress or reaches an ad platform.
 */

import { ArrowLeft, Check, ChevronDown, type LucideIcon } from "lucide-react";
import { useState } from "react";

import { Button, Skeleton } from "../../ui/kit";
import styles from "./builder.module.css";
import {
  applyTemplate,
  previewTemplate,
  type JourneyView,
  type StageView,
  type TemplateLanding,
  type TemplatePreview,
  type TemplateView,
} from "./journey-client";

type Step = "kind" | "stages" | "leads" | "save";

const CLOSED = new Set(["won", "lost", "junk"]);

const NEED_WORDS: Record<string, string> = {
  next_action: "when to follow up",
  meeting: "for the meeting",
  reason: "why",
  nc_reason: "why the call didn't connect",
};

/** What a stage asks when a lead moves in, in words; null when nothing. */
export function asksWords(stage: Pick<StageView, "needs">): string | null {
  const needs = (stage.needs ?? [])
    .map((need) => NEED_WORDS[need])
    .filter(Boolean);
  return needs.length ? `Asks ${needs.join(" and ")}` : null;
}

/** Where a lead can go next from a stage, by name; null when anywhere. */
export function nextWords(
  stage: Pick<StageView, "moves">,
  labels: ReadonlyMap<string, string>,
): string | null {
  if (!stage.moves) return null;
  const names = stage.moves
    .map((key) => labels.get(key))
    .filter((name): name is string => !!name);
  return names.length ? `Then ${names.join(" · ")}` : null;
}

/** Today's stages whose leads can be placed: one row each, their leads added up. */
export function movable(preview: TemplatePreview | null): TemplateLanding[] {
  const rows = new Map<string, TemplateLanding>();
  for (const landing of preview?.landings ?? []) {
    if (!landing.choices.length || landing.leads <= 0) continue;
    const seen = rows.get(landing.fromKey);
    rows.set(
      landing.fromKey,
      seen ? { ...seen, leads: seen.leads + landing.leads } : landing,
    );
  }
  return [...rows.values()];
}

/** The install's map: each of today's stages with leads, to the stage picked for it.
 *  Until someone picks, the new stage that means the same (a booked visit and a
 *  booked demo are both "a meeting booked"), else the server's closest by kind. */
export function placesOf(
  preview: TemplatePreview | null,
  picked: Readonly<Record<string, string>>,
  meanings: ReadonlyMap<string, string> = new Map(),
): Record<string, string> {
  const meaning = new Map(
    (preview?.stages ?? []).map((stage) => [stage.key, stage.milestone]),
  );
  const places: Record<string, string> = {};
  for (const landing of movable(preview)) {
    const chosen = picked[landing.fromKey];
    const was = meanings.get(landing.fromKey);
    const same = was
      ? landing.choices.find((key) => meaning.get(key) === was)
      : undefined;
    places[landing.fromKey] =
      chosen && landing.choices.includes(chosen)
        ? chosen
        : (same ?? landing.toKey);
  }
  return places;
}

/** A stage and what it asks; a tap shows where a lead can go next from it. */
function StageLine({
  stage,
  labels,
  open,
  onToggle,
}: {
  stage: StageView;
  labels: ReadonlyMap<string, string>;
  open: boolean;
  onToggle: () => void;
}) {
  const asks = asksWords(stage);
  const then = nextWords(stage, labels);
  const text = (
    <span className={styles.stageText}>
      <strong>{stage.label}</strong>
      {asks ? <small>{asks}</small> : null}
      {then && open ? <small className={styles.then}>{then}</small> : null}
    </span>
  );
  return (
    <li className={styles.stage} data-kind={stage.kind}>
      {then ? (
        <button
          type="button"
          className={styles.stageButton}
          aria-expanded={open}
          onClick={onToggle}
        >
          <span className={styles.dot} aria-hidden="true" />
          {text}
          <ChevronDown
            className={styles.chevron}
            size={16}
            aria-hidden="true"
          />
        </button>
      ) : (
        <span className={styles.stageButton}>
          <span className={styles.dot} aria-hidden="true" />
          {text}
        </span>
      )}
    </li>
  );
}

export function TemplateBuilder({
  view,
  templates,
  first,
  iconFor,
  onCancel,
  onSaved,
  onFailed,
}: {
  /** The pipeline's stages now: their version, kind of business and leads. */
  view: JourneyView;
  templates: TemplateView[] | null;
  /** Never set up: the first question is what the business sells. */
  first: boolean;
  iconFor: (icon: string) => LucideIcon;
  onCancel?: () => void;
  onSaved: (next: JourneyView) => void;
  onFailed: (reason: unknown, title: string) => void;
}) {
  const [step, setStep] = useState<Step>("kind");
  const [picked, setPicked] = useState<string | null>(view.industry);
  const [loaded, setLoaded] = useState<{
    template: string;
    preview: TemplatePreview;
  } | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [shown, setShown] = useState<string | null>(null);

  const preview = loaded && loaded.template === picked ? loaded.preview : null;
  const chosen = templates?.find((item) => item.id === picked) ?? null;
  const live = (preview?.stages ?? []).filter((stage) => !stage.archived);
  const labels = new Map(live.map((stage) => [stage.key, stage.label]));
  const open = live.filter((stage) => !CLOSED.has(stage.kind));
  const closed = live.filter((stage) => CLOSED.has(stage.kind));
  const rows = movable(preview);
  const places = placesOf(
    preview,
    choices,
    new Map(view.stages.map((stage) => [stage.key, stage.milestone])),
  );
  const leads = view.stages.reduce((sum, stage) => sum + stage.leads, 0);
  // Before the preview answers, a pipeline with leads expects the leads step.
  const hasLeads = preview ? rows.length > 0 : leads > 0;
  const steps: Step[] = hasLeads
    ? ["kind", "stages", "leads", "save"]
    : ["kind", "stages", "save"];
  const at = Math.max(0, steps.indexOf(step));
  const stayJunk = (preview?.landings ?? []).some(
    (landing) => !landing.choices.length && landing.leads > 0,
  );

  const top = () =>
    document
      .getElementById("journey-builder-title")
      ?.scrollIntoView?.({ block: "start", behavior: "smooth" });

  const go = (next: Step) => {
    setStep(next);
    top();
  };

  const toStages = async () => {
    if (!picked) return;
    go("stages");
    if (loaded?.template === picked) return;
    const template = picked;
    setChoices({});
    try {
      const answer = await previewTemplate(
        view.version,
        template,
        view.pipeline,
      );
      setLoaded({ template, preview: answer });
    } catch (reason) {
      setStep("kind");
      onFailed(reason, "Those stages didn't load");
    }
  };

  const save = async () => {
    if (!picked || !preview) return;
    setBusy(true);
    try {
      onSaved(await applyTemplate(view.version, picked, view.pipeline, places));
    } catch (reason) {
      onFailed(reason, "Those stages weren't saved");
    } finally {
      setBusy(false);
    }
  };

  const next = () => {
    if (step === "kind") void toStages();
    else if (step === "stages") go(hasLeads ? "leads" : "save");
    else if (step === "leads") go("save");
    else void save();
  };
  const back = () => {
    if (step === "save") go(hasLeads ? "leads" : "stages");
    else if (step === "leads") go("stages");
    else go("kind");
  };

  const title =
    step === "kind"
      ? first
        ? "What does your business sell?"
        : "Change your kind of business"
      : step === "stages"
        ? "The stages you get"
        : step === "leads"
          ? "Where your leads go"
          : "Check and save";
  const hint =
    step === "kind"
      ? "Pick the closest one. You can rename, add or remove stages after."
      : step === "stages"
        ? `${chosen?.name ?? "This kind"}: ${live.length || "its"} stages, in order. Tap one to see where a lead goes next.`
        : step === "leads"
          ? `Your ${leads} ${leads === 1 ? "lead keeps its" : "leads keep their"} history. Pick where each stage's leads go.`
          : "Nothing is deleted. Old stages stay in each lead's history.";
  const nextLabel =
    step === "kind"
      ? picked
        ? "See the stages"
        : "Pick one to continue"
      : step === "save"
        ? busy
          ? "Saving…"
          : "Use these stages"
        : "Next";
  const moving = rows.filter(
    (row) => row.fromLabel !== labels.get(places[row.fromKey]),
  );

  return (
    <section
      className={styles.builder}
      aria-labelledby="journey-builder-title"
      data-step={step}
    >
      <ol className={styles.progress} aria-hidden="true">
        {steps.map((item, index) => (
          <li key={item} data-done={index <= at ? "" : undefined} />
        ))}
      </ol>
      <header className={styles.head}>
        <small>{`Step ${at + 1} of ${steps.length}`}</small>
        <h2 id="journey-builder-title">{title}</h2>
        <p>{hint}</p>
      </header>

      {step === "kind" ? (
        <ul className={styles.kinds} aria-label="Kinds of business">
          {templates
            ? templates.map((item) => {
                const Icon = iconFor(item.icon);
                const on = item.id === picked;
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={styles.kind}
                      aria-pressed={on}
                      onClick={() => setPicked(item.id)}
                    >
                      <span className={styles.kindIcon} aria-hidden="true">
                        <Icon size={18} strokeWidth={1.9} />
                      </span>
                      <span className={styles.kindText}>
                        <strong>
                          {item.name}
                          {item.id === view.industry && !first ? (
                            <span className={styles.now}>Now</span>
                          ) : null}
                        </strong>
                        <small>{item.blurb}</small>
                      </span>
                      <span className={styles.kindCheck} aria-hidden="true">
                        {on ? <Check size={14} strokeWidth={2.6} /> : null}
                      </span>
                    </button>
                  </li>
                );
              })
            : Array.from({ length: 6 }, (_, index) => (
                <li
                  key={index}
                  aria-hidden="true"
                  className={styles.kindSkeleton}
                >
                  <Skeleton width={36} height={36} />
                  <Skeleton width="60%" height={14} />
                </li>
              ))}
        </ul>
      ) : null}

      {step === "stages" ? (
        preview ? (
          <div className={styles.stageGroups}>
            <ol className={styles.stages} aria-label="Stages, in order">
              {open.map((stage) => (
                <StageLine
                  key={stage.key}
                  stage={stage}
                  labels={labels}
                  open={shown === stage.key}
                  onToggle={() =>
                    setShown((key) => (key === stage.key ? null : stage.key))
                  }
                />
              ))}
            </ol>
            <h3 className={styles.groupTitle}>Closed</h3>
            <ul className={styles.stages} aria-label="Closed stages">
              {closed.map((stage) => (
                <StageLine
                  key={stage.key}
                  stage={stage}
                  labels={labels}
                  open={shown === stage.key}
                  onToggle={() =>
                    setShown((key) => (key === stage.key ? null : stage.key))
                  }
                />
              ))}
            </ul>
          </div>
        ) : (
          <ul className={styles.stages} aria-busy="true">
            {Array.from({ length: 6 }, (_, index) => (
              <li key={index} className={styles.stage}>
                <Skeleton width="55%" height={14} />
              </li>
            ))}
          </ul>
        )
      ) : null}

      {step === "leads" ? (
        <ul className={styles.landings} aria-label="Where your leads go">
          {rows.map((row) => (
            <li key={row.fromKey} className={styles.landing}>
              <span className={styles.landingFrom}>
                <strong>{row.fromLabel}</strong>
                <small>
                  {row.leads} {row.leads === 1 ? "lead" : "leads"}
                </small>
              </span>
              <label className={styles.landingTo}>
                <span className={styles.srOnly}>
                  {`Where the ${row.fromLabel} leads go`}
                </span>
                <select
                  value={places[row.fromKey]}
                  onChange={(event) => {
                    const value = event.target.value;
                    setChoices((items) => ({ ...items, [row.fromKey]: value }));
                  }}
                >
                  {row.choices.map((key) => (
                    <option key={key} value={key}>
                      {labels.get(key) ?? key}
                    </option>
                  ))}
                </select>
              </label>
            </li>
          ))}
          {stayJunk ? (
            <li className={styles.landingNote}>Junk leads stay Junk.</li>
          ) : null}
        </ul>
      ) : null}

      {step === "save" ? (
        <ul className={styles.summary} aria-label="What happens">
          <li>
            <Check size={16} aria-hidden="true" />
            <span>
              {live.length
                ? `${live.length} stages, from ${live[0].label} to ${live[live.length - 1].label}.`
                : "The stages of this kind of business."}
            </span>
          </li>
          {moving.map((row) => (
            <li key={row.fromKey}>
              <Check size={16} aria-hidden="true" />
              <span>
                {`${row.leads} ${row.leads === 1 ? "lead" : "leads"}: ${row.fromLabel} → ${labels.get(places[row.fromKey]) ?? ""}`}
              </span>
            </li>
          ))}
          <li>
            <Check size={16} aria-hidden="true" />
            <span>
              Each lead keeps its calls, chats and history. Ads aren&apos;t told
              about these moves.
            </span>
          </li>
        </ul>
      ) : null}

      <footer className={styles.foot}>
        {step === "kind" ? (
          onCancel ? (
            <Button variant="ghost" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
          ) : (
            <span />
          )
        ) : (
          <Button variant="ghost" onClick={back} disabled={busy}>
            <ArrowLeft size={16} aria-hidden="true" />
            Back
          </Button>
        )}
        <Button
          variant="primary"
          data-builder-next=""
          disabled={
            busy ||
            (step === "kind" && !picked) ||
            (step !== "kind" && !preview)
          }
          onClick={next}
        >
          {nextLabel}
        </Button>
      </footer>
    </section>
  );
}
