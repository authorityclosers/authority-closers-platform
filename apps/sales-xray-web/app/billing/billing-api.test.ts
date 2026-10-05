import { afterEach, expect, it, vi } from "vitest";
import {
  BillingError,
  invoiceDownloadPath,
  notOnSale,
  liveBilling,
} from "./billing-api";

afterEach(() => vi.unstubAllGlobals());

it("sends only C1 checkout fields, verifies bodylessly and retains error codes", async () => {
  const fetch = vi.fn<(path: string, init: RequestInit) => Promise<Response>>(
    async () =>
      new Response(
        JSON.stringify({
          order: {
            order_id: "order-fictional",
            kind: "subscription",
            account: "personal",
            status: "awaiting_payment",
            mode: "test",
            amount: { minor: 249900, currency: "INR", gst_inclusive: true },
            plan_key: "personal",
            plan_name: "Personal",
            interval: "month",
            seats: 1,
            pack_key: null,
            minutes: 800,
            subscription_id: "sub",
            created_at: "2026-10-03T00:00:00Z",
            paid_at: null,
            refund: null,
          },
          hosted: {
            provider: "fake",
            kind: "redirect",
            url: "/return",
            params: {},
            expires_at: null,
          },
        }),
        { headers: { "content-type": "application/json" } },
      ),
  );
  vi.stubGlobal("fetch", fetch);
  await liveBilling.checkout(
    {
      kind: "subscription",
      account: "organisation",
      planKey: "organisation",
      interval: "year",
      seats: 2,
      buyer: { name: "Fictional Closers", gstin: "27ABCDE1234F1Z5" },
    },
    "retry-key",
  );
  const [path, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
  expect(path).toBe("/v1/checkout");
  expect(init.credentials).toBe("same-origin");
  expect(init.headers).toMatchObject({ "Idempotency-Key": "retry-key" });
  expect(JSON.parse(String(init.body))).toEqual({
    kind: "subscription",
    account: "organisation",
    plan_key: "organisation",
    interval: "year",
    seats: 2,
    buyer: { name: "Fictional Closers", gstin: "27ABCDE1234F1Z5" },
  });
  fetch.mockImplementationOnce(
    async () =>
      new Response(
        JSON.stringify({
          type: "about:blank",
          title: "Unavailable",
          status: 409,
          code: "not_on_sale",
          detail: "Off",
        }),
        {
          status: 409,
          headers: { "content-type": "application/problem+json" },
        },
      ),
  );
  await expect(
    liveBilling.verifyOrder("order/one", "verify-key"),
  ).rejects.toMatchObject({
    status: 409,
    code: "not_on_sale",
  } satisfies Partial<BillingError>);
  expect(fetch.mock.calls[1]).toEqual([
    "/v1/orders/order%2Fone/verify",
    expect.objectContaining({ method: "POST", idempotencyKey: "verify-key" }),
  ]);
  expect(
    (fetch.mock.calls[1] as unknown as [string, RequestInit])[1].body,
  ).toBeUndefined();
});

it("reads every invoice page for the selected account and builds a same-origin download", async () => {
  const invoice = {
    invoice_id: "00000000-0000-4000-8000-0000000000cc",
    number: "TEST-1",
    created_at: "2026-10-03T00:00:00Z",
    currency: "INR",
    taxable_minor: 2000000,
    cgst_minor: 0,
    sgst_minor: 0,
    igst_minor: 360000,
    total_minor: 2360000,
    place_of_supply: "27",
  };
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      Response.json({ invoices: [invoice], next_before: invoice.invoice_id }),
    )
    .mockResolvedValueOnce(
      Response.json({
        invoices: [{ ...invoice, invoice_id: "second" }],
        next_before: null,
      }),
    );
  vi.stubGlobal("fetch", fetch);
  const signal = new AbortController().signal;
  expect(await liveBilling.readInvoices("organisation", signal)).toHaveLength(
    2,
  );
  expect(fetch.mock.calls.map(([path]) => path)).toEqual([
    "/v1/invoices?account=organisation",
    `/v1/invoices?account=organisation&before=${invoice.invoice_id}`,
  ]);
  expect(fetch.mock.calls[0][1]).toMatchObject({
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });
  expect(invoiceDownloadPath("id/one")).toBe("/v1/invoices/id%2Fone/download");
});

it("does not interpret an invoice failure as an empty list", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("", { status: 403 })),
  );
  await expect(liveBilling.readInvoices("personal")).rejects.toMatchObject({
    status: 403,
  });
  await expect(liveBilling.readInvoices("organisation")).rejects.toMatchObject({
    status: 403,
  });
});

it("treats a missing organisation billing account as empty, retaining personal 404 errors", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("", { status: 404 })),
  );
  await expect(liveBilling.readInvoices("organisation")).resolves.toEqual([]);
  await expect(liveBilling.readInvoices("personal")).rejects.toMatchObject({
    status: 404,
  });
});

it.each([
  [404, null, true],
  [405, null, true],
  [501, null, true],
  [409, "not_on_sale", true],
  [404, "not_found", false],
  [403, "forbidden", false],
  [500, null, false],
  [503, null, false],
  [400, "billing_disabled", false],
  [400, "not_on_sale", false],
] as const)(
  "classifies C1 not-on-sale status %i/code %s",
  (status, code, expected) => {
    expect(
      notOnSale(new BillingError(status, code, "billing is disabled")),
    ).toBe(expected);
  },
);

it.each(["personal", "organisation"] as const)(
  "retains problem-body invoice 404 for %s",
  async (account) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(
          {
            type: "about:blank",
            title: "Not found",
            status: 404,
            code: "not_found",
            detail: "Missing invoice account",
          },
          { status: 404 },
        ),
      ),
    );
    await expect(liveBilling.readInvoices(account)).rejects.toMatchObject({
      status: 404,
      code: "not_found",
    });
  },
);

it("does not read unvalidated error codes or match detail strings", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json(
        { code: "billing_disabled", detail: "billing is disabled" },
        { status: 403 },
      ),
    ),
  );
  await expect(liveBilling.readSubscriptions("personal")).rejects.toMatchObject(
    { status: 403, code: null, detail: null },
  );
  expect(notOnSale(new Error("network"))).toBe(false);
});
