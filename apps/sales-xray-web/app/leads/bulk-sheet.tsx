"use client";

/**
 * Leads → Select → Actions (owners and admins; the ease-of-use wave, 22 Oct 2026): give
 * the ticked leads to a person (or the lead rules), move them to a stage, or to another
 * pipeline, in one go. Each lead changes as its own action would (POST /leads/bulk);
 * one that is already there is skipped and counted.
 *
 * A WhatsApp template goes only within WhatsApp's rules (orchestrator, 22 Oct 2026):
 * approved templates only, only to leads with a recorded yes, never to one who asked to
 * stop; who gets it is checked first, and the send names that count.
 */

import {
  ChevronLeft,
  MessageCircle,
  Route,
  Shuffle,
  UsersRound,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { Sheet } from "../ui/sheet";
import { readJourney, type StageView } from "./journey/journey-client";
import { ActionList, ActionRow, Button, Field } from "../ui/kit";
import {
  bulkLeads,
  bulkWhatsApp,
  commandId,
  LeadsError,
  readApprovedTemplates,
  readTeam,
  type BulkAction,
  type BulkWhatsApp,
  type RepView,
  type WaTemplate,
} from "./leads-client";
import { KIND_WORDS } from "./stage-tabs";
import { several, usePipelines } from "./use-pipelines";
import styles from "./leads.module.css";

type Step = "menu" | BulkAction | "whatsapp";

const TITLES: Record<Exclude<Step, "menu">, string> = {
  assign: "Give to a person",
  stage: "Move to a stage",
  pipeline: "Move to a pipeline",
  whatsapp: "Send a WhatsApp",
};

const plural = (count: number, one: string, many = `${one}s`) =>
  `${count} ${count === 1 ? one : many}`;

/** One choice on the sheet: the kit's action row. */
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
    <ActionRow
      icon={icon}
      title={label}
      note={note}
      disabled={disabled}
      onClick={onPick}
    />
  );
}

