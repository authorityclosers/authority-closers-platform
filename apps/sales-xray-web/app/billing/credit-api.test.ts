import { afterEach, expect, it, vi } from "vitest";
import { BillingError } from "./billing-api";
import { ContractError, type Account } from "./contract";
import { liveCredits, type CreditHistoryRequest } from "./credit-api";

const ACCOUNT_ID = "11111111-1111-4111-8111-111111111111";
const ENTRY_ID = "22222222-2222-4222-8222-222222222222";
const BALANCE = {
  account: "personal",
  account_id: ACCOUNT_ID,
  balance: "1.250000",
};
const HISTORY = {
  account: "personal",
  account_id: ACCOUNT_ID,
  entries: [
    {
      entry_id: ENTRY_ID,
      quantity: "-0.250000",
      created_at: "2026-10-05T09:00:00Z",
      corrected_entry_id: null,
    },
  ],
  next_before: ENTRY_ID,
};
const OPTIONS = {
  method: "GET",
  credentials: "same-origin",
  cache: "no-store",
  signal: undefined,
};
const readers = [
  () => liveCredits.readBalance(),
  () => liveCredits.readHistory(),
];

afterEach(() => vi.unstubAllGlobals());

it("sends explicit default selectors/options and reads one page only", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(Response.json(BALANCE))
    .mockResolvedValueOnce(Response.json(HISTORY));
  vi.stubGlobal("fetch", fetch);
  expect(await liveCredits.readBalance()).toEqual({
    account: "personal",
    accountId: ACCOUNT_ID,
    balance: "1.250000",
  });
  expect(await liveCredits.readHistory()).toEqual({
    account: "personal",
    accountId: ACCOUNT_ID,
    entries: [
      {
        entryId: ENTRY_ID,
        quantity: "-0.250000",
        createdAt: "2026-10-05T09:00:00Z",
        correctedEntryId: null,
      },
    ],
    nextBefore: ENTRY_ID,
  });
  expect(fetch.mock.calls).toEqual([
    ["/v1/billing/credits?account=personal", OPTIONS],
    ["/v1/billing/credits/history?account=personal&limit=50", OPTIONS],
  ]);
});

it("encodes only supported organisation history fields and follows a cursor only on request", async () => {
  const signal = new AbortController().signal;
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      Response.json({ ...HISTORY, account: "organisation" }),
    )
    .mockResolvedValueOnce(
      Response.json({
        ...HISTORY,
        account: "organisation",
        entries: [],
        next_before: null,
      }),
    );
  vi.stubGlobal("fetch", fetch);
  const page = await liveCredits.readHistory(
    { account: "organisation", limit: 1 },
    signal,
  );
  expect(fetch).toHaveBeenCalledTimes(1);
  await liveCredits.readHistory(
    { account: "organisation", limit: 100, before: page.nextBefore },
    signal,
  );
  expect(fetch.mock.calls).toEqual([
    [
      "/v1/billing/credits/history?account=organisation&limit=1",
      { ...OPTIONS, signal },
    ],
    [
      `/v1/billing/credits/history?account=organisation&limit=100&before=${encodeURIComponent(ENTRY_ID)}`,
      { ...OPTIONS, signal },
    ],
  ]);
});

it.each(["personal", "organisation"] as const)(
  "returns only server-authorized empty %s reads",
  async (account) => {
    const signal = new AbortController().signal;
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({ account, account_id: null, balance: "0" }),
      )
      .mockResolvedValueOnce(
        Response.json({
          account,
          account_id: null,
          entries: [],
          next_before: null,
        }),
      );
    vi.stubGlobal("fetch", fetch);
    expect(await liveCredits.readBalance(account, signal)).toEqual({
      account,
      accountId: null,
      balance: "0",
    });
    expect(
      await liveCredits.readHistory({ account, before: null }, signal),
    ).toEqual({ account, accountId: null, entries: [], nextBefore: null });
    expect(fetch.mock.calls).toEqual([
      [`/v1/billing/credits?account=${account}`, { ...OPTIONS, signal }],
      [
        `/v1/billing/credits/history?account=${account}&limit=50`,
        { ...OPTIONS, signal },
      ],
    ]);
  },
);

it.each([
  "-1.250000",
  "9007199254740993123456789.123456",
  "0.000000000000000000000000001",
])("retains exact %s text through HTTP", async (quantity) => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(Response.json({ ...BALANCE, balance: quantity }))
      .mockResolvedValueOnce(
        Response.json({
          ...HISTORY,
          entries: [{ ...HISTORY.entries[0], quantity }],
        }),
      ),
  );
  expect((await liveCredits.readBalance()).balance).toBe(quantity);
  expect((await liveCredits.readHistory()).entries[0].quantity).toBe(quantity);
});

