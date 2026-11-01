"use client";

import { useEffect, useSyncExternalStore, type ReactNode } from "react";

import { useInApp } from "./in-app-client";
import { phoneStatus, setupStatus } from "./leads/native-phone";
import { useCanHere } from "./workspace-role";

/**
 * The Google Play build is consumption only (owner-approved Play path, 23 Oct 2026). Play
 * counts business-software subscriptions as digital goods, India has no link-out exception,
 * and User Choice Billing would need Play Billing. So inside the Play app nothing shows
 * plans, prices, checkout, top-ups or links to them. The website and the download-link app
 * sell as before. Inside the app, purchases stay hidden until the phone says which store
 * it came from.
 */
export const PLANS_ON_WEB = "Your workspace owner manages plans on the web.";

/** The same place for whoever pays (an owner, or anyone in Personal): their own plan. */
export const YOUR_PLANS_ON_WEB = "You manage your plan and minutes on the web.";

/** Which of the two lines this person reads, by their role here (persona QA ph1-42). */
export function usePlansOnWebLine(): string {
  return useCanHere()("billing.view") === false
    ? PLANS_ON_WEB
    : YOUR_PLANS_ON_WEB;
}

/**
 * What a member of an organisation sees where plans and prices would be:
 * billing belongs to whoever pays (roles.ts "billing.view"), never a price.
 */
export const BILLING_WITH_OWNER =
  "Only your organisation's owner can see billing.";

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

/**
 * True where Sales X-Ray may link to the download-link app (the APK). A Play app updates
 * only through Google Play (Play's Device and Network Abuse policy), so the Play app, and
 * an app that hasn't said its store yet, offer no APK download.
 */
export function useApkLinksAllowed(): boolean {
  return usePurchasesAllowed();
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