export function BulkSheet({
  open,
  leadIds,
  pipeline,
  initialStep = "menu",
  onClose,
  onDone,
}: {
  open: boolean;
  leadIds: string[];
  /** Assign to… and Move stage open the sheet at their step (Back: the menu). */
  initialStep?: "menu" | "assign" | "stage";
  /** The pipeline the list shows; none: every pipeline's leads. */
  pipeline: string | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [step, setStep] = useState<Step>(initialStep);
  const [team, setTeam] = useState<RepView[] | null>(null);
  const [stages, setStages] = useState<StageView[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [templates, setTemplates] = useState<WaTemplate[] | null>(null);
  const [template, setTemplate] = useState<WaTemplate | null>(null);
  const [values, setValues] = useState<string[]>([]);
  const [plan, setPlan] = useState<BulkWhatsApp | null>(null);
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

  useEffect(() => {
    if (step !== "whatsapp" || templates !== null) return;
    const controller = new AbortController();
    readApprovedTemplates(controller.signal).then(setTemplates, () => {
      if (!controller.signal.aborted) setTemplates([]);
    });
    return () => controller.abort();
  }, [step, templates]);

  const pick = (item: WaTemplate) => {
    setTemplate(item);
    setPlan(null);
    // The first part is usually who it's to: each lead's own first name.
    setValues(
      Array.from({ length: item.parts }, (_, index) =>
        index === 0 ? "{name}" : "",
      ),
    );
  };
  const ask = template && {
    leadIds,
    template: template.name,
    language: template.language,
    values,
  };

  async function check() {
    if (!ask) return;
    setBusy(true);
    try {
      setPlan(await bulkWhatsApp(ask));
    } catch (reason) {
      notify({
        id: "bulk-leads",
        tone: "error",
        title: "Couldn't check who gets it",
        message:
          reason instanceof LeadsError
            ? reason.message
            : "Check your connection and try again.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    if (!ask || !plan) return;
    setBusy(true);
    try {
      const done = await bulkWhatsApp(ask, {
        commandId: commandId(),
        confirm: plan.ready,
      });
      notify({
        id: "bulk-leads",
        tone: done.failed ? "info" : "success",
        title: `Sent to ${plural(done.sent, "lead")}`,
        message: done.failed
          ? `${plural(done.failed, "message")} didn't go. Their chats say why.`
          : undefined,
        timeout: 6000,
      });
      onDone();
    } catch (reason) {
      notify({
        id: "bulk-leads",
        tone: "error",
        title: "Nothing was sent",
        message:
          reason instanceof LeadsError
            ? reason.message
            : "Check your connection and try again.",
      });
      setBusy(false);
    }
  }

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
          <ActionList>
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
            <Row
              icon={<MessageCircle size={20} />}
              label="Send a WhatsApp template"
              note="Only to leads who said yes to WhatsApp"
              onPick={() => setStep("whatsapp")}
            />
          </ActionList>
        ) : null}
        {step === "whatsapp" ? (
          templates === null ? (
            <p className={styles.hint}>Loading your WhatsApp templates…</p>
          ) : !templates.length ? (
            <p className={styles.hint}>
              No approved WhatsApp templates yet. Connect WhatsApp and get a
              template approved in{" "}
              <Link href="/settings/apps">Settings → Connected apps</Link>.
            </p>
          ) : !template ? (
            <ActionList>
              {templates.map((item) => (
                <Row
                  key={`${item.name}-${item.language}`}
                  icon={<MessageCircle size={20} />}
                  label={item.name.replaceAll("_", " ")}
                  note={item.text}
                  onPick={() => pick(item)}
                />
              ))}
            </ActionList>
          ) : (
            <div className={styles.bulkSend}>
              <p className={styles.bulkText}>{plan?.text ?? template.text}</p>
              {values.map((value, index) => (
                <Field
                  key={index}
                  label={`Part ${index + 1}`}
                  hint={
                    index === 0
                      ? "{name} becomes each lead's first name."
                      : undefined
                  }
                >
                  <input
                    value={value}
                    maxLength={200}
                    onChange={(event) => {
                      const next = [...values];
                      next[index] = event.target.value;
                      setValues(next);
                      setPlan(null);
                    }}
                  />
                </Field>
              ))}
              {plan ? (
                <div className={styles.bulkPlan} role="status">
                  <strong>
                    {plan.ready
                      ? `Goes to ${plural(plan.ready, "lead")} who said yes to WhatsApp.`
                      : "Nobody here said yes to WhatsApp yet, so nothing would go."}
                  </strong>
                  {plan.skipped.map((item) => (
                    <span key={item.reason}>
                      {plural(item.count, "lead")} skipped: {item.words}.
                    </span>
                  ))}
                  {plan.ready > plan.limit ? (
                    <span>
                      {`That's more than ${plan.limit} at once. Select fewer leads.`}
                    </span>
                  ) : null}
                </div>
              ) : null}
              <div className={styles.bulkActions}>
                {plan ? (
                  <Button
                    variant="primary"
                    disabled={busy || !plan.ready || plan.ready > plan.limit}
                    onClick={() => void send()}
                  >
                    {busy
                      ? "Sending…"
                      : `Send to ${plural(plan.ready, "lead")}`}
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    disabled={busy || values.some((value) => !value.trim())}
                    onClick={() => void check()}
                  >
                    {busy ? "Checking…" : "Check who gets it"}
                  </Button>
                )}
                <Button
                  variant="ghost"
                  onClick={() => {
                    setTemplate(null);
                    setPlan(null);
                  }}
                >
                  Another template
                </Button>
              </div>
            </div>
          )
        ) : null}
        {step === "assign" ? (
          team === null ? (
            <p className={styles.hint}>Loading your team…</p>
          ) : (
            <ActionList>
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
            </ActionList>
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
            <ActionList>
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
            </ActionList>
          )
        ) : null}
        {step === "pipeline" && several(pipes) ? (
          <ActionList>
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
          </ActionList>
        ) : null}
      </div>
    </Sheet>
  );
}
