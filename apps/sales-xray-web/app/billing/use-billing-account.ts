"use client";

import { useEffect, useRef, useState } from "react";
import { useWorkspaceAccess } from "../workspace-access";
import {
  BillingError,
  idempotencyKey,
  invoiceDownloadPath,
  notOnSale,
  liveBilling,
  type BillingClient,
} from "./billing-api";
import type { Invoice, MePlan, Subscriptions, Usage } from "./contract";

type Snapshot = {
  key: string;
  mePlan: MePlan;
  usage: Usage;
  subs: Subscriptions;
};

type InvoiceSnapshot = {
  key: string;
  client: BillingClient;
  attempt: number;
} & ({ status: "ready"; invoices: Invoice[] } | { status: "error" });

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
  const [invoiceSnapshot, setInvoiceSnapshot] =
    useState<InvoiceSnapshot | null>(null);
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
      client.readSubscriptions(account, controller.signal).catch((error) => {
        if (notOnSale(error)) {
          return { current: null, past: [] };
        }
        throw error;
      }),
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

  useEffect(() => {
    if (!enabled || !authenticated) return;
    const controller = new AbortController();
    client
      .readInvoices(account, controller.signal)
      .then((invoices) => {
        if (!controller.signal.aborted)
          setInvoiceSnapshot({
            key,
            client,
            attempt,
            status: "ready",
            invoices,
          });
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          if (notOnSale(error)) {
            setInvoiceSnapshot({
              key,
              client,
              attempt,
              status: "ready",
              invoices: [],
            });
          } else {
            setInvoiceSnapshot({ key, client, attempt, status: "error" });
          }
        }
      });
    return () => controller.abort();
  }, [account, attempt, authenticated, client, enabled, key]);

  const current = snapshot?.key === key && authenticated ? snapshot : null;
  const currentInvoices =
    authenticated &&
    enabled &&
    invoiceSnapshot?.key === key &&
    invoiceSnapshot.client === client &&
    invoiceSnapshot.attempt === attempt
      ? invoiceSnapshot
      : null;
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

  return {
    mePlan: current?.mePlan ?? null,
    usage: current?.usage ?? null,
    subs: current?.subs ?? null,
    invoicesStatus: currentInvoices?.status ?? ("loading" as const),
    documents: (currentInvoices?.status === "ready"
      ? currentInvoices.invoices
      : []
    ).map((invoice) => ({
      id: invoice.invoiceId,
      createdAt: invoice.createdAt,
      description: invoice.number,
      amount: {
        minor: invoice.totalMinor,
        currency: invoice.currency,
        gstInclusive: true,
      },
      status: "Issued",
      invoiceHref: (client.invoiceDownloadHref ?? invoiceDownloadPath)(
        invoice.invoiceId,
      ),
      receiptHref: null,
    })),
    status: current
      ? ("ready" as const)
      : error
        ? ("error" as const)
        : ("loading" as const),
    error,
    busy,
    onRefresh,
    onCancel,
  };
}
