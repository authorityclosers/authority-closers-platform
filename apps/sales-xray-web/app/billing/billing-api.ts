/**
 * The billing routes of contract C1 and the catalogue read, behind one
 * client interface so screens can be mounted on a fictional client in the
 * dev-only fixture. Every POST carries an Idempotency-Key; errors keep the
 * problem code so screens can branch on it.
 */
import {
  parseCheckout,
  parseInvoices,
  parseMePlan,
  parseOfflinePayment,
  parseOrder,
  parsePlans,
  parseProblem,
  parseSubscription,
  parseSubscriptions,
  parseUsage,
  type Account,
  type Checkout,
  type Interval,
  type Invoice,
  type MePlan,
  type OfflinePayment,
  type Order,
  type Plan,
  type Subscription,
  type Subscriptions,
  type Usage,
} from "./contract";

export class BillingError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | null,
    readonly detail: string | null,
  ) {
    super(code ?? `billing_${status}`);
  }
  /** True when the server sent an RFC 9457 problem body. */
  get problem() {
    return this.code !== null;
  }
}

/**
 * C1 §5: a route that is not deployed (404 with no problem body), not
 * implemented (501) or refuses to sell (409 not_on_sale) all mean the same
 * honest thing on screen: not on sale yet.
 */
export const notOnSale = (error: unknown) =>
  error instanceof BillingError &&
  ((error.status === 404 && !error.problem) ||
    error.status === 405 ||
    error.status === 501 ||
    (error.status === 409 && error.code === "not_on_sale"));

export const signedOut = (error: unknown) =>
  error instanceof BillingError && error.status === 401;

export type Buyer = { name: string; gstin: string | null };

export type CheckoutRequest =
  | {
      kind: "subscription";
      account: Account;
      planKey: string;
      interval: Interval;
      seats: number;
      buyer?: Buyer;
    }
  | { kind: "top_up"; account: Account; planKey: string; packKey: string };

export interface BillingClient {
  readPlans(signal?: AbortSignal): Promise<Plan[]>;
  readMePlan(signal?: AbortSignal): Promise<MePlan>;
  readUsage(signal?: AbortSignal): Promise<Usage>;
  readSubscriptions(
    account: Account,
    signal?: AbortSignal,
  ): Promise<Subscriptions>;
  readOfflinePayment(signal?: AbortSignal): Promise<OfflinePayment>;
  readInvoices(account: Account, signal?: AbortSignal): Promise<Invoice[]>;
  /** The development fixture supplies a fictional downloadable document. */
  invoiceDownloadHref?(invoiceId: string): string;
  checkout(request: CheckoutRequest, idempotencyKey: string): Promise<Checkout>;
  readOrder(orderId: string, signal?: AbortSignal): Promise<Order>;
  verifyOrder(orderId: string, idempotencyKey: string): Promise<Order>;
  cancelSubscription(
    subscriptionId: string,
    reason: string | null,
    idempotencyKey: string,
  ): Promise<Subscription>;
}

/** One key per attempt at one action; a retry of the same action reuses it. */
export function idempotencyKey(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
}

async function call(
  path: string,
  init: RequestInit & { idempotencyKey?: string } = {},
): Promise<unknown> {
  const headers: Record<string, string> = {};
  if (init.body) headers["Content-Type"] = "application/json";
  if (init.idempotencyKey) headers["Idempotency-Key"] = init.idempotencyKey;
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: {
      ...headers,
      ...(init.headers as Record<string, string> | undefined),
    },
  });
  if (response.ok) return response.status === 204 ? null : response.json();
  let problem = null;
  try {
    const type = response.headers.get("content-type") ?? "";
    if (/json/.test(type)) {
      problem = parseProblem(await response.json());
    }
  } catch {
    problem = null;
  }
  throw new BillingError(
    response.status,
    problem?.code ?? null,
    problem?.detail ?? null,
  );
}

export const liveBilling: BillingClient = {
  readPlans: async (signal) => parsePlans(await call("/v1/plans", { signal })),
  readMePlan: async (signal) =>
    parseMePlan(await call("/v1/me/plan", { signal })),
  readUsage: async (signal) =>
    parseUsage(await call("/v1/me/usage", { signal })),
  readSubscriptions: async (account, signal) =>
    parseSubscriptions(
      await call(`/v1/subscriptions?account=${account}`, { signal }),
    ),
  readOfflinePayment: async (signal) =>
    parseOfflinePayment(await call("/v1/billing/offline-payment", { signal })),
  readInvoices: async (account, signal) => {
    const invoices: Invoice[] = [];
    const cursors = new Set<string>();
    let before: string | null = null;
    do {
      const query = new URLSearchParams({ account });
      if (before) query.set("before", before);
      let response: unknown;
      try {
        response = await call(`/v1/invoices?${query}`, { signal });
      } catch (error) {
        // A first organisation visit can precede creation of its billing account.
        if (
          account === "organisation" &&
          before === null &&
          error instanceof BillingError &&
          error.status === 404 &&
          notOnSale(error)
        )
          return [];
        throw error;
      }
      const page = parseInvoices(response);
      invoices.push(...page.invoices);
      before = page.nextBefore;
      if (before && cursors.has(before))
        throw new Error("Repeated invoice cursor");
      if (before) cursors.add(before);
    } while (before);
    return invoices;
  },
  checkout: async (request, key) =>
    parseCheckout(
      await call("/v1/checkout", {
        method: "POST",
        idempotencyKey: key,
        body: JSON.stringify(
          request.kind === "subscription"
            ? {
                kind: "subscription",
                account: request.account,
                plan_key: request.planKey,
                interval: request.interval,
                seats: request.seats,
                ...(request.buyer
                  ? {
                      buyer: {
                        name: request.buyer.name,
                        gstin: request.buyer.gstin,
                      },
                    }
                  : {}),
              }
            : {
                kind: "top_up",
                account: request.account,
                plan_key: request.planKey,
                pack_key: request.packKey,
              },
        ),
      }),
    ),
  readOrder: async (orderId, signal) =>
    parseOrder(
      await call(`/v1/orders/${encodeURIComponent(orderId)}`, { signal }),
    ),
  verifyOrder: async (orderId, key) =>
    parseOrder(
      await call(`/v1/orders/${encodeURIComponent(orderId)}/verify`, {
        method: "POST",
        idempotencyKey: key,
      }),
    ),
  cancelSubscription: async (subscriptionId, reason, key) =>
    parseSubscription(
      await call(
        `/v1/subscriptions/${encodeURIComponent(subscriptionId)}/cancel`,
        {
          method: "POST",
          idempotencyKey: key,
          body: JSON.stringify({ reason }),
        },
      ),
    ),
};

/** Where the server sends the buyer back; fixed by the contract, never chosen by the client. */
export const returnPath = (orderId: string) =>
  `/account/billing/return?order=${encodeURIComponent(orderId)}`;

export const invoiceDownloadPath = (invoiceId: string) =>
  `/v1/invoices/${encodeURIComponent(invoiceId)}/download`;
