"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play, RefreshCw, Save, ShieldCheck } from "lucide-react";
import { z } from "zod";
import { newIdempotencyKey } from "@ac/operations-web/api";
import {
  Badge,
  Button,
  Field,
  Kpi,
  Panel,
  Skeleton,
  Tiles,
  Unavailable,
  kitStyles,
} from "../ui/kit";
import styles from "./execution-controls.module.css";

const control = z
  .object({
    revision: z.number().int().nonnegative(),
    paused: z.boolean(),
    changed_at: z.string().nullable(),
  })
  .strict();
const amount = z.number().int().nonnegative();
const budgetAccount = z
  .object({
    cap_paise: amount.max(1_000_000),
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
  .strict();
const schema = z
  .object({
    environment: z.enum(["local", "test", "staging", "production"]),
    control,
    budget: budgetAccount.nullable(),
    history: z.array(control).max(10),
  })
  .strict();
type State = z.infer<typeof schema>;
const budgetSchema = z
  .object({
    scope_id: z.string().uuid(),
    revision: z.number().int().nonnegative(),
    approved_cap_paise: amount.max(1_000_000),
    budget: budgetAccount.nullable(),
  })
  .strict();
type BudgetState = z.infer<typeof budgetSchema>;
const endpoint = "/v1/admin/conversation/execution";
const budgetEndpoint = "/v1/admin/conversation/budget";
const money = (paise: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(
    paise / 100,
  );

async function request(path: string, init: RequestInit = {}) {
  const response = await fetch(path, {
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

function formatBudgetAmount(paise: number) {
  return (paise / 100).toFixed(2);
}

function parseBudgetAmount(value: string) {
  const trimmed = value.trim();
  if (!/^\d+(?:\.\d{1,2})?$/.test(trimmed)) return null;
  const [whole, fraction = ""] = trimmed.split(".");
  const paise = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return Number.isSafeInteger(paise) ? paise : null;
}

export function ExecutionControlsPanel() {
  const [state, setState] = useState<State | null>(null);
  const [budgetState, setBudgetState] = useState<BudgetState | null>(null);
  const [budgetDraft, setBudgetDraft] = useState("");
  const [budgetReason, setBudgetReason] = useState(
    "Reviewed shared processing budget",
  );
  const [busy, setBusy] = useState(false);
  const [budgetBusy, setBudgetBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [budgetError, setBudgetError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [budgetMessage, setBudgetMessage] = useState<string | null>(null);
  const pending = useRef<{
    key: string;
    paused: boolean;
    revision: number;
  } | null>(null);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    // Expired budget approval must not hide the independently authorized
    // pause control. Each response clears only its own error and state.
    await Promise.all([
      (async () => {
        try {
          const next = schema.parse(await request(endpoint, { signal }));
          if (signal?.aborted) return;
          setState(next);
          setError(null);
          if (
            pending.current &&
            next.control.revision > pending.current.revision
          )
            pending.current = null;
        } catch (failure) {
          if (!signal?.aborted)
            setError(
              failure instanceof Error && !(failure instanceof z.ZodError)
                ? failure.message
                : "Analysis availability could not be verified. Refresh to try again.",
            );
        }
      })(),
      (async () => {
        try {
          const nextBudget = budgetSchema.parse(
            await request(budgetEndpoint, { signal }),
          );
          if (signal?.aborted) return;
          setBudgetState(nextBudget);
          if (nextBudget.budget)
            setBudgetDraft(formatBudgetAmount(nextBudget.budget.cap_paise));
          setBudgetError(null);
        } catch {
          if (!signal?.aborted) {
            setBudgetState(null);
            setBudgetError(
              "Budget details are unavailable. Refresh to check the approved limit.",
            );
          }
        }
      })(),
    ]);
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
        await request(endpoint, {
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
  async function changeBudget() {
    if (!budgetState || budgetBusy) return;
    const newCapPaise = parseBudgetAmount(budgetDraft);
    if (
      newCapPaise == null ||
      newCapPaise > budgetState.approved_cap_paise ||
      newCapPaise > 1_000_000
    ) {
      setBudgetError(
        `Enter a valid amount up to ${money(budgetState.approved_cap_paise)}.`,
      );
      setBudgetMessage(null);
      return;
    }
    if (!budgetReason.trim()) {
      setBudgetError("Add a short reason so the budget change is auditable.");
      setBudgetMessage(null);
      return;
    }
    setBudgetBusy(true);
    setBudgetError(null);
    setBudgetMessage(null);
    try {
      const next = budgetSchema.parse(
        await request(budgetEndpoint, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "Idempotency-Key": newIdempotencyKey(),
          },
          body: JSON.stringify({
            expected_revision: budgetState.revision,
            new_cap_paise: newCapPaise,
            reason: budgetReason.trim(),
          }),
        }),
      );
      setBudgetState(next);
      if (next.budget)
        setBudgetDraft(formatBudgetAmount(next.budget.cap_paise));
      setBudgetMessage(
        `Saved shared budget limit as revision ${next.revision}.`,
      );
      const refreshed = schema.parse(await request(endpoint));
      setState(refreshed);
    } catch (failure) {
      setBudgetError(
        failure instanceof Error && !(failure instanceof z.ZodError)
          ? failure.message
          : "The budget limit could not be verified. Refresh before continuing.",
      );
    } finally {
      setBudgetBusy(false);
    }
  }
  const budget = budgetState?.budget ?? state?.budget;
  const approvedBudgetCap = budgetState?.approved_cap_paise;
  return (
    <div className={styles.stack} aria-busy={busy}>
      <Panel
        title={
          state?.control.paused
            ? "New analysis is paused"
            : "Analysis availability"
        }
        sub={state ? state.environment : undefined}
        tools={
          <>
            {state ? (
              <Badge tone={state.control.paused ? "warn" : "good"}>
                {state.control.paused ? "Paused" : "Running"}
              </Badge>
            ) : null}
            <Button
              variant="icon"
              onClick={() => void refresh()}
              disabled={busy}
              aria-label="Refresh analysis controls"
            >
              <RefreshCw size={16} aria-hidden />
            </Button>
          </>
        }
      >
        <div className={styles.body}>
          <p className={kitStyles.muted}>
            <ShieldCheck size={14} aria-hidden /> Pause new analysis when you
            need to check quality, capacity or cost. Saved calls and reports
            stay available. Work already started may finish; its costs stay
            recorded.
          </p>
          {!state && !error ? <Skeleton width={180} height={32} /> : null}
          {error && !state ? (
            <Unavailable title="The pause control" reason={error} />
          ) : null}
          {error && state ? (
            <small role="alert" className={kitStyles.fieldError}>
              {error}
            </small>
          ) : null}
          {message ? <p role="status">{message}</p> : null}
          {state ? (
            <span>
              <Button
                variant={state.control.paused ? "primary" : "secondary"}
                disabled={busy || !!error}
                onClick={() => void change()}
              >
                {state.control.paused ? (
                  <Play size={15} aria-hidden />
                ) : (
                  <Pause size={15} aria-hidden />
                )}
                {busy
                  ? "Saving…"
                  : state.control.paused
                    ? "Resume new analysis"
                    : "Pause new analysis"}
              </Button>
            </span>
          ) : null}
          {state?.history.length ? (
            <details className={styles.history}>
              <summary>Recent availability changes</summary>
              <ol>
                {state.history.map((item) => (
                  <li key={item.revision}>
                    {item.paused ? "Paused" : "Resumed"} ·{" "}
                    {item.changed_at
                      ? new Date(item.changed_at).toLocaleString("en-IN", {
                          timeZone: "Asia/Kolkata",
                        })
                      : "Time unavailable"}
                  </li>
                ))}
              </ol>
            </details>
          ) : null}
        </div>
      </Panel>

      <Panel
        title="Shared processing budget"
        sub={budgetState ? `revision ${budgetState.revision}` : undefined}
      >
        <div className={styles.body}>
          {budgetError && !budget ? (
            <Unavailable title="The budget" reason={budgetError} />
          ) : null}
          {budgetError && budget ? (
            <small role="alert" className={kitStyles.fieldError}>
              {budgetError}
            </small>
          ) : null}
          {budget ? (
            <>
              <Tiles label="Budget">
                <Kpi
                  label="Active budget limit"
                  value={money(budget.cap_paise)}
                />
                <Kpi
                  label="Available to reserve"
                  value={money(budget.available_paise)}
                />
                <Kpi
                  label="Reserved or held"
                  value={money(budget.held_paise)}
                />
                <Kpi
                  label="Settled in the ledger"
                  value={money(budget.settled_paise)}
                />
              </Tiles>
              <p className={kitStyles.muted}>
                {money(budget.uncertain_paise)} is held for outcomes awaiting
                reconciliation. Reservations are cost ceilings, not provider
                invoices.
              </p>
              {budget.warning !== "normal" ? (
                <p role="alert" className={styles.alert}>
                  {budget.warning === "exhausted"
                    ? "The shared budget is exhausted or needs reconciliation. New reservations are stopped by the server."
                    : `Budget warning: at least ${budget.warning === "critical" ? budget.critical_percent : budget.warning_percent}% of the ceiling is committed. Review usage before more analysis.`}
                </p>
              ) : null}
              <p className={styles.hint}>
                Usage refreshes every 30 seconds. Warnings include reserved
                money; the server checks the hard ceiling before each new
                reservation.
              </p>
              {budgetState && approvedBudgetCap != null ? (
                <div className={styles.budgetEditor}>
                  <Field
                    label="Shared budget limit (INR)"
                    hint={`Up to the release-approved ceiling of ${money(approvedBudgetCap)}. Existing reservations remain held.`}
                  >
                    <input
                      aria-label="Shared budget limit in INR"
                      type="number"
                      min="0"
                      max={approvedBudgetCap / 100}
                      step="0.01"
                      inputMode="decimal"
                      value={budgetDraft}
                      onChange={(event) => setBudgetDraft(event.target.value)}
                      disabled={budgetBusy}
                    />
                  </Field>
                  <Field label="Reason for change">
                    <input
                      aria-label="Budget change reason"
                      type="text"
                      maxLength={512}
                      value={budgetReason}
                      onChange={(event) => setBudgetReason(event.target.value)}
                      disabled={budgetBusy}
                    />
                  </Field>
                  <span className={styles.budgetActions}>
                    <Button
                      variant="primary"
                      onClick={() => void changeBudget()}
                      disabled={budgetBusy}
                    >
                      <Save size={15} aria-hidden />
                      {budgetBusy ? "Saving…" : "Save budget limit"}
                    </Button>
                  </span>
                  {budgetMessage ? <p role="status">{budgetMessage}</p> : null}
                </div>
              ) : null}
            </>
          ) : budgetError ? (
            <p className={kitStyles.muted}>
              No zero balance or extra allowance is assumed.
            </p>
          ) : state ? (
            <p className={kitStyles.muted}>
              Budget details are unavailable. No zero balance or extra allowance
              is assumed.
            </p>
          ) : (
            <Skeleton height={96} />
          )}
        </div>
      </Panel>
    </div>
  );
}
