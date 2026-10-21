"use client";

/**
 * Leads → Lead stages: the organisation's pipelines (owner, 22 Oct 2026: "A for partner
 * leads plus B for enquiries as two pipelines"). A strip picks whose stages show; a card
 * says which new leads come into the pipeline picked; owners and admins make a pipeline
 * from a kind of business and choose the lead sources it takes. The first pipeline takes
 * every new lead the others don't, so a lead always lands somewhere.
 */

import { Pencil, Plus, Workflow } from "lucide-react";
import { useState } from "react";

import { notify } from "../../notice-center";
import { Sheet } from "../../ui/sheet";
import { Button, Field } from "../../ui/kit";
import { LeadsError } from "../leads-client";
import {
  changePipeline,
  createPipeline,
  type PipelinesView,
  type PipelineView,
  type TemplateView,
} from "./journey-client";
import styles from "./pipelines.module.css";

const failed = (reason: unknown, title: string) =>
  notify({
    id: "pipeline-error",
    tone: "error",
    title,
    message:
      reason instanceof LeadsError
        ? reason.message
        : "Check your connection and try again.",
  });

/** Which new leads come into a pipeline, in a sentence. */
export function takesWords(pipeline: PipelineView, all: PipelinesView): string {
  const words = (keys: string[]) =>
    keys.map((key) => all.sources[key] ?? key).join(", ");
  if (!pipeline.main)
    return pipeline.sources.length
      ? `New leads from ${words(pipeline.sources)}.`
      : "No new leads come here by themselves. Move or import leads into it.";
  if (all.pipelines.length < 2) return "Every new lead comes here.";
  const taken = new Set(
    all.pipelines.flatMap((item) => (item.main ? [] : item.sources)),
  );
  const rest = Object.keys(all.sources).filter((key) => !taken.has(key));
  return rest.length
    ? `Every other new lead: ${words(rest)}.`
    : "New leads no other pipeline takes.";
}

export function PipelineBar({
  view,
  current,
  canEdit,
  onPick,
  onNew,
}: {
  view: PipelinesView;
  current: string;
  canEdit: boolean;
  onPick: (key: string) => void;
  onNew: () => void;
}) {
  return (
    <div className={styles.bar}>
      <div className={styles.tabs} role="tablist" aria-label="Pipelines">
        {view.pipelines.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={item.key === current}
            className={styles.tab}
            onClick={() => onPick(item.key)}
          >
            <span className={styles.tabName}>{item.name}</span>
            <span className={styles.count}>{item.leads}</span>
          </button>
        ))}
      </div>
      {canEdit ? (
        <button type="button" className={styles.add} onClick={onNew}>
          <Plus size={15} aria-hidden="true" />
          New pipeline
        </button>
      ) : null}
    </div>
  );
}

export function PipelineCard({
  pipeline,
  view,
  canEdit,
  onEdit,
}: {
  pipeline: PipelineView;
  view: PipelinesView;
  canEdit: boolean;
  onEdit: () => void;
}) {
  return (
    <section className={styles.card} aria-label="Leads that come in here">
      <span className={styles.icon} aria-hidden="true">
        <Workflow size={20} strokeWidth={1.9} />
      </span>
      <span className={styles.text}>
        <small>Leads that come in here</small>
        <strong>{pipeline.name}</strong>
        <span>{takesWords(pipeline, view)}</span>
      </span>
      {canEdit ? (
        <Button onClick={onEdit}>
          <Pencil size={14} aria-hidden="true" />
          Edit
        </Button>
      ) : null}
    </section>
  );
}

/**
 * Making a pipeline, or changing one: its name, and for every pipeline but the first,
 * the lead sources whose new leads come to it. A source feeds one pipeline at a time.
 */
export function PipelineSheet({
  open,
  view,
  pipeline,
  templates,
  onClose,
  onSaved,
}: {
  open: boolean;
  view: PipelinesView;
  /** The pipeline to change; none makes a new one. */
  pipeline: PipelineView | null;
  templates: TemplateView[] | null;
  onClose: () => void;
  onSaved: (next: PipelinesView, key: string) => void;
}) {
  const making = pipeline === null;
  const [name, setName] = useState(pipeline?.name ?? "");
  const [template, setTemplate] = useState("simple");
  const [picked, setPicked] = useState<string[]>(pipeline?.sources ?? []);
  const [busy, setBusy] = useState(false);
  const owners = new Map<string, string>();
  for (const item of view.pipelines)
    if (!item.main && item.key !== pipeline?.key)
      for (const source of item.sources) owners.set(source, item.name);
  const ready = name.trim().length > 0 && (!making || !!template);

  async function save() {
    if (!ready) return;
    setBusy(true);
    try {
      if (pipeline === null) {
        const next = await createPipeline({
          name: name.trim(),
          template,
          sources: picked,
        });
        const before = new Set(view.pipelines.map((item) => item.key));
        const made =
          next.pipelines.find((item) => !before.has(item.key)) ??
          next.pipelines[next.pipelines.length - 1];
        notify({
          id: "pipeline-saved",
          tone: "success",
          title: `${made.name} is ready`,
          message: "Its stages are below. Change them any time.",
          timeout: 5000,
        });
        onSaved(next, made.key);
      } else {
        const next = await changePipeline(pipeline.key, {
          name: name.trim(),
          ...(pipeline.main ? {} : { sources: picked }),
        });
        notify({
          id: "pipeline-saved",
          tone: "success",
          title: `${name.trim()} saved`,
          timeout: 4000,
        });
        onSaved(next, pipeline.key);
      }
    } catch (reason) {
      failed(
        reason,
        making ? "The pipeline wasn't made" : "The pipeline wasn't saved",
      );
      setBusy(false);
    }
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={pipeline ? `Edit ${pipeline.name}` : "New pipeline"}
      description={
        making
          ? "A pipeline has its own stages and takes the new leads from the sources you pick."
          : undefined
      }
      footer={
        <div className={styles.footer}>
          <Button
            variant="primary"
            disabled={!ready || busy}
            onClick={() => void save()}
          >
            {busy ? "Saving…" : making ? "Make pipeline" : "Save"}
          </Button>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
      }
    >
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <Field label="Name">
          <input
            value={name}
            maxLength={40}
            placeholder="Partner outreach"
            autoCapitalize="words"
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        {making ? (
          <Field
            label="Kind of business"
            hint="Its stages to start with. Change them any time."
          >
            <select
              value={template}
              onChange={(event) => setTemplate(event.target.value)}
            >
              {(templates ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
        ) : null}
        {pipeline?.main ? (
          <p className={styles.note}>
            Your first pipeline takes every new lead the others don’t, so a lead
            always lands somewhere.
          </p>
        ) : (
          <fieldset className={styles.sources}>
            <legend>New leads that come here</legend>
            {Object.entries(view.sources).map(([key, words]) => (
              <label key={key} className={styles.source}>
                <input
                  type="checkbox"
                  checked={picked.includes(key)}
                  onChange={(event) => {
                    const on = event.target.checked;
                    setPicked((current) =>
                      on
                        ? [...current, key]
                        : current.filter((item) => item !== key),
                    );
                  }}
                />
                <span>
                  {words}
                  {owners.has(key) ? (
                    <em> · now in {owners.get(key)}</em>
                  ) : null}
                </span>
              </label>
            ))}
            <small>
              A source sends its new leads to one pipeline. Leads you already
              have stay where they are.
            </small>
          </fieldset>
        )}
      </form>
    </Sheet>
  );
}
