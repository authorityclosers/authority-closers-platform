"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  BillingError,
  idempotencyKey,
  liveBilling,
  notOnSale,
  returnPath,
  type BillingClient,
  type CheckoutRequest,
} from "../billing/billing-api";
import type { Checkout } from "../billing/contract";
import { useWorkspaceAccess } from "../workspace-access";
import { openHostedCheckout } from "./hosted-checkout";

/** Shared two-step purchase: review AC's total, then open hosted payment. */
export function usePurchaseCheckout(
  client: BillingClient = liveBilling,
  signInReturnTo = "/plans",
) {
  const router = useRouter();
  const access = useWorkspaceAccess();
  const identity = JSON.stringify([access?.authenticated, access?.context]);
  const activeIdentity = useRef<string | null>(identity);
  const [prepared, setPrepared] = useState<{
    identity: string;
    checkout: Checkout;
    client: BillingClient;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<{
    identity: string;
    message: string;
  } | null>(null);
  const attempt = useRef<{
    fingerprint: string;
    key: string;
    checkout?: Checkout;
  } | null>(null);
  const inFlight = useRef(false);

  useEffect(() => {
    activeIdentity.current = identity;
    return () => {
      activeIdentity.current = null;
      attempt.current = null;
    };
  }, [identity, client]);

  const select = () => {
    attempt.current = null;
    setPrepared(null);
    setFailure(null);
  };
  const buy = async (request: CheckoutRequest) => {
    if (inFlight.current) return;
    if (access?.authenticated !== true) {
      if (access?.requestAccountSignIn) access.requestAccountSignIn();
      else router.push(`/login?returnTo=${encodeURIComponent(signInReturnTo)}`);
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setFailure(null);
    const fingerprint = JSON.stringify(request);
    const expiresAt = attempt.current?.checkout?.hosted.expiresAt;
    if (expiresAt && Date.parse(expiresAt) <= Date.now()) select();
    if (attempt.current?.fingerprint !== fingerprint)
      attempt.current = { fingerprint, key: idempotencyKey() };
    const current = attempt.current;
    const isCurrent = () =>
      activeIdentity.current === identity && attempt.current === current;
    try {
      if (!current.checkout) {
        const checkout = await client.checkout(request, current.key);
        if (!isCurrent()) return;
        current.checkout = checkout;
        setPrepared({ identity, checkout, client });
        return;
      }
      const result = await openHostedCheckout(
        current.checkout.hosted,
        current.checkout.order.orderId,
      );
      if (isCurrent() && result !== "left")
        router.push(returnPath(current.checkout.order.orderId));
    } catch (error) {
      if (isCurrent())
        setFailure({
          identity,
          message: notOnSale(error)
            ? "Payments are currently unavailable. Please try again later."
            : error instanceof BillingError && error.detail
              ? error.detail
              : "Checkout could not be opened. Please try again.",
        });
    } finally {
      inFlight.current = false;
      if (activeIdentity.current !== null) setBusy(false);
    }
  };

  return {
    prepared:
      prepared?.identity === identity && prepared.client === client
        ? prepared.checkout
        : null,
    busy,
    error: failure?.identity === identity ? failure.message : null,
    select,
    buy,
  };
}
