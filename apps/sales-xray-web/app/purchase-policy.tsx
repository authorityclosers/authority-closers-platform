"use client";

import { useEffect, useSyncExternalStore, type ReactNode } from "react";

import { useInApp } from "./in-app-client";
import { phoneStatus, setupStatus } from "./leads/native-phone";

/**
 * The Google Play build is consumption only (owner-approved Play path, 23 Oct 2026). Play
 * counts business-software subscriptions as digital goods, India has no link-out exception,
 * and User Choice Billing would need Play Billing. So inside the Play app nothing shows
 * plans, prices, checkout, top-ups or links to them. The website and the download-link app
 * sell as before. Inside the app, purchases stay hidden until the phone says which store
 * it came from.
 */
export const PLANS_ON_WEB = "Your workspace owner manages plans on the web.";

type Store = "direct" | "play";
let store: Store | null = null;
let asked = false;
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

async function readStore(): Promise<Store | null> {
  const status = await phoneStatus();
  if (status?.store) return status.store;
  return (await setupStatus())?.store ?? null;
}

function askStore(): void {
  if (asked) return;
  asked = true;
  void readStore().then((found) => {
    store = found;
    listeners.forEach((listener) => listener());
  });
}

/** True where Sales X-Ray may show plans, prices and purchases. */
export function usePurchasesAllowed(): boolean {
  const inApp = useInApp();
  const known = useSyncExternalStore(
    subscribe,
    () => store,
    () => null,
  );
  useEffect(() => {
    if (inApp) askStore();
  }, [inApp]);
  return !inApp || known === "direct";
}

/** Its children where purchases are allowed, else the fallback. */
export function PurchaseGate({
  children,
  fallback,
}: {
  children: ReactNode;
  fallback: ReactNode;
}) {
  return <>{usePurchasesAllowed() ? children : fallback}</>;
}

/** Tests only: forget what the phone reported. */
export function resetPurchaseStoreForTests(): void {
  store = null;
  asked = false;
}