it.each([
  [401, "authentication_required"],
  [403, "billing_forbidden"],
  [422, "validation_failed"],
  [404, "credit_entry_not_found"],
  [409, "not_on_sale"],
] as const)(
  "retains HTTP %s and problem code %s without fallback/retry",
  async (status, code) => {
    const fetch = vi.fn<(path: string, init: RequestInit) => Promise<Response>>(
      async () =>
        Response.json(
          {
            type: "about:blank",
            title: "Read failed",
            status,
            code,
            detail: "Fictional read failure",
          },
          { status, headers: { "content-type": "application/problem+json" } },
        ),
    );
    vi.stubGlobal("fetch", fetch);
    for (const read of readers) {
      const failure: unknown = await read().catch((error: unknown) => error);
      expect(failure).toBeInstanceOf(BillingError);
      expect(failure).toMatchObject({
        status,
        code,
        detail: "Fictional read failure",
      });
    }
    expect(fetch.mock.calls).toEqual([
      ["/v1/billing/credits?account=personal", OPTIONS],
      ["/v1/billing/credits/history?account=personal&limit=50", OPTIONS],
    ]);
  },
);

it.each([
  new Response("<html>Route absent</html>", { status: 404 }),
  new Response("invalid JSON", {
    status: 404,
    headers: { "content-type": "application/json" },
  }),
  Response.json({ code: "billing_forbidden" }, { status: 403 }),
])("keeps non-problem errors as HTTP failures", async (response) => {
  const fetch = vi.fn(async () => response.clone());
  vi.stubGlobal("fetch", fetch);
  for (const read of readers)
    await expect(read()).rejects.toMatchObject({
      status: response.status,
      code: null,
      detail: null,
    });
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("propagates network failures without retry or account change", async () => {
  const error = new TypeError("Fictional network failure");
  const fetch = vi.fn().mockRejectedValue(error);
  vi.stubGlobal("fetch", fetch);
  for (const read of readers) await expect(read()).rejects.toBe(error);
  expect(fetch.mock.calls).toEqual([
    ["/v1/billing/credits?account=personal", OPTIONS],
    ["/v1/billing/credits/history?account=personal&limit=50", OPTIONS],
  ]);
});

it("rejects invalid success JSON and contract drift", async () => {
  const fetch = vi.fn(async () => new Response("not JSON", { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  for (const read of readers)
    await expect(read()).rejects.toBeInstanceOf(SyntaxError);
  fetch.mockImplementation(async () =>
    Response.json({ ...BALANCE, balance: 1.25 }),
  );
  await expect(liveCredits.readBalance()).rejects.toBeInstanceOf(ContractError);
  fetch.mockImplementation(async () =>
    Response.json({ ...HISTORY, next_before: "bad-cursor" }),
  );
  await expect(liveCredits.readHistory()).rejects.toBeInstanceOf(ContractError);
  expect(fetch).toHaveBeenCalledTimes(4);
});

it.each([
  { account: "personal&tenant_id=fictional" },
  { account: null },
  { limit: 0 },
  { limit: 101 },
  { limit: 1.5 },
  { limit: "50" },
  { limit: null },
  { limit: NaN },
  { limit: Infinity },
  { before: "" },
  { before: `${ENTRY_ID}&account=organisation` },
  { before: `${ENTRY_ID}\n` },
  { before: 1 },
  { tenant_id: ACCOUNT_ID },
  { account_id: ACCOUNT_ID },
  { person_id: ACCOUNT_ID },
  null,
  [],
])("rejects unsupported history input %j before HTTP", async (request) => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  await expect(
    liveCredits.readHistory(request as unknown as CreditHistoryRequest),
  ).rejects.toBeInstanceOf(ContractError);
  expect(fetch).not.toHaveBeenCalled();
});

it("rejects unsupported balance account selectors before HTTP", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  await expect(
    liveCredits.readBalance("personal&tenant_id=fictional" as Account),
  ).rejects.toBeInstanceOf(ContractError);
  expect(fetch).not.toHaveBeenCalled();
});

it.each(["balance", "history"] as const)(
  "propagates cancellation during the %s request",
  async (kind) => {
    const controller = new AbortController();
    const fetch = vi.fn(
      (_path: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal!.addEventListener(
            "abort",
            () => reject(init.signal!.reason),
            { once: true },
          );
        }),
    );
    vi.stubGlobal("fetch", fetch);
    const pending =
      kind === "balance"
        ? liveCredits.readBalance("personal", controller.signal)
        : liveCredits.readHistory({}, controller.signal);
    const rejected = expect(pending).rejects.toMatchObject({
      name: "AbortError",
    });
    controller.abort();
    await rejected;
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
  },
);

it("rejects an already aborted signal before HTTP", async () => {
  const controller = new AbortController();
  controller.abort();
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  await expect(
    liveCredits.readBalance(undefined, controller.signal),
  ).rejects.toBe(controller.signal.reason);
  await expect(
    liveCredits.readHistory(undefined, controller.signal),
  ).rejects.toBe(controller.signal.reason);
  expect(fetch).not.toHaveBeenCalled();
});

it("retains an abort during an error-body read", async () => {
  const controller = new AbortController();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: false,
      status: 403,
      headers: new Headers({ "content-type": "application/problem+json" }),
      json: async () => {
        controller.abort();
        throw controller.signal.reason;
      },
    })),
  );
  await expect(
    liveCredits.readBalance("personal", controller.signal),
  ).rejects.toBe(controller.signal.reason);
});
