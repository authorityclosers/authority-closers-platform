"use client";

import { Check, ChevronDown, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { notify } from "../notice-center";
import { Skeleton } from "../ui/kit";
import { readJourney, type JourneyView } from "./journey/journey-client";
import type { LeadRow } from "./leads-client";
import styles from "./leads.module.css";

/** The actual stage set, not a guessed sequence or a completion score. */
export function PipelineOverview({
  lead,
  name,
}: {
  lead: LeadRow;
  name: string;
}) {
  const [open, setOpen] = useState(false);
  const [round, setRound] = useState(0);
  const [result, setResult] = useState<{
    pipeline: string;
    view: JourneyView;
  } | null>(null);
  const [failed, setFailed] = useState(false);
  const pipeline = lead.pipeline ?? "main";
  useEffect(() => {
    if (!open) return;
    let live = true;
    readJourney(pipeline).then(
      (view) => {
        if (live) {
          setResult({ pipeline, view });
          setFailed(false);
        }
      },
      () => {
        if (!live) return;
        setFailed(true);
        notify({
          id: "lead-pipeline",
          tone: "error",
          title: "The stages didn’t load",
          message: "Try again in a moment.",
        });
      },
    );
    return () => {
      live = false;
    };
  }, [open, pipeline, round]);
  const stages =
    result?.pipeline === pipeline
      ? result.view.stages.filter((stage) => !stage.archived)
      : null;
  return (
    <details
      className={styles.pipelineOverview}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <Workflow size={20} aria-hidden="true" />
        <span>
          <small>Pipeline · {name}</small>
          <strong>{lead.stage_label}</strong>
        </span>
        <ChevronDown size={18} aria-hidden="true" />
      </summary>
      <div className={styles.pipelineStages}>
        <p className={styles.hint}>
          Your team’s stages. Your current stage is marked.
        </p>
        {failed ? (
          <button
            type="button"
            className={styles.linkButton}
            onClick={() => setRound((value) => value + 1)}
          >
            Try again
          </button>
        ) : stages ? (
          <ul aria-label="Pipeline stages">
            {stages.map((stage) => {
              const current = lead.step
                ? stage.key === lead.step
                : stage.label === lead.stage_label;
              return (
                <li key={stage.key} aria-current={current ? "step" : undefined}>
                  <span>{stage.label}</span>
                  {current ? (
                    <small>
                      <Check size={14} aria-hidden="true" />
                      Current
                    </small>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <div aria-label="Loading pipeline stages" aria-busy="true">
            <Skeleton height={44} />
            <Skeleton height={44} />
          </div>
        )}
      </div>
    </details>
  );
}
