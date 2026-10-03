"use client";

import { useEffect, useRef, useState } from "react";
import { useWorkspaceAccess } from "../workspace-access";
import {
  BillingError,
  idempotencyKey,
  liveBilling,
  type BillingClient,
} from "./billing-api";
import type { MePlan, Subscriptions, Usage } from "./contract";

type Snapshot = {
  key: string;
  mePlan: MePlan;
  usage: Usage;
  subs: Subscriptions;
};

/** Account facts are read from AC; provider states never supply the allowance. */
export function useBillingAccount(
  enabled = true,
  client: BillingClient = liveBilling,
) {
  const access = useWorkspaceAccess();
  const workspace = access?.workspaces?.find(
    (item) => item.tenant_id === access.context?.tenantId,
  );
  const account = workspace?.kind ?? "personal";
  const key = JSON.stringify([access?.context, account]);
  const identity = useRef<string | null>(key);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [failure, setFailure] = useState<{
    key: string;
    message: string;
  } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const cancelAttempt = useRef<{ id: string; key: string } | null>(null);
  const inFlight = useRef(false);
  const authenticated = access?.authenticated === true;

  useEffect(() => {
    identity.current = key;
    return () => {
      identity.current = null;
      cancelAttempt.current = null;
    };
  }, [key]);

  useEffect(() => {
    if (!enabled || !authenticated) return;
    const controller = new AbortController();
    Promise.all([
      client.readMePlan(controller.signal),
      client.readUsage(controller.signal),
      client.readSubscriptions(account, controller.signal),
    ])
      .then(([mePlan, usage, subs]) => {
        if (controller.signal.aborted) return;
        setSnapshot({ key, mePlan, usage, subs });
        setFailure(null);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setFailure({
            key,
            message: "Billing details could not be loaded. Please try again.",
          });
      });
    return () => controller.abort();
  }, [account, attempt, authenticated, client, enabled, key]);

  const current = snapshot?.key === key && authenticated ? snapshot : null;
  const error = failure?.key === key ? failure.message : null;
  const onRefresh = () => setAttempt((value) => value + 1);
  const onCancel = async (id: string) => {
    if (
      inFlight.current ||
      !current ||
      current.subs.current?.subscriptionId !== id
    )
      return;
    inFlight.current = true;
    setBusy(true);
    if (cancelAttempt.current?.id !== id)
      cancelAttempt.current = { id, key: idempotencyKey() };
    try {
      const subscription = await client.cancelSubscription(
        id,
        null,
        cancelAttempt.current.key,
      );
      if (identity.current !== key) return;
      setSnapshot({
        ...current,
        subs: { ...current.subs, current: subscription },
      });
      setFailure(null);
      cancelAttempt.current = null;
      onRefresh();
    } catch (error) {
      if (identity.current === key)
        setFailure({
          key,
          message:
            error instanceof BillingError && error.detail
              ? error.detail
              : "Renewal could not be cancelled. Please try again.",
        });
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const onResume = async (id: string) => {
    if (
      inFlight.current ||
      !current ||
      current.subs.current?.subscriptionId !== id
    )
      return;
    inFlight.current = true;
    setBusy(true);
    try {
      if (client.resumeSubscription) {
        const subscription = await client.resumeSubscription(
          id,
          idempotencyKey(),
        );
        if (identity.current !== key) return;
        setSnapshot({
          ...current,
          subs: { ...current.subs, current: subscription },
        });
        setFailure(null);
        onRefresh();
      } else {
        setFailure({
          key,
          message:
            "Renewal resumption is being processed. Your subscription access continues through period end.",
        });
      }
    } catch (error) {
      if (identity.current === key)
        setFailure({
          key,
          message:
            error instanceof BillingError && error.detail
              ? error.detail
              : "Renewal could not be resumed. Please try again.",
        });
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  return {
    mePlan: current?.mePlan ?? null,
    usage: current?.usage ?? null,
    subs: current?.subs ?? null,
    status: current
      ? ("ready" as const)
      : error
        ? ("error" as const)
        : ("loading" as const),
    error,
    busy,
    onRefresh,
    onCancel,
    onResume: client.resumeSubscription ? onResume : undefined,
  };
}
