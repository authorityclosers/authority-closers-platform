"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play, RefreshCw, ShieldCheck } from "lucide-react";
import { z } from "zod";
import { newIdempotencyKey } from "@ac/operations-web/api";
import styles from "./execution-controls.module.css";

const control = z
  .object({
    revision: z.number().int().nonnegative(),
    paused: z.boolean(),
    changed_at: z.string().nullable(),
  })
  .strict();
const amount = z.number().int().nonnegative();
const schema = z
  .object({
    environment: z.enum(["local", "test", "staging", "production"]),
    control,
    budget: z
      .object({
        cap_paise: amount,
        available_paise: z.number().int(),
        committed_paise: amount,
        settled_paise: amount,
        held_paise: amount,
        uncertain_paise: amount,
        reservation_count: amount,
        warning: z.enum(["normal", "warning", "critical", "exhausted"]),
        warning_percent: amount,
        critical_percent: amount,
      })
      .strict()
      .nullable(),
    history: z.array(control).max(10),
  })
  .strict();
type State = z.infer<typeof schema>;
const endpoint = "/v1/admin/conversation/execution";
const money = (paise: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(
    paise / 100,
  );

async function request(init: RequestInit = {}) {
  const response = await fetch(endpoint, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    redirect: "error",
    headers: { accept: "application/json", ...init.headers },
  });
  if (!response.ok)
    throw new Error(
      response.status === 403
        ? "Use your verified AC Admin account to manage analysis."
        : response.status === 409
          ? "Another administrator changed this setting. Refresh before trying again."
          : "The setting could not be confirmed. Refresh to check its current state.",
    );
  return response.json() as Promise<unknown>;
}

export function ExecutionControlsPanel() {
  const [state, setState] = useState<State | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const pending = useRef<{
    key: string;
    paused: boolean;
    revision: number;
  } | null>(null);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const next = schema.parse(await request({ signal }));
      if (signal?.aborted) return;
      setState(next);
      setError(null);
      if (pending.current && next.control.revision > pending.current.revision)
        pending.current = null;
    } catch (failure) {
      if (!signal?.aborted)
        setError(
          failure instanceof Error && !(failure instanceof z.ZodError)
            ? failure.message
            : "Usage details could not be verified. Refresh to try again.",
        );
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => {
      if (!controller.signal.aborted) void refresh(controller.signal);
    });
    const timer = window.setInterval(
      () => void refresh(controller.signal),
      30000,
    );
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [refresh]);
  async function change() {
    if (!state || busy) return;
    const intent = pending.current ?? {
      key: newIdempotencyKey(),
      paused: !state.control.paused,
      revision: state.control.revision,
    };
    pending.current = intent;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = control.parse(
        await request({
          method: "POST",
          headers: {
            "content-type": "application/json",
            "Idempotency-Key": intent.key,
          },
          body: JSON.stringify({
            expected_revision: intent.revision,
            paused: intent.paused,
          }),
        }),
      );
      setState({ ...state, control: result });
      pending.current = null;
      setMessage(
        result.paused
          ? "New analysis is paused. Already-started work may finish."
          : "New analysis may run within its existing approvals and budget.",
      );
      await refresh();
    } catch (failure) {
      setError(
        failure instanceof Error && !(failure instanceof z.ZodError)
          ? failure.message
          : "The result could not be verified. Refresh before continuing.",
      );
    } finally {
      setBusy(false);
    }
  }
  const budget = state?.budget;
  return (
    <section
      className={styles.panel}
      aria-labelledby="execution-control-title"
      aria-busy={busy}
    >
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>
            <ShieldCheck size={16} aria-hidden /> Analysis controls{" "}
            {state && `· ${state.environment}`}
          </p>
          <h2 id="execution-control-title">
            {state?.control.paused
              ? "New analysis is paused"
              : "Manage analysis availability"}
          </h2>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={busy}
          aria-label="Refresh analysis controls"
        >
          <RefreshCw size={17} aria-hidden />
        </button>
      </header>
      <p>
        Pause new analysis when you need to check quality, capacity or cost.
        Saved calls and reports stay available. Work already started may finish;
        its costs stay recorded.
      </p>
      {!state && !error && <p role="status">Loading analysis controls…</p>}
      {error && (
        <p role="alert" className={styles.alert}>
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {state && (
        <button
          type="button"
          className={styles.action}
          disabled={busy || !!error}
          onClick={() => void change()}
        >
          {state.control.paused ? (
            <Play size={17} aria-hidden />
          ) : (
            <Pause size={17} aria-hidden />
          )}
          {busy
            ? "Saving…"
            : state.control.paused
              ? "Resume new analysis"
              : "Pause new analysis"}
        </button>
      )}
      {budget ? (
        <>
          <dl className={styles.metrics}>
            <div>
              <dt>Approved ceiling</dt>
              <dd>{money(budget.cap_paise)}</dd>
            </div>
            <div>
              <dt>Available to reserve</dt>
              <dd>{money(budget.available_paise)}</dd>
            </div>
            <div>
              <dt>Reserved or held</dt>
              <dd>{money(budget.held_paise)}</dd>
            </div>
            <div>
              <dt>Settled in the ledger</dt>
              <dd>{money(budget.settled_paise)}</dd>
            </div>
          </dl>
          <p>
            {money(budget.uncertain_paise)} is held for outcomes awaiting
            reconciliation. Reservations are cost ceilings, not provider
            invoices.
          </p>
          {budget.warning !== "normal" && (
            <p role="alert" className={styles.alert}>
              {budget.warning === "exhausted"
                ? "The shared budget is exhausted or needs reconciliation. New reservations are stopped by the server."
                : `Budget warning: at least ${budget.warning === "critical" ? budget.critical_percent : budget.warning_percent}% of the ceiling is committed. Review usage before more analysis.`}
            </p>
          )}
          <p className={styles.hint}>
            Usage refreshes every 30 seconds. Warnings include reserved money;
            the server checks the hard ceiling before each new reservation.
          </p>
        </>
      ) : (
        state && (
          <p>
            Budget details are unavailable. No zero balance or extra allowance
            is assumed.
          </p>
        )
      )}
      {!!state?.history.length && (
        <details>
          <summary>Recent availability changes</summary>
          <ol>
            {state.history.map((item) => (
              <li key={item.revision}>
                {item.paused ? "Paused" : "Resumed"} ·{" "}
                {item.changed_at
                  ? new Date(item.changed_at).toLocaleString()
                  : "Time unavailable"}
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}
