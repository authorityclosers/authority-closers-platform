"use client";

import { useEffect, useRef, useState } from "react";

import {
  notAnalysedCalls,
  prepareAnalyseAll,
  runAnalyseAll,
  type CallRun,
  type Preparation,
  type RunResult,
} from "./analyse-all";
import styles from "./analyse-all.module.css";
import { Button, Dialog, Meter } from "./ui/kit";

type Step =
  | { kind: "idle" }
  | { kind: "checking"; checked: number; total: number }
  | { kind: "confirm"; preparation: Preparation }
  | {
      kind: "running";
      total: number;
      started: number;
      done: number;
      failed: number;
    }
  | { kind: "finished"; total: number; result: RunResult }
  | { kind: "error" };

const plural = (count: number, one: string, many = `${one}s`) =>
  `${count} ${count === 1 ? one : many}`;

/**
 * The "Not analysed yet" group's action: start analysis for every saved call
 * of the signed-in person that never started, one call at a time, after one
 * confirm that shows the count and the quoted maximum cost.
 */
export function AnalyseAllControl({
  viewerId,
  everyone = false,
  onFinished,
}: {
  viewerId: string | null;
  /** The viewer runs this organisation: members' calls are included. */
  everyone?: boolean;
  /** Re-read the list once the run ends, so rows show their new status. */
  onFinished: () => void;
}) {
  const [step, setStep] = useState<Step>({ kind: "idle" });
  const run = useRef<AbortController | null>(null);

  // Leaving the page stops the run after the current call (it keeps going).
  useEffect(() => () => run.current?.abort(), []);

  async function check() {
    const controller = new AbortController();
    run.current = controller;
    setStep({ kind: "checking", checked: 0, total: 0 });
    try {
      const ids = await notAnalysedCalls(viewerId, controller.signal, everyone);
      setStep({ kind: "checking", checked: 0, total: ids.length });
      const preparation = await prepareAnalyseAll(
        ids,
        controller.signal,
        (checked) => setStep({ kind: "checking", checked, total: ids.length }),
      );
      setStep({ kind: "confirm", preparation });
    } catch {
      setStep(controller.signal.aborted ? { kind: "idle" } : { kind: "error" });
    }
  }

  async function start(preparation: Preparation) {
    const controller = new AbortController();
    run.current = controller;
    const total = preparation.planned.length;
    const counts = { started: 0, done: 0, failed: 0 };
    setStep({ kind: "running", total, ...counts });
    const onCall = (_id: string, state: CallRun) => {
      if (state === "analysing") counts.started += 1;
      if (state === "done") counts.done += 1;
      if (state === "failed") counts.failed += 1;
      setStep({ kind: "running", total, ...counts });
    };
    const result = await runAnalyseAll(
      preparation.planned,
      controller.signal,
      onCall,
    );
    setStep({ kind: "finished", total, result });
    onFinished();
  }

  const confirm = step.kind === "confirm" ? step.preparation : null;
  const checks =
    confirm?.skipped.filter((item) => item.reason === "checks").length ?? 0;
  const attention =
    confirm?.skipped.filter((item) => item.reason === "attention").length ?? 0;

  return (
    <span className={styles.control} data-analyse-all={step.kind}>
      {step.kind === "idle" || step.kind === "error" ? (
        <>
          {step.kind === "error" ? (
            <span className={styles.text} role="status">
              Couldn&apos;t check your calls. Try again.
            </span>
          ) : null}
          <Button className={styles.button} onClick={() => void check()}>
            Analyse all
          </Button>
        </>
      ) : null}
      {step.kind === "checking" ? (
        <>
          <span className={styles.text} role="status">
            {step.total
              ? `Checking calls · ${step.checked} of ${step.total}`
              : "Finding calls…"}
          </span>
          <Meter value={step.checked} max={step.total || 1} />
          <Button
            variant="ghost"
            className={styles.button}
            onClick={() => run.current?.abort()}
          >
            Cancel
          </Button>
        </>
      ) : null}
      {step.kind === "running" ? (
        <>
          <span className={styles.text} role="status">
            {`Analysing · ${step.started} of ${step.total} started · ${plural(step.done, "report")} ready`}
            {step.failed ? ` · ${step.failed} need attention` : ""}
          </span>
          <Meter value={step.done + step.failed} max={step.total || 1} />
          <Button
            variant="ghost"
            className={styles.button}
            onClick={() => run.current?.abort()}
          >
            Stop
          </Button>
        </>
      ) : null}
      {step.kind === "finished" ? (
        <>
          <span className={styles.text} role="status">
            {step.result.stoppedBy === "budget"
              ? `Stopped: the analysis budget can't cover the next call · ${step.result.started} of ${step.total} started`
              : step.result.stoppedBy === "cancelled"
                ? `Stopped · ${step.result.started} of ${step.total} started`
                : `${step.result.started} of ${step.total} started · ${plural(step.result.done, "report")} ready`}
            {step.result.failed
              ? ` · ${step.result.failed} need attention`
              : ""}
          </span>
          <Button
            variant="ghost"
            className={styles.button}
            onClick={() => setStep({ kind: "idle" })}
          >
            Done
          </Button>
        </>
      ) : null}
      <Dialog
        open={confirm !== null}
        title={
          confirm && confirm.planned.length
            ? `Analyse ${plural(confirm.planned.length, "call")}?`
            : "No calls can start right now"
        }
        description={
          confirm && confirm.planned.length
            ? "Each call is analysed one at a time with the usual analysis (transcript, report and coaching). You can stop at any time."
            : confirm?.budgetStopped
              ? "The analysis budget can't cover another call right now. Nothing was started."
              : "None of these calls is ready to start. Open a call to see what it needs."
        }
        onClose={() => setStep({ kind: "idle" })}
        actions={
          confirm && confirm.planned.length ? (
            <>
              <Button variant="ghost" onClick={() => setStep({ kind: "idle" })}>
                Cancel
              </Button>
              <Button variant="primary" onClick={() => void start(confirm)}>
                {`Start ${plural(confirm.planned.length, "analysis", "analyses")}`}
              </Button>
            </>
          ) : (
            <Button onClick={() => setStep({ kind: "idle" })}>Close</Button>
          )
        }
      >
        {confirm && confirm.planned.length ? (
          <ul className={styles.facts}>
            {confirm.budgetStopped ? (
              <li>
                The analysis budget covers only these calls for now; the rest
                stay not analysed.
              </li>
            ) : (
              <li>
                If the analysis budget runs out, the remaining calls wait.
              </li>
            )}
            {checks ? (
              <li>
                {`${plural(checks, "call")} can't start yet: ${checks === 1 ? "its" : "their"} file checks didn't finish. Open ${checks === 1 ? "it" : "them"} to try again.`}
              </li>
            ) : null}
            {attention ? (
              <li>{`${plural(attention, "call")} need${attention === 1 ? "s" : ""} attention first. Open ${attention === 1 ? "it" : "them"} to review.`}</li>
            ) : null}
          </ul>
        ) : null}
      </Dialog>
    </span>
  );
}
