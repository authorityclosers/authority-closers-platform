"use client";

/**
 * Where people get stuck (owner, 25 Oct 2026: "automatically find where users
 * stop, which screen they get stuck on ... and why"). A flow is a journey of
 * several steps (first-run setup, phone setup, adding a lead, "How did it
 * go?"); each run sends sx.flow when it starts, at each new step, when a
 * Continue or Save is refused for something missing, and once when it ends:
 * done, skipped, cancelled, failed, or left half way (the screen closed or the
 * page went away). The weekly friction report (telemetry/friction.py) reads
 * where runs stop. Step names only, never what was typed or chosen.
 *
 *   const flow = useFlow("onboarding", { active: ready, via: path });
 *   flow.step("name", 1, 5);  flow.blocked("name");  flow.done();
 */
import { useEffect, useRef, useState } from "react";

import {
  telemetry,
  track,
  type FlowName,
  type FlowStep,
  type FlowVia,
} from "./telemetry";

const MAX_MS = 3_600_000;
const MAX_COUNT = 20;

type Ending = "done" | "skip" | "cancel" | "abandon" | "fail";
type Counts = { index?: number; steps?: number; left?: number };

const count = (value: number | undefined) =>
  typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, Math.min(MAX_COUNT, Math.round(value)))
    : undefined;

/**
 * One flow's runs. A run starts at start() or its first step; after it ends,
 * the next step starts a new run (quick add: one run per lead).
 */
export class FlowRun {
  private started: number | null = null;
  private last: FlowStep | undefined;
  private shown: Counts = {};

  constructor(
    readonly flow: FlowName,
    private via: FlowVia | undefined = undefined,
    private readonly clock: () => number = () => performance.now(),
    private readonly send: typeof track = track,
  ) {}

  get running() {
    return this.started !== null;
  }

  /** Which way in (setup's path); later events carry the new one. */
  setVia(via: FlowVia | undefined) {
    this.via = via;
  }

  start(step?: FlowStep, counts: Counts = {}) {
    if (this.started !== null) return;
    this.started = this.clock();
    this.last = step;
    this.shown = counts;
    this.emit("start", step, counts);
  }

  step(step: FlowStep, index?: number, steps?: number) {
    const counts = { index, steps };
    if (this.started === null) {
      this.start(step, counts);
      return;
    }
    if (step === this.last) return;
    this.last = step;
    this.shown = counts;
    this.emit("step", step, counts);
  }

  /** Continue or Save tapped while something it needs is missing. */
  blocked(step: FlowStep | undefined = this.last) {
    if (this.started === null) this.start(step);
    this.emit("blocked", step, this.shown);
  }

  done(extra: { step?: FlowStep; left?: number } = {}) {
    this.end("done", extra.step, { left: extra.left });
  }

  skip(step?: FlowStep) {
    this.end("skip", step);
  }

  cancel(step?: FlowStep) {
    this.end("cancel", step);
  }

  fail(step?: FlowStep) {
    this.end("fail", step);
  }

  /** The screen closed or the page went away before it ended. */
  abandon() {
    this.end("abandon");
  }

  private end(outcome: Ending, step?: FlowStep, extra: Counts = {}) {
    if (this.started === null) return;
    this.emit(outcome, step ?? this.last, { ...this.shown, ...extra });
    this.started = null;
    this.last = undefined;
    this.shown = {};
  }

  private emit(
    outcome: "start" | "step" | "blocked" | Ending,
    step: FlowStep | undefined,
    counts: Counts,
  ) {
    try {
      const index = count(counts.index);
      const steps = count(counts.steps);
      const left = count(counts.left);
      this.send("sx.flow", {
        flow: this.flow,
        outcome,
        ...(step ? { step } : {}),
        ...(this.via ? { via: this.via } : {}),
        ...(index !== undefined ? { index } : {}),
        ...(steps !== undefined ? { steps } : {}),
        ...(left !== undefined ? { left } : {}),
        ...(this.started !== null
          ? {
              ms: Math.max(
                0,
                Math.min(MAX_MS, Math.round(this.clock() - this.started)),
              ),
            }
          : {}),
      });
    } catch {
      // Telemetry never breaks a flow.
    }
  }
}

/**
 * A flow on this screen. It starts when `active` turns true (or at its first
 * step), and a run still going when the component unmounts or the page goes
 * away counts as left half way.
 */
export function useFlow(
  flow: FlowName,
  { active = false, via }: { active?: boolean; via?: FlowVia } = {},
): FlowRun {
  const [run] = useState(() => new FlowRun(flow, via));
  const mounted = useRef(false);

  useEffect(() => {
    run.setVia(via);
  }, [run, via]);

  useEffect(() => {
    if (active) run.start();
  }, [active, run]);

  useEffect(() => {
    mounted.current = true;
    const away = () => {
      if (!run.running) return;
      run.abandon();
      // telemetry.ts flushed on this pagehide already, before this was queued.
      void telemetry.flush(true);
    };
    window.addEventListener("pagehide", away);
    return () => {
      mounted.current = false;
      window.removeEventListener("pagehide", away);
      // Checked a moment later: React's development remount isn't leaving.
      setTimeout(() => {
        if (!mounted.current && run.running) run.abandon();
      }, 0);
    };
  }, [run]);

  return run;
}
