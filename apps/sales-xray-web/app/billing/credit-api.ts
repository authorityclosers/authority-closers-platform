/** Credit-only reads; the server resolves the caller's account and authority. */
import { BillingError } from "./billing-api";
import { ContractError, parseProblem, type Account } from "./contract";
import {
  parseCreditAccount,
  parseCreditBalance,
  parseCreditHistory,
  parseCreditId,
  type CreditBalance,
  type CreditHistory,
} from "./credit-contract";

export type CreditHistoryRequest = {
  account?: Account;
  limit?: number;
  before?: string | null;
};

export interface CreditsClient {
  readBalance(account?: Account, signal?: AbortSignal): Promise<CreditBalance>;
  readHistory(
    request?: CreditHistoryRequest,
    signal?: AbortSignal,
  ): Promise<CreditHistory>;
}

async function read(path: string, signal?: AbortSignal): Promise<unknown> {
  signal?.throwIfAborted();
  const response = await fetch(path, {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });
  if (response.ok) {
    const value: unknown = await response.json();
    signal?.throwIfAborted();
    return value;
  }
  let problem = null;
  try {
    if (/json/.test(response.headers.get("content-type") ?? ""))
      problem = parseProblem(await response.json());
  } catch {
    signal?.throwIfAborted();
  }
  signal?.throwIfAborted();
  throw new BillingError(
    response.status,
    problem?.code ?? null,
    problem?.detail ?? null,
  );
}

export const liveCredits: CreditsClient = {
  readBalance: async (account = "personal", signal) => {
    const query = new URLSearchParams({
      account: parseCreditAccount(account, "credits.request.account"),
    });
    return parseCreditBalance(
      await read(`/v1/billing/credits?${query}`, signal),
    );
  },
  readHistory: async (request = {}, signal) => {
    const path = "credits.history.request";
    if (!request || typeof request !== "object" || Array.isArray(request))
      throw new ContractError(path, "expected an object");
    for (const key of Object.keys(request))
      if (!["account", "limit", "before"].includes(key))
        throw new ContractError(`${path}.${key}`, "unknown field");
    const { account = "personal", limit = 50, before } = request;
    if (!Number.isInteger(limit) || limit < 1 || limit > 100)
      throw new ContractError(
        `${path}.limit`,
        "expected a limit from 1 to 100",
      );
    const query = new URLSearchParams({
      account: parseCreditAccount(account, `${path}.account`),
      limit: String(limit),
    });
    if (before !== undefined && before !== null)
      query.set("before", parseCreditId(before, `${path}.before`));
    return parseCreditHistory(
      await read(`/v1/billing/credits/history?${query}`, signal),
    );
  },
};
