"use client";

/**
 * Leads → Select → Actions (owners and admins; the ease-of-use wave, 22 Oct 2026): give
 * the ticked leads to a person (or the lead rules), move them to a stage, or to another
 * pipeline, in one go. Each lead changes as its own action would (POST /leads/bulk);
 * one that is already there is skipped and counted.
 */

import {
  ChevronLeft,
  ChevronRight,
  Route,
  Shuffle,
  UsersRound,
  Workflow,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { Sheet } from "../ui/sheet";
import { readJourney, type StageView } from "./journey/journey-client";
import {
  bulkLeads,
  LeadsError,
  readTeam,
  type BulkAction,
  type RepView,
} from "./leads-client";
import { KIND_WORDS } from "./stage-tabs";
import { several, usePipelines } from "./use-pipelines";
import styles from "./leads.module.css";

type Step = "menu" | BulkAction;

const TITLES: Record<BulkAction, string> = {
  assign: "Give to a person",
  stage: "Move to a stage",
  pipeline: "Move to a pipeline",
};

function Row({
  icon,
  label,
  note,
  disabled,
  onPick,
}: {
  icon: ReactNode;
  label: string;
  note?: string;
  disabled?: boolean;
  onPick: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        className={styles.menuRow}
        disabled={disabled}
        onClick={onPick}
      >
        <span className={styles.menuIcon} aria-hidden="true">
          {icon}
        </span>
        <span className={styles.menuWords}>
          <strong>{label}</strong>
          {note ? <small>{note}</small> : null}
        </span>
        <ChevronRight size={18} aria-hidden="true" />
      </button>
    </li>
  );
}

export function BulkSheet({
  open,
  leadIds,
  pipeline,
  onClose,
  onDone,
}: {
  open: boolean;
  leadIds: string[];
  /** The pipeline the list shows; none: every pipeline's leads. */
  pipeline: string | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [step, setStep] = useState<Step>("menu");
  const [team, setTeam] = useState<RepView[] | null>(null);
  const [stages, setStages] = useState<StageView[] | null>(null);
  const [busy, setBusy] = useState(false);
  const pipes = usePipelines(open);
  const n = leadIds.length;
  const leads = `${n} lead${n === 1 ? "" : "s"}`;
  // Across several pipelines a stage belongs to one of them: pick it first.
  const stagesFrom = several(pipes) ? pipeline : "main";

  useEffect(() => {
    if (step !== "assign" || team !== null) return;
    const controller = new AbortController();
    readTeam(controller.signal).then(
      (next) => setTeam(next.reps),
      () => {
        if (!controller.signal.aborted) setTeam([]);
      },
    );
    return () => controller.abort();
  }, [step, team]);

  useEffect(() => {
    if (step !== "stage" || stages !== null || !stagesFrom) return;
    let live = true;
    readJourney(stagesFrom).then(
      (view) => {
        if (live)
          setStages(
            view.stages.filter(
              (stage) => !stage.archived && stage.kind !== "not_connected",
            ),
          );
      },
      () => {
        if (live) setStages([]);
      },
    );
    return () => {
      live = false;
    };
  }, [step, stages, stagesFrom]);

  async function run(body: {
    action: BulkAction;
    person_id?: string | null;
    step?: string;
    pipeline?: string;
  }) {
    setBusy(true);
    try {
      const result = await bulkLeads({ ...body, lead_ids: leadIds });
      notify({
        id: "bulk-leads",
        tone: result.done ? "success" : "info",
        title: result.words,
        timeout: 6000,
      });
      onDone();
    } catch (reason) {
      notify({
        id: "bulk-leads",
        tone: "error",
        title: "Those leads weren't changed",
        message:
          reason instanceof LeadsError
            ? reason.message
            : "Check your connection and try again.",
      });
      setBusy(false);
    }
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={step === "menu" ? `${leads} selected` : TITLES[step]}
      wide="center"
    >
      <div className={styles.bulk} aria-busy={busy}>
        {step !== "menu" ? (
          <button
            type="button"
            className={styles.bulkBack}
            onClick={() => setStep("menu")}
          >
            <ChevronLeft size={16} aria-hidden="true" />
            All actions
          </button>
        ) : null}
        {step === "menu" ? (
          <ul className={styles.menuList}>
            <Row
              icon={<UsersRound size={20} />}
              label="Give to a person"
              note="Or let the lead rules share them out"
              onPick={() => setStep("assign")}
            />
            <Row
              icon={<Route size={20} />}
              label="Move to a stage"
              note="Without a call, as after a meeting"
              onPick={() => setStep("stage")}
            />
            {several(pipes) ? (
              <Row
                icon={<Workflow size={20} />}
                label="Move to a pipeline"
                note="They keep their owner and follow-ups"
                onPick={() => setStep("pipeline")}
              />
            ) : null}
          </ul>
        ) : null}
        {step === "assign" ? (
          team === null ? (
            <p className={styles.hint}>Loading your team…</p>
          ) : (
            <ul className={styles.menuList}>
              <Row
                icon={<Shuffle size={20} />}
                label="Let the lead rules pick"
                note="Whoever is free and fits each lead"
                disabled={busy}
                onPick={() => void run({ action: "assign", person_id: null })}
              />
              {team.map((rep) => (
                <Row
                  key={rep.person_id}
                  icon={<UsersRound size={20} />}
                  label={displayName(rep.name)}
                  note={`${rep.open_leads} open lead${rep.open_leads === 1 ? "" : "s"}${rep.available ? "" : " · away now"}`}
                  disabled={busy}
                  onPick={() =>
                    void run({ action: "assign", person_id: rep.person_id })
                  }
                />
              ))}
            </ul>
          )
        ) : null}
        {step === "stage" ? (
          !stagesFrom ? (
            <p className={styles.hint}>
              Each pipeline has its own stages. Pick one with the Pipeline chip
              first, then select its leads.
            </p>
          ) : stages === null ? (
            <p className={styles.hint}>Loading the stages…</p>
          ) : (
            <ul className={styles.menuList}>
              {stages.map((stage) => (
                <Row
                  key={stage.key}
                  icon={<Route size={20} />}
                  label={stage.label}
                  note={KIND_WORDS[stage.kind]}
                  disabled={busy}
                  onPick={() => void run({ action: "stage", step: stage.key })}
                />
              ))}
            </ul>
          )
        ) : null}
        {step === "pipeline" && several(pipes) ? (
          <ul className={styles.menuList}>
            {pipes.pipelines
              .filter((item) => item.key !== pipeline)
              .map((item) => (
                <Row
                  key={item.key}
                  icon={<Workflow size={20} />}
                  label={item.name}
                  note={`${item.leads} lead${item.leads === 1 ? "" : "s"} now`}
                  disabled={busy}
                  onPick={() =>
                    void run({ action: "pipeline", pipeline: item.key })
                  }
                />
              ))}
          </ul>
        ) : null}
      </div>
    </Sheet>
  );
}
